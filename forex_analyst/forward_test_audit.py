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

ZONE-BREAKOUT forward test (July 2026, short-history M15/M30 models routed
here per owner directive — NEVER wire these live before 90 clean days):
    ZB-CMPX-GER40-M30  : atr50 pctile(720) <= 0.25 AND close breaks the 48-bar
                         extreme -> continuation, BOTH sides, stop 2*ATR
                         entry-relative, TP 3R, time exit 96 M30 bars.
    ZB-BOX-GBPUSD-M15  : 24-bar Darvas box (range <= 2.5*ATR); close beyond the
                         box +/- 0.1*ATR -> continuation, BOTH sides, stop
                         2*ATR, TP 3R, time exit 192 M15 bars.
    Logs: forward_zb_signals.csv / forward_zb_tradebook.csv (M5-resolved MAE/
    MFE per side), state under the "zb_*" keys. Max 2 signals/model/day.

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
ZB_SIGNALS_CSV = "forward_zb_signals.csv"
ZB_TRADEBOOK_CSV = "forward_zb_tradebook.csv"
# ZONE-BREAKOUT paper models (exact zone_breakout_lab.py cells, short-history tier)
ZB_MODELS = {
    "ZB-CMPX-GER40-M30": dict(symbol="GER40", tf="M30", fam="CMPX", q=0.25, brk=48,
                              stop_atr=2.0, rr=3.0, max_hold=96, bar_sec=1800,
                              bars=1600, ref_avg_r=0.15),
    "ZB-BOX-GBPUSD-M15": dict(symbol="GBPUSD", tf="M15", fam="BOX", N=24, tight=2.5,
                              pad=0.1, stop_atr=2.0, rr=3.0, max_hold=192,
                              bar_sec=900, bars=600, ref_avg_r=0.11),
}


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
        return {"open": [], "last_bar": {}, "per_day": {},
                "zb_open": [], "zb_last_bar": {}, "zb_per_day": {}}


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


def zb_frame(mt5, bsym, m):
    tf = {"M30": mt5.TIMEFRAME_M30, "M15": mt5.TIMEFRAME_M15}[m["tf"]]
    r = mt5.copy_rates_from_pos(bsym, tf, 0, m["bars"])
    if r is None or len(r) < min(m["bars"] - 50, 250):
        return None
    df = pd.DataFrame(r)
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    if m["fam"] == "CMPX":
        df["atr_pctile"] = df["atr50"].rolling(720, min_periods=200).rank(pct=True)
    return df


def zb_signal_on_closed(df, m):
    """Signal on the LAST CLOSED bar (index -2), mirroring zone_breakout_lab
    sig_cmpx / sig_box EXACTLY. Returns dict(side=+1/-1, ...) or None."""
    i = len(df) - 2
    if i < max(60, m.get("N", 0) + 1, m.get("brk", 0) + 1):
        return None
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float); atr = df["atr50"].to_numpy(float)
    if not np.isfinite(atr[i]):
        return None
    side = 0
    if m["fam"] == "CMPX":
        pct = df["atr_pctile"].to_numpy(float)
        if not np.isfinite(pct[i]) or pct[i] > m["q"]:
            return None
        bh = h[i - m["brk"]:i].max(); bl = l[i - m["brk"]:i].min()
        if c[i] > bh:
            side = 1
        elif c[i] < bl:
            side = -1
    else:
        bh = h[i - m["N"]:i].max(); bl = l[i - m["N"]:i].min()
        if (bh - bl) > m["tight"] * atr[i]:
            return None
        if c[i] > bh + m["pad"] * atr[i]:
            side = 1
        elif c[i] < bl - m["pad"] * atr[i]:
            side = -1
    if side == 0:
        return None
    return dict(bar_time=int(df["time"].iloc[i]), side=side, close=float(c[i]),
                atr=float(atr[i]))


def zb_step(mt5, names, st):
    """One poll pass for every ZONE-BREAKOUT paper model (read-only)."""
    for name, m in ZB_MODELS.items():
        bsym = names.get(m["symbol"])
        if not bsym:
            continue
        df = zb_frame(mt5, bsym, m)
        if df is None:
            continue
        # --- manage open ZB paper trades on M5 (side-aware MAE/MFE) ---
        for pos in list(st["zb_open"]):
            if pos["model"] != name:
                continue
            m5 = mt5.copy_rates_range(bsym, mt5.TIMEFRAME_M5,
                                      datetime.fromtimestamp(pos["last_seen"],
                                                             tz=timezone.utc),
                                      datetime.now(timezone.utc))
            if m5 is None or len(m5) < 2:
                continue
            for b in pd.DataFrame(m5[:-1]).itertuples():
                s = pos["side"]
                pos["mae"] = min(pos["mae"], s * (float(b.low if s == 1 else -b.high)))
                pos["mfe"] = max(pos["mfe"], s * (float(b.high if s == 1 else -b.low)))
                pos["last_seen"] = int(b.time)
                exit_px = reason = None
                if s == 1 and b.low <= pos["stop"]:
                    exit_px, reason = pos["stop"], "stop"
                elif s == -1 and b.high >= pos["stop"]:
                    exit_px, reason = pos["stop"], "stop"
                elif s == 1 and b.high >= pos["tp"]:
                    exit_px, reason = pos["tp"], "tp"
                elif s == -1 and b.low <= pos["tp"]:
                    exit_px, reason = pos["tp"], "tp"
                elif (b.time - pos["entry_time"]) >= m["max_hold"] * m["bar_sec"]:
                    exit_px, reason = float(b.close), "time"
                if exit_px is not None:
                    risk = abs(pos["entry"] - pos["stop"])
                    r = (s * (exit_px - pos["entry"])) / risk
                    append_csv(ZB_TRADEBOOK_CSV, [
                        pos["signal_ts"], pos["entry_ts"], name, m["symbol"],
                        "long" if s == 1 else "short", pos["entry"], pos["stop"],
                        pos["tp"],
                        datetime.fromtimestamp(b.time, tz=timezone.utc).isoformat(),
                        exit_px, reason, round(r, 4),
                        round((pos["mae"] - s * pos["entry"]) / risk, 4),
                        round((pos["mfe"] - s * pos["entry"]) / risk, 4)],
                        ["signal_ts", "entry_ts", "model", "symbol", "side",
                         "entry", "stop", "tp", "exit_ts", "exit_px", "reason",
                         "r", "mae_r", "mfe_r"])
                    st["zb_open"].remove(pos)
                    print(f"{name}: paper exit {reason} r={r:+.2f}")
                    break
        # --- fill pending at the new bar's open ---
        for pos in st["zb_open"]:
            if pos["model"] == name and pos.get("pending")                     and int(df["time"].iloc[-1]) > pos["signal_bar"]:
                s = pos["side"]
                pos["entry"] = float(df["open"].iloc[-1])
                pos["entry_time"] = int(df["time"].iloc[-1])
                pos["entry_ts"] = datetime.fromtimestamp(pos["entry_time"],
                                                         tz=timezone.utc).isoformat()
                pos["stop"] = pos["entry"] - s * m["stop_atr"] * pos["atr"]
                risk = abs(pos["entry"] - pos["stop"])
                if risk <= 0 or not (0.3 * pos["atr"] <= risk <= 4.0 * pos["atr"]):
                    st["zb_open"].remove(pos); continue
                pos["tp"] = pos["entry"] + s * m["rr"] * risk
                pos["mae"] = s * pos["entry"]; pos["mfe"] = s * pos["entry"]
                pos["last_seen"] = pos["entry_time"]
                pos["pending"] = False
                print(f"{name}: paper ENTRY {'long' if s == 1 else 'short'} "
                      f"{pos['entry']:.5f} stop {pos['stop']:.5f} tp {pos['tp']:.5f}")
        # --- new signal on a newly closed bar ---
        closed_t = int(df["time"].iloc[-2])
        if st["zb_last_bar"].get(name) == closed_t:
            continue
        st["zb_last_bar"][name] = closed_t
        sig = zb_signal_on_closed(df, m)
        if sig is None:
            continue
        day = datetime.fromtimestamp(closed_t, tz=timezone.utc).date().isoformat()
        key = f"{name}|{day}"
        st["zb_per_day"][key] = st["zb_per_day"].get(key, 0) + 1
        taken = st["zb_per_day"][key] <= MAX_PER_DAY             and not any(p["model"] == name for p in st["zb_open"])
        append_csv(ZB_SIGNALS_CSV, [
            datetime.fromtimestamp(closed_t, tz=timezone.utc).isoformat(), name,
            m["symbol"], "long" if sig["side"] == 1 else "short", sig["close"],
            round(sig["atr"], 5), "taken" if taken else "skipped(day-cap/open)"],
            ["signal_ts", "model", "symbol", "side", "close", "atr50", "status"])
        if taken:
            st["zb_open"].append(dict(
                model=name, side=sig["side"], pending=True, signal_bar=closed_t,
                atr=sig["atr"],
                signal_ts=datetime.fromtimestamp(closed_t,
                                                 tz=timezone.utc).isoformat()))
            print(f"{name}: ZB SIGNAL logged (pending next-open entry)")


def watch():
    mt5 = attach()
    all_syms = tuple(sorted(set(SYMBOLS) | {m["symbol"] for m in ZB_MODELS.values()}))
    names = {s: broker_name(mt5, s) for s in all_syms}
    names = {k: v for k, v in names.items() if v}
    print(f"forward test running (READ-ONLY, no orders): {names}")
    st = load_state()
    for k, d in (("zb_open", []), ("zb_last_bar", {}), ("zb_per_day", {})):
        st.setdefault(k, d)
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
            zb_step(mt5, names, st)
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
    if os.path.exists(ZB_TRADEBOOK_CSV):
        t = pd.read_csv(ZB_TRADEBOOK_CSV)
        print(f"ZONE-BREAKOUT tradebook: {len(t)} closed paper trades")
        for name, g in t.groupby("model"):
            r = g["r"]; ref_r = ZB_MODELS[name]["ref_avg_r"]
            drift = "  << DRIFT FLAG" if len(g) >= 20 \
                and abs(r.mean() - ref_r) > 0.20 else ""
            print(f"  {name}: n={len(g)} WR={(r > 0).mean():.0%} avg={r.mean():+.3f} "
                  f"(backtest {ref_r:+.3f}) net={r.sum():+.1f}R "
                  f"medMAE={g['mae_r'].median():+.2f}R "
                  f"medMFE={g['mfe_r'].median():+.2f}R{drift}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    if ap.parse_args().report:
        report()
    else:
        watch()
