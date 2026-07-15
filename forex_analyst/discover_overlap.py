"""DISCOVERY STUDY 3 — overlap vs the deployed gold book + finalist battery.

Before anything reaches the slate it must prove it is NOT the deployed book in
disguise: daily-R correlation + concurrent-open fraction vs the deployed gold
trend anchors (DONCH96 fixed-rr3, and a STRAD-like W24 box breakout), plus a
neighbor plateau and yearly table for each finalist.

Finalists from study 1:
  F1  VCX gold W96 q0.25 rr3 stop2 (vol-contraction -> expansion breakout)
  F2  DONCH96 entry + chandelier exit (adaptive exit on the deployed entry —
      same entries by construction; reported as an exit-upgrade proposal)
  F3  MTF-DONCH N24 H4-gated rr3 (faster channel, H4 alignment)
"""
import numpy as np
import pandas as pd

import discovery_engine as DE
from discover_trend import gold_h1, donch_sig, h4_gate


def daily_r(t):
    if t is None or not len(t):
        return pd.Series(dtype=float)
    d = pd.to_datetime(t["entry_ts"]).dt.date
    return t.groupby(d)["r"].sum()


def overlap_frac(a, b):
    if not len(a) or not len(b):
        return 0.0
    ints_b = list(zip(pd.to_datetime(b["entry_ts"]), pd.to_datetime(b["exit_ts"])))
    hit = sum(1 for e, x in zip(pd.to_datetime(a["entry_ts"]),
                                pd.to_datetime(a["exit_ts"]))
              if any(e < bx and x > be for be, bx in ints_b))
    return hit / len(a)


def yearly(t):
    ys = t.groupby("year")["r"].sum()
    return "  ".join(f"{y}:{ys[y]:+.0f}" for y in sorted(ys.index))


def main():
    g = gold_h1()
    cost = DE.COST["XAUUSD"]

    donch96 = DE.run_trades(g, donch_sig(g, 96), None, cost, stop_atr=2.0, rr=3.0,
                            max_hold=96, max_tpd=2)
    c = g["close"].to_numpy(float); atr = g["atr50"].to_numpy(float)
    boxhi24 = g["high"].shift(1).rolling(24).max().to_numpy(float)
    stradlike = DE.run_trades(g, c > boxhi24 + 0.1 * atr, None, cost,
                              stop_atr=2.0, rr=2.0, max_hold=48, max_tpd=2)

    print("=" * 100)
    print("F1 — VCX W96 q0.25 rr3: neighbor plateau, yearly, overlap")
    print("=" * 100)
    rng = (g["high"].shift(1).rolling(96).max() - g["low"].shift(1).rolling(96).min())
    tight = rng.rolling(720, min_periods=200).rank(pct=True).to_numpy(float)
    hi96 = g["high"].shift(1).rolling(96).max().to_numpy(float)
    base_sig = None
    for q in (0.20, 0.25, 0.30):
        for pad in (0.05, 0.1, 0.2):
            for st in (1.5, 2.0, 2.5):
                sig = (tight <= q) & (c > hi96 + pad * atr)
                DE.gate(f"F1 neighbor q{q} pad{pad} stop{st}",
                        lambda m, s_=sig, st_=st: DE.run_trades(
                            g, s_, None, cost * m, stop_atr=st_, rr=3.0,
                            max_hold=96, max_tpd=2), note="neighbor", min_n=50)
                if q == 0.25 and pad == 0.1 and st == 2.0:
                    base_sig = sig
    f1 = DE.run_trades(g, base_sig, None, cost, stop_atr=2.0, rr=3.0,
                       max_hold=96, max_tpd=2)
    print("F1 yearly:", yearly(f1))
    a1, a2 = daily_r(f1).align(daily_r(donch96), join="outer", fill_value=0.0)
    print(f"F1 vs DONCH96: daily-R corr {a1.corr(a2):+.3f}, "
          f"open-time overlap {overlap_frac(f1, donch96):.1%}")
    b1, b2 = daily_r(f1).align(daily_r(stradlike), join="outer", fill_value=0.0)
    print(f"F1 vs STRAD-like W24: daily-R corr {b1.corr(b2):+.3f}, "
          f"open-time overlap {overlap_frac(f1, stradlike):.1%}")

    print()
    print("=" * 100)
    print("F2 — DONCH96 + chandelier exit (same entries as deployed; exit upgrade)")
    print("=" * 100)
    sig96 = donch_sig(g, 96)
    for trail in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        DE.gate(f"F2 trail{trail} maxhold192",
                lambda m, t=trail: DE.run_trades(g, sig96, None, cost * m,
                                                 stop_atr=2.0, trail_atr=t,
                                                 max_hold=192, max_tpd=2),
                note="exit-upgrade")
    f2 = DE.run_trades(g, sig96, None, cost, stop_atr=2.0, trail_atr=4.0,
                       max_hold=192, max_tpd=2)
    print("F2 (trail4) yearly:", yearly(f2))
    print(f"F2 vs deployed fixed-rr3 exit: same entries; net {f2['r'].sum():+.1f}R "
          f"vs {donch96['r'].sum():+.1f}R")

    print()
    print("=" * 100)
    print("F3 — MTF-DONCH N24 H4-gated rr3: neighbors, yearly, overlap")
    print("=" * 100)
    gate4 = h4_gate("XAUUSD", g)
    for N in (16, 24, 32):
        for rr in (2.5, 3.0, 3.5):
            sig = donch_sig(g, N) & gate4
            DE.gate(f"F3 neighbor N{N} rr{rr}",
                    lambda m, s_=sig, r_=rr: DE.run_trades(
                        g, s_, None, cost * m, stop_atr=2.0, rr=r_,
                        max_hold=96, max_tpd=2), note="neighbor")
    f3 = DE.run_trades(g, donch_sig(g, 24) & gate4, None, cost, stop_atr=2.0,
                       rr=3.0, max_hold=96, max_tpd=2)
    print("F3 yearly:", yearly(f3))
    a1, a2 = daily_r(f3).align(daily_r(donch96), join="outer", fill_value=0.0)
    print(f"F3 vs DONCH96: daily-R corr {a1.corr(a2):+.3f}, "
          f"open-time overlap {overlap_frac(f3, donch96):.1%}")
    b1, b2 = daily_r(f3).align(daily_r(f1), join="outer", fill_value=0.0)
    print(f"F3 vs F1(VCX): daily-R corr {b1.corr(b2):+.3f}, "
          f"open-time overlap {overlap_frac(f3, f1):.1%}")

    print()
    for name, t in (("DONCH96 deployed-shape", donch96), ("F1 VCX", f1),
                    ("F2 trail4", f2), ("F3 MTF-N24", f3)):
        yrs = (pd.to_datetime(t["entry_ts"]).max()
               - pd.to_datetime(t["entry_ts"]).min()).days / 365.25
        print(f"freq {name}: {len(t)/yrs:.0f} trades/yr, avg {t['r'].mean():+.3f}R "
              f"-> {len(t)/yrs*t['r'].mean()/12:+.2f} R/month")


if __name__ == "__main__":
    main()
