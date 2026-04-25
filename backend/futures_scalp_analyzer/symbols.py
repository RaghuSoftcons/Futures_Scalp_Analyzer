"""Static futures instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    schwab_symbol: str
    tick_size: float
    tick_value: float
    point_value: float
    description: str
    is_micro: bool
    atr_reference: float
    liquidity_score: str


@dataclass(frozen=True)
class InstrumentMetadata:
    symbol: str
    display_symbol: str
    provider_symbol: str
    asset_class: str
    exchange: str
    session_type: str
    tick_size: float
    tick_value: float
    point_value: float
    position_unit: str
    decisions_enabled: bool


SUPPORTED_SYMBOLS: dict[str, SymbolSpec] = {
    "NQ": SymbolSpec("NQ", schwab_symbol="/NQ", tick_size=0.25, tick_value=5.0, point_value=20.0, description="E-mini Nasdaq-100", is_micro=False, atr_reference=220.0, liquidity_score="good"),
    "ES": SymbolSpec("ES", schwab_symbol="/ES", tick_size=0.25, tick_value=12.5, point_value=50.0, description="E-mini S&P 500", is_micro=False, atr_reference=55.0, liquidity_score="good"),
    "CL": SymbolSpec("CL", schwab_symbol="/CL", tick_size=0.01, tick_value=10.0, point_value=1000.0, description="Crude Oil", is_micro=False, atr_reference=1.8, liquidity_score="acceptable"),
    "GC": SymbolSpec("GC", schwab_symbol="/GC", tick_size=0.1, tick_value=10.0, point_value=100.0, description="Gold", is_micro=False, atr_reference=32.0, liquidity_score="acceptable"),
    "SI": SymbolSpec("SI", schwab_symbol="/SI", tick_size=0.005, tick_value=25.0, point_value=5000.0, description="Silver", is_micro=False, atr_reference=0.8, liquidity_score="acceptable"),
    "ZB": SymbolSpec("ZB", schwab_symbol="/ZB", tick_size=0.03125, tick_value=31.25, point_value=1000.0, description="30-Year U.S. Treasury Bond", is_micro=False, atr_reference=2.2, liquidity_score="acceptable"),
    "UB": SymbolSpec("UB", schwab_symbol="/UB", tick_size=0.03125, tick_value=31.25, point_value=1000.0, description="Ultra U.S. Treasury Bond", is_micro=False, atr_reference=2.8, liquidity_score="weak"),
    "MNQ": SymbolSpec("MNQ", schwab_symbol="/MNQ", tick_size=0.25, tick_value=0.5, point_value=2.0, description="Micro E-mini Nasdaq-100", is_micro=True, atr_reference=220.0, liquidity_score="good"),
    "MES": SymbolSpec("MES", schwab_symbol="/MES", tick_size=0.25, tick_value=1.25, point_value=5.0, description="Micro E-mini S&P 500", is_micro=True, atr_reference=55.0, liquidity_score="good"),
    "MCL": SymbolSpec("MCL", schwab_symbol="/MCL", tick_size=0.01, tick_value=1.0, point_value=100.0, description="Micro WTI Crude Oil", is_micro=True, atr_reference=1.8, liquidity_score="acceptable"),
    "MGC": SymbolSpec("MGC", schwab_symbol="/MGC", tick_size=0.1, tick_value=1.0, point_value=10.0, description="Micro Gold", is_micro=True, atr_reference=32.0, liquidity_score="acceptable"),
    "SIL": SymbolSpec("SIL", schwab_symbol="/SIL", tick_size=0.005, tick_value=2.5, point_value=500.0, description="Micro Silver", is_micro=True, atr_reference=0.8, liquidity_score="acceptable"),
}


FUTURES_EXCHANGES: dict[str, str] = {
    "ES": "CME",
    "NQ": "CME",
    "MNQ": "CME",
    "MES": "CME",
    "CL": "NYMEX",
    "MCL": "NYMEX",
    "GC": "COMEX",
    "MGC": "COMEX",
    "SI": "COMEX",
    "SIL": "COMEX",
    "ZB": "CBOT",
    "UB": "CBOT",
}

ETF_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
STOCK_SYMBOLS = ("AAPL", "MSFT", "NVDA", "TSLA")


def _future_metadata(symbol: str, spec: SymbolSpec) -> InstrumentMetadata:
    return InstrumentMetadata(
        symbol=symbol,
        display_symbol=spec.schwab_symbol,
        provider_symbol=spec.schwab_symbol,
        asset_class="future",
        exchange=FUTURES_EXCHANGES.get(symbol, "CME"),
        session_type="futures_eth",
        tick_size=spec.tick_size,
        tick_value=spec.tick_value,
        point_value=spec.point_value,
        position_unit="contracts",
        decisions_enabled=True,
    )


def _equity_metadata(symbol: str, asset_class: str) -> InstrumentMetadata:
    return InstrumentMetadata(
        symbol=symbol,
        display_symbol=symbol,
        provider_symbol=symbol,
        asset_class=asset_class,
        exchange="NYSE_ARCA" if asset_class == "etf" else "NASDAQ",
        session_type="equity_rth",
        tick_size=0.01,
        tick_value=0.01,
        point_value=1.0,
        position_unit="shares",
        decisions_enabled=False,
    )


INSTRUMENT_REGISTRY: dict[str, InstrumentMetadata] = {
    **{symbol: _future_metadata(symbol, spec) for symbol, spec in SUPPORTED_SYMBOLS.items()},
    **{symbol: _equity_metadata(symbol, "etf") for symbol in ETF_SYMBOLS},
    **{symbol: _equity_metadata(symbol, "stock") for symbol in STOCK_SYMBOLS},
}


def normalize_instrument_symbol(symbol: str) -> str:
    return symbol.strip().upper().removeprefix("/")


def get_instrument_metadata(symbol: str) -> InstrumentMetadata | None:
    return INSTRUMENT_REGISTRY.get(normalize_instrument_symbol(symbol))
