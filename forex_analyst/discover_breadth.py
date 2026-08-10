"""DISCOVERY STUDY 6 (Part B) — BREADTH: every symbol x timeframe, concept families
not yet covered. TZ-verified data, all-in costs, conservative executor, iron gate.

New ground vs studies 1-5:
  A. GOLD MULTI-TF trend/structure: DONCH-96 + VCX + trail exits at M15/M30/H4
     (frequency comes from breadth of timeframe, never from loosening filters).
  B. SESSION-DISPLACEMENT CONTINUATION ported to TREND assets (the validated FX
     E-family mechanism: tight consolidation -> displacement bar at session-open
     hours -> continuation). Gold M15/H1 + GER40/US30 M15/H1.
  C. FX MEAN-REVERSION AT H4 — the one fade variant never tried: at H4 the cost
     is a far smaller fraction of the move (fades died at M15/M30 because of
     cost, not direction). EURUSD/GBPUSD/USDCHF/USDCAD H4 band-fade.
  D. INDEX H4 trend (SPX500/GER40/US30/JPN225/HK50, 2022+ evidence grade).
Every cell -> discovery_ledger.csv.
"""
import numpy as np
import pandas as pd

import discovery_engine as DE

GOLD_START = "2008-01-01"


def gold(tf):
    g = DE.frames("XAUUSD", tf)
    return g[g["ny_date"] >= GOLD_START].reset_index(drop=True)


def donch_sig(d, N, pad=0.1):
    hiN = d["high"].shift(1).rolling(N).max().to_numpy(float)
    return d["close"].to_numpy(float) > hiN + pad * d["atr50"].to_numpy(float)


def vcx_sig(d, W, q):
    rng = (d["high"].shift(1).rolling(W).max() - d["low"].shift(1).rolling(W).min())
    tight = rng.rolling(720, min_periods=200).rank(pct=True).to_numpy(float)
    boxhi = d["high"].shift(1).rolling(W).max().to_numpy(float)
    return (tight <= q) & (d["close"].to_numpy(float)
                           > boxhi + 0.1 * d["atr50"].to_numpy(float))


def sess_disp_sig(d, hours, consol_bars=6, consol_max_atr=1.5, disp_min_atr=1.2,
                  close_loc=0.65):
    h = d["high"]; l = d["low"]; c = d["close"]; o = d["open"]
    atr = d["atr50"]
    consol = ((h.shift(1).rolling(consol_bars).max()
               - l.shift(1).rolling(consol_bars).min()) <= consol_max_atr * atr)
    rng = (h - l)
    disp_up = (rng >= disp_min_atr * atr) & (c > o) \
        & ((c - l) / rng.replace(0, np.nan) >= close_loc)
    return (consol & disp_up & d["hour"].isin(hours)).to_numpy()


def main():
    print("=" * 110)
    print("STUDY 6 — PART B BREADTH (multi-TF trend, session displacement, H4 fades, index H4)")
    print("=" * 110)
    cost_g = DE.COST["XAUUSD"]

    # ---------- A. gold multi-TF ----------
    print("\n[A] gold trend/structure at M15/M30/H4:")
    for tf, lbl in ((15, "M15"), (30, "M30"), (240, "H4")):
        d = gold(tf)
        c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
        stop_abs = c - 2.0 * atr
        mh = 96 if tf < 240 else 48
        sig = donch_sig(d, 96)
        DE.gate(f"DONCH96 gold {lbl} rr3",
                lambda m, s=sig, dd=d, sa=stop_abs, k=mh: DE.run_trades(
                    dd, s, None, cost_g * m, stop_abs=sa, rr=3.0,
                    max_hold=k, max_tpd=2))
        DE.gate(f"DONCH96 gold {lbl} trail4",
                lambda m, s=sig, dd=d, sa=stop_abs, k=mh * 2: DE.run_trades(
                    dd, s, None, cost_g * m, stop_abs=sa, trail_atr=4.0,
                    max_hold=k, max_tpd=2))
        sigv = vcx_sig(d, 96, 0.25)
        DE.gate(f"VCX gold {lbl} W96 q0.25 rr3",
                lambda m, s=sigv, dd=d, sa=stop_abs, k=mh: DE.run_trades(
                    dd, s, None, cost_g * m, stop_abs=sa, rr=3.0,
                    max_hold=k, max_tpd=2))

    # ---------- B. session displacement on trend assets ----------
    print("\n[B] session-displacement continuation (E-family mechanism on trend assets):")
    sess = {"london": (2, 3, 4), "ny": (8, 9, 10)}
    for sym, tfs in (("XAUUSD", (15, 60)), ("GER40", (15, 60)), ("US30", (15, 60))):
        for tf in tfs:
            d = gold(tf) if sym == "XAUUSD" else DE.frames(sym, tf)
            cost = DE.COST[sym]
            c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
            stop_abs = c - 1.5 * atr
            note = "" if sym == "XAUUSD" else "2022+ only"
            for sname, hrs in sess.items():
                sig = sess_disp_sig(d, hrs)
                DE.gate(f"SESSDISP {sym} {tf}m {sname} rr2.5",
                        lambda m, s=sig, dd=d, sa=stop_abs, co=cost: DE.run_trades(
                            dd, s, None, co * m, stop_abs=sa, rr=2.5,
                            max_hold=72 if tf == 60 else 288, max_tpd=2),
                        note=note, min_n=40 if sym == "XAUUSD" else 20)

    # ---------- C. FX H4 band-fade ----------
    print("\n[C] FX H4 band-fade (cost is small at H4 — the untried fade variant):")
    for sym in ("EURUSD", "GBPUSD", "USDCHF", "USDCAD"):
        d = DE.frames(sym, 240)
        cost = DE.COST[sym]
        c = d["close"]; sma = c.rolling(20).mean(); sdv = c.rolling(20).std()
        tgt = sma.to_numpy(float)
        for sd in (2.0, 2.5):
            sl = (c < sma - sd * sdv).to_numpy()
            ss = (c > sma + sd * sdv).to_numpy()
            DE.gate(f"BOLL-H4 {sym} sd{sd} fade->SMA20",
                    lambda m, a=sl, b=ss, dd=d, t=tgt, co=cost: DE.run_trades(
                        dd, a, b, co * m, stop_atr=1.5, target_abs=t,
                        max_hold=30, max_tpd=2), min_n=60)

    # ---------- D. index H4 trend ----------
    print("\n[D] index H4 trend (2022+ evidence grade):")
    for sym in ("SPX500", "GER40", "US30", "JPN225", "HK50"):
        try:
            d = DE.frames(sym, 240)
        except Exception as e:
            print(f"  {sym}: no data ({e})"); continue
        cost = DE.COST[sym]
        c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
        stop_abs = c - 2.0 * atr
        for N in (24, 48):
            sig = donch_sig(d, N)
            DE.gate(f"DONCH{N} {sym} H4 trail4",
                    lambda m, s=sig, dd=d, sa=stop_abs, co=cost: DE.run_trades(
                        dd, s, None, co * m, stop_abs=sa, trail_atr=4.0,
                        max_hold=96, max_tpd=1),
                    note="2022+ only", min_n=15)


if __name__ == "__main__":
    main()
