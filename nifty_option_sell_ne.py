"""
NIFTY CE OPTION SELL — SINGLE EXECUTION FILE
==============================================
Run:   python3 nifty_option_sell.py           (live trading)
       python3 nifty_option_sell.py --dry      (dry run — scanner + signal, no orders)
       python3 nifty_option_sell.py test        (test — fetch data NOW, show signal, ask to save CSV)
       python3 nifty_option_sell.py scanner     (standalone scanner — fetch + detect + CSV update)
       python3 nifty_option_sell.py backtest    (backtest on CSV history — no Dhan API needed)

Requires: nifty_option_chain_data.csv in /home/
Dhan token: auto-generated at startup via OAuth, cached in dhan_token.txt (reused same day)
Flow:  Dhan token → Login Tradex → Wait 9:16 → Scan (Dhan) → Update CSV → SELL on Tradex → SL after delay → Monitor → Square off at 3:20 PM
"""

import json
import base64
import sys
import time
import math
import re
import logging
import numpy as np
import pyotp
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor
import requests
import pandas as pd
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"nifty_trade_{date.today().strftime('%Y%m%d')}.log"),
    ],
)
log = logging.getLogger("nifty_sell")

# ══════════════════════════════════════════════════════════════════════════════
#  ALL CONFIGURABLE VARIABLES — EDIT HERE ONLY
# ══════════════════════════════════════════════════════════════════════════════

# --- TIMING ---
SCAN_TIME         = "09:15"   # Candle whose close is used for signals (= 9:16 open price)
ENTRY_TIME        = "09:16"   # Exact time to place the order (must be > SCAN_TIME)
EXIT_TIME         = "15:10"   # Time to square off (change to "15:20" etc.)
SL_DELAY_SECONDS  = 125       # Seconds to wait after entry before placing SL order

# --- RISK / SIZING ---
# Qty is auto-calculated: floor(SL_RISK_RS / (entry_price * SL_PERCENT))
# Example: SL_RISK_RS=1000, entry=100, SL_PERCENT=0.50 → risk/unit=50 → qty=20
SL_RISK_RS        = 1000      # Max loss in INR per trade (primary SL knob)
SL_PERCENT        = 0.50      # SL trigger: exit if price rises X% above entry (for SELL)
SKEW_SIZE_FACTOR  = 0.80      # Reduce qty by this factor for skew trades
MIN_QTY           = 4         # Minimum qty regardless of calculation
MIN_PURCHASE_AMOUNT = 450     # Ensure qty * entry_price >= this

# --- DTE FILTER ---
# Only trade on days with these DTE values. Backtest shows DTE 4/5/6 are best.
# 0=Tuesday expiry day, 1=Monday, 4=Thursday, 5=Wednesday, 6=Tuesday (new week)
ALLOWED_DTE       = [4, 5, 6] # Set to [] to disable filter (trade all DTEs)

# --- HEDGE ---
HEDGE_ENABLED         = False
HEDGE_DISTANCE_STEPS  = 6

# --- STRATEGY ---
# SCAN_SIDES: which option sides to evaluate for signals
# ["CE"] = CE only (old behaviour), ["CE", "PE"] = both (recommended)
SCAN_SIDES        = ["CE", "PE"]  # Sides to scan for overvalued signals
ALLOW_LONG        = False          # Set True to also BUY undervalued options
ATM_OVERRIDE_FACTOR = 1.5
DRY_RUN           = False          # True = scan + log only, no orders placed

# --- SEVERITY / SCANNER ---
ROBUST_Z_THRESHOLD = 1.25   # Minimum robust Z-score to flag as overvalued
ROBUST_WINDOW      = 20     # Rolling window (same-DTE rows) for Z-score
MIN_SAMPLES        = 12     # Min same-DTE history rows before generating signal
STD5               = 5
STD10              = 20
REGIME_THRESHOLD   = 1.10

# --- SKEW FALLBACK ---
SKEW_FALLBACK_ENABLED = True
SKEW_ATM_Z_MIN        = 1.00
SKEW_ATM_Z_MAX        = ROBUST_Z_THRESHOLD
SKEW_Z_THRESHOLD      = 1.50
SKEW_MIN_EDGE         = 15.0
SKEW_MAX_DISTANCE     = 3
SKEW_MIN_DTE          = 3
SKEW_SLOPE_MIN        = 0.40

# --- DHAN API (OAuth — token generated fresh daily) ---
DHAN_API_KEY = "2e042ecd"
DHAN_API_SECRET = "254912b6-5f00-4205-88f9-b9c514beda52"
DHAN_CLIENT_ID = "1102446172"
DHAN_MOBILE = "9829950174"
DHAN_PIN = "211600"
DHAN_TOTP_SECRET = "N6QJKHMQBWBNN3QWTLJ32OGPGXK3KJMC"

ACCESS_TOKEN = ""
CLIENT_ID = 1102446172

# --- DHAN INSTRUMENT ---
NIFTY_ID = 13
EXCHANGE_SEGMENT = "NSE_FNO"
INSTRUMENT = "OPTIDX"
EXPIRY_FLAG = "WEEK"
EXPIRY_CODE = 1
INTERVAL = "1"
REQUIRED_DATA = ["open", "high", "low", "close", "volume", "strike", "oi", "spot", "iv"]
PRICE_FIELD = "open"
MAX_WORKERS = 4
API_STAGGER_DELAY = 0.15
STRIKE_STEP = 50
STRIKE_COUNT = 5
STRIKE_MODE = "OFFSET"

HEADERS = {}
BASE_URL = "https://api.dhan.co/v2"


def _build_headers():
    global HEADERS
    HEADERS = {
        "access-token": str(ACCESS_TOKEN),
        "client-id": str(CLIENT_ID),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


DHAN_TOKEN_FILE = "dhan_token.txt"


def _is_token_fresh():
    import os
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
                exp_dt = datetime.utcfromtimestamp(int(exp))
                if exp_dt <= datetime.utcnow() + timedelta(minutes=5):
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
    log.info(f"Token saved to {DHAN_TOKEN_FILE}")


def _load_token():
    with open(DHAN_TOKEN_FILE, "r") as f:
        return f.read().strip()


def _generate_fresh_token():
    """Generate Dhan access token via direct HTTP API — no browser needed.

    Retries up to 3 times to handle TOTP window-boundary failures.
    If the TOTP code is generated at the very end of a 30-second window,
    the server may reject it. We wait ~31s for the next window and retry.
    """
    if not all([DHAN_CLIENT_ID, DHAN_PIN, DHAN_TOTP_SECRET]):
        log.error("Missing DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET")
        raise ValueError("Missing Dhan credentials")

    for attempt in range(3):
        totp_code = pyotp.TOTP(DHAN_TOTP_SECRET).now()
        log.info(f"[DEBUG] TOTP for {DHAN_CLIENT_ID}: {totp_code} (attempt {attempt + 1}/3)")

        url = (
            f"https://auth.dhan.co/app/generateAccessToken"
            f"?dhanClientId={DHAN_CLIENT_ID}&pin={DHAN_PIN}&totp={totp_code}"
        )

        log.info(f"[{attempt + 1}/3] Requesting access token from DhanHQ API...")
        resp = requests.post(url, timeout=20)

        if resp.status_code != 200:
            raise Exception(f"DHAN token generation failed: HTTP {resp.status_code} — {resp.text}")

        data = resp.json()

        if data.get("status") == "error":
            msg = data.get("message", str(data))
            if "totp" in msg.lower() and attempt < 2:
                log.warning(f"  TOTP rejected (window boundary?) — waiting 31s for next window... [{msg}]")
                time.sleep(31)
                continue
            raise Exception(f"DHAN token generation failed: {msg}")

        if "accessToken" not in data:
            raise Exception(f"DHAN token generation failed — no accessToken in response: {data}")

        access_token = data["accessToken"]
        expiry = data.get("expiryTime", "24h")
        log.info(f"[SUCCESS] Token generated (expires: {expiry}): {access_token[:30]}...")
        return access_token

    raise Exception("DHAN token generation failed after 3 attempts — check TOTP secret or PIN")


def generate_dhan_token(force=False):
    global ACCESS_TOKEN

    if not force and _is_token_fresh():
        ACCESS_TOKEN = _load_token()
        _build_headers()
        log.info(f"Reusing today's cached token from {DHAN_TOKEN_FILE}: {ACCESS_TOKEN[:30]}...")
        return

    log.info("No valid token for today. Generating fresh Dhan access token...")
    ACCESS_TOKEN = _generate_fresh_token()
    _save_token(ACCESS_TOKEN)
    _build_headers()
    log.info(f"Dhan token generated and cached: {ACCESS_TOKEN[:30]}...")


def refresh_dhan_token():
    log.warning("Refreshing Dhan token due to auth error...")
    generate_dhan_token(force=True)

# --- TRADEX LIVE ---
TRADEX_EMAIL = "nitimajain91@gmail.com"
TRADEX_PASSWORD = "P@ssword123"
TRADEX_URL = "https://web.tradex1.live"
HEADLESS = False
LOGIN_TIMEOUT = 15000
ACTION_TIMEOUT = 8000
SHORT_WAIT = 1.5
MEDIUM_WAIT = 3.0

# --- CSV ---
CSV_PATH = "nifty_option_chain_data.csv"
POSITION_CSV = "position_for_today.csv"
ALL_TRADES_CSV = "all_trades_data.csv"
CSV_COLUMNS = [
    "date", "day", "price",
    "atm_ce_1", "atm_pe_1",
    "itm_ce_1", "itm_ce_2", "itm_ce_3", "itm_ce_4", "itm_ce_5",
    "itm_pe_1", "itm_pe_2", "itm_pe_3", "itm_pe_4", "itm_pe_5",
    "otm_ce_1", "otm_ce_2", "otm_ce_3", "otm_ce_4", "otm_ce_5",
    "otm_pe_1", "otm_pe_2", "otm_pe_3", "otm_pe_4", "otm_pe_5",
]
POSITION_COLUMNS = [
    "date", "symbol", "strike", "dte", "signal_type", "column",
    "entry_price", "qty", "sl_price", "robust_z", "rupee_edge",
    "signal_strength", "regime_confirmed", "entry_time", "spot",
]
TRADES_COLUMNS = [
    "date", "symbol", "strike", "dte", "signal_type", "column",
    "entry_price", "exit_price", "qty", "pnl", "pnl_total",
    "sl_price", "sl_hit", "robust_z", "rupee_edge",
    "signal_strength", "regime_confirmed",
    "entry_time", "exit_time", "spot",
]


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1: DHAN DATA FETCH
# ══════════════════════════════════════════════════════════════════════════════

def get_tuesday_expiry(d):
    weekday = d.weekday()
    days_ahead = (1 - weekday) % 7
    if days_ahead == 0 and weekday != 1:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def days_to_expiry(d):
    if isinstance(d, str):
        d = datetime.strptime(d, "%d-%m-%Y").date()
    exp = get_tuesday_expiry(d)
    delta = np.busday_count(d, exp)
    return int(delta)


def fetch_rolling_data(option_type, from_date, to_date, strike):
    """Fetch option data using Dhan rollingoption API (working format)."""
    if strike is None:
        return pd.DataFrame()

    url = f"{BASE_URL}/charts/rollingoption"
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

    refreshed = False
    for attempt in range(3):
        try:
            time.sleep(API_STAGGER_DELAY)
            resp = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=20)
            if resp.status_code == 429:
                wait = 1.5 * (attempt + 1)
                log.warning(f"Rate limited (429) on {strike} {option_type}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                body = resp.text[:300]
                log.warning(f"Non-200 response for {strike} {option_type}: {resp.status_code} | {body}")
                if not refreshed and (resp.status_code in (401, 403) or "token" in body.lower() or "unauthorized" in body.lower()):
                    refresh_dhan_token()
                    refreshed = True
                    continue
                return pd.DataFrame()

            data = resp.json()

            # Data is nested under data.ce or data.pe
            key = "ce" if option_type == "CALL" else "pe"
            if "data" not in data or key not in data["data"]:
                log.warning(f"Missing data.{key} for {strike} {option_type}")
                return pd.DataFrame()

            df = pd.DataFrame(data["data"][key])
            if df.empty:
                return df

            # Convert timestamp to datetime with IST offset
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s") + pd.Timedelta(hours=5, minutes=30)
            df["time"] = df["datetime"].dt.strftime("%H:%M")

            # Debug: log first row for ATM strikes
            if strike == "ATM" and attempt == 0 and len(df) > 0:
                first = df.iloc[0]
                log.info(f"  DEBUG API sample (strike={strike}, type={option_type}): "
                         f"spot={first.get('spot', 'N/A')}, open={first.get('open', 'N/A')}, "
                         f"strike_field={first.get('strike', 'N/A')}")

            return df

        except Exception as e:
            if attempt < 2:
                time.sleep(0.5)
                continue
            log.warning(f"Fetch exception for {strike} {option_type}: {e}")
            return pd.DataFrame()

    return pd.DataFrame()


def pick_candle_at_time(df, target_time):
    if df.empty:
        return None
    match = df[df["time"] == target_time]
    if len(match) > 0:
        return match.iloc[-1]

    target_h, target_m = map(int, target_time.split(":"))
    target_mins = target_h * 60 + target_m

    df = df.copy()
    df["mins"] = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    nearby = df[(df["mins"] >= target_mins - 2) & (df["mins"] <= target_mins + 2)]
    if len(nearby) > 0:
        return nearby.iloc[-1]
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


def fetch_price_at_time(option_type, from_date, to_date, strike):
    df = fetch_rolling_data(option_type, from_date, to_date, strike)
    if df.empty:
        return None
    candle = pick_candle_at_time(df, SCAN_TIME)
    if candle is None:
        return None
    return float(candle.get(PRICE_FIELD, 0))


def col_to_meta(col):
    side = "CE" if "ce" in col else "PE"
    if col.startswith("atm"):
        return side, 0
    idx = int(col.split("_")[-1])
    return side, idx


def fetch_today_premiums(trade_date, candle_time=None):
    if candle_time is None:
        candle_time = SCAN_TIME
    fd = trade_date.strftime("%Y-%m-%d")
    t_start = time.time()

    tasks = [
        ("atm_ce_1", "CALL", build_strike_value("ATM", 0), 0),
        ("atm_pe_1", "PUT", build_strike_value("ATM", 0), 0),
    ]
    for i in range(1, STRIKE_COUNT + 1):
        tasks.append((f"itm_ce_{i}", "CALL", build_strike_value("ITM", i), i))
        tasks.append((f"otm_ce_{i}", "CALL", build_strike_value("OTM", i), i))
        tasks.append((f"itm_pe_{i}", "PUT", build_strike_value("ITM", i), i))
        tasks.append((f"otm_pe_{i}", "PUT", build_strike_value("OTM", i), i))

    log.info(f"  Fetching {len(tasks)} strikes in parallel (max {MAX_WORKERS} workers)...")
    results_map = {}
    spot_value = None

    def _fetch_one(col, opt_type, strike_val, dist):
        df = fetch_rolling_data(opt_type, fd, fd, strike_val)
        if df.empty:
            log.warning(f"  {col}: DataFrame empty for strike {strike_val}")
            return col, None, dist, None, None
        candle = pick_candle_at_time(df, candle_time)
        if candle is None:
            log.warning(f"  {col}: No candle found at {candle_time}")
            return col, None, dist, None, None

        price = float(candle.get(PRICE_FIELD, 0))
        sp = float(candle.get("spot", 0))
        strike = candle.get("strike", None)

        # Debug logging
        log.info(f"  {col}: price={price:.2f} spot={sp} strike_raw={strike} strike_val={strike_val}")

        try:
            strike = float(strike) if strike is not None else None
        except Exception:
            strike = None
        return col, price, dist, sp, strike

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_fetch_one, t[0], t[1], t[2], t[3]) for t in tasks]
        for f in futures:
            col, price, dist, sp, strike = f.result()
            results_map[col] = {"price": price, "dist": dist, "strike": strike}
            if sp and sp > 0 and spot_value is None:
                spot_value = sp

    elapsed = time.time() - t_start
    log.info(f"  All {len(tasks)} strikes fetched in {elapsed:.2f}s")

    # Debug: show what we collected
    log.info(f"  DEBUG: spot_value from candles = {spot_value}")
    log.info(f"  DEBUG: results_map keys = {list(results_map.keys())[:5]}...")

    atm_ce_strike = results_map.get("atm_ce_1", {}).get("strike")
    atm_pe_strike = results_map.get("atm_pe_1", {}).get("strike")
    log.info(f"  DEBUG: atm_ce_strike={atm_ce_strike}, atm_pe_strike={atm_pe_strike}")
    atm_strike_raw = None
    for s in (atm_ce_strike, atm_pe_strike):
        if s and s > 0:
            atm_strike_raw = s
            log.info(f"  DEBUG: Found valid strike for fallback: {atm_strike_raw}")
            break

    if spot_value is None or spot_value == 0:
        if atm_strike_raw:
            spot_value = float(atm_strike_raw)
            log.warning(f"Spot price missing (0). Using ATM strike {atm_strike_raw} as proxy spot.")
        else:
            log.error("Spot price is 0 and ATM strike missing — market may not be open")
            log.error(f"DEBUG: All strikes in results_map: {[(k, v.get('strike')) for k, v in results_map.items()]}")
            return None

    atm_ce = results_map.get("atm_ce_1", {}).get("price")
    atm_pe = results_map.get("atm_pe_1", {}).get("price")
    if atm_ce is None or atm_pe is None:
        log.error("Could not fetch ATM candles")
        return None

    atm_strike = get_atm_strike(spot_value) if spot_value else None
    if atm_strike is None and atm_strike_raw:
        atm_strike = int(round(float(atm_strike_raw) / STRIKE_STEP) * STRIKE_STEP)

    row = {
        "date": trade_date.strftime("%d-%m-%Y"),
        "day": days_to_expiry(trade_date),
        "price": spot_value,
    }

    premiums = []
    for col, data in results_map.items():
        val = data["price"]
        dist = data["dist"]
        row[col] = val
        side = "CE" if "ce" in col else "PE"
        premiums.append({"column": col, "value": val, "distance": dist, "type": side})

    missing = [p["column"] for p in premiums if p["value"] is None]
    if missing:
        log.warning(f"Missing data for: {missing}")
        premiums = [p for p in premiums if p["value"] is not None]

    return {"row": row, "premiums": premiums, "spot": spot_value, "atm_strike": atm_strike}


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2: ROBUST SEVERITY & CANDIDATE EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def compute_robust_severity(hist_series, current_value):
    hist = hist_series.dropna().tail(ROBUST_WINDOW)

    if len(hist) < MIN_SAMPLES or current_value <= 0:
        return None

    median = hist.median()
    mad = (hist - median).abs().median()

    if mad == 0:
        return None

    robust_z = 0.6745 * (current_value - median) / mad

    std_ratio = None
    regime_confirmed = False
    if len(hist) >= STD10:
        std5_val = hist.tail(STD5).std(ddof=0)
        std10_val = hist.tail(STD10).std(ddof=0)
        if std10_val > 0:
            std_ratio = std5_val / std10_val
            regime_confirmed = std_ratio > REGIME_THRESHOLD

    return {
        "robust_z": robust_z,
        "median": median,
        "mad": mad,
        "std_ratio": std_ratio,
        "regime_confirmed": regime_confirmed,
        "pct_dev": (current_value - median) / median if median > 0 else None,
    }


def evaluate_candidates(df, premiums, dte):
    same_dte = df[df["day"] == dte]
    results = []
    over = []
    under = []

    for p in premiums:
        col = p["column"]
        val = p["value"]
        dist = p["distance"]
        side = p["type"]

        if col not in same_dte.columns:
            results.append({**p, "robust_z": None, "median": None, "mad": None,
                            "std_ratio": None, "regime_confirmed": False, "pct_dev": None,
                            "rupee_edge": None, "status": "NO_DATA", "signal_strength": None})
            continue

        hist = same_dte[col].astype(float)
        sev = compute_robust_severity(hist, val)

        if sev is None:
            results.append({**p, "robust_z": None, "median": None, "mad": None,
                            "std_ratio": None, "regime_confirmed": False, "pct_dev": None,
                            "rupee_edge": None, "status": "INSUFFICIENT", "signal_strength": None})
            continue

        entry = {
            **p,
            **sev,
            "rupee_edge": val - sev["median"],
            "status": "FAIR",
            "signal_strength": None,
        }

        if side in SCAN_SIDES:
            if sev["robust_z"] >= ROBUST_Z_THRESHOLD:
                entry["status"] = "OVERVALUED"
                entry["signal_strength"] = "STRONG" if sev["regime_confirmed"] else "WEAK"
                over.append(entry)
            elif ALLOW_LONG and sev["robust_z"] <= -ROBUST_Z_THRESHOLD:
                entry["status"] = "UNDERVALUED"
                entry["signal_strength"] = "STRONG" if sev["regime_confirmed"] else "WEAK"
                under.append(entry)

        results.append(entry)

    return {"all": results, "over": over, "under": under}


def check_skew_fallback(all_results, dte):
    """all_results should already be pre-filtered to a single side by the caller."""
    if not SKEW_FALLBACK_ENABLED:
        return None
    if dte < SKEW_MIN_DTE:
        return None

    ce_results = all_results  # caller passes side-filtered list
    atm_results = [r for r in ce_results if r["distance"] == 0 and r.get("robust_z") is not None]
    if not atm_results:
        return None

    atm_z = atm_results[0]["robust_z"]

    if not (SKEW_ATM_Z_MIN <= atm_z < SKEW_ATM_Z_MAX):
        return None

    z_by_dist = {}
    for r in ce_results:
        z_by_dist[r["distance"]] = r["robust_z"]

    z_dist2 = z_by_dist.get(2)
    z_dist0 = z_by_dist.get(0)
    skew_slope = None
    if z_dist2 is not None and z_dist0 is not None:
        skew_slope = z_dist2 - z_dist0

    if skew_slope is not None and skew_slope < SKEW_SLOPE_MIN:
        return None

    skew_candidates = []
    for r in ce_results:
        if r["distance"] < 1 or r["distance"] > SKEW_MAX_DISTANCE:
            continue
        if r["robust_z"] < SKEW_Z_THRESHOLD:
            continue
        if r.get("rupee_edge", 0) < SKEW_MIN_EDGE:
            continue
        r["status"] = "SKEW_OVERVALUED"
        r["signal_strength"] = "STRONG" if r.get("regime_confirmed") else "WEAK"
        skew_candidates.append(r)

    if not skew_candidates:
        return None

    best = max(skew_candidates, key=lambda x: x["rupee_edge"])
    return {"candidate": best, "atm_z": atm_z, "skew_slope": skew_slope, "all_skew": skew_candidates}


def choose_best_candidate(candidates):
    if not candidates:
        return None

    atm_candidates = [c for c in candidates if c["distance"] == 0]
    non_atm = [c for c in candidates if c["distance"] > 0]

    best_atm = max(atm_candidates, key=lambda x: x["rupee_edge"]) if atm_candidates else None
    best_other = max(non_atm, key=lambda x: x["rupee_edge"]) if non_atm else None

    if best_atm and best_other:
        if best_other["rupee_edge"] >= ATM_OVERRIDE_FACTOR * best_atm["rupee_edge"]:
            return best_other
        return best_atm

    if best_atm:
        return best_atm
    if best_other:
        return best_other
    return None
def append_to_csv(row, csv_path):
    new_row = {col: row.get(col) for col in CSV_COLUMNS}
    new_df = pd.DataFrame([new_row])

    try:
        existing = pd.read_csv(csv_path)
        if row["date"] in existing["date"].values:
            log.info(f"Date {row['date']} already in CSV — replacing row")
            existing = existing[existing["date"] != row["date"]]
        updated = pd.concat([existing, new_df], ignore_index=True)
    except FileNotFoundError:
        updated = new_df

    updated[CSV_COLUMNS].to_csv(csv_path, index=False)
    log.info(f"CSV updated -> {csv_path} ({len(updated)} rows)")


def save_position_csv(trade_info):
    df = pd.DataFrame([{col: trade_info.get(col) for col in POSITION_COLUMNS}])
    df.to_csv(POSITION_CSV, index=False)
    log.info(f"Position saved -> {POSITION_CSV}")


def save_trade_to_history(trade_info):
    new_row = {col: trade_info.get(col) for col in TRADES_COLUMNS}
    new_df = pd.DataFrame([new_row])

    try:
        existing = pd.read_csv(ALL_TRADES_CSV)
        updated = pd.concat([existing, new_df], ignore_index=True)
    except FileNotFoundError:
        updated = new_df

    updated.to_csv(ALL_TRADES_CSV, index=False)
    log.info(f"Trade history updated -> {ALL_TRADES_CSV} ({len(updated)} trades)")


def clear_position_csv():
    import os
    if os.path.exists(POSITION_CSV):
        os.remove(POSITION_CSV)
        log.info(f"Position file cleared: {POSITION_CSV}")


def print_severity_table(results):
    print()
    header = (f"{'COLUMN':<12} {'VALUE':>8} {'DIST':>4} {'TYPE':>4} {'ROBUST_Z':>9} "
              f"{'EDGE':>8} {'MEDIAN':>8} {'STD_RATIO':>10} {'REGIME':>7} {'SIGNAL':>7} {'STATUS':<18}")
    print(header)
    print("-" * len(header))

    for r in sorted(results, key=lambda x: abs(x.get("robust_z", 0) or 0), reverse=True):
        rz = f"{r['robust_z']:.3f}" if r.get("robust_z") is not None else "N/A"
        edge = f"{r.get('rupee_edge', 0):.2f}" if r.get("rupee_edge") is not None else "N/A"
        med = f"{r.get('median', 0):.2f}" if r.get("median") is not None else "N/A"
        sr = f"{r.get('std_ratio', 0):.3f}" if r.get("std_ratio") is not None else "N/A"
        regime = "YES" if r.get("regime_confirmed") else "NO"
        sig = r.get("signal_strength") or "-"
        status = r.get("status", "")
        val = r["value"] if r["value"] is not None else 0.0

        print(f"{r['column']:<12} {val:>8.2f} {r['distance']:>4} {r['type']:>4} "
              f"{rz:>9} {edge:>8} {med:>8} {sr:>10} {regime:>7} {sig:>7} {status:<18}")

    print()


def print_signal_box(label, candidate):
    regime_str = "CONFIRMED" if candidate["regime_confirmed"] else "NOT CONFIRMED"
    sr = f"{candidate['std_ratio']:.3f}" if candidate["std_ratio"] is not None else "N/A"
    w = 54
    print()
    print(f"  +{'=' * w}+")
    print(f"  | {label:<{w}} |")
    print(f"  +{'-' * w}+")
    print(f"  | {'Strike Column':<18}: {candidate['column']:<{w - 21}} |")
    print(f"  | {'Option Type':<18}: {candidate['type']:<{w - 21}} |")
    print(f"  | {'Premium':<18}: {candidate['value']:<{w - 21}.2f} |")
    print(f"  | {'Robust Z':<18}: {candidate['robust_z']:<{w - 21}.3f} |")
    edge = f"{candidate['rupee_edge']:.2f}" if candidate.get("rupee_edge") is not None else "N/A"
    print(f"  | {'Rupee Edge':<18}: {edge:<{w - 21}} |")
    print(f"  | {'Median':<18}: {candidate['median']:<{w - 21}.2f} |")
    print(f"  | {'MAD':<18}: {candidate['mad']:<{w - 21}.2f} |")
    print(f"  | {'Distance from ATM':<18}: {candidate['distance']:<{w - 21}} |")
    print(f"  | {'Std Ratio':<18}: {sr:<{w - 21}} |")
    print(f"  | {'Regime':<18}: {regime_str:<{w - 21}} |")
    sig = candidate.get("signal_strength", "N/A")
    print(f"  | {'Signal Strength':<18}: {sig:<{w - 21}} |")
    pct = f"{candidate['pct_dev'] * 100:.1f}%" if candidate.get("pct_dev") is not None else "N/A"
    print(f"  | {'% Above Median':<18}: {pct:<{w - 21}} |")
    print(f"  +{'=' * w}+")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3: SCANNER (RUN AT 9:16)
# ══════════════════════════════════════════════════════════════════════════════

def run_scanner(trade_date=None):
    if trade_date is None:
        trade_date = date.today()

    dte = days_to_expiry(trade_date)

    print(f"\n{'=' * 60}")
    print(f"  NIFTY OPTION SELL SCANNER")
    print(f"  Date      : {trade_date.strftime('%d-%m-%Y')}")
    print(f"  DTE       : {dte}")
    print(f"  Entry     : {ENTRY_TIME}")
    print(f"  Exit      : {EXIT_TIME}")
    print(f"  Sides     : {SCAN_SIDES}")
    print(f"  Allowed DTE: {ALLOWED_DTE if ALLOWED_DTE else 'ALL'}")
    print(f"  Robust Z  : {ROBUST_Z_THRESHOLD}")
    print(f"  SL Risk   : Rs.{SL_RISK_RS} ({SL_PERCENT*100:.0f}% of entry)")
    print(f"  Regime    : std5/std{STD10} > {REGIME_THRESHOLD}")
    print(f"{'=' * 60}")

    print(f"\n[1/5] Reading CSV baseline...")
    try:
        df = pd.read_csv(CSV_PATH)
        same_dte = len(df[df["day"] == dte])
        print(f"  Loaded {len(df)} rows | {same_dte} rows for DTE={dte}")
    except FileNotFoundError:
        print(f"  ERROR: {CSV_PATH} not found")
        return None

    if same_dte < MIN_SAMPLES:
        print(f"  WARNING: Only {same_dte} samples for DTE={dte}, need {MIN_SAMPLES}")

    print(f"\n[2/5] Fetching {SCAN_TIME} close premiums via Dhan...")
    result = fetch_today_premiums(trade_date)
    if result is None:
        print("  ABORT: Could not fetch premiums")
        return None

    row = result["row"]
    premiums = result["premiums"]
    spot = result["spot"]
    atm_strike = result["atm_strike"]

    print(f"  Spot: {spot} | ATM Strike: {atm_strike} | Premiums: {len(premiums)}")

    print(f"\n[3/5] Computing robust severity (median + MAD)...")
    print(f"  Scanning sides: {SCAN_SIDES}")
    evaluation = evaluate_candidates(df, premiums, dte)

    for side in SCAN_SIDES:
        side_results = [r for r in evaluation["all"] if r["type"] == side]
        print(f"\n  --- {side} Candidates ---")
        print_severity_table(side_results)

    other_sides = [s for s in ["CE", "PE"] if s not in SCAN_SIDES]
    for side in other_sides:
        ref_results = [r for r in evaluation["all"] if r["type"] == side]
        if ref_results:
            print(f"  --- {side} (Reference Only) ---")
            print_severity_table(ref_results)

    over_count = len(evaluation["over"])
    print(f"  Overvalued candidates: {over_count} across {SCAN_SIDES}")

    print(f"\n[4/5] Selecting best candidate...")

    # Primary: ATM overvalued (any scanned side)
    atm_over = [c for c in evaluation["over"] if c["distance"] == 0]
    best_short = choose_best_candidate(atm_over)
    skew_result = None

    if best_short:
        print_signal_box(f"SHORT SIGNAL — ATM {best_short['type']} PRIMARY", best_short)
    else:
        print("\n  >> ATM not overvalued. Checking skew fallback...")
        # Skew fallback: try each scanned side
        for side in SCAN_SIDES:
            skew_result = check_skew_fallback(
                [r for r in evaluation["all"] if r["type"] == side], dte
            )
            if skew_result:
                best_short = skew_result["candidate"]
                print(f"\n  SKEW FALLBACK TRIGGERED ({side})")
                print(f"  ATM z={skew_result['atm_z']:.3f} (close but FAIR)")
                print(f"  Skew candidates found: {len(skew_result['all_skew'])}")
                for sc in sorted(skew_result['all_skew'], key=lambda x: x['rupee_edge'], reverse=True):
                    print(f"    {sc['column']}: z={sc['robust_z']:.3f} edge=Rs.{sc['rupee_edge']:.2f}")
                print_signal_box(f"SHORT SIGNAL — SKEW FALLBACK ({side})", best_short)
                break

        if not best_short:
            print("  >> No skew fallback either. No trade today.")

    if ALLOW_LONG:
        best_long = choose_best_candidate(evaluation["under"])
        if best_long:
            print_signal_box("LONG SIGNAL DETECTED", best_long)
        else:
            print("  >> No undervalued candidates. No long signal today.")

    print(f"\n[5/5] Updating CSV with today's data...")
    missing_cols = [k for k, v in row.items() if v is None and k in CSV_COLUMNS]
    if missing_cols:
        print(f"  WARNING: {len(missing_cols)} columns missing (will write None): {missing_cols}")
    append_to_csv(row, CSV_PATH)

    # --- DTE FILTER (moved after CSV update so data is always recorded) ---
    if ALLOWED_DTE and dte not in ALLOWED_DTE:
        print(f"  DTE={dte} not in ALLOWED_DTE={ALLOWED_DTE}. No trade today (CSV updated).")
        log.info(f"DTE {dte} filtered out. ALLOWED_DTE={ALLOWED_DTE}. CSV updated, skipping trade.")
        return None

    if best_short:
        best_short["spot"] = spot

    return best_short
# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 4: TRADEX LIVE BROKER (PLAYWRIGHT AUTOMATION)
# ══════════════════════════════════════════════════════════════════════════════


class TradexBroker:

    DIALOG_SELECTOR = ".MuiDialog-root"
    WL_ITEM = "div.MuiBox-root.css-j2rc6e[role='button']"
    SEARCH_INPUT = "input[placeholder='Search symbols...']"

    def __init__(self, email, password, headless=False):
        self.email = email
        self.password = password
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self._logged_in = False
        self._positions = []

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.firefox.launch(headless=self.headless)
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(ACTION_TIMEOUT)
        log.info("Browser launched (Firefox)")

    def login(self):
        page = self.page
        page.goto(TRADEX_URL, wait_until="domcontentloaded", timeout=LOGIN_TIMEOUT)
        time.sleep(SHORT_WAIT)

        page.locator("#username").fill(self.email)
        page.locator("#password").fill(self.password)
        page.locator("button[type='submit']").click()

        page.wait_for_url("**/dashboard**", timeout=LOGIN_TIMEOUT)
        time.sleep(MEDIUM_WAIT)

        try:
            cb = page.locator("input[type='checkbox']").first
            if cb.is_visible(timeout=5000):
                cb.click()
                time.sleep(0.5)
            agree = page.locator("button:has-text('I Agree')")
            if agree.is_visible(timeout=3000):
                agree.click()
                time.sleep(SHORT_WAIT)
        except Exception:
            log.warning("No agreement dialog or already dismissed")

        page.wait_for_selector(self.SEARCH_INPUT, timeout=LOGIN_TIMEOUT)
        self._logged_in = True
        log.info("Logged in to Tradex Live")

    def _dismiss_dialog(self):
        page = self.page
        try:
            close_btn = page.locator(
                ".MuiDialog-root button:has(svg[data-testid='CloseIcon']), "
                ".MuiDialog-root [aria-label='close']"
            )
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
                time.sleep(0.5)
                return True
            page.keyboard.press("Escape")
            time.sleep(0.5)
            return True
        except Exception:
            return False

    def _is_dialog_open(self):
        try:
            return self.page.locator(self.DIALOG_SELECTOR).count() > 0
        except Exception:
            return False

    def search_and_add_symbol(self, strike, option_type="CE"):
        page = self.page
        if self._is_dialog_open():
            self._dismiss_dialog()
            time.sleep(0.5)

        query = f"NIFTY {strike} {option_type}"
        log.info(f"Searching: {query}")

        search_box = page.locator(self.SEARCH_INPUT)
        search_box.click()
        search_box.fill("")
        time.sleep(0.3)
        search_box.fill(query)
        time.sleep(MEDIUM_WAIT)

        results = page.evaluate("""() => {
            var papers = document.querySelectorAll('.MuiPaper-root.MuiPaper-rounded');
            var items = [];
            for (var p = 0; p < papers.length; p++) {
                var divs = papers[p].querySelectorAll('div');
                for (var i = 0; i < divs.length; i++) {
                    var d = divs[i];
                    var text = (d.innerText || '').trim();
                    var rect = d.getBoundingClientRect();
                    var style = window.getComputedStyle(d);
                    if (style.cursor === 'pointer' && rect.height > 35 && rect.height < 65
                        && rect.top > 80 && rect.left < 400
                        && text.indexOf('NIFTY') === 0 && text.indexOf('Expiry') !== -1) {
                        var lines = text.split('\\n');
                        items.push({
                            text: text,
                            name: lines[0] ? lines[0].trim() : '',
                            x: Math.round(rect.left + rect.width / 2),
                            y: Math.round(rect.top + rect.height / 2)
                        });
                    }
                }
            }
            return items;
        }""")

        if not results:
            log.error(f"No search results for: {query}")
            return None

        log.info(f"  Found {len(results)} results")
        for r in results[:5]:
            log.info(f"    {r['name']}")

        today = datetime.now().date()
        best = None
        for r in results:
            name = r["name"]
            if str(strike) not in name or option_type not in name:
                continue
            match = re.search(r"Expiry:\s*(\d{1,2}\s+\w{3}\s+\d{4})", r["text"])
            if match:
                try:
                    exp_date = datetime.strptime(match.group(1), "%d %b %Y").date()
                    if exp_date < today:
                        continue
                    if best is None or exp_date < best["exp"]:
                        best = {"r": r, "exp": exp_date}
                except ValueError:
                    continue

        if best is None and results:
            best = {"r": results[0], "exp": None}

        if best is None:
            log.error(f"No matching result for strike={strike} type={option_type}")
            return None

        chosen = best["r"]
        already_in = "Already in watchlist" in chosen["name"]
        symbol_text = re.sub(r'\(Already in watchlist\)', '', chosen["name"]).strip()
        log.info(f"Selected: {symbol_text} | already_in_watchlist={already_in}")

        if already_in:
            page.keyboard.press("Escape")
            time.sleep(0.5)
            log.info(f"{symbol_text} already in watchlist, skipping click")
        else:
            page.mouse.click(chosen["x"], chosen["y"])
            time.sleep(SHORT_WAIT)
            if self._is_dialog_open():
                self._dismiss_dialog()
                time.sleep(0.5)
            log.info(f"Added {symbol_text} to watchlist")

        search_box = page.locator(self.SEARCH_INPUT)
        search_box.fill("")
        time.sleep(0.3)

        return symbol_text

    def _find_watchlist_item(self, symbol_text):
        page = self.page
        items = page.locator(self.WL_ITEM).all()
        search_key = symbol_text[:25]
        for item in items:
            try:
                text = item.inner_text()
                if search_key in text:
                    return item
            except Exception:
                continue
        for item in items:
            try:
                text = item.inner_text()
                parts = symbol_text.split()
                if len(parts) >= 3 and parts[-1] in text and parts[-2] in text:
                    return item
            except Exception:
                continue
        log.warning(f"Watchlist item not found for: {symbol_text}")
        return None

    def get_ltp_from_watchlist(self, symbol_text):
        try:
            item = self._find_watchlist_item(symbol_text)
            if item is None:
                return None
            text = item.inner_text()
            numbers = re.findall(r'[\d,]+\.\d+', text)
            if numbers:
                return float(numbers[0].replace(',', ''))
        except Exception as e:
            log.warning(f"Could not read LTP: {e}")
        return None

    def _open_order_dialog(self, symbol_text, side="SELL"):
        page = self.page
        if self._is_dialog_open():
            self._dismiss_dialog()
            time.sleep(0.5)

        item = self._find_watchlist_item(symbol_text)
        if item is None:
            raise Exception(f"Watchlist item not found: {symbol_text}")

        item.click()
        time.sleep(SHORT_WAIT)

        page.wait_for_selector(self.DIALOG_SELECTOR, timeout=ACTION_TIMEOUT)
        log.info("Order dialog opened")

        side_upper = side.upper()
        dialog = page.locator(self.DIALOG_SELECTOR)

        if side_upper == "SELL":
            sell_btn = dialog.locator("button:has-text('SELL')").first
            if sell_btn.count() > 0:
                sell_btn.click()
                time.sleep(0.3)
                log.info("Switched to SELL tab")
        elif side_upper == "BUY":
            buy_btn = dialog.locator("button:has-text('BUY')").first
            if buy_btn.count() > 0:
                buy_btn.click()
                time.sleep(0.3)
                log.info("Switched to BUY tab")

    def _select_product_type(self, product="INTRADAY"):
        dialog = self.page.locator(self.DIALOG_SELECTOR)
        btn = dialog.locator(f"button:has-text('{product}')")
        if btn.count() > 0:
            btn.first.click()
            time.sleep(0.3)
        else:
            log.warning(f"Product type button '{product}' not found")

    def _select_order_type(self, order_type="MARKET"):
        dialog = self.page.locator(self.DIALOG_SELECTOR)
        btn = dialog.locator(f"button:has-text('{order_type}')")
        if btn.count() > 0:
            btn.first.click()
            time.sleep(0.3)
        else:
            log.warning(f"Order type button '{order_type}' not found")

    def _set_quantity(self, qty):
        dialog = self.page.locator(self.DIALOG_SELECTOR)
        qty_inputs = dialog.locator("input").all()
        qty_input = None
        for inp in qty_inputs:
            try:
                parent_text = inp.locator("xpath=ancestor::div[1]").inner_text()
                if "Qty" in parent_text or "Quantity" in parent_text:
                    qty_input = inp
                    break
            except Exception:
                continue
        if qty_input is None and qty_inputs:
            qty_input = qty_inputs[0]
        if qty_input:
            qty_input.click()
            qty_input.fill("")
            qty_input.fill(str(qty))
            time.sleep(0.3)
        else:
            log.error("Quantity input not found in dialog")

    def _set_price(self, price):
        dialog = self.page.locator(self.DIALOG_SELECTOR)
        inputs = dialog.locator("input").all()
        price_input = None
        for inp in inputs:
            try:
                parent_text = inp.locator("xpath=ancestor::div[1]").inner_text()
                if "Price" in parent_text or "price" in parent_text:
                    price_input = inp
                    break
            except Exception:
                continue
        if price_input is None and len(inputs) >= 2:
            price_input = inputs[1]
        if price_input:
            price_input.click()
            price_input.fill("")
            price_input.fill(str(round(price, 2)))
            time.sleep(0.3)
        else:
            log.error("Price input not found in dialog")

    def _click_submit_order(self, side="SELL"):
        dialog = self.page.locator(self.DIALOG_SELECTOR)
        all_btns = dialog.locator("button").all()
        submit = None
        for btn in reversed(all_btns):
            try:
                text = btn.inner_text().strip().upper()
                if text == side.upper():
                    box = btn.bounding_box()
                    if box and box["y"] > 700:
                        submit = btn
                        break
            except Exception:
                continue
        if submit is None:
            submit = dialog.locator(f"button:has-text('{side}')").last

        try:
            if not submit.is_enabled():
                log.warning(f"{side} submit button not enabled (may need funds)")
                return False
        except Exception:
            pass

        submit.click()
        time.sleep(MEDIUM_WAIT)

        try:
            error_el = dialog.locator("[class*='alert'], [class*='error'], [class*='Alert']")
            if error_el.count() > 0:
                err_text = error_el.first.inner_text()
                if "insufficient" in err_text.lower() or "not enough" in err_text.lower():
                    log.error(f"Order failed: {err_text}")
                    return False
                log.warning(f"Alert in dialog: {err_text[:100]}")
        except Exception:
            pass

        log.info(f"{side} order submitted")
        return True

    def get_ltp_from_dialog(self):
        try:
            dialog = self.page.locator(self.DIALOG_SELECTOR)
            dialog_text = dialog.inner_text()
            ltp_match = re.search(r'LTP[\s\n]*[^\d]*([\d,]+\.\d+)', dialog_text)
            if ltp_match:
                return float(ltp_match.group(1).replace(',', ''))
            all_prices = re.findall(r'[\u20b9]\s*([\d,]+\.\d+)', dialog_text)
            if len(all_prices) >= 2:
                return float(all_prices[1].replace(',', ''))
        except Exception as e:
            log.warning(f"Could not read LTP from dialog: {e}")
        return None

    def place_sell_order(self, symbol_text, qty, order_type="MARKET", product="INTRADAY"):
        log.info(f"SELL {qty}x {symbol_text} | {order_type} | {product}")
        self._open_order_dialog(symbol_text, side="SELL")
        ltp = self.get_ltp_from_dialog()
        log.info(f"LTP from dialog: {ltp}")
        self._select_product_type(product)
        self._select_order_type(order_type)
        self._set_quantity(qty)
        success = self._click_submit_order("SELL")
        result = {
            "action": "SELL", "symbol": symbol_text, "qty": qty,
            "order_type": order_type, "product": product,
            "ltp_at_order": ltp, "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        if success:
            self._positions.append({
                "symbol": symbol_text, "side": "SHORT", "qty": qty,
                "entry_ltp": ltp, "entry_time": datetime.now(),
            })
        if self._is_dialog_open():
            self._dismiss_dialog()
        return result

    def place_buy_order(self, symbol_text, qty, order_type="MARKET", product="INTRADAY"):
        log.info(f"BUY {qty}x {symbol_text} | {order_type} | {product}")
        self._open_order_dialog(symbol_text, side="BUY")
        ltp = self.get_ltp_from_dialog()
        log.info(f"LTP from dialog: {ltp}")
        self._select_product_type(product)
        self._select_order_type(order_type)
        self._set_quantity(qty)
        success = self._click_submit_order("BUY")
        result = {
            "action": "BUY", "symbol": symbol_text, "qty": qty,
            "order_type": order_type, "product": product,
            "ltp_at_order": ltp, "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        if self._is_dialog_open():
            self._dismiss_dialog()
        return result

    def place_sl_order(self, symbol_text, qty, sl_price, product="INTRADAY"):
        log.info(f"SL BUY {qty}x {symbol_text} @ {sl_price} via Portfolio (covering short position)")
        page = self.page

        if self._is_dialog_open():
            self._dismiss_dialog()
            time.sleep(0.5)

        page.locator("button:has-text('Portfolio')").click()
        time.sleep(MEDIUM_WAIT)

        short_name = symbol_text.split()[0] if symbol_text else ""
        rows = page.locator("input[type='checkbox']").all()
        checked = False
        for cb in rows:
            try:
                parent_text = cb.locator("xpath=ancestor::tr[1]").inner_text()
            except Exception:
                try:
                    parent_text = cb.locator("xpath=ancestor::div[1]").inner_text()
                except Exception:
                    continue
            if short_name in parent_text or symbol_text[:20] in parent_text:
                if not cb.is_checked():
                    cb.click()
                    time.sleep(0.5)
                checked = True
                log.info(f"  Checked position: {short_name}")
                break

        if not checked:
            all_cbs = page.locator("input[type='checkbox']").all()
            if len(all_cbs) >= 2 and not all_cbs[1].is_checked():
                all_cbs[1].click()
                time.sleep(0.5)
                log.info("  Checked first position row (fallback)")
                checked = True

        if not checked:
            log.error("Could not find/check position checkbox")
            return {"action": "SL_BUY", "symbol": symbol_text, "success": False, "timestamp": datetime.now().isoformat()}

        sq_btn = page.locator("button:has-text('Square Off')")
        page.wait_for_selector("button:has-text('Square Off')", timeout=5000)
        sq_btn.first.click()
        time.sleep(SHORT_WAIT)

        page.wait_for_selector(self.DIALOG_SELECTOR, timeout=ACTION_TIMEOUT)
        log.info("  Square Off dialog opened")

        dialog = page.locator(self.DIALOG_SELECTOR)

        buy_btn = dialog.locator("button:has-text('BUY')").first
        if buy_btn.count() > 0:
            buy_btn.click()
            time.sleep(0.3)

        sl_btn = dialog.locator("button:has-text('SL')")
        if sl_btn.count() > 0:
            sl_btn.first.click()
            time.sleep(0.5)
            log.info("  SL order type selected")

        self._set_quantity(qty)
        self._set_price(sl_price)

        success = self._click_submit_order("BUY")
        result = {
            "action": "SL_BUY", "symbol": symbol_text, "qty": qty,
            "sl_price": sl_price, "product": product,
            "success": success, "timestamp": datetime.now().isoformat(),
        }
        if self._is_dialog_open():
            self._dismiss_dialog()

        page.locator("button:has-text('Dashboard')").click()
        time.sleep(SHORT_WAIT)

        return result

    def square_off_all(self):
        results = []
        page = self.page

        if self._is_dialog_open():
            self._dismiss_dialog()
            time.sleep(0.5)

        page.locator("button:has-text('Portfolio')").click()
        time.sleep(MEDIUM_WAIT)

        header_cb = page.locator("th input[type='checkbox'], thead input[type='checkbox']").first
        if header_cb.count() > 0:
            if not header_cb.is_checked():
                header_cb.click()
                time.sleep(0.5)
            log.info("  Checked all positions via header checkbox")

        sq_btn = page.locator("button:has-text('Square Off')")
        try:
            page.wait_for_selector("button:has-text('Square Off')", timeout=5000)
        except Exception:
            log.warning("Square Off button not found - no open positions?")
            page.locator("button:has-text('Dashboard')").click()
            time.sleep(SHORT_WAIT)
            return results

        sq_btn.first.click()
        time.sleep(SHORT_WAIT)

        dialog = page.locator(self.DIALOG_SELECTOR)
        if dialog.count() > 0:
            page.wait_for_selector(self.DIALOG_SELECTOR, timeout=ACTION_TIMEOUT)
            log.info("  Square Off dialog opened")

            sell_btn = dialog.locator("button:has-text('SELL')").first
            if sell_btn.count() > 0:
                sell_btn.click()
                time.sleep(0.3)

            self._select_order_type("MARKET")

            ltp = self.get_ltp_from_dialog()
            success = self._click_submit_order("SELL")
            results.append({
                "action": "SQUARE_OFF", "ltp_at_order": ltp,
                "success": success, "timestamp": datetime.now().isoformat(),
            })

            if self._is_dialog_open():
                self._dismiss_dialog()

        self._positions.clear()

        page.locator("button:has-text('Dashboard')").click()
        time.sleep(SHORT_WAIT)

        return results

    def get_positions(self):
        return list(self._positions)

    def close(self):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:
            log.warning(f"Error during close: {e}")
        log.info("Browser closed")

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 5: BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _find_expiry_row(df, entry_idx, entry_dte):
    entry_date = pd.to_datetime(df.iloc[entry_idx]["date"], format="%d-%m-%Y")
    expiry_target = entry_date + timedelta(days=entry_dte)

    for i in range(entry_idx + 1, len(df)):
        row_date = pd.to_datetime(df.iloc[i]["date"], format="%d-%m-%Y")
        if row_date >= expiry_target and int(df.iloc[i]["day"]) == 0:
            return i
        if row_date > expiry_target + timedelta(days=2):
            break

    for i in range(entry_idx + 1, len(df)):
        row_date = pd.to_datetime(df.iloc[i]["date"], format="%d-%m-%Y")
        if row_date > entry_date and int(df.iloc[i]["day"]) == 0:
            return i
        if row_date > expiry_target + timedelta(days=5):
            break
    return None

def _get_intermediate_rows(df, entry_idx, expiry_idx, col):
    prices = []
    for i in range(entry_idx + 1, expiry_idx + 1):
        val = df.iloc[i].get(col)
        if pd.notna(val):
            prices.append(float(val))
    return prices

def run_backtest():
    print(f"\n{'=' * 60}")
    print(f"  BACKTEST — NIFTY CE OPTION SELL")
    print(f"{'=' * 60}")

    df = pd.read_csv(CSV_PATH)
    trades = []

    for idx in range(MIN_SAMPLES, len(df)):
        row = df.iloc[idx]
        trade_date_str = row["date"]
        dte = int(row["day"])

        same_dte_before = df.iloc[:idx]
        same_dte_before = same_dte_before[same_dte_before["day"] == dte]
        if len(same_dte_before) < MIN_SAMPLES:
            continue

        premiums = []
        for col in CSV_COLUMNS[3:]:
            val = row.get(col)
            if pd.notna(val):
                side, dist = col_to_meta(col)
                premiums.append({"column": col, "value": float(val), "distance": dist, "type": side})

        evaluation = evaluate_candidates(same_dte_before, premiums, dte)

        atm_over = [c for c in evaluation["over"] if c["distance"] == 0]
        best = choose_best_candidate(atm_over)
        signal_type = "ATM"

        if not best:
            skew = check_skew_fallback(evaluation["all"], dte)
            if skew:
                best = skew["candidate"]
                signal_type = "SKEW"

        if not best:
            continue

        expiry_idx = _find_expiry_row(df, idx, dte)
        if expiry_idx is None:
            continue

        col = best["column"]
        entry_price = best["value"]
        exit_val = df.iloc[expiry_idx].get(col)
        if pd.isna(exit_val):
            continue
        exit_price = float(exit_val)

        intermediate = _get_intermediate_rows(df, idx, expiry_idx, col)
        mae = max(intermediate) - entry_price if intermediate else 0
        max_fav = entry_price - min(intermediate) if intermediate else 0

        pnl = entry_price - exit_price

        trades.append({
            "date": trade_date_str, "dte": dte, "signal": signal_type,
            "column": col, "entry": entry_price, "exit": exit_price,
            "pnl": pnl, "mae": mae, "max_favorable": max_fav,
            "robust_z": best["robust_z"],
            "strength": best.get("signal_strength", "N/A"),
        })

    if not trades:
        print("No trades found.")
        return pd.DataFrame()

    tdf = pd.DataFrame(trades)
    atm_trades = tdf[tdf["signal"] == "ATM"]
    skew_trades = tdf[tdf["signal"] == "SKEW"]

    print(f"\nTotal Trades: {len(tdf)} | ATM: {len(atm_trades)} | SKEW: {len(skew_trades)}")
    print(f"Win Rate: {(tdf['pnl'] > 0).mean() * 100:.1f}%")
    print(f"Total PnL: Rs.{tdf['pnl'].sum():.2f}")
    print(f"Avg PnL: Rs.{tdf['pnl'].mean():.2f}")
    print(f"Max PnL: Rs.{tdf['pnl'].max():.2f}")
    print(f"Max Loss: Rs.{tdf['pnl'].min():.2f}")
    print(f"Avg MAE: Rs.{tdf['mae'].mean():.2f}")

    print(f"\nTrade Details:")
    print(f"{'DATE':<12} {'DTE':>3} {'SIGNAL':<15} {'COLUMN':<12} "
          f"{'ENTRY':>8} {'EXIT':>8} {'PNL':>8} {'MAE':>8} {'MAX_FAV':>8} {'Z':>7} {'STR':<7}")
    print("-" * 100)

    for _, t in tdf.iterrows():
        print(f"{t['date']:<12} {t['dte']:>3} {t['signal']:<15} {t['column']:<12} "
              f"{t['entry']:>8.2f} {t['exit']:>8.2f} {t['pnl']:>8.2f} {t['mae']:>8.2f} "
              f"{t['max_favorable']:>8.2f} {t['robust_z']:>7.3f} {t['strength']:<7}")

    print(f"\nPnL Distribution:")
    for bucket_name, subset in [("ATM", atm_trades), ("SKEW", skew_trades)]:
        if len(subset) == 0:
            continue
        pnls = subset["pnl"]
        print(f"  {bucket_name}: min={pnls.min():.2f} | p25={pnls.quantile(0.25):.2f} | "
              f"median={pnls.median():.2f} | p75={pnls.quantile(0.75):.2f} | max={pnls.max():.2f}")

    return tdf

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 6: LIVE TRADER (MAIN ORCHESTRATOR)
# ══════════════════════════════════════════════════════════════════════════════

def wait_until(target_time_str):
    now = datetime.now()
    target_h, target_m = map(int, target_time_str.split(":"))
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

    if now >= target:
        log.info(f"Already past {target_time_str} — proceeding immediately")
        return True

    diff = (target - now).total_seconds()
    log.info(f"Waiting {diff:.0f}s until {target_time_str} (current: {now.strftime('%H:%M:%S')})")

    while datetime.now() < target:
        remaining = (target - datetime.now()).total_seconds()
        if remaining > 60:
            time.sleep(30)
            log.info(f"  ...{remaining:.0f}s remaining until {target_time_str}")
        elif remaining > 5:
            time.sleep(1)
        else:
            time.sleep(0.2)

    log.info(f"Reached {target_time_str}")
    return True

def calculate_qty(entry_price, signal_type="ATM"):
    if entry_price <= 0:
        return MIN_QTY

    sl_price = entry_price * (1 + SL_PERCENT)
    risk_per_unit = sl_price - entry_price

    if risk_per_unit <= 0:
        return MIN_QTY

    raw_qty = math.floor(SL_RISK_RS / risk_per_unit)

    if signal_type == "SKEW":
        raw_qty = math.floor(raw_qty * SKEW_SIZE_FACTOR)

    if raw_qty < MIN_QTY:
        log.warning(f"Calculated qty={raw_qty} < MIN_QTY={MIN_QTY}. Using MIN_QTY.")
        raw_qty = MIN_QTY

    min_amount_qty = math.ceil(MIN_PURCHASE_AMOUNT / entry_price) if entry_price > 0 else MIN_QTY
    if raw_qty < min_amount_qty:
        log.warning(f"qty={raw_qty} below min purchase amount. Adjusting to {min_amount_qty}.")
        raw_qty = min_amount_qty

    return raw_qty

def _refresh_csv_with_entry_candle(trade_date):
    """Re-fetch all strike prices using ENTRY_TIME candle and overwrite today's CSV row.

    Called after the order fires so the CSV always stores 9:16 prices (not 9:15).
    append_to_csv handles duplicate dates by replacing the existing row.
    """
    import threading
    def _do_refresh():
        log.info(f"[CSV] Waiting 20s for {ENTRY_TIME} candle to settle before CSV refresh...")
        time.sleep(20)
        log.info(f"[CSV] Re-fetching {ENTRY_TIME} candle prices to update CSV...")
        result = fetch_today_premiums(trade_date, candle_time=ENTRY_TIME)
        if result and result.get("row"):
            append_to_csv(result["row"], CSV_PATH)
            log.info(f"[CSV] Row overwritten with {ENTRY_TIME} candle prices")
        else:
            log.warning(f"[CSV] Could not fetch {ENTRY_TIME} candle — CSV keeps {SCAN_TIME} prices")
    t = threading.Thread(target=_do_refresh, daemon=True)
    t.start()
    return t


def run_live():
    log.info("=" * 60)
    log.info("  NIFTY OPTION SELL — LIVE TRADER")
    log.info(f"  Date       : {date.today()}")
    log.info(f"  Entry      : {ENTRY_TIME}")
    log.info(f"  Exit       : {EXIT_TIME}")
    log.info(f"  Sides      : {SCAN_SIDES}")
    log.info(f"  Allowed DTE: {ALLOWED_DTE if ALLOWED_DTE else 'ALL'}")
    log.info(f"  SL Risk    : Rs.{SL_RISK_RS} | SL%: {SL_PERCENT*100:.0f}%")
    log.info(f"  SL Delay   : {SL_DELAY_SECONDS}s after entry")
    log.info(f"  Hedge      : {HEDGE_ENABLED}")
    log.info(f"  Dry Run    : {DRY_RUN}")
    log.info("=" * 60)

    log.info("\n[PHASE 0] Generating fresh Dhan access token...")
    try:
        generate_dhan_token()
    except Exception as e:
        log.error(f"FATAL: Dhan token generation failed — {e}")
        log.error("Cannot proceed without a valid access token. Exiting.")
        sys.exit(1)

    now = datetime.now()
    exit_h, exit_m = map(int, EXIT_TIME.split(":"))
    exit_dt = now.replace(hour=exit_h, minute=exit_m, second=0)

    if now > exit_dt:
        log.warning(f"Already past exit time {EXIT_TIME}. Updating today's CSV data and exiting.")
        run_scanner(trade_date=date.today())
        return

    broker = None
    position_open = False
    symbol_text = None
    entry_price = None
    qty = 0
    sl_placed = False

    try:
        # PHASE 1: Launch browser
        log.info("\n[PHASE 1] Launching Tradex Live browser...")
        if not DRY_RUN:
            broker = TradexBroker(TRADEX_EMAIL, TRADEX_PASSWORD, headless=HEADLESS)
            broker.start()
            broker.login()
            log.info("Tradex Live ready")
        else:
            log.info("DRY RUN — skipping broker launch")

        # PHASE 2: Wait for entry time (9:15 candle completes at exactly 9:16:00)
        log.info(f"\n[PHASE 2] Waiting until {ENTRY_TIME} — 9:15 candle will be complete at this moment...")
        wait_until(ENTRY_TIME)

        # PHASE 3: Fetch 9:15 close prices and compute signals
        # 9:15 candle is now fully closed. Fetch immediately for fastest order placement.
        log.info(f"\n[PHASE 3] Running scanner (9:15 close = price at {ENTRY_TIME})...")
        best_short = run_scanner(trade_date=date.today())

        if best_short is None:
            log.info("NO SIGNAL TODAY. Waiting ~20s then refreshing CSV with 9:16 prices...")
            time.sleep(20)
            _refresh_csv_with_entry_candle(date.today())
            return

        strike_col = best_short["column"]
        strike_dist = best_short["distance"]
        robust_z = best_short["robust_z"]
        rupee_edge = best_short.get("rupee_edge", 0)
        premium = best_short["value"]
        signal_type = "SKEW" if best_short.get("status") == "SKEW_OVERVALUED" else "ATM"
        spot = best_short.get("spot", 0)

        log.info(f"\n  SIGNAL DETECTED:")
        log.info(f"    Column    : {strike_col}")
        log.info(f"    Type      : {signal_type}")
        log.info(f"    Premium   : Rs.{premium:.2f}")
        log.info(f"    Robust Z  : {robust_z:.3f}")
        log.info(f"    Rupee Edge: Rs.{rupee_edge:.2f}")
        log.info(f"    Distance  : {strike_dist}")

        atm_strike = get_atm_strike(spot)

        if "otm" in strike_col:
            target_strike = atm_strike + strike_dist * STRIKE_STEP
        elif "itm" in strike_col:
            target_strike = atm_strike - strike_dist * STRIKE_STEP
        else:
            target_strike = atm_strike

        option_type = best_short.get("type", "CE")   # CE or PE from signal
        entry_price = premium
        qty = calculate_qty(entry_price, signal_type)
        sl_price = round(entry_price * (1 + SL_PERCENT), 2)
        risk_total = round((sl_price - entry_price) * qty, 2)

        log.info(f"\n  TRADE PLAN:")
        log.info(f"    Spot          : {spot}")
        log.info(f"    ATM Strike    : {atm_strike}")
        log.info(f"    Target Strike : {target_strike}")
        log.info(f"    Side          : SHORT {option_type}")
        log.info(f"    Entry Price   : Rs.{entry_price:.2f}")
        log.info(f"    SL Price      : Rs.{sl_price:.2f}  (+{SL_PERCENT*100:.0f}% above entry)")
        log.info(f"    Quantity      : {qty}  (SL_RISK_RS={SL_RISK_RS} / risk_per_unit={sl_price-entry_price:.2f})")
        log.info(f"    Max Risk      : Rs.{risk_total:.2f}")

        if DRY_RUN:
            log.info("\n  [DRY RUN] Would place SELL order here. Skipping.")
            log.info("  DRY RUN complete. Exiting.")
            return

        # PHASE 4: Place SELL order
        log.info(f"\n[PHASE 4] Placing SELL order on Tradex Live at {datetime.now().strftime('%H:%M:%S')}...")

        symbol_text = broker.search_and_add_symbol(target_strike, option_type)
        if symbol_text is None:
            log.error(f"Could not find {target_strike} {option_type} on Tradex. Aborting.")
            return

        sell_result = broker.place_sell_order(symbol_text, qty, order_type="MARKET", product="INTRADAY")
        log.info(f"  Sell result: {sell_result}")

        if not sell_result["success"]:
            log.error("SELL order FAILED. Aborting.")
            return

        position_open = True
        actual_entry = sell_result.get("ltp_at_order") or entry_price
        sl_price = round(actual_entry * (1 + SL_PERCENT), 2)
        entry_timestamp = datetime.now().isoformat()

        # Refresh CSV with 9:16 candle prices in background (overwrites 9:15 row)
        _refresh_csv_with_entry_candle(date.today())

        log.info(f"  SHORT POSITION OPEN: {qty}x {symbol_text} @ ~{actual_entry}")
        log.info(f"  SL will be placed at Rs.{sl_price} after {SL_DELAY_SECONDS}s delay")

        trade_info = {
            "date": date.today().strftime("%d-%m-%Y"),
            "symbol": symbol_text,
            "strike": target_strike,
            "dte": days_to_expiry(date.today()),
            "signal_type": signal_type,
            "column": strike_col,
            "entry_price": actual_entry,
            "qty": qty,
            "sl_price": sl_price,
            "robust_z": robust_z,
            "rupee_edge": rupee_edge,
            "signal_strength": best_short.get("signal_strength", ""),
            "regime_confirmed": best_short.get("regime_confirmed", False),
            "entry_time": entry_timestamp,
            "spot": spot,
        }
        save_position_csv(trade_info)

        # PHASE 4b: Hedge (optional)
        if HEDGE_ENABLED:
            hedge_strike = target_strike + HEDGE_DISTANCE_STEPS * STRIKE_STEP
            log.info(f"\n[PHASE 4b] Placing HEDGE: BUY {hedge_strike} {option_type}...")
            hedge_symbol = broker.search_and_add_symbol(hedge_strike, option_type)
            if hedge_symbol:
                hedge_result = broker.place_buy_order(hedge_symbol, qty, order_type="MARKET",
                                                      product="INTRADAY")
                log.info(f"  Hedge result: {hedge_result}")
            else:
                log.warning(f"Could not find hedge strike {hedge_strike}. Continuing without hedge.")

        # PHASE 5: Wait then place SL
        log.info(f"\n[PHASE 5] Waiting {SL_DELAY_SECONDS}s before placing SL order...")
        for elapsed in range(SL_DELAY_SECONDS):
            time.sleep(1)
            if elapsed % 30 == 0 and elapsed > 0:
                log.info(f"  ...{elapsed}s / {SL_DELAY_SECONDS}s")
            if datetime.now() >= exit_dt:
                log.warning("Exit time reached during SL wait. Skipping SL, going to square off.")
                break
        else:
            log.info(f"\n[PHASE 5b] Placing SL order @ Rs.{sl_price}...")
            sl_result = broker.place_sl_order(symbol_text, qty, sl_price, product="INTRADAY")
            log.info(f"  SL result: {sl_result}")
            sl_placed = sl_result["success"]
            if not sl_placed:
                log.warning("SL order failed! Will manually exit at exit time.")

        # PHASE 6: Monitor until exit
        log.info(f"\n[PHASE 6] Monitoring until {EXIT_TIME}...")
        while datetime.now() < exit_dt:
            remaining = (exit_dt - datetime.now()).total_seconds()

            ltp = broker.get_ltp_from_watchlist(symbol_text)
            if ltp:
                unrealized = round((actual_entry - ltp) * qty, 2)
                log.info(f"  LTP={ltp:.2f} | Entry={actual_entry:.2f} | "
                         f"PnL=Rs.{unrealized:.2f} | {remaining:.0f}s to exit")
                if sl_placed and ltp >= sl_price:
                    log.warning(f"  LTP {ltp} >= SL {sl_price} — SL likely triggered")
                    position_open = False
                    break

            sleep_interval = 60 if remaining > 300 else 30
            time.sleep(sleep_interval)

        # PHASE 7: Square off
        sl_hit = False
        exit_ltp = None

        if position_open:
            log.info(f"\n[PHASE 7] EXIT TIME {EXIT_TIME} — Squaring off positions...")
            results = broker.square_off_all()
            for r in results:
                log.info(f"  Square-off: {r}")
                if r.get("ltp_at_order"):
                    exit_ltp = r["ltp_at_order"]
            position_open = False
            log.info("All positions squared off")
        else:
            log.info("Position already closed (SL triggered or manual)")
            sl_hit = True
            exit_ltp = sl_price

        exit_timestamp = datetime.now().isoformat()
        final_exit = exit_ltp or sl_price
        pnl_per_unit = round(actual_entry - final_exit, 2)
        pnl_total = round(pnl_per_unit * qty, 2)

        trade_info.update({
            "exit_price": final_exit,
            "exit_time": exit_timestamp,
            "pnl": pnl_per_unit,
            "pnl_total": pnl_total,
            "sl_hit": sl_hit,
        })
        save_trade_to_history(trade_info)
        clear_position_csv()

        log.info("\n" + "=" * 60)
        log.info("  SESSION COMPLETE")
        log.info(f"  Entry : {qty}x {symbol_text} @ {actual_entry:.2f}")
        log.info(f"  Exit  : @ {final_exit:.2f}")
        log.info(f"  PnL   : Rs.{pnl_per_unit:.2f}/unit | Rs.{pnl_total:.2f} total")
        log.info(f"  SL Hit: {sl_hit} | Signal: {signal_type} | Z: {robust_z:.3f}")
        log.info("=" * 60)

    except KeyboardInterrupt:
        log.warning("\nManual interrupt received!")
        if position_open and broker:
            log.info("Squaring off due to interrupt...")
            results = broker.square_off_all()
            for r in results:
                log.info(f"  {r}")

    except Exception as e:
        log.error(f"\nFATAL ERROR: {e}", exc_info=True)
        if position_open and broker:
            log.info("Attempting emergency square-off...")
            try:
                results = broker.square_off_all()
                for r in results:
                    log.info(f"  {r}")
            except Exception as e2:
                log.error(f"Emergency square-off also failed: {e2}")
                log.error(f"MANUAL INTERVENTION REQUIRED: Close {qty}x {symbol_text}")

    finally:
        if broker:
            broker.close()
        log.info("Live trader finished.")

def run_test():
    log.info("=" * 60)
    log.info("  TEST MODE — Full flow (Dhan + Tradex), no time wait")
    log.info(f"  Date      : {date.today()}")
    log.info(f"  Time now  : {datetime.now().strftime('%H:%M:%S')}")
    log.info("=" * 60)

    try:
        generate_dhan_token()
    except Exception as e:
        log.error(f"FATAL: Dhan token generation failed — {e}")
        log.error("Cannot proceed without a valid access token. Exiting.")
        return

    trade_date = date.today()
    dte = days_to_expiry(trade_date)

    print(f"\n[TEST 1/6] Fetching {ENTRY_TIME} premiums via Dhan API...")
    result = fetch_today_premiums(trade_date)

    if result is None:
        print("  FAILED: Could not fetch premiums. Check if market was open today and 9:16 has passed.")
        return

    row = result["row"]
    premiums = result["premiums"]
    spot = result["spot"]
    atm_strike = result["atm_strike"]

    print(f"  Spot       : {spot}")
    print(f"  ATM Strike : {atm_strike}")
    print(f"  DTE        : {dte}")
    print(f"  Premiums fetched: {len(premiums)}")

    print(f"\n[TEST 2/6] Raw premium values at {ENTRY_TIME}:")
    for p in sorted(premiums, key=lambda x: (x["type"], x["distance"])):
        val = f"Rs.{p['value']:.2f}" if p["value"] else "MISSING"
        print(f"  {p['column']:<12} {p['type']:>2} dist={p['distance']}  {val}")

    print(f"\n[TEST 3/6] Running scanner logic...")
    best = None
    atm_over = []
    signal_type = "ATM"
    try:
        df = pd.read_csv(CSV_PATH)
        same_dte = len(df[df["day"] == dte])
        print(f"  CSV: {len(df)} rows | {same_dte} rows for DTE={dte}")

        if same_dte < MIN_SAMPLES:
            print(
                f"  WARNING: Only {same_dte} samples for DTE={dte}, need {MIN_SAMPLES}. Severity may not compute.")

        evaluation = evaluate_candidates(df, premiums, dte)
        all_results = evaluation["all"]
        side_results = [r for r in all_results if r["type"] in SCAN_SIDES]

        print(f"\n  --- Severity Table ({SCAN_SIDES}) ---")
        print_severity_table(side_results)

        atm_over = [c for c in evaluation["over"] if c["distance"] == 0]
        best = choose_best_candidate(atm_over)
        if best:
            print_signal_box("TEST: SHORT SIGNAL — ATM PRIMARY", best)
        else:
            print("  ATM not overvalued. Checking skew fallback...")
            skew = check_skew_fallback(evaluation["all"], dte)
            if skew:
                best = skew["candidate"]
                signal_type = "SKEW"
                print_signal_box("TEST: SHORT SIGNAL — SKEW FALLBACK", best)
            else:
                print("  No signal today.")

    except FileNotFoundError:
        print(f"  CSV not found at {CSV_PATH}")

    print(f"\n[TEST 4/6] CSV update...")
    missing = [k for k, v in row.items() if v is None and k in CSV_COLUMNS]
    if missing:
        print(f"  WARNING: {len(missing)} columns missing (writing with None): {missing}")
    print(f"  Appending row: date={row['date']} DTE={row['day']} spot={row['price']}")
    append_to_csv(row, CSV_PATH)

    if best is None:
        print(f"\n  No signal — choosing ATM CE for Tradex UI test anyway")
        target_strike = atm_strike
        entry_price = row.get("atm_ce_1", 100)
    else:
        entry_price = best["value"]
        if "otm" in best["column"]:
            target_strike = atm_strike + best["distance"] * STRIKE_STEP
        elif "itm" in best["column"]:
            target_strike = atm_strike - best["distance"] * STRIKE_STEP
        else:
            target_strike = atm_strike

    qty = calculate_qty(entry_price, signal_type)
    sl_price = round(entry_price * (1 + SL_PERCENT), 2)

    option_type = best["type"] if best else SCAN_SIDES[0]
    print(f"\n  TRADE PLAN:")
    print(f"    Target Strike : {target_strike} {option_type}")
    print(f"    Entry Price   : Rs.{entry_price:.2f}")
    print(f"    SL Price      : Rs.{sl_price:.2f}")
    print(f"    Quantity      : {qty}")
    print(f"    Max Risk      : Rs.{round((sl_price - entry_price) * qty, 2)}")

    print(f"\n[TEST 5/6] Tradex Live — UI automation test...")
    broker = None
    try:
        broker = TradexBroker(TRADEX_EMAIL, TRADEX_PASSWORD, headless=HEADLESS)
        broker.start()
        broker.login()
        print("  ✓ Login successful")

        symbol_text = broker.search_and_add_symbol(target_strike, option_type)
        if symbol_text:
            print(f"  ✓ Symbol found: {symbol_text}")
        else:
            print(f"  ✗ Could not find {target_strike} {option_type}")
            return

        ltp = broker.get_ltp_from_watchlist(symbol_text)
        print(f"  ✓ LTP from watchlist: {ltp}")

        print(f"\n  Ready to place SELL order: {qty}x {symbol_text}")
        confirm = input("  Place SELL order on Tradex? (y/n): ").strip().lower()

        if confirm == "y":
            sell_result = broker.place_sell_order(symbol_text, qty, order_type="MARKET", product="INTRADAY")
            print(f"  Sell result: {sell_result}")

            if sell_result["success"]:
                actual_entry = sell_result.get("ltp_at_order") or entry_price
                sl_price = round(actual_entry * (1 + SL_PERCENT), 2)

                trade_info = {
                    "date": date.today().strftime("%d-%m-%Y"),
                    "symbol": symbol_text,
                    "strike": target_strike,
                    "dte": dte,
                    "signal_type": signal_type,
                    "column": best["column"] if best else "atm_ce_1",
                    "entry_price": actual_entry,
                    "qty": qty,
                    "sl_price": sl_price,
                    "robust_z": best["robust_z"] if best else 0,
                    "rupee_edge": best.get("rupee_edge", 0) if best else 0,
                    "signal_strength": best.get("signal_strength", "") if best else "",
                    "regime_confirmed": best.get("regime_confirmed", False) if best else False,
                    "entry_time": datetime.now().isoformat(),
                    "spot": spot,
                }
                save_position_csv(trade_info)
                print(f"  ✓ Position saved to {POSITION_CSV}")

                print(f"\n  Waiting {SL_DELAY_SECONDS}s before SL order...")
                confirm_sl = input(f"  Place SL order after delay? (y/n): ").strip().lower()

                if confirm_sl == "y":
                    for elapsed in range(SL_DELAY_SECONDS):
                        time.sleep(1)
                        if elapsed % 30 == 0 and elapsed > 0:
                            print(f"    ...{elapsed}s / {SL_DELAY_SECONDS}s")

                    sl_result = broker.place_sl_order(symbol_text, qty, sl_price, product="INTRADAY")
                    print(f"  SL result: {sl_result}")
                else:
                    print("  Skipped SL order")

                print(f"\n  Position is OPEN. Square off now?")
                confirm_exit = input("  Square off? (y/n): ").strip().lower()

                if confirm_exit == "y":
                    exit_results = broker.square_off_all()
                    for r in exit_results:
                        print(f"  Exit: {r}")

                    exit_ltp = None
                    for r in exit_results:
                        if r.get("ltp_at_order"):
                            exit_ltp = r["ltp_at_order"]

                    final_exit = exit_ltp or actual_entry
                    pnl_per = round(actual_entry - final_exit, 2)
                    pnl_total = round(pnl_per * qty, 2)

                    trade_info.update({
                        "exit_price": final_exit,
                        "exit_time": datetime.now().isoformat(),
                        "pnl": pnl_per,
                        "pnl_total": pnl_total,
                        "sl_hit": False,
                    })
                    save_trade_to_history(trade_info)
                    clear_position_csv()
                    print(f"  ✓ Trade saved to {ALL_TRADES_CSV}")
                    print(f"  PnL: Rs.{pnl_per:.2f}/unit | Rs.{pnl_total:.2f} total")
                else:
                    print("  Position left OPEN — square off manually or run live mode")
            else:
                print("  ✗ SELL order failed — check Tradex UI for errors")
        else:
            print("  Skipped order placement. UI test only.")

    except Exception as e:
        log.error(f"  Tradex test error: {e}", exc_info=True)
    finally:
        if broker:
            print(f"\n  Close browser?")
            confirm_close = input("  Close? (y/n): ").strip().lower()
            if confirm_close == "y":
                broker.close()
            else:
                print("  Browser left open. Close manually.")

    print(f"\n[TEST 6/6] Summary")
    print(f"{'=' * 60}")
    print("  TEST COMPLETE")
    print(f"{'=' * 60}")

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        _build_headers()
        run_backtest()
    elif len(sys.argv) > 1 and sys.argv[1] == "scanner":
        generate_dhan_token()
        run_scanner()
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    elif len(sys.argv) > 1 and sys.argv[1] == "--dry":
        DRY_RUN = True
        run_live()
    else:
        run_live()