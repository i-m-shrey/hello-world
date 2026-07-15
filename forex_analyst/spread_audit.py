"""SPREAD AUDIT (A1 support tool — runs on the OWNER's Windows terminal, READ-ONLY).

Two modes:
  python spread_audit.py --collect     sample real bid/ask spreads for every book
                                       symbol every 30s, append to spread_log.csv.
                                       Leave it running for a FULL trading week.
  python spread_audit.py --report      NY-hour-bucketed spread table per symbol +
                                       per-strategy expectancy at the MEASURED
                                       all-in cost (spread + commission), using
                                       the validated cost-sensitivity pairs in
                                       strategy_cost_sensitivity.json
                                       (expectancy is ~linear in cost, so
                                       avg(true) ~ avg1x - (mult-1)*(avg1x-avg2x)).

Credentials come from live_mt5_bot.py by regex (never printed). copy_* only —
no orders of any kind. Commission convention: $7/lot round trip, converted to
price units exactly as live_signals.FX_SPREADS documents.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD", "USDCHF", "XAUUSD",
           "SPX500", "GER40", "US30", "JPN225", "HK50")
LOG = "spread_log.csv"
SENS = "strategy_cost_sensitivity.json"
# assumed all-in round-trip costs (live_signals.FX_SPREADS) and $7/lot commission
ASSUMED = {"EURUSD": 0.00008, "GBPUSD": 0.00010, "USDCAD": 0.00014,
           "USDCHF": 0.00010, "XAUUSD": 0.23, "SPX500": 1.7, "GER40": 4.7,
           "US30": 3.4, "JPN225": 13.5, "HK50": 8.3}
COMMISSION = {"EURUSD": 0.00007, "GBPUSD": 0.00007, "USDCAD": 0.00007,
              "USDCHF": 0.00007, "XAUUSD": 0.07, "SPX500": 0.7, "GER40": 0.7,
              "US30": 0.7, "JPN225": 7.0, "HK50": 5.6}
# each deployed strategy's trading window in NY hours (None = 24h structural)
STRAT_HOURS = {
    "EURUSD_E": (2, 3, 4, 8, 9, 10, 14, 15), "GBPUSD_E": None,
    "USDCAD_A": None, "USDCHF_A": None, "GBPUSD_P1": None, "EURUSD_P1_30": None,
    "USDCHF_RSI30": tuple(range(14, 24)), "GBPUSD_AVWAP": tuple(range(14, 24)),
    "XAUUSD_S5": None, "XAUUSD_S6": None, "XAUUSD_S4": (6, 7, 8, 9, 10, 11),
    "XAUUSD_S3LO": (9, 10, 11), "XAUUSD_H1A": None, "XAUUSD_STRAD": None,
    "XAUUSD_DONCH": None, "XAUUSD_DONCH_TR": None, "XAUUSD_MACROSS": None,
    "XAUUSD_CRASH": None, "XAUUSD_BOS": None,
    "SPX500_DONCH": None, "GER40_DONCH": None, "GER40_BOS": None,
    "US30_DONCH": None, "JPN225_DONCH": None, "HK50_MACROSS": None,
}
SYM_OF = lambda k: k.split("_")[0]


def attach():
    import MetaTrader5 as mt5
    src = open("live_mt5_bot.py", encoding="utf-8").read()

    def grab(pat):
        m = re.search(pat, src, re.M)
        if not m:
            sys.exit(f"cannot find {pat} in live_mt5_bot.py")
        return m.group(1)
    acct = int(grab(r"^MT5_ACCOUNT\s*=\s*(\d+)"))
    pw = grab(r'^MT5_PASSWORD\s*=\s*"([^"]+)"')
    srv = grab(r'^MT5_SERVER\s*=\s*"([^"]+)"')
    term = grab(r'^MT5_TERMINAL_PATH\s*=\s*"(.+)"').encode().decode("unicode_escape")
    if not mt5.initialize(term, login=acct, password=pw, server=srv):
        sys.exit(f"initialize failed: {mt5.last_error()}")
    return mt5


def broker_names(mt5):
    out = {}
    for s in SYMBOLS:
        for cand in (s, s + ".i", s + "m", s + ".raw"):
            if mt5.symbol_info(cand) is not None:
                mt5.symbol_select(cand, True)
                out[s] = cand
                break
    return out


def collect():
    mt5 = attach()
    names = broker_names(mt5)
    print(f"collecting spreads for {names} -> {LOG} (Ctrl-C to stop; run a full week)")
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts_utc", "symbol", "bid", "ask", "spread"])
        try:
            while True:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for s, b in names.items():
                    t = mt5.symbol_info_tick(b)
                    if t and t.bid and t.ask:
                        w.writerow([now, s, t.bid, t.ask, round(t.ask - t.bid, 6)])
                f.flush()
                time.sleep(30)
        except KeyboardInterrupt:
            print("stopped")
    mt5.shutdown()


def report():
    import pandas as pd
    df = pd.read_csv(LOG)
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ny_hour"] = df["ts"].dt.tz_convert("America/New_York").dt.hour
    days = df["ts"].dt.date.nunique()
    print(f"spread_log.csv: {len(df)} samples over {days} days\n")
    print("median spread by NY hour (p75 in parens):")
    piv = df.groupby(["symbol", "ny_hour"])["spread"].agg(["median", lambda x: x.quantile(0.75)])
    for sym in sorted(df["symbol"].unique()):
        med_all = df[df.symbol == sym]["spread"].median()
        print(f"  {sym}: 24h median {med_all}")
    sens = json.load(open(SENS)) if os.path.exists(SENS) else {}
    print("\nper-strategy verdicts at MEASURED all-in cost:")
    print(f"{'strategy':<18} {'hours-med spread':>16} {'all-in':>10} {'assumed':>9} "
          f"{'mult':>6} {'avg@true':>9} verdict")
    for strat, hours in STRAT_HOURS.items():
        sym = SYM_OF(strat)
        sub = df[df.symbol == sym]
        if not len(sub):
            continue
        if hours:
            sub = sub[sub.ny_hour.isin(hours)]
        med = sub["spread"].median()
        allin = med + COMMISSION.get(sym, 0)
        assumed = ASSUMED[sym]
        mult = allin / assumed
        s = sens.get(strat)
        if s:
            avg_true = s["avg1x"] - (mult - 1) * (s["avg1x"] - s["avg2x"])
            verdict = "OK" if avg_true > 0.03 else ("THIN" if avg_true > 0 else "DEAD — bench")
            print(f"{strat:<18} {med:>16.5f} {allin:>10.5f} {assumed:>9.5f} "
                  f"{mult:>6.2f} {avg_true:>+9.3f} {verdict}")
        else:
            note = "cost x{:.1f} vs assumption — re-run its lab at this cost".format(mult)
            print(f"{strat:<18} {med:>16.5f} {allin:>10.5f} {assumed:>9.5f} "
                  f"{mult:>6.2f} {'n/a':>9} {note}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.collect:
        collect()
    elif a.report:
        report()
    else:
        print(__doc__)
