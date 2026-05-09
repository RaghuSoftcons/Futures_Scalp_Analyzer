"""Read-only live price abstraction for Schwab quote access."""

from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any, Mapping
import urllib.parse

import httpx

from .symbols import SUPPORTED_SYMBOLS

LOGGER = logging.getLogger(__name__)

ROOT_DISPLAY_NAMES: dict[str, str] = {
    "/ES": "E-Mini S&P 500",
    "/NQ": "E-Mini Nasdaq 100",
    "/GC": "Gold",
    "/CL": "Crude Oil",
    "/SI": "Silver",
    "/ZB": "30Y T-Bond",
    "/UB": "Ultra T-Bond",
    "/MNQ": "Micro Nasdaq",
    "/MES": "Micro S&P",
    "/MCL": "Micro Crude",
    "/MGC": "Micro Gold",
    "/SIL": "Micro Silver",
}

FALLBACK_ACTIVE_CONTRACTS: dict[str, str] = {
    "/ES": "/ESM26",
    "/NQ": "/NQM26",
    "/GC": "/GCM26",
    "/CL": "/CLK26",
    "/SI": "/SIM26",
    "/ZB": "/ZBM26",
    "/UB": "/UBM26",
    "/MNQ": "/MNQM26",
    "/MES": "/MESM26",
    "/MCL": "/MCLK26",
    "/MGC": "/MGCM26",
    "/SIL": "/SILM26",
}

ROOT_SYMBOLS: tuple[str, ...] = tuple(FALLBACK_ACTIVE_CONTRACTS.keys())
ACTIVE_CONTRACT_CACHE_TTL = timedelta(hours=24)
BROKER_TIMEOUT_SECONDS = 10.0


def normalize_root_symbol(symbol: str) -> str | None:
    """Normalize user-facing symbols like ES or /ES into the root futures symbol."""
    normalized = symbol.strip().upper()
    if not normalized:
        return None
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized in FALLBACK_ACTIVE_CONTRACTS:
        return normalized
    short_symbol = normalized.removeprefix("/")
    spec = SUPPORTED_SYMBOLS.get(short_symbol)
    if spec is not None:
        return spec.schwab_symbol.upper()
    return None


class PriceFeed(ABC):
    """Read-only interface for fetching live futures pricing and bars."""

    @abstractmethod
    async def get_live_price(self, symbol: str) -> float | None:
        raise NotImplementedError

    @abstractmethod
    async def get_bars(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        raise NotImplementedError


class StaticPriceFeed(PriceFeed):
    """Simple in-memory feed useful for tests or local development."""

    def __init__(self, prices: Mapping[str, float] | None = None) -> None:
        self._prices = dict(prices or {})

    async def get_live_price(self, symbol: str) -> float | None:
        return self._prices.get(symbol.upper())

    async def get_bars(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        del symbol, frequency_type, frequency, period_type, period
        return []


class ActiveContractResolver:
    """
    Resolve front-month futures contracts from Schwab root symbols.

    The resolver keeps an in-memory cache that is refreshed on startup, every
    24 hours, and immediately when a contract quote returns 404.
    """

    def __init__(self, client: "SchwabQuotePriceFeed") -> None:
        self._client = client
        self._cache: dict[str, dict[str, str | None]] = {}
        self._last_refresh_at: datetime | None = None
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> dict[str, dict[str, str | None]]:
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._cache
            and self._last_refresh_at is not None
            and now - self._last_refresh_at < ACTIVE_CONTRACT_CACHE_TTL
        ):
            return self._cache

        if self._client.broker_enabled:
            broker_cache = self._client.fetch_broker_active_contracts()
            if broker_cache:
                self._cache = broker_cache
                self._last_refresh_at = now
                return self._cache

        encoded_roots = ",".join(urllib.parse.quote(root, safe="") for root in ROOT_SYMBOLS)
        try:
            response, _ = self._client.fetch_json(
                f"{self._client.api_base_url}/marketdata/v1/quotes?symbols={encoded_roots}"
            )
            if response is None:
                raise RuntimeError("No response received from Schwab active-contract lookup")
            if response.status_code >= 400:
                raise RuntimeError(f"Schwab active-contract lookup returned {response.status_code}")

            payload = response.json()
            refreshed_cache: dict[str, dict[str, str | None]] = {}
            for root in ROOT_SYMBOLS:
                quote_payload = self._client.extract_quote_payload(payload, root)
                active_contract = quote_payload.get("futureActiveSymbol") if quote_payload else None
                expiration = quote_payload.get("futureExpirationDate") if quote_payload else None
                refreshed_cache[root] = {
                    "active_contract": str(active_contract) if active_contract else FALLBACK_ACTIVE_CONTRACTS[root],
                    "expiration": str(expiration) if expiration else None,
                }

            self._cache = refreshed_cache
            self._last_refresh_at = now
            return self._cache
        except Exception:
            LOGGER.warning("Falling back to hardcoded active contract map", exc_info=True)
            self._cache = {
                root: {"active_contract": contract, "expiration": None}
                for root, contract in FALLBACK_ACTIVE_CONTRACTS.items()
            }
            self._last_refresh_at = now
            return self._cache

    def get_active_contract(self, symbol: str, force_refresh: bool = False) -> str | None:
        root = normalize_root_symbol(symbol)
        if root is None:
            return None
        cache = self.refresh(force=force_refresh)
        details = cache.get(root)
        if details is None:
            return FALLBACK_ACTIVE_CONTRACTS.get(root)
        return details.get("active_contract") or FALLBACK_ACTIVE_CONTRACTS.get(root)

    def list_contracts(self) -> list[dict[str, str | None]]:
        cache = self.refresh(force=False)
        return [
            {
                "root": root,
                "active_contract": cache.get(root, {}).get("active_contract") or FALLBACK_ACTIVE_CONTRACTS[root],
                "expiration": cache.get(root, {}).get("expiration"),
                "display_name": ROOT_DISPLAY_NAMES.get(root, root),
            }
            for root in ROOT_SYMBOLS
        ]


class SchwabQuotePriceFeed(PriceFeed):
    """Read-only Schwab quote client with in-memory token refresh."""

    def __init__(self) -> None:
        self._access_token = os.getenv("SCHWAB_ACCESS_TOKEN")
        self._refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN")
        self._client_id = os.getenv("SCHWAB_CLIENT_ID")
        self._client_secret = os.getenv("SCHWAB_CLIENT_SECRET")
        self.api_base_url = os.getenv("SCHWAB_API_BASE_URL", "https://api.schwabapi.com").rstrip("/")
        self._token_url = os.getenv("SCHWAB_TOKEN_URL", "https://api.schwabapi.com/v1/oauth/token")
        self._broker_base_url = os.getenv("SCHWAB_BROKER_BASE_URL", "").rstrip("/")
        self._broker_api_key = os.getenv("SCHWAB_BROKER_API_KEY", "")
        self._resolver = ActiveContractResolver(self)

    async def get_live_price(self, symbol: str) -> float | None:
        return await asyncio.to_thread(self.get_price, symbol)

    @property
    def broker_enabled(self) -> bool:
        return bool(self._broker_base_url and self._broker_api_key)

    async def get_bars(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        return await asyncio.to_thread(
            self.get_price_history,
            symbol,
            frequency_type,
            frequency,
            period_type,
            period,
        )

    def get_price_history(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        root_symbol = normalize_root_symbol(symbol)
        if root_symbol is None:
            LOGGER.warning("Unsupported symbol requested for bars: %s", symbol)
            return []

        if self.broker_enabled:
            broker_bars = self._fetch_broker_price_history(
                root_symbol,
                frequency_type,
                frequency,
                period_type,
                period,
            )
            if broker_bars:
                return broker_bars

        allowed_frequency_type = {"minute", "daily"}
        allowed_frequency = {1, 3, 5, 15, 30}
        allowed_period_type = {"day"}
        allowed_period = {1, 2, 5}
        if (
            frequency_type not in allowed_frequency_type
            or frequency not in allowed_frequency
            or period_type not in allowed_period_type
            or period not in allowed_period
        ):
            LOGGER.warning(
                "Invalid Schwab bar request: symbol=%s frequency_type=%s frequency=%s period_type=%s period=%s",
                symbol,
                frequency_type,
                frequency,
                period_type,
                period,
            )
            return []

        params = urllib.parse.urlencode(
            {
                "symbol": root_symbol,
                "frequencyType": frequency_type,
                "frequency": frequency,
                "periodType": period_type,
                "period": period,
                "needExtendedHoursData": "true",
                "needPreviousClose": "false",
            }
        )
        url = f"{self.api_base_url}/marketdata/v1/pricehistory?{params}"

        response, _ = self.fetch_json(url)
        if response is None or response.status_code >= 400:
            LOGGER.warning(
                "Schwab price history request failed for %s (%s): status=%s",
                symbol,
                root_symbol,
                None if response is None else response.status_code,
            )
            return []

        try:
            payload = response.json()
            candles = payload.get("candles", [])
            bars: list[dict[str, float | int | str]] = []
            for candle in candles:
                bars.append(
                    {
                        "open": float(candle.get("open", 0.0)),
                        "high": float(candle.get("high", 0.0)),
                        "low": float(candle.get("low", 0.0)),
                        "close": float(candle.get("close", 0.0)),
                        "volume": float(candle.get("volume", 0.0)),
                        "datetime": int(candle.get("datetime", 0)),
                    }
                )
            return bars
        except Exception:
            LOGGER.exception("Failed to parse Schwab price history payload for %s", symbol)
            return []

    def get_price(self, symbol: str) -> float | None:
        quote_details = self.get_quote_details(symbol)
        if not quote_details:
            return None
        last_price = quote_details.get("last")
        if last_price is not None:
            return float(last_price)
        mark = quote_details.get("mark")
        if mark is not None:
            return float(mark)
        return None

    def get_active_contract(self, symbol: str) -> str | None:
        return self._resolver.get_active_contract(symbol)

    def list_active_contracts(self) -> list[dict[str, str | None]]:
        return self._resolver.list_contracts()

    def get_quote_details(self, symbol: str) -> dict[str, Any] | None:
        root_symbol = normalize_root_symbol(symbol)
        if root_symbol is None:
            LOGGER.warning("Unsupported symbol requested from Schwab feed: %s", symbol)
            return None

        if self.broker_enabled:
            broker_quote = self._fetch_broker_quote_details(root_symbol)
            if broker_quote is not None:
                return broker_quote

        active_contract = self._resolver.get_active_contract(root_symbol)
        if active_contract is None:
            LOGGER.warning("No active contract available for %s", root_symbol)
            return None

        response, token_refreshed = self.fetch_quote_response(active_contract)
        if response is not None and response.status_code == 404:
            # A 404 usually means the cached contract rolled, so refresh the
            # active-contract cache immediately and retry with the new mapping.
            self._resolver.refresh(force=True)
            active_contract = self._resolver.get_active_contract(root_symbol) or FALLBACK_ACTIVE_CONTRACTS[root_symbol]
            response, retry_refreshed = self.fetch_quote_response(active_contract)
            token_refreshed = token_refreshed or retry_refreshed

        if response is None:
            return None
        if response.status_code >= 400:
            LOGGER.warning("Schwab quote request failed for %s with status %s", active_contract, response.status_code)
            return None

        try:
            payload = response.json()
            quote_data = self.extract_quote_payload(payload, active_contract)
            if quote_data is None:
                LOGGER.warning("No quote payload found for %s", active_contract)
                return None
            return {
                "root": root_symbol,
                "active_contract": active_contract,
                "last": quote_data.get("lastPrice"),
                "bid": quote_data.get("bidPrice"),
                "ask": quote_data.get("askPrice"),
                "mark": quote_data.get("mark"),
                "timestamp": self.format_quote_timestamp(quote_data),
                "token_refreshed": token_refreshed,
                "source": "schwab_live",
            }
        except Exception:
            LOGGER.exception("Failed to parse Schwab quote payload for %s", active_contract)
            return None

    def fetch_broker_active_contracts(self) -> dict[str, dict[str, str | None]] | None:
        payload = self._fetch_broker_json("/broker/futures/active-contracts")
        if payload is None:
            return None
        contracts = payload.get("contracts", [])
        refreshed_cache: dict[str, dict[str, str | None]] = {}
        for item in contracts:
            root = str(item.get("root", "") or "")
            if not root:
                continue
            refreshed_cache[root] = {
                "active_contract": str(item.get("active_contract") or FALLBACK_ACTIVE_CONTRACTS.get(root, root)),
                "expiration": str(item.get("expiration") or "") or None,
            }
        return refreshed_cache or None

    def _fetch_broker_quote_details(self, root_symbol: str) -> dict[str, Any] | None:
        payload = self._fetch_broker_json(f"/broker/futures/quote/{root_symbol.removeprefix('/')}")
        if payload is None:
            return None
        return {
            "root": str(payload.get("root") or root_symbol),
            "active_contract": str(payload.get("active_contract") or root_symbol),
            "last": payload.get("last"),
            "bid": payload.get("bid"),
            "ask": payload.get("ask"),
            "mark": payload.get("mark"),
            "timestamp": payload.get("timestamp"),
            "token_refreshed": False,
            "source": str(payload.get("source") or "schwab_broker"),
        }

    def _fetch_broker_price_history(
        self,
        root_symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        payload = self._fetch_broker_json(
            f"/broker/futures/pricehistory/{root_symbol.removeprefix('/')}",
            params={
                "frequency_type": frequency_type,
                "frequency": frequency,
                "period_type": period_type,
                "period": period,
            },
        )
        if payload is None:
            return []
        candles = payload.get("candles", [])
        try:
            return [
                {
                    "open": float(candle.get("open", 0.0)),
                    "high": float(candle.get("high", 0.0)),
                    "low": float(candle.get("low", 0.0)),
                    "close": float(candle.get("close", 0.0)),
                    "volume": float(candle.get("volume", 0.0)),
                    "datetime": int(candle.get("datetime", 0)),
                }
                for candle in candles
            ]
        except Exception:
            LOGGER.exception("Failed to parse broker price history payload for %s", root_symbol)
            return []

    def _fetch_broker_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.broker_enabled:
            return None
        try:
            response = httpx.get(
                f"{self._broker_base_url}{path}",
                headers={"X-API-Key": self._broker_api_key},
                params=params,
                timeout=BROKER_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            LOGGER.warning("Broker returned non-dict payload for %s", path)
            return None
        except httpx.HTTPError:
            LOGGER.exception("Broker request failed for %s", path)
            return None
        except Exception:
            LOGGER.exception("Unexpected broker error for %s", path)
            return None

    def fetch_quote_response(self, schwab_symbol: str) -> tuple[httpx.Response | None, bool]:
        encoded_symbol = urllib.parse.quote(schwab_symbol, safe="")
        url = f"{self.api_base_url}/marketdata/v1/quotes?symbols={encoded_symbol}"
        return self.fetch_json(url)

    def fetch_json(self, url: str) -> tuple[httpx.Response | None, bool]:
        if not self._access_token:
            LOGGER.warning("SCHWAB_ACCESS_TOKEN is not set; Schwab request skipped for %s", url)
            return None, False

        response = self._http_get(url, self._access_token)
        token_refreshed = False
        if response is None:
            return None, token_refreshed

        if response.status_code == 401:
            token_refreshed = self._refresh_access_token()
            if not token_refreshed:
                LOGGER.warning("Schwab token refresh failed for %s", url)
                return None, False
            response = self._http_get(url, self._access_token)

        return response, token_refreshed

    def _http_get(self, url: str, access_token: str | None) -> httpx.Response | None:
        try:
            return httpx.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
        except httpx.HTTPError:
            LOGGER.exception("Network error while fetching Schwab resource %s", url)
            return None
        except Exception:
            LOGGER.exception("Unexpected error while fetching Schwab resource %s", url)
            return None

    def _refresh_access_token(self) -> bool:
        if not all([self._refresh_token, self._client_id, self._client_secret]):
            LOGGER.warning("Schwab refresh credentials are incomplete")
            return False

        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        try:
            response = httpx.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=10.0,
            )
            LOGGER.info(
                "Schwab token refresh status=%s body=%s",
                response.status_code,
                response.text,
            )
            if response.status_code >= 400:
                LOGGER.warning("Schwab token refresh returned status %s", response.status_code)
                return False
            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                LOGGER.warning("Schwab token refresh response did not include access_token")
                return False
            self._access_token = str(access_token)
            return True
        except httpx.HTTPError:
            LOGGER.exception("Network error while refreshing Schwab access token")
            return False
        except Exception:
            LOGGER.exception("Unexpected error while refreshing Schwab access token")
            return False

    @staticmethod
    def extract_quote_payload(payload: Mapping[str, Any], schwab_symbol: str) -> Mapping[str, Any] | None:
        direct_payload = payload.get(schwab_symbol)
        if isinstance(direct_payload, Mapping):
            nested_quote = direct_payload.get("quote")
            if isinstance(nested_quote, Mapping):
                return nested_quote
            return direct_payload
        return None

    @staticmethod
    def format_quote_timestamp(quote_payload: Mapping[str, Any]) -> str | None:
        raw_timestamp = (
            quote_payload.get("quoteTime")
            or quote_payload.get("tradeTime")
            or quote_payload.get("timestamp")
        )
        if raw_timestamp is None:
            return None

        if isinstance(raw_timestamp, (int, float)):
            timestamp_value = float(raw_timestamp)
            if timestamp_value > 1_000_000_000_000:
                timestamp_value /= 1000.0
            return datetime.fromtimestamp(timestamp_value, tz=timezone.utc).isoformat().replace("+00:00", "Z")

        if isinstance(raw_timestamp, str):
            return raw_timestamp

        return None
