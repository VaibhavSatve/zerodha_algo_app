"""Nifty 100 EMA 6/21 scanner. All times are India Standard Time (IST).

Install once:  python -m pip install kiteconnect pandas requests
Run:           python nifty100_ema_scanner.py

Keep credentials.txt next to this script, with these two labeled lines:
    API Key = your_api_key
    API Secret = your_api_secret

At the hidden prompt, paste a fresh request_token from your Kite login redirect.
Never put real credentials in this source file or commit them to GitHub.
"""

import csv
import getpass
import io
import math
import os
from pathlib import Path
import re
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException


FOLDER = Path(__file__).resolve().parent
CREDENTIALS_FILE = FOLDER / "credentials.txt"
OUTPUT_FILE = FOLDER / "nifty100_ema_signals.csv"
NIFTY100_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
SHORT_EMA = 6
LONG_EMA = 21
MINIMUM_CANDLES = LONG_EMA + 1
REQUEST_GAP_SECONDS = 0.55  # Fewer than 2 historical calls/second (Kite allows 3).
TIMEFRAMES = ("Daily", "5 Minute", "15 Minute", "1 Hour", "4 Hour")
OUTPUT_COLUMNS = ["Rank", "Symbol", "Company", "Timeframe", "Signal Type",
                  "Crossover Date", "Close", "EMA 6", "EMA 21"]


def read_credentials(path=CREDENTIALS_FILE):
    """Accept API Key/API Secret labels with ':' or '='; never echo values."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise ValueError("Cannot read credentials.txt. Put it beside this script and check its permissions.") from None
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"\s*([A-Za-z _-]+)\s*[:=]\s*(.*?)\s*", line)
        if not match:
            raise ValueError("Use two labeled lines in credentials.txt: API Key = ... and API Secret = ...")
        label = re.sub(r"[ _-]", "", match.group(1)).lower()
        label = label.removeprefix("kite")
        if label not in {"apikey", "apisecret"} or label in values:
            raise ValueError("credentials.txt must contain one API Key and one API Secret, without duplicate labels.")
        value = match.group(2).strip().strip("\"'")
        if not value or any(character.isspace() for character in value):
            raise ValueError("API Key and API Secret must each be a non-empty value without spaces.")
        values[label] = value
    if set(values) != {"apikey", "apisecret"}:
        raise ValueError("Both API Key and API Secret are required in credentials.txt.")
    return values["apikey"], values["apisecret"]


def authenticate_kite(api_key, api_secret, request_token=None):
    """Exchange a one-use request token. Secrets remain in process memory."""
    kite = KiteConnect(api_key=api_key, timeout=15, debug=False)
    # An environment variable supports private automation; normal runs prompt.
    request_token = request_token or os.environ.pop("KITE_REQUEST_TOKEN", "")
    if not request_token:
        if not sys.stdin.isatty():
            raise ValueError("Run this script in a terminal to paste a fresh request token at its hidden prompt.")
        print("Opening Kite login. After signing in, copy request_token from the redirect address.")
        try:
            webbrowser.open_new_tab(kite.login_url())
        except Exception:
            print("Could not open a browser. Complete Kite login manually to get the request token.")
        request_token = getpass.getpass("Paste request token (hidden): ").strip()
    if not request_token:
        raise ValueError("A fresh Kite request token is required.")
    try:
        session = kite.generate_session(request_token.strip(), api_secret=api_secret)
        kite.set_access_token(session["access_token"])
    except (KiteException, requests.RequestException, KeyError, TypeError):
        raise ValueError("Kite login failed. Check your API key/secret and get a NEW request token; it is single-use and expires quickly.") from None
    print("Kite authentication successful. Credentials will not be printed or written to the CSV.")
    return kite


def download_nifty100():
    """Read the official list on every run; there is no hardcoded stock list."""
    try:
        response = requests.get(NIFTY100_URL, timeout=(10, 30),
                                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"})
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        if not {"Symbol", "Company Name", "Series"}.issubset(reader.fieldnames or []):
            raise ValueError("The official Nifty CSV has an unexpected format. Try again later.")
        members = []
        seen = set()
        for row in reader:
            symbol = (row.get("Symbol") or "").strip().upper()
            company = (row.get("Company Name") or "").strip()
            if (row.get("Series") or "").strip() != "EQ":
                continue
            if not re.fullmatch(r"[A-Z0-9&._-]+", symbol) or not company:
                print("Warning: skipping an incomplete row in the Nifty CSV.")
                continue
            if symbol not in seen:
                members.append({"Symbol": symbol, "Company": company})
                seen.add(symbol)
        if not members:
            raise ValueError("No equity symbols were found in the official Nifty CSV.")
        return sorted(members, key=lambda member: member["Symbol"])
    except (requests.RequestException, csv.Error, UnicodeError):
        raise ValueError("Cannot download or parse the official Nifty 100 CSV. Check your connection and try again.") from None


def get_nse_instruments(kite):
    """Fetch the NSE instrument master once for the entire scan."""
    try:
        instruments = kite.instruments("NSE")
        if not instruments:
            raise ValueError("Kite returned an empty NSE instrument list. Please try again later.")
        return instruments
    except (KiteException, requests.RequestException):
        raise ValueError("Cannot retrieve Kite NSE instruments. Check the Kite session and connection.") from None


def map_instrument_tokens(members, instruments):
    """Exact official stock symbols + NSE cash EQ prevent derivative matches."""
    equities = {}
    for item in instruments:
        if (item.get("exchange") == "NSE" and item.get("segment") == "NSE"
                and item.get("instrument_type") == "EQ"):
            equities.setdefault(item.get("tradingsymbol"), []).append(item)
    mapped = []
    for member in members:
        matches = equities.get(member["Symbol"], [])
        if len(matches) != 1:
            print(f"Warning: {member['Symbol']} has no unique NSE equity mapping; skipped.")
            continue
        try:
            token = int(matches[0]["instrument_token"])
            if token <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            print(f"Warning: invalid instrument token for {member['Symbol']}; skipped.")
            continue
        mapped.append({**member, "Instrument Token": token})
    return mapped


def fetch_historical_data(kite, instrument_token, interval, days, as_of):
    """One request per native interval, with bounded retries and rate limiting."""
    start = (as_of - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    for attempt in range(3):
        time.sleep(REQUEST_GAP_SECONDS)
        try:
            candles = kite.historical_data(instrument_token, start, as_of, interval,
                                          continuous=False, oi=False)
            return pd.DataFrame(candles)
        except TokenException:
            raise  # Expired authentication affects every stock; the caller handles it.
        except (KiteException, requests.RequestException) as error:
            code = getattr(error, "code", None)
            retryable = code == 429 or (isinstance(code, int) and code >= 500) or isinstance(error, requests.RequestException)
            if retryable and attempt < 2:
                delay = 2 ** (attempt + 1)
                print(f"    Kite is busy or unavailable; retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            raise ValueError("Historical candles unavailable. Check Kite historical-data access or try again later.") from None
    return pd.DataFrame()


def completed_candles(candles, interval, as_of):
    """Kite timestamps mark candle starts. Compare their ends against one scan snapshot."""
    if candles.empty:
        return pd.DataFrame()
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(candles.columns):
        raise ValueError("Candle data is missing required OHLC/volume fields.")
    frame = candles.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")))
    dates = dates.tz_localize(IST) if dates.tz is None else dates.tz_convert(IST)
    frame.index = dates
    frame.index.name = "date"
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate candle timestamps were returned; this timeframe was skipped.")
    opening = frame.index.normalize() + pd.Timedelta(hours=9, minutes=15)
    closing = frame.index.normalize() + pd.Timedelta(hours=15, minutes=30)
    if interval == "day":
        ends = closing
        in_session = pd.Series(True, index=frame.index)
    else:
        minutes = {"5minute": 5, "15minute": 15, "60minute": 60}[interval]
        regular_end = frame.index + pd.Timedelta(minutes=minutes)
        # The last hourly candle (15:15) ends at 15:30, not at 16:15.
        ends = pd.DatetimeIndex([min(end, close) for end, close in zip(regular_end, closing)])
        in_session = (frame.index >= opening) & (frame.index < closing)
    frame = frame.loc[in_session & (ends <= pd.Timestamp(as_of))].copy()
    if frame.empty:
        return frame
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not frame[column].map(lambda value: pd.notna(value) and math.isfinite(value)).all():
            raise ValueError("Candle data contains missing or invalid numeric values.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame["volume"] < 0).any():
        raise ValueError("Candle data contains invalid prices or volume.")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Candle OHLC values are inconsistent.")
    return frame


def resample_to_4hour(hourly, as_of):
    """NSE-session bars: 09:15-13:15 and the shorter 13:15-15:30 closing bar.

    Never join separate trading days. A bucket is emitted only after its close
    and only when ALL expected hourly source candles are available.
    """
    if hourly.empty:
        return pd.DataFrame()
    pieces = []
    for session_day, session in hourly.groupby(hourly.index.normalize()):
        session_close = session_day + pd.Timedelta(hours=15, minutes=30)
        aggregated = session.resample("4h", origin="start_day", offset="9h15min",
                                     closed="left", label="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        for start, row in aggregated.iterrows():
            end = min(start + pd.Timedelta(hours=4), session_close)
            if end > pd.Timestamp(as_of) or start >= session_close:
                continue
            expected = pd.date_range(start, end, freq="60min", inclusive="left")
            present = session.loc[(session.index >= start) & (session.index < end)].index
            if len(expected) and present.equals(expected) and row.notna().all():
                pieces.append(pd.DataFrame([row], index=pd.DatetimeIndex([start], name="date")))
    return pd.concat(pieces).sort_index() if pieces else pd.DataFrame()


def calculate_ema(candles):
    """Use pandas directly; retain full precision for crossover comparisons."""
    if len(candles) < MINIMUM_CANDLES:
        raise ValueError(f"Need at least {MINIMUM_CANDLES} completed candles to compare two EMA 21 values.")
    frame = candles.copy()
    frame["EMA 6"] = frame["close"].ewm(span=SHORT_EMA, adjust=False).mean()
    frame["EMA 21"] = frame["close"].ewm(span=LONG_EMA, adjust=False).mean()
    return frame


def find_latest_crossover(candles, timeframe):
    """Return the last actual sign change, not the current above/below state."""
    previous_short = candles["EMA 6"].shift(1)
    previous_long = candles["EMA 21"].shift(1)
    bullish = (previous_short <= previous_long) & (candles["EMA 6"] > candles["EMA 21"])
    bearish = (previous_short >= previous_long) & (candles["EMA 6"] < candles["EMA 21"])
    eligible = pd.Series(True, index=candles.index)
    eligible.iloc[:LONG_EMA] = False  # Both compared candles have at least 21 observations.
    if timeframe != "Daily":
        # A missing intraday candle must not create a crossover across the gap.
        previous_time = candles.index.to_series().shift(1)
        same_day = candles.index.normalize() == pd.DatetimeIndex(previous_time).normalize()
        if timeframe == "4 Hour":
            adjacent = candles.index.to_series() - previous_time == pd.Timedelta(hours=4)
        else:
            minutes = {"5 Minute": 5, "15 Minute": 15, "1 Hour": 60}[timeframe]
            adjacent = candles.index.to_series() - previous_time == pd.Timedelta(minutes=minutes)
        last_start = {"5 Minute": "15:25", "15 Minute": "15:15", "1 Hour": "15:15", "4 Hour": "13:15"}[timeframe]
        overnight = ((candles.index.strftime("%H:%M") == "09:15")
                     & (previous_time.dt.strftime("%H:%M") == last_start))
        eligible &= (same_day & adjacent) | (~same_day & overnight)
    crossings = candles.loc[(bullish | bearish) & eligible]
    if crossings.empty:
        return None
    stamp = crossings.index[-1]
    row = crossings.iloc[-1]
    return {"Timeframe": timeframe, "Signal Type": "Bullish" if bullish.loc[stamp] else "Bearish",
            "Crossover Date": stamp, "Close": row["close"], "EMA 6": row["EMA 6"], "EMA 21": row["EMA 21"]}


def scan_stock(kite, stock, as_of):
    """Fetch hourly data once and reuse it for both 1 Hour and 4 Hour analysis."""
    intervals = {"Daily": ("day", 365), "5 Minute": ("5minute", 30),
                 "15 Minute": ("15minute", 60), "1 Hour": ("60minute", 180)}
    signals = []
    attempted = 0
    analyzed = 0
    hourly = pd.DataFrame()
    for timeframe in TIMEFRAMES:
        attempted += 1
        try:
            if timeframe == "4 Hour":
                frame = resample_to_4hour(hourly, as_of)
            else:
                interval, days = intervals[timeframe]
                raw = fetch_historical_data(kite, stock["Instrument Token"], interval, days, as_of)
                frame = completed_candles(raw, interval, as_of)
                if timeframe == "1 Hour":
                    hourly = frame
            if frame.empty:
                print(f"    {timeframe:<9} -> No completed candle data; skipped.")
                continue
            frame = calculate_ema(frame)
            analyzed += 1
            latest = find_latest_crossover(frame, timeframe)
            if latest:
                signals.append({"Symbol": stock["Symbol"], "Company": stock["Company"], **latest})
                stamp = latest["Crossover Date"].strftime("%Y-%m-%d %H:%M")
                print(f"    {timeframe:<9} -> {latest['Signal Type']} crossover: {stamp}")
            else:
                print(f"    {timeframe:<9} -> No crossover found.")
        except TokenException:
            print("Kite session expired or was revoked. Stopping API calls and saving signals collected so far.")
            return signals, attempted, analyzed, True
        except ValueError:
            # Keep raw parsing and upstream errors out of the terminal.
            print(f"    {timeframe:<9} -> Unavailable or insufficient candle data; skipped.")
        except Exception:
            # Never print SDK payloads, credential-bearing URLs, or raw exceptions.
            print(f"    {timeframe:<9} -> Could not process this timeframe; continuing.")
    return signals, attempted, analyzed, False


def ranked_dataframe(signals):
    """Sort real timestamps first; format dates and round only at the end."""
    if not signals:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    result = pd.DataFrame(signals)
    result = result.sort_values(["Crossover Date", "Symbol", "Timeframe"],
                                ascending=[False, True, True], kind="stable").reset_index(drop=True)
    result.insert(0, "Rank", range(1, len(result) + 1))
    result["Crossover Date"] = result["Crossover Date"].dt.strftime("%Y-%m-%d %H:%M")
    result[["Close", "EMA 6", "EMA 21"]] = result[["Close", "EMA 6", "EMA 21"]].round(2)
    return result[OUTPUT_COLUMNS]


def main():
    print("Nifty 100 | EMA 6 / EMA 21 | Daily, 5 Minute, 15 Minute, 1 Hour, 4 Hour")
    print("Only completed candles are used. Crossover dates are candle START times in IST.")
    try:
        api_key, api_secret = read_credentials()
        kite = authenticate_kite(api_key, api_secret)
        # One snapshot gives every stock the same completed-candle cutoff.
        as_of = datetime.now(IST)
        members = download_nifty100()
        mapped = map_instrument_tokens(members, get_nse_instruments(kite))
    except ValueError as error:
        print(f"ERROR: {error}")
        print("Scan did not start. Any previous results CSV is unchanged.")
        return 1
    print(f"Loaded {len(members)} official symbols; mapped {len(mapped)} NSE equities.")
    print(f"Candle cutoff: {as_of:%Y-%m-%d %H:%M:%S} IST. A full scan can take several minutes.")
    all_signals = []
    attempted = analyzed = 0
    interrupted = False
    for number, stock in enumerate(mapped, start=1):
        print(f"[{number}/{len(mapped)}] Scanning {stock['Symbol']}...")
        try:
            signals, stock_attempted, stock_analyzed, expired = scan_stock(kite, stock, as_of)
        except KeyboardInterrupt:
            print("Scan interrupted. Saving results collected from previous stocks.")
            interrupted = True
            break
        all_signals.extend(signals)
        attempted += stock_attempted
        analyzed += stock_analyzed
        if expired:
            interrupted = True
            break
    result = ranked_dataframe(all_signals)
    print("\n" + (result.to_string(index=False, float_format=lambda value: f"{value:.2f}")
                   if not result.empty else "No crossover signals found in the available completed candles."))
    try:
        result.to_csv(OUTPUT_FILE, index=False, float_format="%.2f")
    except OSError:
        print("ERROR: Cannot write the CSV. Close it in Excel and check folder permissions.")
        return 1
    bullish = int((result["Signal Type"] == "Bullish").sum())
    bearish = int((result["Signal Type"] == "Bearish").sum())
    print("\nSummary" + (" (partial scan)" if interrupted else ""))
    print(f"  Nifty 100 symbols loaded: {len(members)}")
    print(f"  Successfully mapped: {len(mapped)}")
    print(f"  Stock/timeframe combinations scanned: {attempted}")
    print(f"  Combinations with sufficient data: {analyzed}")
    print(f"  Bullish signals: {bullish}")
    print(f"  Bearish signals: {bearish}")
    print(f"  CSV output: {OUTPUT_FILE}")
    return 1 if interrupted or not analyzed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Run again with a fresh request token when ready.")
        sys.exit(1)
    except Exception:
        print("ERROR: Scanner could not finish. Check package installation, credentials format, and network access.")
        sys.exit(1)
