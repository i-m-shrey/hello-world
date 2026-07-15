"""FORWARD TEST AUDIT (Phase 2, July 2026) — paper-trades the index PULLBACK
models on LIVE data feeds for the 90-day forward test. NO ORDERS, EVER — this
script only reads bars (copy_rates_*) and writes CSV logs.

Models under forward test (validated 2022+ only -> short-history flag):
    PULLBACK dip3 rr3 on GER40, US30, JPN225 (H1):
      uptrend: ema50 > ema200 AND close > ema200
      dip: close was below ema20 within the last 3 closed bars
      trigger: close back above ema20 (previous close not above its ema20)
      -> theoretical LONG at the NEXT H1 open, stop = signal_close - 2*ATR50,
         TP = entry + 3 * risk, time exit 96 H1 bars, max 2 signals/day.

Logs:
    forward_signals.csv    every trigger (also the ones skipped by the day cap)
    forward_tradebook.csv  every closed paper trade with M5-RESOLVED MAE/MFE
    forward_state.json     open paper positions (restart-proof)

Run on the owner's machine (any terminal, read-only): python forward_test_audit.py
Review weekly:                                        python forward_test_audit.py --report
After 90 days: compare realized WR / avg R / MAE vs the backtest line
(US30 +0.096, JPN225 +0.111, GER40 +0.096 avg R; drift > 20 points on 20+
trades = flag). NOTE: no pivot/swing logic is used; the house rule for any
future pivot logic is EXACTLY 5 closed candles left and right (PIVOT_K = 5).
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SYMBOLS = ("GER40", "US30", "JPN225")
SIGNALS_CSV = "forward_signals.csv"
TRADEBOOK_CSV = "forward_tradebook.csv"
STATE_JSON = "forward_state.json"
MAX_PER_DAY = 2
MAX_HOLD_H1 = 96
STOP_ATR = 2.0
RR = 3.0
POLL_SEC = 60
PIVOT_K = 5   # house rule for any future pivot logic: exactly 5L/5R closed candles


def attach():
    import MetaTrader5 as mt5
    src = open("live_mt5_bot.py", encoding="utf-8").read()

    def grab(pat):
        m = re.search(pat, src, re.M)
        if not m:
            sys.exit(f"cannot find {pat} in live_mt5_bot.py")
        return m.group(1)
    ok = mt5.initialize(grab(r'^MT5_TERMINAL_PATH\s*=\s*"(.+)"').encode().decode("unicode_escape"),
                        login=int(grab(r"^MT5_ACCOUNT\s*=\s*(\d+)")),
                        password=grab(r'^MT5_PASSWORD\s*=\s*"([^"]+)"'),
                        server=grab(r'^MT5_SERVER\s*=\s*"([^"]+)"'))
    if not ok:
        sys.exit(f"initialize failed: {mt5.last_error()}")
    return mt5


def broker_name(mt5, s):
    for cand in (s, s + ".i", s + "m", s + ".cash"):
        if mt5.symbol_info(cand) is not None:
            mt5.symbol_select(cand, True)
            return cand
    return None


def load_state():
    try:
        return json.load(open(STATE_JSON))
    except Exception:
        return {"open": [], "last_bar": {}, "per_day": {}}


def save_state(st):
    json.dump(st, open(STATE_JSON, "w"), indent=1, default=str)


def append_csv(path, row, header):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def h1_frame(mt5, bsym):
    r = mt5.copy_rates_from_pos(bsym, mt5.TIMEFRAME_H1, 0, 300)
    if r is None or len(r) < 220:
        return None
    df = pd.DataFrame(r)
    c = df["close"]
    prev = c.shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    for s in (20, 50, 200):
        df[f"ema{s}"] = c.ewm(span=s, adjust=False).mean()
    return df


def signal_on_closed(df):
    """PULLBACK dip3 on the LAST CLOSED bar (index -2; -1 is forming)."""
    i = len(df) - 2
    if i < 210:
        return None
    row = df.iloc[i]
    if not (row["ema50"] > row["ema200"] and row["close"] > row["ema200"]):
        return None
    dipped = any(df["close"].iloc[i - k] < df["ema20"].iloc[i - k] for k in (1, 2, 3))
    if not dipped:
        return None
    if not (row["close"] > row["ema20"]):
        return None
    if df["close"].iloc[i - 1] > df["ema20"].iloc[i - 1]:
        return None                       # trigger = the reclaim bar itself
    if not np.isfinite(row["atr50"]):
        return None
    return dict(bar_time=int(row["time"]), close=float(row["close"]),
                atr=float(row["atr50"]),
                stop=float(row["close"] - STOP_ATR * row["atr50"]))


def watch():
    mt5 = attach()
    names = {s: broker_name(mt5, s) for s in SYMBOLS}
    names = {k: v for k, v in names.items() if v}
    print(f"forward test running (READ-ONLY, no orders): {names}")
    st = load_state()
    while True:
        try:
            for sym, bsym in names.items():
                df = h1_frame(mt5, bsym)
                if df is None:
                    continue
                closed_t = int(df["time"].iloc[-2])
                # --- manage open paper trades on M5 resolution ---
                for pos in list(st["open"]):
                    if pos["symbol"] != sym:
                        continue
                    m5 = mt5.copy_rates_range(bsym, mt5.TIMEFRAME_M5,
                                              datetime.fromtimestamp(pos["last_seen"],
                                                                     tz=timezone.utc),
                                              datetime.now(timezone.utc))
                    if m5 is None or len(m5) < 2:
                        continue
                    m5 = pd.DataFrame(m5[:-1])        # closed M5 bars only
                    for b in m5.itertuples():
                        pos["mae"] = min(pos["mae"], float(b.low))
                        pos["mfe"] = max(pos["mfe"], float(b.high))
                        pos["last_seen"] = int(b.time)
                        exit_px = None; reason = None
                        if b.low <= pos["stop"]:
                            exit_px, reason = pos["stop"], "stop"
                        elif b.high >= pos["tp"]:
                            exit_px, reason = pos["tp"], "tp"
                        elif (b.time - pos["entry_time"]) >= MAX_HOLD_H1 * 3600:
                            exit_px, reason = float(b.close), "time"
                        if exit_px is not None:
                            risk = pos["entry"] - pos["stop"]
                            append_csv(TRADEBOOK_CSV, [
                                pos["signal_ts"], pos["entry_ts"], sym,
                                pos["entry"], pos["stop"], pos["tp"],
                                datetime.fromtimestamp(b.time, tz=timezone.utc)
                                .isoformat(), exit_px, reason,
                                round((exit_px - pos["entry"]) / risk, 4),
                                round((pos["mae"] - pos["entry"]) / risk, 4),
                                round((pos["mfe"] - pos["entry"]) / risk, 4)],
                                ["signal_ts", "entry_ts", "symbol", "entry",
                                 "stop", "tp", "exit_ts", "exit_px", "reason",
                                 "r", "mae_r", "mfe_r"])
                            st["open"].remove(pos)
                            print(f"{sym}: paper exit {reason} r="
                                  f"{(exit_px - pos['entry']) / risk:+.2f}")
                            break
                # --- fill pending signal at the new bar's open ---
                for pos in st["open"]:
                    if pos["symbol"] == sym and pos.get("pending") \
                            and int(df["time"].iloc[-1]) > pos["signal_bar"]:
                        pos["entry"] = float(df["open"].iloc[-1])
                        pos["entry_time"] = int(df["time"].iloc[-1])
                        pos["entry_ts"] = datetime.fromtimestamp(
                            pos["entry_time"], tz=timezone.utc).isoformat()
                        risk = pos["entry"] - pos["stop"]
                        if risk <= 0:
                            st["open"].remove(pos); continue
                        pos["tp"] = pos["entry"] + RR * risk
                        pos["mae"] = pos["entry"]; pos["mfe"] = pos["entry"]
                        pos["last_seen"] = pos["entry_time"]
                        pos["pending"] = False
                        print(f"{sym}: paper ENTRY {pos['entry']:.2f} "
                              f"stop {pos['stop']:.2f} tp {pos['tp']:.2f}")
                # --- new signal on a newly closed bar ---
                if st["last_bar"].get(sym) == closed_t:
                    continue
                st["last_bar"][sym] = closed_t
                sig = signal_on_closed(df)
                if sig is None:
                    continue
                day = datetime.fromtimestamp(closed_t, tz=timezone.utc).date().isoformat()
                key = f"{sym}|{day}"
                st["per_day"][key] = st["per_day"].get(key, 0) + 1
                taken = st["per_day"][key] <= MAX_PER_DAY \
                    and not any(p["symbol"] == sym for p in st["open"])
                append_csv(SIGNALS_CSV, [
                    datetime.fromtimestamp(closed_t, tz=timezone.utc).isoformat(),
                    sym, sig["close"], round(sig["atr"], 3), round(sig["stop"], 3),
                    "taken" if taken else "skipped(day-cap/open)"],
                    ["signal_ts", "symbol", "close", "atr50", "stop", "status"])
                if taken:
                    st["open"].append(dict(
                        symbol=sym, pending=True, signal_bar=closed_t,
                        signal_ts=datetime.fromtimestamp(closed_t,
                                                         tz=timezone.utc).isoformat(),
                        stop=sig["stop"]))
                    print(f"{sym}: SIGNAL logged (pending next-open entry)")
            save_state(st)
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            save_state(st); print("stopped"); break
        except Exception as e:
            print(f"loop error: {e}"); time.sleep(120)


def report():
    if not os.path.exists(TRADEBOOK_CSV):
        print("no closed paper trades yet"); return
    t = pd.read_csv(TRADEBOOK_CSV)
    print(f"forward tradebook: {len(t)} closed paper trades")
    ref = {"GER40": 0.096, "US30": 0.096, "JPN225": 0.111}
    for sym, g in t.groupby("symbol"):
        r = g["r"]
        drift = ""
        if len(g) >= 20:
            d_wr = abs((r > 0).mean() - 0.33) * 100
            drift = "  << DRIFT FLAG" if d_wr > 20 else ""
        print(f"  {sym}: n={len(g)} WR={(r > 0).mean():.0%} avg={r.mean():+.3f} "
              f"(backtest {ref.get(sym, float('nan')):+.3f}) net={r.sum():+.1f}R "
              f"medMAE={g['mae_r'].median():+.2f}R{drift}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    if ap.parse_args().report:
        report()
    else:
        watch()
