"""Static futures instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    tick_size: float
    tick_value: float
    point_value: float
    atr_reference: float
    liquidity_score: str


SUPPORTED_SYMBOLS: dict[str, SymbolSpec] = {
    "NQ": SymbolSpec("NQ", tick_size=0.25, tick_value=5.0, point_value=20.0, atr_reference=220.0, liquidity_score="good"),
    "ES": SymbolSpec("ES", tick_size=0.25, tick_value=12.5, point_value=50.0, atr_reference=55.0, liquidity_score="good"),
    "CL": SymbolSpec("CL", tick_size=0.01, tick_value=10.0, point_value=1000.0, atr_reference=1.8, liquidity_score="acceptable"),
    "GC": SymbolSpec("GC", tick_size=0.1, tick_value=10.0, point_value=100.0, atr_reference=32.0, liquidity_score="acceptable"),
    "SI": SymbolSpec("SI", tick_size=0.005, tick_value=25.0, point_value=5000.0, atr_reference=0.8, liquidity_score="acceptable"),
    "ZB": SymbolSpec("ZB", tick_size=0.03125, tick_value=31.25, point_value=1000.0, atr_reference=2.2, liquidity_score="acceptable"),
    "UB": SymbolSpec("UB", tick_size=0.03125, tick_value=31.25, point_value=1000.0, atr_reference=2.8, liquidity_score="weak"),
}

