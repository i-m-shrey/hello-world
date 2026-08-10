"""VERIFY BOLL30R (July 2026) — proves EURUSD_BOLL30R (magic 55101) reproduces the
boll15_refit_lab.py survivor cell EXACTLY before real money touches it.

  [1] Reference — lab re-run must match the frozen refit numbers (n=400, avg +0.102,
      train +13.5 / holdout +27.4, 3x +6.5).
  [2] Windowed live-signal parity — live_signals.signal_at_last_bar (BOLL family,
      long-only, atrp<=0.50) on 3600-bar live-cache windows over lab signal bars
      + quiet bars: same fires, zero false positives.
  [3] Config cross-check — magic 55101, feed EURUSD_30, lot 0.04 (owner FX size step-up), params exact,
      legacy EURUSD_BOLL30 (81001) stays DISABLED (superseded).
"""
import sys

import numpy as np
import pandas as pd
from unittest.mock import MagicMock

sys.modules.setdefault("MetaTrader5", MagicMock())
sys.path.insert(0, ".")

import live_signals as LS
import boll15_refit_lab as B
from multi_symbol_lab import load_mt5_export

FAILS = []


def check(sec, ok, detail):
    print(f"  {'PASS' if ok else 'FAIL'}  {sec}: {detail}")
    if not ok:
        FAILS.append(sec)


def main():
    d30 = B.prep(load_mt5_export("data/EURUSD30.csv"), 30)
    months = max((d30["timestamp_ny"].iloc[-1] - d30["timestamp_ny"].iloc[0]).days, 1) / 30.44
    live = B.LIVE_COST["EURUSD"]

    print("[1] reference reproduction (refit survivor cell)")
    sma = d30["close"].rolling(20).mean(); sd = d30["close"].rolling(20).std()
    ok = (d30["atr_pctile"] <= 0.50) & d30["atr50"].notna() & (d30["hour"] != 17) \
         & d30["hour"].isin(range(14, 24))
    sl = (ok & (d30["close"] < sma - 2 * sd)).to_numpy()
    none = np.zeros(len(d30), bool)
    t = B.exec_x(d30, sl, none, live)
    t3 = B.exec_x(d30, sl, none, live * 3)
    st = B.stats(t, months)
    check("reference", st["n"] == 400 and abs(st["avg"] - 0.102) < 0.005
          and abs(st["tr"] - 13.5) < 0.2 and abs(st["ho"] - 27.4) < 0.2
          and abs(t3["r"].sum() - 6.5) < 0.2,
          f"n={st['n']} avg={st['avg']:+.3f} tr={st['tr']:+.1f} ho={st['ho']:+.1f} "
          f"3x={t3['r'].sum():+.1f}")

    print("[2] windowed live-signal parity (3600-bar cache windows)")
    cfg = LS.FX_STRATS["EURUSD-BOLL30R"]
    rng = np.random.RandomState(11)
    idx = np.flatnonzero(sl); idx = idx[idx > 3000]
    take = idx if len(idx) <= 150 else rng.choice(idx, 150, replace=False)
    quiet = rng.choice(np.flatnonzero(~sl & (np.arange(len(sl)) > 4000)), 300, replace=False)
    hit = miss = ff = 0
    for i in sorted(map(int, np.r_[take, quiet])):
        w = d30.iloc[max(0, i - 3599):i + 1].reset_index(drop=True)
        res = LS.signal_at_last_bar(w, cfg)
        got = 0 if res is None else (1 if res["direction"] == "long" else -1)
        want = 1 if sl[i] else 0
        if want:
            hit += got == want; miss += got != want
        elif got:
            ff += 1
    check("parity", miss == 0 and ff == 0,
          f"{hit}/{len(take)} signal bars match, {ff} false fires on {len(quiet)} quiet bars")

    print("[3] config cross-check")
    import live_mt5_bot as BOT
    inst = BOT.INSTANCES["EURUSD_BOLL30R"]
    check("config", inst["magic"] == 55101 and BOT.feed_of(inst) == "EURUSD_30"
          and BOT.LOTS["EURUSD_BOLL30R"] == 0.04
          and cfg["atrp_max"] == 0.50 and cfg["sides"] == ("long",)
          and cfg["bb_len"] == 20 and cfg["sd_mult"] == 2.0 and cfg["stop_atr"] == 1.2
          and BOT.ENABLE.get("EURUSD_BOLL30") is False
          and BOT.ENABLE.get("EURUSD_BOLL30R") is True,
          "magic/feed/lot/params exact; legacy 81001 disabled; R enabled")

    print("\nOVERALL:", "ALL SECTIONS PASS" if not FAILS else f"FAILURES: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
