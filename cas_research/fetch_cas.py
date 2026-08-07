"""Dhan rollingoption fetcher for CAS closing-window research.

Fetches 1-min option candles (open/high/low/close/volume/strike/oi/spot/iv)
via POST /v2/charts/rollingoption, relative strikes ATM/ITMn/OTMn, CE+PE,
date chunks <=20 days, throttle >=1.2s/request, dedupe on
(date_ist, time_ist, strike, option_type, series).

Appends to per-series master CSVs under data/: <series>_master.csv
Series examples: NIFTY_WEEK, NIFTY_MONTH, BANKNIFTY_MONTH, SENSEX_WEEK.

Usage:
  python3 fetch_cas.py --series NIFTY_WEEK --from 2026-08-03 --to 2026-08-07 --width 5
  python3 fetch_cas.py --daily-update          # appends yesterday..today for all default series
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

import dhan_auth

BASE_URL = "https://api.dhan.co/v2"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
THROTTLE_S = 1.25

INDEX_META = {
    "NIFTY": {"securityId": 13, "exchangeSegment": "NSE_FNO", "step": 50},
    "BANKNIFTY": {"securityId": 25, "exchangeSegment": "NSE_FNO", "step": 100},
    "SENSEX": {"securityId": 51, "exchangeSegment": "BSE_FNO", "step": 100},
}

DEFAULT_SERIES = ["NIFTY_WEEK", "NIFTY_MONTH", "BANKNIFTY_MONTH", "SENSEX_WEEK"]

_last_call = [0.0]


def _throttled_post(url, payload, hdrs, tries=4):
    for attempt in range(tries):
        wait = THROTTLE_S - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        resp = requests.post(url, headers=hdrs, data=json.dumps(payload), timeout=30)
        if resp.status_code == 429:
            back = 2.5 * (attempt + 1)
            print(f"  429 rate-limited, backing off {back:.0f}s")
            time.sleep(back)
            continue
        return resp
    return resp


def _pick_ts_convention(ts_series: pd.Series) -> str:
    """Dhan epochs are ambiguous: sometimes UTC (need +5:30), sometimes IST-naive.
    Pick per-response the convention whose times land inside 09:00-15:45."""

    def frac_in_session(dt: pd.Series) -> float:
        mins = dt.dt.hour * 60 + dt.dt.minute
        return ((mins >= 540) & (mins <= 945)).mean()

    naive = pd.to_datetime(ts_series, unit="s")
    shifted = naive + pd.Timedelta(hours=5, minutes=30)
    return "utc+530" if frac_in_session(shifted) >= frac_in_session(naive) else "ist-naive"


def fetch_leg(index: str, expiry_flag: str, strike_label: str, option_type: str,
              d_from: str, d_to: str, hdrs: dict) -> pd.DataFrame:
    meta = INDEX_META[index]
    payload = {
        "exchangeSegment": meta["exchangeSegment"],
        "interval": "1",
        "securityId": meta["securityId"],
        "instrument": "OPTIDX",
        "expiryFlag": expiry_flag,
        "expiryCode": 1,
        "strike": strike_label,
        "drvOptionType": option_type,
        "requiredData": ["open", "high", "low", "close", "volume", "strike", "oi", "spot", "iv"],
        "fromDate": d_from,
        "toDate": d_to,
    }
    resp = _throttled_post(f"{BASE_URL}/charts/rollingoption", payload, hdrs)
    if resp.status_code != 200:
        print(f"  WARN {index} {expiry_flag} {strike_label} {option_type} {d_from}->{d_to}: "
              f"HTTP {resp.status_code} {resp.text[:150]}")
        return pd.DataFrame()
    data = resp.json()
    key = "ce" if option_type == "CALL" else "pe"
    rows = (data.get("data") or {}).get(key) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "timestamp" not in df.columns or df.empty:
        return pd.DataFrame()
    conv = _pick_ts_convention(df["timestamp"])
    dt = pd.to_datetime(df["timestamp"], unit="s")
    if conv == "utc+530":
        dt = dt + pd.Timedelta(hours=5, minutes=30)
    df["datetime_ist"] = dt
    df["ts_convention"] = conv
    df["strike_label"] = strike_label
    df["option_type"] = "CE" if option_type == "CALL" else "PE"
    return df


def strike_labels(width: int) -> list[str]:
    labels = ["ATM"]
    for i in range(1, width + 1):
        labels += [f"ITM{i}", f"OTM{i}"]
    return labels


def chunks(d0: date, d1: date, max_days: int = 18):
    cur = d0
    while cur <= d1:
        end = min(cur + timedelta(days=max_days - 1), d1)
        yield cur, end
        cur = end + timedelta(days=1)


def fetch_series(series: str, d_from: date, d_to: date, width: int, hdrs: dict) -> pd.DataFrame:
    index, flag = series.rsplit("_", 1)
    frames = []
    labels = strike_labels(width)
    n_req = 0
    for c0, c1 in chunks(d_from, d_to):
        # toDate is exclusive-ish in some Dhan chart APIs; pad by +1 day to be safe
        f, t = c0.strftime("%Y-%m-%d"), (c1 + timedelta(days=1)).strftime("%Y-%m-%d")
        for lab in labels:
            for opt in ("CALL", "PUT"):
                df = fetch_leg(index, flag, lab, opt, f, t, hdrs)
                n_req += 1
                if not df.empty:
                    frames.append(df)
        print(f"[{series}] chunk {c0}->{c1}: {sum(len(x) for x in frames)} rows so far ({n_req} req)")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["series"] = series
    out["date_ist"] = out["datetime_ist"].dt.date.astype(str)
    out["time_ist"] = out["datetime_ist"].dt.strftime("%H:%M")
    # keep only requested calendar range (post-padding)
    out = out[(out["date_ist"] >= str(d_from)) & (out["date_ist"] <= str(d_to))]
    return out


def append_master(series: str, df: pd.DataFrame) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{series}_master.csv")
    if df.empty:
        print(f"[{series}] nothing to append")
        return path
    cols = ["series", "date_ist", "time_ist", "datetime_ist", "timestamp", "ts_convention",
            "strike_label", "option_type", "strike", "spot", "open", "high", "low", "close",
            "volume", "oi", "iv"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]
    if os.path.exists(path):
        old = pd.read_csv(path)
        df = pd.concat([old, df], ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(subset=["date_ist", "time_ist", "strike", "option_type"], keep="last")
    df = df.sort_values(["date_ist", "time_ist", "option_type", "strike"])
    df.to_csv(path, index=False)
    print(f"[{series}] master now {len(df)} rows (deduped {before - len(df)}) -> {path}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="e.g. NIFTY_WEEK, BANKNIFTY_MONTH, SENSEX_WEEK")
    ap.add_argument("--from", dest="d_from")
    ap.add_argument("--to", dest="d_to")
    ap.add_argument("--width", type=int, default=5, help="strikes each side of ATM")
    ap.add_argument("--daily-update", action="store_true")
    args = ap.parse_args()

    hdrs = dhan_auth.headers()

    if args.daily_update:
        today = date.today()
        d0 = today - timedelta(days=4)
        for s in DEFAULT_SERIES:
            df = fetch_series(s, d0, today, args.width, hdrs)
            append_master(s, df)
        return

    if not (args.series and args.d_from and args.d_to):
        ap.error("--series/--from/--to required unless --daily-update")
    d0 = datetime.strptime(args.d_from, "%Y-%m-%d").date()
    d1 = datetime.strptime(args.d_to, "%Y-%m-%d").date()
    df = fetch_series(args.series, d0, d1, args.width, hdrs)
    append_master(args.series, df)


if __name__ == "__main__":
    main()
