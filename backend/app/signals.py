"""Nifty 100 scanner. Only public signal fields leave this backend module."""

import csv
import io
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import pandas as pd
import requests
from kiteconnect.exceptions import KiteException, TokenException
from pydantic import BaseModel, ConfigDict, Field, model_validator

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY100_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
Timeframe = Literal["5minute", "15minute", "60minute", "4hour"]
INTERVAL_MINUTES = {"5minute": 5, "15minute": 15, "60minute": 60, "4hour": 240}
REQUEST_GAP = 0.55  # Below Kite's historical-data limit of three calls/second.


class ScanDataError(ValueError):
    """A safe, user-facing explanation with no upstream exception text."""


class ScanSessionChanged(Exception):
    """Stop a running scan if the saved login is replaced or disconnected."""


class ScanParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    short_ema: int = Field(default=6, ge=1, le=100)
    long_ema: int = Field(default=21, ge=1, le=100)
    timeframe: Timeframe = "5minute"
    lookback_days: int = Field(default=30, ge=1, le=90)
    max_stocks: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.short_ema >= self.long_ema:
            raise ValueError("Short EMA must be smaller than Long EMA.")
        return self


class Signal(BaseModel):
    rank: int
    ticker: str
    company: str
    crossover_type: Literal["Bullish", "Bearish"]
    crossover_at: datetime
    crossover_date: str
    crossover_time: str
    close: float
    short_ema: float
    long_ema: float


class ScanWarning(BaseModel):
    ticker: str | None = None
    message: str


class ScanResult(BaseModel):
    parameters: ScanParameters
    generated_at: datetime
    candle_cutoff: datetime
    lookback_start: datetime
    stocks_selected: int
    stocks_mapped: int
    stocks_scanned: int
    stocks_analyzed: int
    signals_found: int
    bullish_signals: int
    bearish_signals: int
    warnings: list[ScanWarning]
    signals: list[Signal]


def load_constituents():
    try:
        response = requests.get(NIFTY100_URL, timeout=(10, 30),
                                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"})
        response.raise_for_status()
        rows = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        if not {"Symbol", "Company Name", "Series"}.issubset(rows.fieldnames or []):
            raise ValueError
        members = {}
        for row in rows:
            symbol = (row.get("Symbol") or "").strip().upper()
            company = (row.get("Company Name") or "").strip()
            if (row.get("Series") or "").strip() == "EQ" and company and re.fullmatch(r"[A-Z0-9&._-]+", symbol):
                members[symbol] = {"ticker": symbol, "company": company}
        if not members:
            raise ValueError
        return [members[symbol] for symbol in sorted(members)]
    except (requests.RequestException, csv.Error, UnicodeError, ValueError):
        raise ScanDataError("Could not download the official Nifty 100 list. Check your connection and try again.") from None


def map_instruments(members, instruments):
    equities = {}
    for item in instruments:
        if item.get("exchange") == "NSE" and item.get("segment") == "NSE" and item.get("instrument_type") == "EQ":
            equities.setdefault(item.get("tradingsymbol"), []).append(item)
    mapped, warnings = [], []
    for member in members:
        matches = equities.get(member["ticker"], [])
        try:
            if len(matches) != 1:
                raise ValueError
            token = int(matches[0]["instrument_token"])
            if token <= 0:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            warnings.append(ScanWarning(ticker=member["ticker"], message="No unique NSE equity mapping; skipped."))
            continue
        mapped.append({**member, "instrument_token": token})
    return mapped, warnings


def kite_call(operation: Callable, check_session: Callable):
    """Bounded retries; never reflect an SDK exception or request URL."""
    for attempt in range(3):
        check_session()
        time.sleep(REQUEST_GAP)
        try:
            return operation()
        except TokenException:
            raise
        except (KiteException, requests.RequestException) as error:
            code = getattr(error, "code", None)
            retryable = code == 429 or (isinstance(code, int) and code >= 500) or isinstance(error, requests.RequestException)
            if retryable and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise ScanDataError("Kite data unavailable. Check historical-data access or try again later.") from None


def fetch_candles(kite, token, interval, start, end, check_session):
    """Chunk requests into at most 60 calendar days, including EMA warm-up."""
    records = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=60), end)
        records.extend(kite_call(lambda: kite.historical_data(
            token, cursor, chunk_end, interval, continuous=False, oi=False), check_session))
        cursor = chunk_end + timedelta(seconds=1)  # Kite endpoints include both bounds.
    return pd.DataFrame(records)


def completed_candles(raw, interval, as_of):
    if raw.empty:
        return pd.DataFrame()
    if not {"date", "open", "high", "low", "close", "volume"}.issubset(raw.columns):
        raise ScanDataError("Candle data is incomplete; skipped.")
    frame = raw[["date", "open", "high", "low", "close", "volume"]].copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    dates = dates.tz_localize(IST) if dates.tz is None else dates.tz_convert(IST)
    frame.index = dates
    frame = frame.sort_index()
    if frame.index.has_duplicates or frame.index.hasnans:
        raise ScanDataError("Candle timestamps are invalid; skipped.")
    # Recompute after sorting; the final hourly candle closes at 15:30.
    opening = frame.index.normalize() + pd.Timedelta(hours=9, minutes=15)
    closing = frame.index.normalize() + pd.Timedelta(hours=15, minutes=30)
    duration = pd.Timedelta(minutes=INTERVAL_MINUTES[interval])
    ends = pd.DatetimeIndex([min(start + duration, close) for start, close in zip(frame.index, closing)])
    in_session = (frame.index >= opening) & (frame.index < closing)
    on_grid = (frame.index - opening) % duration == pd.Timedelta(0)
    frame = frame.loc[in_session & on_grid & (ends <= pd.Timestamp(as_of))].copy()
    if frame.empty:
        return frame
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not frame[column].map(lambda value: pd.notna(value) and math.isfinite(value)).all():
            raise ScanDataError("Candle prices or volume are invalid; skipped.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame["volume"] < 0).any():
        raise ScanDataError("Candle prices or volume are invalid; skipped.")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ScanDataError("Candle OHLC values are inconsistent; skipped.")
    return frame


def resample_4hour(hourly, as_of):
    """09:15-13:15 plus the completed 13:15-15:30 closing session bar."""
    pieces = []
    if hourly.empty:
        return hourly
    for day, session in hourly.groupby(hourly.index.normalize()):
        session_close = day + pd.Timedelta(hours=15, minutes=30)
        bars = session.resample("4h", origin="start_day", offset="9h15min", closed="left", label="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        for start, row in bars.iterrows():
            end = min(start + pd.Timedelta(hours=4), session_close)
            if end > pd.Timestamp(as_of) or start >= session_close:
                continue
            expected = pd.date_range(start, end, freq="60min", inclusive="left")
            present = session.loc[(session.index >= start) & (session.index < end)].index
            if len(expected) and present.equals(expected) and row.notna().all():
                pieces.append(pd.DataFrame([row], index=pd.DatetimeIndex([start])))
    return pd.concat(pieces).sort_index() if pieces else pd.DataFrame()


def latest_crossover(candles, parameters, lookback_start):
    if len(candles) < parameters.long_ema + 1:
        raise ScanDataError("Insufficient completed candles for these EMA periods; skipped.")
    frame = candles.copy()
    short = frame["close"].ewm(span=parameters.short_ema, adjust=False).mean()
    long = frame["close"].ewm(span=parameters.long_ema, adjust=False).mean()
    bullish = (short.shift(1) <= long.shift(1)) & (short > long)
    bearish = (short.shift(1) >= long.shift(1)) & (short < long)
    previous = frame.index.to_series().shift(1)
    same_day = frame.index.normalize() == pd.DatetimeIndex(previous).normalize()
    adjacent = frame.index.to_series() - previous == pd.Timedelta(minutes=INTERVAL_MINUTES[parameters.timeframe])
    last_start = {"5minute": "15:25", "15minute": "15:15", "60minute": "15:15", "4hour": "13:15"}[parameters.timeframe]
    overnight = (frame.index.strftime("%H:%M") == "09:15") & (previous.dt.strftime("%H:%M") == last_start)
    eligible = ((same_day & adjacent) | (~same_day & overnight)) & (frame.index >= lookback_start)
    eligible.iloc[:parameters.long_ema] = False
    crossings = frame.loc[(bullish | bearish) & eligible]
    if crossings.empty:
        return None
    stamp = crossings.index[-1]
    return {"crossover_type": "Bullish" if bullish.loc[stamp] else "Bearish",
            "crossover_at": stamp.to_pydatetime(), "crossover_date": stamp.strftime("%Y-%m-%d"),
            "crossover_time": stamp.strftime("%H:%M"), "close": round(float(frame.loc[stamp, "close"]), 2),
            "short_ema": round(float(short.loc[stamp]), 2), "long_ema": round(float(long.loc[stamp]), 2)}


def scan(kite, parameters: ScanParameters, check_session: Callable, as_of=None):
    as_of = as_of or datetime.now(IST)
    lookback_start = as_of - timedelta(days=parameters.lookback_days)
    bars_per_day = {"5minute": 75, "15minute": 25, "60minute": 7, "4hour": 2}[parameters.timeframe]
    warmup_days = math.ceil(parameters.long_ema * 5 / bars_per_day * 7 / 5) + 14
    start = (lookback_start - timedelta(days=warmup_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    members = load_constituents()[:parameters.max_stocks]
    instruments = kite_call(lambda: kite.instruments("NSE"), check_session)
    mapped, warnings = map_instruments(members, instruments)
    interval = "60minute" if parameters.timeframe == "4hour" else parameters.timeframe
    signals, analyzed = [], 0
    for stock in mapped:
        check_session()
        try:
            raw = fetch_candles(kite, stock["instrument_token"], interval, start, as_of, check_session)
            candles = completed_candles(raw, interval, as_of)
            if parameters.timeframe == "4hour":
                candles = resample_4hour(candles, as_of)
            if candles.empty:
                raise ScanDataError("No completed candle data available; skipped.")
            signal = latest_crossover(candles, parameters, lookback_start)
            analyzed += 1
            if signal:
                signals.append({"ticker": stock["ticker"], "company": stock["company"], **signal})
        except (TokenException, ScanSessionChanged):
            raise
        except ScanDataError as error:
            warnings.append(ScanWarning(ticker=stock["ticker"], message=str(error)))
        except Exception:
            warnings.append(ScanWarning(ticker=stock["ticker"], message="Unavailable, invalid, or insufficient candle data. Check historical-data access or retry."))
    check_session()
    signals.sort(key=lambda item: (-item["crossover_at"].timestamp(), item["ticker"]))
    ranked = [Signal(rank=rank, **item) for rank, item in enumerate(signals, start=1)]
    bullish = sum(item.crossover_type == "Bullish" for item in ranked)
    return ScanResult(parameters=parameters, generated_at=datetime.now(IST), candle_cutoff=as_of,
                      lookback_start=lookback_start, stocks_selected=len(members), stocks_mapped=len(mapped),
                      stocks_scanned=len(mapped), stocks_analyzed=analyzed, signals_found=len(ranked),
                      bullish_signals=bullish, bearish_signals=len(ranked) - bullish,
                      warnings=warnings, signals=ranked)
