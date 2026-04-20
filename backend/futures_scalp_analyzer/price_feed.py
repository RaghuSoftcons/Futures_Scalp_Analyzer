"""Read-only live price abstraction for Schwab quote access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping


class PriceFeed(ABC):
    """Read-only interface for fetching a live futures price."""

    @abstractmethod
    async def get_live_price(self, symbol: str) -> float | None:
        raise NotImplementedError


class StaticPriceFeed(PriceFeed):
    """Simple in-memory feed useful for tests or local development."""

    def __init__(self, prices: Mapping[str, float] | None = None) -> None:
        self._prices = dict(prices or {})

    async def get_live_price(self, symbol: str) -> float | None:
        return self._prices.get(symbol.upper())


class SchwabQuotePriceFeed(PriceFeed):
    """
    Placeholder for a read-only Schwab quote bridge.

    This service stays self-contained: integration details can be wired here
    later without coupling to any external options codebase.
    """

    async def get_live_price(self, symbol: str) -> float | None:
        return None

