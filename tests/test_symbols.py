from __future__ import annotations

import asyncio

from futures_scalp_analyzer.models import FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import FALLBACK_ACTIVE_CONTRACTS, StaticPriceFeed, normalize_root_symbol
from futures_scalp_analyzer.service import analyze_request
from futures_scalp_analyzer.symbols import INSTRUMENT_REGISTRY, SUPPORTED_SYMBOLS, get_instrument_metadata


def test_mnq_contract_metadata():
    mnq = SUPPORTED_SYMBOLS["MNQ"]
    assert mnq.point_value == 2.0
    assert mnq.tick_value == 0.50
    assert mnq.is_micro is True


def test_nq_contract_metadata():
    nq = SUPPORTED_SYMBOLS["NQ"]
    assert nq.point_value == 20.0
    assert nq.tick_value == 5.0
    assert nq.is_micro is False


def test_instrument_metadata_identifies_futures():
    nq = get_instrument_metadata("/NQ")

    assert nq is not None
    assert nq.asset_class == "future"
    assert nq.display_symbol == "/NQ"
    assert nq.provider_symbol == "/NQ"
    assert nq.session_type == "futures_eth"
    assert nq.position_unit == "contracts"
    assert nq.decisions_enabled is True


def test_instrument_metadata_identifies_etfs():
    spy = get_instrument_metadata("SPY")

    assert spy is not None
    assert spy.asset_class == "etf"
    assert spy.display_symbol == "SPY"
    assert spy.provider_symbol == "SPY"
    assert spy.session_type == "equity_rth"
    assert spy.position_unit == "shares"
    assert spy.decisions_enabled is False


def test_instrument_metadata_identifies_stocks():
    nvda = get_instrument_metadata("NVDA")

    assert nvda is not None
    assert nvda.asset_class == "stock"
    assert nvda.display_symbol == "NVDA"
    assert nvda.provider_symbol == "NVDA"
    assert nvda.session_type == "equity_rth"
    assert nvda.position_unit == "shares"
    assert nvda.decisions_enabled is False


def test_instrument_registry_contains_prepared_equity_symbols():
    for symbol in ("SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "TSLA"):
        assert symbol in INSTRUMENT_REGISTRY


def test_zb_has_no_micro_counterpart():
    assert "MZB" not in SUPPORTED_SYMBOLS


def test_symbol_normalization_variants():
    assert normalize_root_symbol("ES") == "/ES"
    assert normalize_root_symbol("/ES") == "/ES"
    assert normalize_root_symbol("es") == "/ES"


def test_fallback_active_contracts_cover_all_supported_symbols():
    assert len(FALLBACK_ACTIVE_CONTRACTS) == 12
    for root_symbol in ("/ES", "/NQ", "/GC", "/CL", "/SI", "/ZB", "/UB", "/MNQ", "/MES", "/MCL", "/MGC", "/SIL"):
        assert root_symbol in FALLBACK_ACTIVE_CONTRACTS


def test_mnq_risk_calculation_within_50k_limit():
    request = FuturesScalpIdeaRequest(
        symbol="MNQ",
        side="long",
        entry_price=20000.0,
        stop_price=19950.0,
        target_price=20100.0,
        contracts=1,
        account_size=50000,
        mode="idea_eval",
        session="RTH",
        realized_pnl_today=0.0,
        realized_loss_count_today=0,
        open_positions=[],
    )

    response = asyncio.run(analyze_request(request, StaticPriceFeed({"MNQ": 19999.0})))
    assert response.risk_per_contract == 100.0
    assert response.per_trade_risk_limit == 100.0
    assert response.risk_rule_violations.per_trade_risk_exceeds_limit is False
    assert response.verdict in {"GO", "WAIT", "NO GO"}
    assert response.market_data_available is False
    assert response.ema9 == "unavailable"
    assert response.trend == "unavailable"


def test_nq_risk_calculation_within_50k_limit():
    request = FuturesScalpIdeaRequest(
        symbol="NQ",
        side="long",
        entry_price=18000.0,
        stop_price=17995.0,
        target_price=18010.0,
        contracts=1,
        account_size=50000,
        mode="idea_eval",
        session="RTH",
        realized_pnl_today=0.0,
        realized_loss_count_today=0,
        open_positions=[],
    )

    response = asyncio.run(analyze_request(request, StaticPriceFeed({"NQ": 17999.0})))
    assert response.risk_per_contract == 100.0
    assert response.per_trade_risk_limit == 100.0
    assert response.risk_rule_violations.per_trade_risk_exceeds_limit is False
    assert response.vwap == "unavailable"
    assert response.market_structure == "unavailable"
