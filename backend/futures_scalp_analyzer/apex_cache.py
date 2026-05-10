"""In-memory Apex market data cache and polling service."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Callable

from .apex_pipeline import MarketDataProvider, build_market_session, build_payload


LOGGER = logging.getLogger(__name__)


@dataclass
class CachedApexPayload:
    payload: dict
    updated_at: datetime


class ApexMarketDataCache:
    """Small process-local cache to keep dashboard refreshes from hammering Schwab."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float | None = None,
        closed_interval_seconds: float | None = None,
        active_symbol_ttl_seconds: float | None = None,
    ) -> None:
        self.poll_interval_seconds = poll_interval_seconds or float(os.getenv("APEX_POLL_INTERVAL_SECONDS", "8"))
        self.closed_interval_seconds = closed_interval_seconds or float(os.getenv("APEX_CLOSED_POLL_INTERVAL_SECONDS", "60"))
        self.active_symbol_ttl_seconds = active_symbol_ttl_seconds or float(os.getenv("APEX_ACTIVE_SYMBOL_TTL_SECONDS", "600"))
        self._payloads: dict[str, CachedApexPayload] = {}
        self._active_symbols: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self, provider_factory: Callable[[], MarketDataProvider]) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._poll_loop(provider_factory))

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def get_payload(
        self,
        symbol: str,
        provider: MarketDataProvider,
        *,
        max_age_seconds: float | None = None,
    ) -> dict:
        normalized_symbol = _normalize_symbol(symbol)
        await self.mark_active(normalized_symbol)
        cached = await self._get_cached(normalized_symbol)
        ttl = max_age_seconds if max_age_seconds is not None else self._cache_ttl_seconds()
        if cached is not None and _age_seconds(cached.updated_at) <= ttl:
            return deepcopy(cached.payload)

        payload = await asyncio.to_thread(
            build_payload,
            normalized_symbol,
            provider,
            None,
            None,
            None,
            False,
            None,
        )
        await self.set_payload(normalized_symbol, payload)
        return deepcopy(payload)

    async def mark_active(self, symbol: str) -> None:
        async with self._lock:
            self._active_symbols[_normalize_symbol(symbol)] = datetime.now(timezone.utc)

    async def set_payload(self, symbol: str, payload: dict) -> None:
        async with self._lock:
            self._payloads[_normalize_symbol(symbol)] = CachedApexPayload(
                payload=deepcopy(payload),
                updated_at=datetime.now(timezone.utc),
            )

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "poll_interval_seconds": self.poll_interval_seconds,
                "closed_interval_seconds": self.closed_interval_seconds,
                "active_symbols": sorted(self._active_symbols),
                "cached_symbols": sorted(self._payloads),
                "cache": {
                    symbol: {
                        "updated_at": cached.updated_at.isoformat().replace("+00:00", "Z"),
                        "age_seconds": _age_seconds(cached.updated_at),
                        "data_source": cached.payload.get("market_data", {}).get("data_source"),
                        "provider_status": cached.payload.get("market_data", {}).get("provider_status"),
                        "data_gate_status": cached.payload.get("market_data", {}).get("data_gate_status"),
                        "market_session_status": cached.payload.get("market_session", {}).get("status"),
                    }
                    for symbol, cached in self._payloads.items()
                },
            }

    async def _get_cached(self, symbol: str) -> CachedApexPayload | None:
        async with self._lock:
            cached = self._payloads.get(_normalize_symbol(symbol))
            if cached is None:
                return None
            return CachedApexPayload(payload=deepcopy(cached.payload), updated_at=cached.updated_at)

    async def _poll_loop(self, provider_factory: Callable[[], MarketDataProvider]) -> None:
        while True:
            try:
                session = build_market_session()
                if session["status"] in {"closed", "maintenance"}:
                    await self._wait(self.closed_interval_seconds)
                    continue

                symbols = await self._current_active_symbols()
                for symbol in symbols:
                    provider = provider_factory()
                    payload = await asyncio.to_thread(
                        build_payload,
                        symbol,
                        provider,
                        None,
                        None,
                        None,
                        False,
                        None,
                    )
                    await self.set_payload(symbol, payload)
                await self._wait(self.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Apex market data cache poll failed")
                await self._wait(self.poll_interval_seconds)

    async def _current_active_symbols(self) -> list[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.active_symbol_ttl_seconds)
        async with self._lock:
            self._active_symbols = {
                symbol: last_seen
                for symbol, last_seen in self._active_symbols.items()
                if last_seen >= cutoff
            }
            return sorted(self._active_symbols)

    def _cache_ttl_seconds(self) -> float:
        session = build_market_session()
        if session["status"] in {"closed", "maintenance"}:
            return self.closed_interval_seconds
        return self.poll_interval_seconds

    async def _wait(self, seconds: float) -> None:
        if self._stop_event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().removeprefix("/")


def _age_seconds(updated_at: datetime) -> float:
    return round((datetime.now(timezone.utc) - updated_at).total_seconds(), 3)
