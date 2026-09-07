"""Synthetic candles and fake Kite responses; no live account or network."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from kiteconnect.exceptions import GeneralException, TokenException
from requests.exceptions import ConnectionError

from app import signals
from app.main import create_app

NOW = datetime(2026, 9, 4, 15, 30, tzinfo=signals.IST)
HEADERS = {"X-Kite-Client": "local-web"}
FAKE_TOKEN = "signals-test-only-access-token"


def candles(closes, start="2026-09-04 09:15", frequency="5min"):
    return pd.DataFrame({"date": pd.date_range(start, periods=len(closes), freq=frequency, tz=signals.IST),
                         "open": closes, "high": [value + 1 for value in closes],
                         "low": [value - 1 for value in closes], "close": closes, "volume": 10})


def scanner_candles(closes, start="2026-09-04 09:15", frequency="5min"):
    """Existing scanner scenarios with mature indicators from earlier sessions."""
    raw = candles(closes, start, frequency)
    first = raw.date.iloc[0]
    earlier = pd.concat([candles([closes[0]] * 75, start=str(day.date()) + " 09:15")
                         for day in pd.bdate_range(end=first.normalize() - timedelta(days=1), periods=4)])
    return pd.concat([earlier, raw], ignore_index=True)


def instrument(symbol, token=1, **overrides):
    return {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ",
            "tradingsymbol": symbol, "instrument_token": token, **overrides}


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(signals.time, "sleep", MagicMock())


@pytest.fixture
def api_setup(tmp_path, monkeypatch):
    sdk = MagicMock()
    sdk.generate_session.return_value = {"access_token": FAKE_TOKEN}
    sdk.profile.return_value = {"user_name": "Test User", "user_id": "TEST", "products": [], "exchanges": []}
    sdk.instruments.return_value = [instrument("AAA"), instrument("BBB", 2)]
    sdk.historical_data.return_value = scanner_candles([100] * 30 + [102, 104]).to_dict("records")
    monkeypatch.setattr(signals, "load_constituents", lambda: [
        {"ticker": "AAA", "company": "Alpha Company"}, {"ticker": "BBB", "company": "Beta Company"}])
    monkeypatch.setattr("app.main.scan", lambda kite, parameters, guard: signals.scan(kite, parameters, guard, NOW))
    factory = MagicMock(return_value=sdk)
    path = tmp_path / "session.json"
    app = create_app(path, factory)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"api_key": "fake-key", "api_secret": "fake-secret", "request_token": "fake-request"}, headers=HEADERS).status_code == 200
        yield client, sdk, path, app, factory


@pytest.mark.parametrize("interval,minutes", [("5minute", 5), ("15minute", 15), ("60minute", 60)])
def test_forming_candle_is_excluded_until_its_end(interval, minutes):
    raw = candles([100, 101], frequency=f"{minutes}min")
    boundary = raw.date.iloc[1] + timedelta(minutes=minutes)
    assert len(signals.completed_candles(raw, interval, boundary - timedelta(seconds=1))) == 1
    assert len(signals.completed_candles(raw, interval, boundary)) == 2


def test_final_hourly_candle_ends_at_market_close():
    raw = candles([100], start="2026-09-04 15:15", frequency="60min")
    assert signals.completed_candles(raw, "60minute", NOW - timedelta(seconds=1)).empty
    assert len(signals.completed_candles(raw, "60minute", NOW)) == 1


def test_unsorted_candles_are_sorted_and_invalid_rows_rejected():
    raw = candles([100, 101, 102]).iloc[::-1]
    frame = signals.completed_candles(raw, "5minute", NOW)
    assert list(frame.close) == [100, 101, 102]
    with pytest.raises(signals.ScanDataError):
        signals.completed_candles(pd.concat([raw, raw]), "5minute", NOW)
    raw.loc[0, "close"] = float("nan")
    with pytest.raises(signals.ScanDataError):
        signals.completed_candles(raw, "5minute", NOW)


def test_four_hour_ohlcv_completion_and_no_overnight_mix():
    raw = pd.concat([candles(list(range(100, 107)), frequency="60min"),
                     candles(list(range(200, 207)), start="2026-09-03 09:15", frequency="60min")])
    hourly = signals.completed_candles(raw, "60minute", NOW)
    bars = signals.resample_4hour(hourly, NOW)
    assert len(bars) == 4
    assert list(bars.index.strftime("%H:%M")) == ["09:15", "13:15", "09:15", "13:15"]
    assert bars.iloc[2].to_dict() == {"open": 100, "high": 104, "low": 99, "close": 103, "volume": 40}
    assert bars.iloc[3].to_dict() == {"open": 104, "high": 107, "low": 103, "close": 106, "volume": 30}
    at_noon = NOW.replace(hour=12, minute=30)
    assert len(signals.resample_4hour(hourly, at_noon)) == 2
    assert len(signals.resample_4hour(hourly, NOW - timedelta(seconds=1))) == 3
    missing = hourly.drop(pd.Timestamp("2026-09-04 10:15", tz=signals.IST))
    assert len(signals.resample_4hour(missing, NOW)) == 3


def test_four_hour_crossovers_need_consecutive_complete_session_bars():
    # A full sequence has both morning and closing bars each session.
    stamps = [day + timedelta(hours=hour, minutes=15)
              for day in pd.bdate_range(end='2026-09-04', periods=190, tz=signals.IST)
              for hour in (9, 13)]
    frame = pd.DataFrame({'close': [100] * (len(stamps)-1) + [105]}, index=stamps)
    parameters = signals.ScanParameters(timeframe='4hour')
    result = signals.latest_crossover(frame, parameters, NOW - timedelta(days=30))
    assert result['crossover_type'] == 'Bullish'
    # If every closing bar lacks hourly source data, mornings must not be bridged.
    mornings = frame.loc[frame.index.hour == 9]
    with pytest.raises(signals.ScanDataError, match='No consecutive completed candles'):
        signals.latest_crossover(mornings, parameters, NOW - timedelta(days=30))


@pytest.mark.parametrize("direction,last", [("Bullish", 102), ("Bearish", 98)])
def test_equality_is_a_genuine_crossover_and_rounding_is_only_for_output(direction, last):
    frame = signals.completed_candles(scanner_candles([100] * 30 + [last, last]), "5minute", NOW)
    result = signals.latest_crossover(frame, signals.ScanParameters(), NOW - timedelta(days=1))
    assert result["crossover_type"] == direction
    assert result["crossover_time"] == "11:45"  # Latest candle is 11:50; crossover was earlier.
    assert result["short_ema"] == frame.close.ewm(span=6, adjust=False).mean().iloc[-2]


def test_above_or_below_alone_never_generates_a_signal():
    for closes in (list(range(100, 150)), list(range(150, 100, -1)), [100] * 50):
        frame = signals.completed_candles(scanner_candles(closes), "5minute", NOW)
        assert signals.latest_crossover(frame, signals.ScanParameters(), frame.index[-10]) is None


def test_most_recent_actual_cross_and_lookback_cutoff():
    frame = signals.completed_candles(scanner_candles([100] * 30 + [110] * 10 + [90] * 10), "5minute", NOW)
    result = signals.latest_crossover(frame, signals.ScanParameters(), NOW - timedelta(days=1))
    assert result["crossover_type"] == "Bearish"
    assert signals.latest_crossover(frame, signals.ScanParameters(), result["crossover_at"] + timedelta(seconds=1)) is None


def test_missing_intraday_candle_cannot_create_a_cross():
    frame = signals.completed_candles(scanner_candles([100] * 30 + [110]), "5minute", NOW)
    assert signals.latest_crossover(frame.drop(frame.index[-2]), signals.ScanParameters(), NOW - timedelta(days=1)) is None


def test_forming_spike_and_rounded_equality_do_not_change_detection():
    raw = scanner_candles([100] * 30 + [100.0001])
    cutoff = raw.date.iloc[-1] + timedelta(minutes=4)
    completed = signals.completed_candles(raw, "5minute", cutoff)
    assert signals.latest_crossover(completed, signals.ScanParameters(), NOW - timedelta(days=1)) is None
    completed = signals.completed_candles(raw, "5minute", cutoff + timedelta(minutes=1))
    result = signals.latest_crossover(completed, signals.ScanParameters(), NOW - timedelta(days=1))
    assert result["crossover_type"] == "Bullish" and round(result["short_ema"], 2) == round(result["long_ema"], 2) == 100


def test_cross_between_consecutive_sessions_is_included():
    raw = pd.concat([scanner_candles([100] * 75, start="2026-09-03 09:15"), candles([105])])
    frame = signals.completed_candles(raw, "5minute", NOW)
    result = signals.latest_crossover(frame, signals.ScanParameters(), NOW - timedelta(days=1))
    assert result["crossover_time"] == "09:15"
    # An absent previous session closing bar cannot be bridged.
    with pytest.raises(signals.ScanDataError, match='No consecutive completed candles'):
        signals.latest_crossover(frame.drop(frame.index[-2]), signals.ScanParameters(), NOW - timedelta(days=1))


def test_dynamic_periods_and_insufficient_data():
    frame = signals.completed_candles(scanner_candles([100] * 30 + [102]), "5minute", NOW)
    result = signals.latest_crossover(frame, signals.ScanParameters(short_ema=9), NOW - timedelta(days=1))
    assert result["short_ema"] == frame.close.ewm(span=9, adjust=False).mean().iloc[-1]
    with pytest.raises(signals.ScanDataError):
        signals.latest_crossover(frame.iloc[:21], signals.ScanParameters(), NOW - timedelta(days=1))


def test_mapping_uses_exact_nse_equities_and_reports_missing():
    members = [{"ticker": "AAA", "company": "Alpha"}, {"ticker": "MISS", "company": "Missing"}]
    mapped, warnings = signals.map_instruments(members, [instrument("AAA"), instrument("AAA", segment="NFO", instrument_type="FUT")])
    assert [stock["instrument_token"] for stock in mapped] == [1]
    assert warnings[0].ticker == "MISS"


def test_csv_download_and_error_are_sanitized(monkeypatch):
    response = MagicMock(text="Company Name,Symbol,Series\nBeta,BBB,EQ\nAlpha,AAA,EQ\nFund,FUND,BE\n")
    get = MagicMock(return_value=response)
    monkeypatch.setattr(signals.requests, "get", get)
    assert [row["ticker"] for row in signals.load_constituents()] == ["AAA", "BBB"]
    assert get.call_args.args[0] == signals.NIFTY100_URL
    get.side_effect = ConnectionError(FAKE_TOKEN)
    with pytest.raises(signals.ScanDataError) as error:
        signals.load_constituents()
    assert FAKE_TOKEN not in str(error.value)


def test_rate_limit_retries_are_bounded():
    operation = MagicMock(side_effect=[GeneralException(FAKE_TOKEN, code=429), GeneralException("busy", code=503), []])
    assert signals.kite_call(operation, lambda: None) == []
    assert [call.args[0] for call in signals.time.sleep.call_args_list] == [.55, 2, .55, 4, .55]
    operation.side_effect = GeneralException(FAKE_TOKEN, code=429)
    with pytest.raises(signals.ScanDataError) as error:
        signals.kite_call(operation, lambda: None)
    assert FAKE_TOKEN not in str(error.value)
    assert operation.call_count == 6


def test_chunked_history_covers_warmup_without_duplicate_bounds():
    sdk = MagicMock()
    sdk.historical_data.return_value = []
    start = NOW - timedelta(days=121)
    signals.fetch_candles(sdk, 1, "60minute", start, NOW, lambda: None)
    calls = sdk.historical_data.call_args_list
    assert len(calls) == 3 and calls[0].args[1] == start and calls[-1].args[2] == NOW
    assert calls[1].args[1] == calls[0].args[2] + timedelta(seconds=1)


def test_scan_ranks_full_timestamps_and_limits_selected_stocks(monkeypatch):
    monkeypatch.setattr(signals, "load_constituents", lambda: [
        {"ticker": name, "company": name} for name in ("AAA", "BBB", "CCC", "DDD")])
    sdk = MagicMock()
    sdk.instruments.return_value = [instrument(name, index) for index, name in enumerate(("AAA", "BBB", "CCC", "DDD"), 1)]
    sdk.historical_data.side_effect = [scanner_candles([100] * 30 + [102], start="2026-09-03 09:15").to_dict("records"),
                                     scanner_candles([100] * 30 + [102]).to_dict("records"), scanner_candles([100] * 32 + [98]).to_dict("records")]
    result = signals.scan(sdk, signals.ScanParameters(max_stocks=3), lambda: None, NOW)
    assert [row.ticker for row in result.signals] == ["CCC", "BBB", "AAA"]
    assert [row.rank for row in result.signals] == [1, 2, 3]
    assert result.stocks_scanned == 3 and result.bullish_signals == 2 and result.bearish_signals == 1
    assert sdk.historical_data.call_count == 3


def test_four_hour_uses_hourly_once_and_fetches_warmup(monkeypatch):
    monkeypatch.setattr(signals, "load_constituents", lambda: [{"ticker": "AAA", "company": "Alpha"}])
    sdk = MagicMock()
    sdk.instruments.return_value = [instrument("AAA")]
    sdk.historical_data.return_value = []
    result = signals.scan(sdk, signals.ScanParameters(timeframe="4hour"), lambda: None, NOW)
    assert result.stocks_scanned == 1 and result.stocks_analyzed == 0
    calls = sdk.historical_data.call_args_list
    assert len(calls) == 3  # 30-day lookback plus 137 MACD warm-up days, in 60-day chunks.
    assert all(call.args[3] == "60minute" for call in calls)
    assert calls[0].args[1] < result.lookback_start


def test_endpoint_reuses_session_and_returns_only_public_fields(api_setup):
    client, sdk, _, _, _ = api_setup
    response = client.get("/api/signals/ema", headers=HEADERS)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["signals_found"] == 2
    assert [row["ticker"] for row in data["signals"]] == ["AAA", "BBB"]
    assert data["parameters"]["short_ema"] == 6
    assert {row["timeframe"] for row in data["signals"]} == {"5minute"}
    sdk.generate_session.assert_called_once()
    sdk.set_access_token.assert_called_with(FAKE_TOKEN)
    for secret in (FAKE_TOKEN, "fake-key", "fake-secret", "fake-request", "instrument_token", "api_key", "access_token"):
        assert secret not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["short_ema=0", "long_ema=-1", "short_ema=21&long_ema=21", "short_ema=22", "lookback_days=0", "lookback_days=91", "max_stocks=0", "max_stocks=101", "timeframe=day", "short_ema=2.5", "api_secret=private-test-input"])
def test_invalid_queries_do_not_call_kite_or_echo_inputs(api_setup, query):
    client, sdk, _, _, _ = api_setup
    response = client.get("/api/signals/ema?" + query, headers=HEADERS)
    assert response.status_code == 422
    assert "private-test-input" not in response.text
    sdk.historical_data.assert_not_called()


def test_individual_failure_does_not_stop_other_stocks(api_setup):
    client, sdk, path, _, _ = api_setup
    sdk.historical_data.side_effect = [RuntimeError(FAKE_TOKEN), scanner_candles([100] * 30 + [102]).to_dict("records")]
    response = client.get("/api/signals/ema", headers=HEADERS)
    data = response.json()
    assert response.status_code == 200 and data["stocks_scanned"] == 2 and data["signals_found"] == 1
    assert len(data["warnings"]) == 1 and data["warnings"][0]["ticker"] == "AAA"
    assert FAKE_TOKEN not in response.text and path.exists()


def test_expired_token_stops_scan_clears_session_and_unlocks(api_setup):
    client, sdk, path, _, _ = api_setup
    sdk.historical_data.side_effect = TokenException(FAKE_TOKEN)
    response = client.get("/api/signals/ema", headers=HEADERS)
    assert response.status_code == 401 and FAKE_TOKEN not in response.text and not path.exists()
    assert sdk.historical_data.call_count == 1


def test_session_required_and_header_required(api_setup):
    client, sdk, _, app, _ = api_setup
    assert client.get("/api/signals/ema").status_code == 403
    with TestClient(app) as stranger:
        assert stranger.get("/api/signals/ema", headers=HEADERS).status_code == 401
    sdk.historical_data.assert_not_called()


def test_overlapping_scans_rejected_and_lock_released(api_setup, monkeypatch):
    client, _, _, _, _ = api_setup
    entered, release = Event(), Event()
    original_scan = lambda kite, parameters, guard: signals.scan(kite, parameters, guard, NOW)

    def waiting_scan(*args):
        entered.set()
        assert release.wait(5)
        return original_scan(*args)

    monkeypatch.setattr("app.main.scan", waiting_scan)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.get, "/api/signals/ema", headers=HEADERS)
        try:
            assert entered.wait(5)
            assert client.get("/api/signals/ema", headers=HEADERS).status_code == 409
        finally:
            release.set()
        assert first.result().status_code == 200
    assert client.get("/api/signals/ema", headers=HEADERS).status_code == 200


def test_logout_during_scan_stops_further_requests(api_setup):
    client, sdk, path, _, _ = api_setup

    def disconnect(*_args, **_kwargs):
        path.unlink()
        return scanner_candles([100] * 30 + [102]).to_dict("records")

    sdk.historical_data.side_effect = disconnect
    assert client.get("/api/signals/ema", headers=HEADERS).status_code == 401
    assert sdk.historical_data.call_count == 1


def test_global_download_failure_preserves_session_and_unlocks(api_setup, monkeypatch):
    client, _, path, _, _ = api_setup
    monkeypatch.setattr(signals, "load_constituents", MagicMock(side_effect=signals.ScanDataError("Official Nifty CSV is unavailable.")))
    for _ in range(2):
        response = client.get("/api/signals/ema", headers=HEADERS)
        assert response.status_code == 503 and path.exists()
