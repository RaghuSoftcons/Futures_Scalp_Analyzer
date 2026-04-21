from futures_scalp_analyzer.service import _compute_timeframe_alignment, _compute_timeframe_bias


def _make_bars_from_closes(closes: list[float]) -> list[dict]:
    bars: list[dict] = []
    for idx, close in enumerate(closes):
        bars.append(
            {
                "open": close,
                "high": close + 0.25,
                "low": close - 0.25,
                "close": close,
                "volume": 100 + idx,
            }
        )
    return bars


def test_compute_timeframe_bias_long():
    closes = [100.0 + (i * 1.0) for i in range(30)]
    bars = _make_bars_from_closes(closes)
    assert _compute_timeframe_bias(bars) == "long"


def test_compute_timeframe_bias_short():
    closes = [130.0 - (i * 1.0) for i in range(30)]
    bars = _make_bars_from_closes(closes)
    assert _compute_timeframe_bias(bars) == "short"


def test_compute_timeframe_bias_mixed_returns_neutral():
    bars = []
    for idx in range(30):
        close = 100.0 + idx
        if idx < 20:
            high = close + 200.0
            low = close + 180.0
            volume = 1000
        else:
            high = close + 0.25
            low = close - 0.25
            volume = 100
        bars.append({"open": close, "high": high, "low": low, "close": close, "volume": volume})
    assert _compute_timeframe_bias(bars) == "neutral"


def test_compute_timeframe_alignment_all_long():
    assert _compute_timeframe_alignment("long", "long", "long", "long") == "aligned_long"


def test_compute_timeframe_alignment_all_short():
    assert _compute_timeframe_alignment("short", "short", "short", "short") == "aligned_short"


def test_compute_timeframe_alignment_mixed():
    assert _compute_timeframe_alignment("short", "long", "long", "short") == "mixed"


def test_compute_timeframe_alignment_neutral_when_two_or_more_neutral():
    assert _compute_timeframe_alignment("neutral", "long", "short", "neutral") == "neutral"
