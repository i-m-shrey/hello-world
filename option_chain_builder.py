import json
import time
import base64
import os
import pyotp
import threading
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pandas as pd

# --- DHAN CREDENTIALS ---
DHAN_CLIENT_ID = "1102446172"
DHAN_PIN = "211600"
DHAN_TOTP_SECRET = "N6QJKHMQBWBNN3QWTLJ32OGPGXK3KJMC"
DHAN_TOKEN_FILE = "dhan_token.txt"

ACCESS_TOKEN = ""   # populated at runtime by generate_dhan_token()
CLIENT_ID = "1102446172"

NIFTY_ID = 13
EXCHANGE_SEGMENT = "NSE_FNO"
INSTRUMENT = "OPTIDX"
EXPIRY_FLAG = "WEEK"
EXPIRY_CODE = 1
INTERVAL = "1"
REQUIRED_DATA = ["open", "high", "low", "close", "volume", "strike", "oi", "spot", "iv"]

STRIKE_STEP = 50
STRIKE_COUNT = 5

# ── CONFIGURABLE SNAPSHOT TIMES ──────────────────────────────────────────────
# Both times are fetched per day and stored as separate columns in the CSV.
# Set EXIT_TIME = None to disable and only fetch ENTRY_TIME.
ENTRY_TIME = "09:16"
# EXIT_TIME  = "15:10"       # Set to None to disable exit snapshot
EXIT_TIME  = None       # Set to None to disable exit snapshot
# ─────────────────────────────────────────────────────────────────────────────

PRICE_FIELD = "open"
EXACT_TIME_ONLY = True
STRIKE_MODE = "OFFSET"  # OFFSET uses ITM1/OTM1, NUMERIC uses strike prices

START_DATE = date(2026, 4, 1)
END_DATE = date.today()

OUTPUT_CSV = "nifty_option_chain_data_new.csv"

OVERVALUED_Z = 1.25
UNDERVALUED_Z = 1.25
SEVERITY_TOLERANCE = 0.15
PROXIMITY_PENALTY = 0.08
ALLOW_LONG = True
HEDGE_DISTANCE_STEPS = 6
USE_LONG_HEDGE = False

MAX_WORKERS    = 4      # parallel strike fetches per day
MAX_RPS        = 3      # max requests per second globally — Dhan rolling-option limit ~3 req/s
RETRY_COUNT    = 4      # retries on non-200 / 429
RETRY_DELAY    = 3.0    # base backoff (seconds); doubles on each 429 retry
PRINT_PROGRESS = True
PRINT_EVERY    = 1

# ── Global rate limiter (token-bucket style) ─────────────────────────────────
# Each thread reserves a time-slot atomically, then sleeps OUTSIDE the lock.
# This prevents the burst pattern where all workers queue behind a sleeping
# lock-holder and then fire simultaneously when it releases.
_rl_lock       = threading.Lock()
_rl_next_slot  = 0.0          # earliest time the next request may be sent
_rl_interval   = 1.0 / MAX_RPS

def _rate_throttle():
    """Reserve the next available slot and sleep until it arrives.

    The lock is held only for the instant needed to read/update _rl_next_slot,
    NOT during the sleep. This allows all workers to schedule their slots
    in rapid succession and then sleep concurrently — eliminating the burst
    that caused 429s when sleep() was called inside the lock.
    """
    global _rl_next_slot
    with _rl_lock:
        now          = time.monotonic()
        # Slot is either the next interval after the last, or now (if idle)
        slot         = max(_rl_next_slot, now)
        _rl_next_slot = slot + _rl_interval
    # Sleep OUTSIDE the lock — workers sleep concurrently, not serially
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)

# When a 429 is received, pause the global slot queue to drain the burst
def _rate_throttle_pause(extra_seconds):
    """Push all pending slots forward by extra_seconds after a 429."""
    global _rl_next_slot
    with _rl_lock:
        _rl_next_slot = time.monotonic() + extra_seconds

HEADERS = {}  # built by _build_headers() after token generation


def _build_headers():
    global HEADERS
    HEADERS = {
        "access-token": ACCESS_TOKEN,
        "client-id": CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_token_fresh():
    if not os.path.exists(DHAN_TOKEN_FILE):
        return False
    try:
        with open(DHAN_TOKEN_FILE, "r") as f:
            token = f.read().strip()
    except Exception:
        return False
    if len(token) <= 20:
        return False
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
            exp = payload.get("exp")
            if exp:
                from datetime import timezone
                exp_dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
                now_utc = datetime.now(tz=timezone.utc)
                if exp_dt <= now_utc + timedelta(minutes=5):
                    return False
                return True
    except Exception:
        pass
    mod_time = datetime.fromtimestamp(os.path.getmtime(DHAN_TOKEN_FILE))
    if mod_time.date() != date.today():
        return False
    return True


def _save_token(token):
    with open(DHAN_TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"Token saved to {DHAN_TOKEN_FILE}")


def _load_token():
    with open(DHAN_TOKEN_FILE, "r") as f:
        return f.read().strip()


def _generate_fresh_token():
    """Generate Dhan access token via direct HTTP API.

    Retries up to 3 times to handle TOTP window-boundary failures.
    """
    if not all([DHAN_CLIENT_ID, DHAN_PIN, DHAN_TOTP_SECRET]):
        raise ValueError("Missing Dhan credentials (DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET)")

    for attempt in range(3):
        totp_code = pyotp.TOTP(DHAN_TOTP_SECRET).now()
        print(f"[DEBUG] TOTP for {DHAN_CLIENT_ID}: {totp_code} (attempt {attempt + 1}/3)")

        url = (
            f"https://auth.dhan.co/app/generateAccessToken"
            f"?dhanClientId={DHAN_CLIENT_ID}&pin={DHAN_PIN}&totp={totp_code}"
        )
        print(f"[{attempt + 1}/3] Requesting access token from DhanHQ API...")
        resp = requests.post(url, timeout=20)

        if resp.status_code != 200:
            raise Exception(f"DHAN token generation failed: HTTP {resp.status_code} — {resp.text}")

        data = resp.json()

        if data.get("status") == "error":
            msg = data.get("message", str(data))
            if "totp" in msg.lower() and attempt < 2:
                print(f"  TOTP rejected (window boundary?) — waiting 31s for next window... [{msg}]")
                time.sleep(31)
                continue
            raise Exception(f"DHAN token generation failed: {msg}")

        if "accessToken" not in data:
            raise Exception(f"DHAN token generation failed — no accessToken in response: {data}")

        access_token = data["accessToken"]
        expiry = data.get("expiryTime", "24h")
        print(f"[SUCCESS] Token generated (expires: {expiry}): {access_token[:30]}...")
        return access_token

    raise Exception("DHAN token generation failed after 3 attempts — check TOTP secret or PIN")


def generate_dhan_token(force=False):
    global ACCESS_TOKEN
    if not force and _is_token_fresh():
        ACCESS_TOKEN = _load_token()
        _build_headers()
        print(f"Reusing today's cached token: {ACCESS_TOKEN[:30]}...")
        return
    print("No valid token for today. Generating fresh Dhan access token...")
    ACCESS_TOKEN = _generate_fresh_token()
    _save_token(ACCESS_TOKEN)
    _build_headers()
    print(f"Dhan token generated and cached: {ACCESS_TOKEN[:30]}...")


# ─────────────────────────────────────────────────────────────────────────────
#  DATA FETCH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def next_tuesday(d):
    weekday = d.weekday()
    delta = (1 - weekday) % 7
    return d + timedelta(days=delta)


def days_to_expiry(d):
    return (next_tuesday(d) - d).days


def fetch_rolling_data(option_type, from_date, to_date, strike):
    """Fetch full-day candle data for one strike.

    Applies a global rate throttle before each attempt so all workers
    combined stay within MAX_RPS.  Uses exponential backoff + jitter on 429.
    """
    if strike is None:
        return pd.DataFrame()
    url = "https://api.dhan.co/v2/charts/rollingoption"
    payload = {
        "exchangeSegment": EXCHANGE_SEGMENT,
        "interval": INTERVAL,
        "securityId": NIFTY_ID,
        "instrument": INSTRUMENT,
        "expiryFlag": EXPIRY_FLAG,
        "expiryCode": int(EXPIRY_CODE),
        "strike": strike,
        "drvOptionType": option_type,
        "requiredData": REQUIRED_DATA,
        "fromDate": from_date,
        "toDate": to_date,
    }
    last_error = None
    backoff = RETRY_DELAY

    for attempt in range(RETRY_COUNT + 1):
        _rate_throttle()          # global throttle — applied before every attempt
        try:
            response = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=30)

            if response.status_code == 429:
                # Push the global slot queue forward so OTHER workers also slow down,
                # not just this one thread.  This prevents a cascade of 429s.
                import random as _rnd
                jitter = backoff * 0.2 * (2 * _rnd.random() - 1)
                wait   = backoff + jitter
                _rate_throttle_pause(wait)   # slow down all workers globally
                if PRINT_PROGRESS:
                    print(f"  [429] Rate limited ({strike} {option_type}) — "
                          f"global pause {wait:.1f}s (attempt {attempt+1}/{RETRY_COUNT+1})")
                time.sleep(wait)
                backoff = min(backoff * 2, 30)   # cap at 30s
                continue

            if response.status_code != 200:
                last_error = f"{response.status_code} {response.text[:120]}"
                if PRINT_PROGRESS:
                    print(f"  [ERR] {strike} {option_type}: {last_error}")
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 15)
                continue

            data = response.json()
            key  = "ce" if option_type == "CALL" else "pe"
            if "data" not in data or key not in data["data"]:
                return pd.DataFrame()

            df = pd.DataFrame(data["data"][key])
            if df.empty:
                return df
            df["datetime"] = (
                pd.to_datetime(df["timestamp"], unit="s")
                + pd.Timedelta(hours=5, minutes=30)
            )
            return df

        except Exception as exc:
            last_error = str(exc)
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 15)

    if PRINT_PROGRESS and last_error:
        print(f"  [FAIL] {option_type} {from_date} strike={strike}: {last_error}")
    return pd.DataFrame()


def pick_candle_at_time(df, time_str):
    """Return the candle at exactly time_str (HH:MM). Returns None if not found."""
    if df.empty or time_str is None:
        return None
    target = datetime.strptime(time_str, "%H:%M").time()
    df = df.sort_values("datetime")
    exact = df[df["datetime"].dt.time == target]
    if not exact.empty:
        return exact.iloc[0]
    if EXACT_TIME_ONLY:
        return None
    after = df[df["datetime"].dt.time > target]
    if not after.empty:
        return after.iloc[0]
    return df.iloc[-1]


def get_atm_strike(spot):
    return int(round(spot / STRIKE_STEP) * STRIKE_STEP)


def build_strike_value(kind, index, atm_strike=None):
    if kind == "ATM":
        return "ATM"
    if STRIKE_MODE == "OFFSET":
        return f"{kind}{index}"
    if atm_strike is None:
        return None
    if kind == "ITM":
        return str(atm_strike - index * STRIKE_STEP)
    return str(atm_strike + index * STRIKE_STEP)


def fetch_prices_at_times(option_type, from_date, to_date, strike):
    """Fetch a strike once and return prices at BOTH ENTRY_TIME and EXIT_TIME.

    Returns (entry_price, exit_price).  Either may be None if data is missing.
    A single API call serves both time snapshots — halves total API calls vs
    fetching each snapshot separately.
    """
    df = fetch_rolling_data(option_type, from_date, to_date, strike)
    if df.empty:
        return None, None

    entry_candle = pick_candle_at_time(df, ENTRY_TIME)
    entry_price  = float(entry_candle.get(PRICE_FIELD, 0)) if entry_candle is not None else None

    exit_price = None
    if EXIT_TIME is not None:
        exit_candle = pick_candle_at_time(df, EXIT_TIME)
        exit_price  = float(exit_candle.get(PRICE_FIELD, 0)) if exit_candle is not None else None

    return entry_price, exit_price


# ─────────────────────────────────────────────────────────────────────────────
#  COLUMN HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _entry_columns():
    """Return ordered list of entry-time data columns (no prefix)."""
    cols = ["atm_ce_1", "atm_pe_1"]
    for i in range(1, STRIKE_COUNT + 1):
        cols.append(f"itm_ce_{i}")
    for i in range(1, STRIKE_COUNT + 1):
        cols.append(f"itm_pe_{i}")
    for i in range(1, STRIKE_COUNT + 1):
        cols.append(f"otm_ce_{i}")
    for i in range(1, STRIKE_COUNT + 1):
        cols.append(f"otm_pe_{i}")
    return cols


def _exit_columns():
    """Return ordered list of exit-time data columns (exit_ prefix)."""
    return ["exit_" + c for c in _entry_columns()]


def all_output_columns():
    """Full ordered column list for the output CSV."""
    cols = ["date", "day", "price"]
    cols += _entry_columns()
    if EXIT_TIME is not None:
        cols += ["exit_price"] + _exit_columns()
    return cols


# ─────────────────────────────────────────────────────────────────────────────
#  ROW BUILDER  (single fetch per strike — serves both ENTRY and EXIT times)
# ─────────────────────────────────────────────────────────────────────────────

def build_chain_row(trade_date):
    """Build one CSV row for trade_date.

    KEY OPTIMISATION: each strike is fetched ONCE from the Dhan API.
    The returned day's candles are used to extract prices at both
    ENTRY_TIME and EXIT_TIME — eliminating duplicate API calls that
    the old _fetch_snapshot approach made.

    API calls per day:
      Old: 22 calls × 2 snapshots = 44
      New: 22 calls (ATM CE + ATM PE + 20 ITM/OTM) = 22  (-50%)
    """
    from_date = to_date = trade_date.strftime("%Y-%m-%d")

    # ── Step 1: fetch ATM CE+PE first to determine spot and ATM strike ───────
    ce_atm_df = fetch_rolling_data("CALL", from_date, to_date, build_strike_value("ATM", 0))
    pe_atm_df = fetch_rolling_data("PUT",  from_date, to_date, build_strike_value("ATM", 0))

    ce_entry_candle = pick_candle_at_time(ce_atm_df, ENTRY_TIME)
    pe_entry_candle = pick_candle_at_time(pe_atm_df, ENTRY_TIME)

    if ce_entry_candle is None or pe_entry_candle is None:
        if PRINT_PROGRESS:
            print(f"  Skip {trade_date}: no ATM data at {ENTRY_TIME}")
        return None

    spot_entry = float(ce_entry_candle.get("spot", 0))
    if spot_entry == 0:
        return None
    atm_strike = get_atm_strike(spot_entry)

    row = {
        "date":    trade_date.strftime("%d-%m-%Y"),
        "day":     days_to_expiry(trade_date),
        "price":   spot_entry,
        "atm_ce_1": float(ce_entry_candle.get(PRICE_FIELD, 0)),
        "atm_pe_1": float(pe_entry_candle.get(PRICE_FIELD, 0)),
    }

    # Extract ATM exit prices from the SAME dataframes — no extra API call
    if EXIT_TIME is not None:
        ce_exit_candle = pick_candle_at_time(ce_atm_df, EXIT_TIME)
        pe_exit_candle = pick_candle_at_time(pe_atm_df, EXIT_TIME)
        row["exit_price"]    = float(ce_exit_candle.get("spot", 0)) if ce_exit_candle is not None else None
        row["exit_atm_ce_1"] = float(ce_exit_candle.get(PRICE_FIELD, 0)) if ce_exit_candle is not None else None
        row["exit_atm_pe_1"] = float(pe_exit_candle.get(PRICE_FIELD, 0)) if pe_exit_candle is not None else None

    # ── Step 2: build ITM/OTM tasks ──────────────────────────────────────────
    tasks = []
    for i in range(1, STRIKE_COUNT + 1):
        tasks.append((f"itm_ce_{i}", "CALL", build_strike_value("ITM", i, atm_strike)))
        tasks.append((f"otm_ce_{i}", "CALL", build_strike_value("OTM", i, atm_strike)))
        tasks.append((f"itm_pe_{i}", "PUT",  build_strike_value("ITM", i, atm_strike)))
        tasks.append((f"otm_pe_{i}", "PUT",  build_strike_value("OTM", i, atm_strike)))

    # ── Step 3: fetch all strikes in parallel, extract BOTH times each ───────
    def _fetch_one(col, opt_type, strike_val):
        entry_p, exit_p = fetch_prices_at_times(opt_type, from_date, to_date, strike_val)
        return col, entry_p, exit_p

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_one, col, opt_type, strike_val): col
            for col, opt_type, strike_val in tasks
        }
        for future in as_completed(futures):
            try:
                col, entry_p, exit_p = future.result()
            except Exception:
                col = futures[future]
                entry_p = exit_p = None
            row[col] = entry_p
            if EXIT_TIME is not None:
                row[f"exit_{col}"] = exit_p

    # ── Step 4: validate entry prices (exit is allowed to be partial) ─────────
    entry_required = ["atm_ce_1", "atm_pe_1"] + \
                     [f"{k}_{i}" for k in ("itm_ce","itm_pe","otm_ce","otm_pe")
                      for i in range(1, STRIKE_COUNT + 1)]
    missing_entry = [c for c in entry_required if row.get(c) is None]
    if missing_entry:
        if PRINT_PROGRESS:
            print(f"  Skip {trade_date}: missing entry strikes {missing_entry}")
        return None

    return row


# ─────────────────────────────────────────────────────────────────────────────
#  CSV BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_option_chain_csv():
    rows = []
    current    = START_DATE
    total_days = (END_DATE - START_DATE).days + 1
    processed  = 0
    t_start    = time.monotonic()

    # Estimate: 22 API calls/day ÷ MAX_RPS req/s  (rough lower bound)
    calls_per_day = 2 + 4 * STRIKE_COUNT   # ATM CE+PE + ITM/OTM pairs
    est_sec_per_day = calls_per_day / MAX_RPS

    times_label = ENTRY_TIME + (f" + {EXIT_TIME}" if EXIT_TIME else "")
    api_calls   = calls_per_day  # same calls serve both times now
    if PRINT_PROGRESS:
        print(f"Starting build: {START_DATE} to {END_DATE}  total_days={total_days}")
        print(f"Snapshot times : [{times_label}]")
        print(f"API calls/day  : {api_calls}  (single fetch serves both times)")
        print(f"Workers        : {MAX_WORKERS}   Rate limit: {MAX_RPS} req/s")
        print(f"Est. time      : ~{int(total_days * 5/7 * est_sec_per_day)}s total\n")

    while current <= END_DATE:
        if current.weekday() < 5:
            t_day   = time.monotonic()
            row     = build_chain_row(current)
            elapsed = time.monotonic() - t_day

            if row:
                rows.append(row)
                status = "ok"
            else:
                status = "miss"
            processed += 1

            if PRINT_PROGRESS and processed % PRINT_EVERY == 0:
                # Running ETA
                elapsed_total = time.monotonic() - t_start
                rate          = processed / elapsed_total if elapsed_total > 0 else 1
                bdays_left    = sum(
                    1 for d in range((END_DATE - current).days + 1)
                    if (current + timedelta(days=d)).weekday() < 5
                )
                eta_sec = int(bdays_left / rate) if rate > 0 else 0
                eta_str = f"{eta_sec//60}m{eta_sec%60:02d}s" if eta_sec > 60 else f"{eta_sec}s"
                print(f"{current}  {status:<4}  rows={len(rows):>4}  "
                      f"day_took={elapsed:.1f}s  ETA={eta_str}")
        else:
            pass   # skip weekends silently
        current += timedelta(days=1)

    if not rows:
        if PRINT_PROGRESS:
            print("No rows collected")
        return

    columns = all_output_columns()
    df = pd.DataFrame(rows)
    # Ensure all expected columns present
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df = df[columns]

    if PRINT_PROGRESS:
        entry_cols  = len(_entry_columns()) + 3   # +date,day,price
        exit_cols   = (len(_exit_columns()) + 1) if EXIT_TIME else 0
        print(f"\nWriting CSV: {len(rows)} rows x {len(columns)} columns -> {OUTPUT_CSV}")
        print(f"  Entry columns ({ENTRY_TIME}): {entry_cols}")
        if EXIT_TIME:
            print(f"  Exit columns  ({EXIT_TIME}): {exit_cols}")

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Done. Saved to {OUTPUT_CSV}")


# ─────────────────────────────────────────────────────────────────────────────
#  ANALYSIS HELPERS (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

def compute_severity(df, column, current_value, dte):
    hist = df[df["day"] == dte][column].dropna().tail(50)
    if hist.empty or current_value <= 0:
        return None
    mean = hist.mean()
    std = hist.std(ddof=0)
    if std == 0 or mean == 0:
        return None
    z = (current_value - mean) / std
    pct = (current_value - mean) / mean
    return {"z": z, "pct": pct, "mean": mean, "std": std}


def choose_candidate(candidates):
    if not candidates:
        return None
    candidates = sorted(candidates, key=lambda x: x["adjusted"], reverse=True)
    top = candidates[0]
    if len(candidates) == 1:
        return top
    second = candidates[1]
    if abs(top["adjusted"] - second["adjusted"]) <= SEVERITY_TOLERANCE:
        if top["distance"] > second["distance"]:
            return second
    return top


def evaluate_over_undervaluation(df, current_premiums, dte):
    over_candidates = []
    under_candidates = []

    for item in current_premiums:
        col = item["column"]
        value = item["value"]
        distance = item["distance"]
        sev = compute_severity(df, col, value, dte)
        if sev is None:
            continue
        adjusted = sev["z"] - PROXIMITY_PENALTY * distance
        record = {"column": col, "value": value, "distance": distance, "severity": sev, "adjusted": adjusted}
        if sev["z"] >= OVERVALUED_Z:
            over_candidates.append(record)
        if sev["z"] <= -UNDERVALUED_Z:
            under_candidates.append(record)

    best_over = choose_candidate(over_candidates)
    best_under = choose_candidate(under_candidates)

    if ALLOW_LONG and best_under and (not best_over or abs(best_under["adjusted"]) > abs(best_over["adjusted"])):
        return {"side": "LONG", "candidate": best_under}
    if best_over:
        return {"side": "SHORT", "candidate": best_over}
    return None


def get_today_premiums(trade_date):
    from_date = trade_date.strftime("%Y-%m-%d")
    to_date = from_date

    ce_atm_df = fetch_rolling_data("CALL", from_date, to_date, build_strike_value("ATM", 0))
    pe_atm_df = fetch_rolling_data("PUT",  from_date, to_date, build_strike_value("ATM", 0))

    ce_atm_candle = pick_candle_at_time(ce_atm_df, ENTRY_TIME)
    pe_atm_candle = pick_candle_at_time(pe_atm_df, ENTRY_TIME)

    if ce_atm_candle is None or pe_atm_candle is None:
        return None

    spot = float(ce_atm_candle.get("spot", 0))
    atm_strike = get_atm_strike(spot)

    premiums = [
        {"column": "atm_ce_1", "value": float(ce_atm_candle.get(PRICE_FIELD, 0)), "distance": 0},
        {"column": "atm_pe_1", "value": float(pe_atm_candle.get(PRICE_FIELD, 0)), "distance": 0},
    ]

    tasks = []
    for i in range(1, STRIKE_COUNT + 1):
        tasks.append((f"itm_ce_{i}", "CALL", build_strike_value("ITM", i, atm_strike), i))
        tasks.append((f"otm_ce_{i}", "CALL", build_strike_value("OTM", i, atm_strike), i))
        tasks.append((f"itm_pe_{i}", "PUT",  build_strike_value("ITM", i, atm_strike), i))
        tasks.append((f"otm_pe_{i}", "PUT",  build_strike_value("OTM", i, atm_strike), i))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_prices_at_times, t[1], from_date, to_date, t[2]): t
            for t in tasks
        }
        for future in as_completed(futures):
            col, _, _, dist = futures[future]
            try:
                entry_p, _ = future.result()   # only need entry price here
            except Exception:
                entry_p = None
            premiums.append({"column": col, "value": entry_p, "distance": dist})

    if any(p["value"] is None for p in premiums):
        if PRINT_PROGRESS:
            print(f"Missing {ENTRY_TIME} data for {trade_date}")
        return None

    return atm_strike, premiums


def pick_hedge_strike(atm_strike, option_type, distance_steps):
    if option_type == "CALL":
        return atm_strike + distance_steps * STRIKE_STEP
    return atm_strike - distance_steps * STRIKE_STEP


def main():
    generate_dhan_token()
    build_option_chain_csv()


if __name__ == "__main__":
    main()
