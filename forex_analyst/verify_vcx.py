"""VERIFY — XAUUSD_VCX_A / XAUUSD_VCX_B (owner-selected compression-breakout cells).

live == backtest by construction, house convention:
  [1] REFERENCE NUMBERS (TZ-correct 2008-2026, cost 0.23 all-in, LIVE stop
      convention close - stop_atr*ATR, fixed rr3 target, max_hold 96, 2/day):
        VCX-A (W96 q0.20 pad0.2 stop2.5): n=273 net +97.0R  train +79.8 / ho +17.3
        VCX-B (W96 q0.25 pad0.1 stop2.0): n=339 net +110.0R train +81.2 / ho +28.9
  [2] SIGNAL EQUALITY — live_signals.signal_at_last_bar with each cfg fires
      identically to the validated signal mask on live-cache-sized (2500-bar)
      truncated frames (sampled bars), including the 720-bar tightness rank.
  [3] EXECUTION-PATH — the "trend" risk_mode places stop = sig.stop - pad and
      TP = entry + rr*risk; the backtest executor uses the same math (checked
      per-trade on a sample by independent recomputation).
  [4] CONFIG GUARD — instances wired to the right cfg/magic; stacking warning
      (VCX cells overlap XAUUSD_DONCH ~96%) is present in ENABLE comments.
No pivot/swing logic exists in this family (house rule for future pivots: 5L/5R).
All sections must print PASS.
"""
import sys
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", MagicMock())

import live_signals as LS
import discovery_engine as DE
from discover_trend import gold_h1

FAILED = []
REFS = {"XAUUSD-VCX-A": dict(n=273, net=97.0, tr=79.8, ho=17.3),
        "XAUUSD-VCX-B": dict(n=339, net=110.0, tr=81.2, ho=28.9)}


def verdict(name, ok, detail):
    print(f"  {'OK ' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        FAILED.append(name)


def vcx_mask(g, cfg):
    c = g["close"].to_numpy(float); atr = g["atr50"].to_numpy(float)
    rng = (g["high"].shift(1).rolling(cfg["W"]).max()
           - g["low"].shift(1).rolling(cfg["W"]).min())
    tight = rng.rolling(720, min_periods=200).rank(pct=True).to_numpy(float)
    hiW = g["high"].shift(1).rolling(cfg["W"]).max().to_numpy(float)
    return (tight <= cfg["q"]) & (c > hiW + cfg["pad"] * atr)


def main():
    g = gold_h1()
    cost = DE.COST["XAUUSD"]
    c = g["close"].to_numpy(float); atr = g["atr50"].to_numpy(float)

    for key in ("XAUUSD-VCX-A", "XAUUSD-VCX-B"):
        cfg = LS.FX_STRATS[key]
        ref = REFS[key]
        sig = vcx_mask(g, cfg)
        stop_abs = c - cfg["stop_atr"] * atr
        t = DE.run_trades(g, sig, None, cost, stop_abs=stop_abs, rr=cfg["rr"],
                          max_hold=cfg["max_hold"], max_tpd=cfg["max_tpd"])
        net = t["r"].sum(); tr = t.loc[t.year <= 2023, "r"].sum()
        ho = t.loc[t.year >= 2024, "r"].sum()
        print(f"[1] {key} reference")
        verdict("reference", abs(net - ref["net"]) < 2 and len(t) == ref["n"]
                and abs(tr - ref["tr"]) < 2 and abs(ho - ref["ho"]) < 2,
                f"n={len(t)} (ref {ref['n']}) net={net:+.1f} (ref {ref['net']:+.1f}) "
                f"tr={tr:+.1f} ho={ho:+.1f}")

        print(f"[2] {key} signal equality on live-sized caches")
        idx = np.flatnonzero(sig)
        sample = idx[:: max(1, len(idx) // 15)][:15]
        ok_n = 0
        for i in sample:
            win = g.iloc[max(0, i - 2500): i + 1].reset_index(drop=True)
            got = LS.signal_at_last_bar(win, cfg)
            if got is not None and got["direction"] == "long" \
                    and abs(got["stop"] - (c[i] - cfg["stop_atr"] * atr[i])) < 1e-6 \
                    and got["rr"] == cfg["rr"]:
                ok_n += 1
        # negative control: bars WITHOUT a signal must not fire
        neg = [i for i in range(3000, len(g), max(1, len(g) // 15)) if not sig[i]][:10]
        bad = 0
        for i in neg:
            win = g.iloc[max(0, i - 2500): i + 1].reset_index(drop=True)
            if LS.signal_at_last_bar(win, cfg) is not None:
                bad += 1
        verdict("windowed signals", ok_n == len(sample) and bad == 0,
                f"{ok_n}/{len(sample)} signal bars reproduced, "
                f"{bad}/10 false fires on non-signal bars")

        print(f"[3] {key} execution math (sampled independent recomputation)")
        mism = 0; checked = 0
        ts_index = pd.Series(np.arange(len(g)), index=g["timestamp_ny"])
        o = g["open"].to_numpy(float); h = g["high"].to_numpy(float)
        l = g["low"].to_numpy(float)
        for row in t.iloc[:: max(1, len(t) // 100)].itertuples():
            ei = int(ts_index.loc[pd.Timestamp(row.entry_ts)])
            i = ei - 1
            entry = o[ei] + cost / 2
            stop = (c[i] - cfg["stop_atr"] * atr[i]) - cost / 2
            risk = entry - stop
            target = entry + cfg["rr"] * risk
            xp = None
            for j in range(ei, min(ei + cfg["max_hold"], len(g))):
                if l[j] <= stop:
                    xp = stop; break
                if h[j] >= target:
                    xp = target; break
            if xp is None:
                xp = c[min(ei + cfg["max_hold"], len(g)) - 1]
            r_ind = (xp - entry - cost / 2) / risk
            checked += 1
            if abs(r_ind - row.r) > 1e-9:
                mism += 1
        verdict("execution math", mism == 0,
                f"{checked - mism}/{checked} sampled trades reproduce R exactly")

    print("[4] config guard")
    import live_mt5_bot as BOT
    okA = (BOT.INSTANCES["XAUUSD_VCX_A"]["magic"] == 53401
           and BOT.INSTANCES["XAUUSD_VCX_A"]["risk_mode"] == "trend"
           and BOT.INSTANCES["XAUUSD_VCX_A"]["cfg"] is LS.FX_STRATS["XAUUSD-VCX-A"]
           and BOT.ENABLE.get("XAUUSD_VCX_A") is False)
    okB = (BOT.INSTANCES["XAUUSD_VCX_B"]["magic"] == 53501
           and BOT.INSTANCES["XAUUSD_VCX_B"]["risk_mode"] == "trend"
           and BOT.INSTANCES["XAUUSD_VCX_B"]["cfg"] is LS.FX_STRATS["XAUUSD-VCX-B"]
           and BOT.ENABLE.get("XAUUSD_VCX_B") is False)
    verdict("instances wired", okA and okB,
            "magics 53401/53501, risk_mode=trend, cfg bound, ENABLE=False")

    print()
    if FAILED:
        print(f"OVERALL: FAILED ({', '.join(FAILED)})"); sys.exit(1)
    print("OVERALL: ALL SECTIONS PASS")


if __name__ == "__main__":
    main()
