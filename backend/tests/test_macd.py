"""Same-candle confirmation using synthetic prices, independent scalar EMAs, and fake Kite."""

from datetime import timedelta
from math import ceil
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app import signals


def scalar_ema(values, span):
    result = [float(values[0])]
    alpha = 2 / (span + 1)
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def oracle(closes, short=6, long=21):
    fast, slow = scalar_ema(closes, 12), scalar_ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    return scalar_ema(closes, short), scalar_ema(closes, long), macd, scalar_ema(macd, 9)


def intraday_index(count, timeframe):
    offsets = {
        "5minute": range(0, 375, 5), "15minute": range(0, 375, 15),
        "60minute": range(0, 375, 60), "4hour": (0, 240),
    }[timeframe]
    days = pd.bdate_range(end="2026-09-04", periods=ceil(count / len(offsets)), tz=signals.IST)
    return pd.DatetimeIndex([day + timedelta(hours=9, minutes=15 + offset)
                             for day in days for offset in offsets][-count:])


def frame_for(closes, timeframe="5minute"):
    return pd.DataFrame({"close": closes}, index=intraday_index(len(closes), timeframe))


def assert_cross(row, direction):
    if direction == "Bullish":
        assert row["previous_short_ema"] <= row["previous_long_ema"]
        assert row["short_ema"] > row["long_ema"]
        assert row["previous_macd"] <= row["previous_macd_signal"]
        assert row["macd"] > row["macd_signal"]
    else:
        assert row["previous_short_ema"] >= row["previous_long_ema"]
        assert row["short_ema"] < row["long_ema"]
        assert row["previous_macd"] >= row["previous_macd_signal"]
        assert row["macd"] < row["macd_signal"]
    assert row["crossover_type"] == direction


@pytest.mark.parametrize("direction,last", [("Bullish", 110), ("Bearish", 90)])
@pytest.mark.parametrize("short,long", [(6, 21), (9, 21), (20, 50)])
def test_both_crossovers_and_returned_evidence_match_independent_calculation(direction, last, short, long):
    closes = [100] * 500 + [last]
    frame = frame_for(closes)
    row = signals.latest_crossover(frame, signals.ScanParameters(short_ema=short, long_ema=long), frame.index[-1])
    assert_cross(row, direction)
    for name, series in zip(("short_ema", "long_ema", "macd", "macd_signal"), oracle(closes, short, long)):
        assert row[name] == pytest.approx(series[-1])
        assert row["previous_" + name] == pytest.approx(series[-2])
    assert row["previous_candle_at"] == frame.index[-2]


@pytest.mark.parametrize("mirror", [False, True], ids=["bearish", "bullish"])
@pytest.mark.parametrize("kind,last,offset", [("macd_only", 5, 5), ("ema_only", 6, 6), ("different_candles", 6, 5)])
def test_one_indicator_or_crossovers_on_different_candles_are_rejected(mirror, kind, last, offset):
    # MACD reverses at index 205; EMA reverses one candle later, at 206.
    closes = [100] * 200 + [110] * 5 + [90] * 2
    if mirror:
        closes = [200 - close for close in closes]
    closes = closes[:201 + last]
    short, long, macd, signal = oracle(closes)
    direction = 1 if mirror else -1
    ema_change = direction * (short[-2] - long[-2]) <= 0 < direction * (short[-1] - long[-1])
    macd_change = direction * (macd[-2] - signal[-2]) <= 0 < direction * (macd[-1] - signal[-1])
    if kind == "ema_only":
        assert ema_change and not macd_change
    elif kind == "macd_only":
        assert macd_change and not ema_change
    else:
        assert ema_change and not macd_change
        assert direction * (macd[-3] - signal[-3]) <= 0 < direction * (macd[-2] - signal[-2])
    frame = frame_for(closes)
    assert signals.latest_crossover(frame, signals.ScanParameters(), frame.index[200 + offset]) is None


def test_latest_qualifying_cross_survives_a_more_recent_unconfirmed_cross():
    frame = frame_for([100] * 200 + [110] * 5 + [90] * 2)
    row = signals.latest_crossover(frame, signals.ScanParameters(), frame.index[200])
    assert row["crossover_at"] == frame.index[200]
    assert_cross(row, "Bullish")
    assert signals.latest_crossover(frame, signals.ScanParameters(), frame.index[200] + timedelta(seconds=1)) is None


def test_signals_during_warmup_are_suppressed_even_inside_lookback():
    frame = frame_for([100] * 170 + [110] * 10)
    assert signals.latest_crossover(frame, signals.ScanParameters(), frame.index[0]) is None
    for count in (21, 34, 100, 175):
        with pytest.raises(signals.ScanDataError, match=r"Insufficient completed candles for EMA \+ MACD"):
            signals.latest_crossover(frame.iloc[:count], signals.ScanParameters(), frame.index[0])
    boundary = frame_for([100] * 175 + [110])
    assert_cross(signals.latest_crossover(boundary, signals.ScanParameters(), boundary.index[0]), "Bullish")


def raw_for(frame, timeframe):
    records = []
    for stamp, row in frame.iterrows():
        ends = min(stamp + timedelta(hours=4), stamp.normalize() + timedelta(hours=15, minutes=30))
        stamps = pd.date_range(stamp, ends, freq="60min", inclusive="left") if timeframe == "4hour" else [stamp]
        for source_stamp in stamps:
            value = row.close
            records.append({"date": source_stamp, "open": value, "high": value + 1,
                            "low": value - 1, "close": value, "volume": 10})
    return pd.DataFrame(records)


@pytest.mark.parametrize("timeframe", ["5minute", "15minute", "60minute", "4hour"])
@pytest.mark.parametrize("direction,last", [("Bullish", 110), ("Bearish", 90)])
def test_all_timeframes_fetch_warmup_and_exclude_forming_confirmations(monkeypatch, timeframe, direction, last):
    frame = frame_for([100] * 500 + [last], timeframe)
    raw = raw_for(frame, timeframe)
    monkeypatch.setattr(signals.time, "sleep", lambda _: None)
    monkeypatch.setattr(signals, "load_constituents", lambda: [{"ticker": "TEST", "company": "Synthetic Company"}])
    sdk = MagicMock()
    sdk.instruments.return_value = [{"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "TEST", "instrument_token": 1}]

    def history(_token, start, end, _interval, **_kwargs):
        # Realistic range-limited response avoids duplicates across 60-day chunks.
        return raw.loc[(raw.date >= start) & (raw.date <= end)].to_dict("records")

    sdk.historical_data.side_effect = history
    parameters = signals.ScanParameters(timeframe=timeframe, lookback_days=1, max_stocks=1)
    close = frame.index[-1].normalize() + timedelta(hours=15, minutes=30)
    before = signals.scan(sdk, parameters, lambda: None, close - timedelta(seconds=1))
    assert before.stocks_analyzed == 1 and before.signals_found == 0 and before.warnings == []
    after = signals.scan(sdk, parameters, lambda: None, close)
    assert after.signals_found == 1 and after.stocks_analyzed == 1 and after.warnings == []
    assert_cross(after.signals[0].model_dump(), direction)
    assert after.bullish_signals == int(direction == "Bullish")
    assert after.bearish_signals == int(direction == "Bearish")
    assert after.signals[0].crossover_at == frame.index[-1]
    assert after.signals[0].crossover_at >= after.lookback_start
    calls = sdk.historical_data.call_args_list
    assert all(call.args[3] == ("60minute" if timeframe == "4hour" else timeframe) for call in calls)
    start = calls[0].args[1]
    assert len(frame.loc[(frame.index >= start) & (frame.index < after.lookback_start)]) >= 175
