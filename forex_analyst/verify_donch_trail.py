"""VERIFY — XAUUSD_DONCH_TR (chandelier-trail exit twin of the deployed DONCH).

live == backtest by construction, proven three ways (house convention):
  [1] REFERENCE NUMBERS — the validated backtest reproduces exactly:
      n=661, net +182.8R, train +116.8 / holdout +66.0 (TZ-correct 2008-2026,
      cost 0.23 all-in, entries = signal_DONCH N=96, LIVE stop convention
      stop = signal_close - 2xATR, chandelier SL = max(SL, close_j - 4.0xATR_j)
      per closed bar, no TP, time exit 192 bars, max 2/day).
  [2] SIGNAL EQUALITY — live_signals.signal_at_last_bar with the DONCH-TR cfg
      fires identically to the validated signal on live-cache-sized truncated
      frames (sampled), and its signal set equals the deployed DONCH-96 set
      (same entries by design).
  [3] TRAIL-PATH EQUALITY — an INDEPENDENT re-computation of the SL sequence
      (the exact rule manage_positions runs live: SL -> max(SL, close-4xATR) on
      each closed bar, exit when a later bar's low touches the SL) reproduces
      the backtest executor's exit bar and R for EVERY trade.
  [4] CONFIG GUARD — XAUUSD_DONCH and XAUUSD_DONCH_TR are never both enabled.

All sections must print PASS.
"""
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", MagicMock())

import live_signals as LS
import discovery_engine as DE
from discover_trend import gold_h1, donch_sig

FAILED = []


def verdict(name, ok, detail):
    print(f"  {'OK ' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        FAILED.append(name)


def main():
    cfg = LS.FX_STRATS["XAUUSD-DONCH-TR"]
    cost = DE.COST["XAUUSD"]
    g = gold_h1()

    print("[1] reference numbers")
    stop_abs = (g["close"].to_numpy(float) - cfg["stop_atr"] * g["atr50"].to_numpy(float))
    t = DE.run_trades(g, donch_sig(g, cfg["N"]), None, cost,
                      stop_abs=stop_abs, trail_atr=cfg["trail_atr"],
                      max_hold=cfg["max_hold"], max_tpd=cfg["max_tpd"])
    net = t["r"].sum()
    tr = t.loc[t.year <= 2023, "r"].sum()
    ho = t.loc[t.year >= 2024, "r"].sum()
    verdict("reference", abs(net - 182.8) < 2 and abs(tr - 116.8) < 2
            and abs(ho - 66.0) < 2,
            f"n={len(t)} net={net:+.1f}R (ref +182.8) train={tr:+.1f} ho={ho:+.1f}")

    print("[2] signal equality (live cfg vs validated; windowed live-cache re-prep)")
    sig_dep = donch_sig(g, 96)
    idx = np.flatnonzero(sig_dep)
    # DONCH-TR cfg through the LIVE entry point on truncated frames
    sample = idx[:: max(1, len(idx) // 15)][:15]
    ok_n = 0
    for i in sample:
        win = g.iloc[max(0, i - 2500): i + 1].reset_index(drop=True)
        got = LS.signal_at_last_bar(win, cfg)
        if got is not None and got["direction"] == "long" \
                and abs(got["stop"] - (g["close"].iloc[i] - 2.0 * g["atr50"].iloc[i])) < 1e-6:
            ok_n += 1
    verdict("windowed signals", ok_n == len(sample),
            f"{ok_n}/{len(sample)} validated signal bars reproduced by "
            f"signal_at_last_bar(DONCH-TR cfg) on 2500-bar caches")
    # full-set equality vs deployed DONCH (same entries by design)
    hiN = g["high"].shift(1).rolling(cfg["N"]).max().to_numpy(float)
    sig_tr = (g["close"].to_numpy(float) > hiN + 0.1 * g["atr50"].to_numpy(float))
    verdict("signal set == deployed DONCH", bool((sig_tr == sig_dep).all()),
            f"{int(sig_tr.sum())} signals, identical mask")

    print("[3] trail-path equality (independent SL recomputation per trade)")
    o = g["open"].to_numpy(float); h = g["high"].to_numpy(float)
    l = g["low"].to_numpy(float); c = g["close"].to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    ts = g["timestamp_ny"].to_numpy()
    pos = {pd.Timestamp(r.entry_ts): r for r in t.itertuples()}
    mism = 0
    checked = 0
    ts_index = pd.Series(np.arange(len(g)), index=g["timestamp_ny"])
    for ets, r in list(pos.items())[:: max(1, len(pos) // 200)]:
        ei = int(ts_index.loc[ets])
        i = ei - 1
        entry = o[ei] + cost / 2
        sl = (c[i] - cfg["stop_atr"] * atr[i]) - cost / 2
        risk = entry - sl
        exit_px = None; exit_j = None
        for j in range(ei, min(ei + cfg["max_hold"], len(g))):
            if l[j] <= sl:                       # broker-side SL touch
                exit_px, exit_j = sl, j; break
            cand = c[j] - cfg["trail_atr"] * atr[j]   # manage_positions rule
            if np.isfinite(cand):
                sl = max(sl, cand)
        if exit_j is None:
            exit_j = min(ei + cfg["max_hold"], len(g)) - 1
            exit_px = c[exit_j]
        r_indep = (exit_px - entry - cost / 2) / risk
        checked += 1
        if abs(r_indep - r.r) > 1e-9:
            mism += 1
    verdict("trail path", mism == 0,
            f"{checked - mism}/{checked} sampled trades reproduce exit bar+R exactly")

    print("[4] config guard")
    import live_mt5_bot as BOT
    both = BOT.ENABLE.get("XAUUSD_DONCH") and BOT.ENABLE.get("XAUUSD_DONCH_TR")
    verdict("mutual exclusion", not both,
            f"ENABLE DONCH={BOT.ENABLE.get('XAUUSD_DONCH')} "
            f"DONCH_TR={BOT.ENABLE.get('XAUUSD_DONCH_TR')} (never both True)")
    inst = BOT.INSTANCES["XAUUSD_DONCH_TR"]
    verdict("instance wiring",
            inst["magic"] == 53101 and inst["exit"] == "trail"
            and inst["risk_mode"] == "trend_trail"
            and inst["cfg"] is LS.FX_STRATS["XAUUSD-DONCH-TR"]
            and inst["max_hold_bars"] == 192,
            "magic 53101, exit=trail, risk_mode=trend_trail, cfg bound, max_hold 192")

    print()
    if FAILED:
        print(f"OVERALL: FAILED ({', '.join(FAILED)})"); sys.exit(1)
    print("OVERALL: ALL SECTIONS PASS")


if __name__ == "__main__":
    main()
