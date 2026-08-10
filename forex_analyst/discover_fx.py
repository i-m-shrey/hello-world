"""DISCOVERY STUDY 2 — FX MEAN-REVERSION refinements + REGIME ROUTING (Mandate 2).

House law: FX majors mean-revert. Deployed fades are thin (~51%, ~1:1) low-cost
edges (BOLL30/BOLL15/RSI30/AVWAP). This study asks, on TZ-CORRECT data
(deep M15 2008-2026 via the NY+5 rule; USDCAD on true-UTC H1):

  A. REGIME ROUTING (the untested high-leverage idea): does gating the fades on
     a LOW efficiency-ratio percentile (ranging regime) improve expectancy, and
     does the trending control hurt them symmetrically?
  B. BAND-FADE baseline + neighbors: Bollinger fade toward the mid on M30 built
     from the deep files (longer history than the broker-30m validation),
     quiet-hours window + alternates + the all-hours essentiality control.
  C. RANGE-EXTREME fade: in a ranging regime, price touching the W-bar Donchian
     extreme reverts toward the channel mid (structure fade, not indicator fade).
  D. RSI-fade replication across pairs (deployed only on USDCHF 30m).

Every cell -> discovery_ledger.csv, pass or reject.
"""
import numpy as np
import pandas as pd

import discovery_engine as DE

PAIRS = ("EURUSD", "GBPUSD", "USDCHF")


def boll_fade_sigs(d, hours, sd=2.0, atrp_max=0.70):
    c = d["close"]
    sma = c.rolling(20).mean()
    sdv = c.rolling(20).std()
    up, lo = sma + sd * sdv, sma - sd * sdv
    ok = d["hour"].isin(hours) & (d["atr_pctile"] <= atrp_max)
    return (ok & (c < lo)).to_numpy(), (ok & (c > up)).to_numpy(), sma.to_numpy(float)


def wilder_rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def main():
    print("=" * 110)
    print("STUDY 2 — FX MEAN-REVERSION + REGIME ROUTING (deep M15->M30 2008-2026, TZ-correct)")
    print("=" * 110)
    Q = set(range(14, 24))

    for sym in PAIRS:
        d = DE.frames(sym, 30)
        cost = DE.COST[sym]
        sig_l, sig_s, sma = boll_fade_sigs(d, Q)
        erp = d["er_pctile"].to_numpy(float)

        def mk(sl, ss, m):
            return DE.run_trades(d, sl, ss, cost * m, stop_atr=1.2,
                                 target_abs=sma, max_hold=20, max_tpd=3)

        print(f"\n[{sym}] BOLL30-style fade (target=SMA20, stop 1.2ATR):")
        DE.gate(f"BOLL30 {sym} base hours14-24", lambda m: mk(sig_l, sig_s, m))
        for hset, lbl in ((set(range(12, 22)), "hours12-22 (neighbor)"),
                          (set(range(16, 24)) | {0, 1}, "hours16-02 (neighbor)"),
                          (set(range(24)), "all-hours (control)")):
            l2, s2, _ = boll_fade_sigs(d, hset)
            DE.gate(f"BOLL30 {sym} {lbl}", lambda m, a=l2, b=s2: mk(a, b, m))

        print(f"[{sym}] regime routing on the fade:")
        for p, lbl in ((0.5, "er<0.5 ranging"), (0.35, "er<0.35 deep range")):
            DE.gate(f"ROUTE {sym} BOLL30 {lbl}",
                    lambda m, a=sig_l & (erp < p), b=sig_s & (erp < p): mk(a, b, m))
        DE.gate(f"ROUTE {sym} BOLL30 er>=0.5 trending (control)",
                lambda m, a=sig_l & (erp >= 0.5), b=sig_s & (erp >= 0.5): mk(a, b, m))

        print(f"[{sym}] range-extreme fade (H1 Donchian touch in range regime):")
        h = DE.frames(sym, 60)
        erp_h = h["er_pctile"].to_numpy(float)
        for W in (48, 96):
            lo = h["low"].shift(1).rolling(W).min()
            hi = h["high"].shift(1).rolling(W).max()
            mid = ((hi + lo) / 2).to_numpy(float)
            sl = (h["close"] <= lo).to_numpy() & (erp_h < 0.5)
            ss = (h["close"] >= hi).to_numpy() & (erp_h < 0.5)
            DE.gate(f"EXTREME {sym} H1 W{W} fade->mid er<0.5",
                    lambda m, a=sl, b=ss, hh=h, md=mid: DE.run_trades(
                        hh, a, b, DE.COST[sym] * m, stop_atr=1.5,
                        target_abs=md, max_hold=48, max_tpd=2))

        print(f"[{sym}] RSI(14) 30m quiet-hours fade:")
        rsi = wilder_rsi(d["close"])
        ok = d["hour"].isin(Q) & (d["atr_pctile"] <= 0.70)
        sl = (ok & (rsi < 25)).to_numpy()
        ss = (ok & (rsi > 75)).to_numpy()
        DE.gate(f"RSI30 {sym} 25/75 both",
                lambda m, a=sl, b=ss: DE.run_trades(
                    d, a, b, cost * m, stop_atr=1.0, rr=1.5, max_hold=24, max_tpd=3))
        DE.gate(f"RSI30 {sym} short-only (deployed shape)",
                lambda m, b=ss: DE.run_trades(
                    d, None, b, cost * m, stop_atr=1.0, rr=1.5, max_hold=24, max_tpd=3))

    print("\n[USDCAD] H1 fades (no sub-hour deep history):")
    d = DE.frames("USDCAD", 60)
    cost = DE.COST["USDCAD"]
    c = d["close"]; sma = c.rolling(20).mean(); sdv = c.rolling(20).std()
    ok = (d["atr_pctile"] <= 0.70)
    sl = (ok & (c < sma - 2 * sdv)).to_numpy()
    ss = (ok & (c > sma + 2 * sdv)).to_numpy()
    tgt = sma.to_numpy(float)
    DE.gate("BOLL-H1 USDCAD both all-hours",
            lambda m, a=sl, b=ss: DE.run_trades(
                d, a, b, cost * m, stop_atr=1.2, target_abs=tgt,
                max_hold=20, max_tpd=3))
    erp = d["er_pctile"].to_numpy(float)
    DE.gate("BOLL-H1 USDCAD er<0.5 ranging",
            lambda m, a=sl & (erp < 0.5), b=ss & (erp < 0.5): DE.run_trades(
                d, a, b, cost * m, stop_atr=1.2, target_abs=tgt,
                max_hold=20, max_tpd=3))


if __name__ == "__main__":
    main()
