"""DISCOVERY STUDY 1 — gold/index TREND & STRUCTURE family (Mandate 2, July 2026).

Concepts tested (every cell goes to discovery_ledger.csv, pass or reject):
  A. VCX — volatility-contraction -> expansion breakout: the W-bar box is
     unusually tight (range percentile <= q), close breaks box-high + 0.1*ATR.
     LONG-only on secular-long assets (house law: gold/indices trend).
  B. PULLBACK-CONTINUATION: established uptrend (ema50>ema200, close>ema200),
     price pulls back below ema20 then closes back above -> continuation long.
  C. MTF ALIGNMENT: H4 ema20>ema50 gate on a faster H1 Donchian (N=48) breakout
     (the deployed DONCH-96 has no gate — is a gated faster channel additive?).
  D. ADAPTIVE EXITS: the deployed DONCH-96 entry with chandelier trails vs the
     fixed rr=3 exit (the BOS rr-grid showed exits carry real R — test the lens).
  E. REGIME GATE on trend: only take DONCH breakouts when the efficiency-ratio
     percentile says "trending" (er_pctile >= p) — the routing hypothesis, trend half.
  F. CROSS-ASSET: gold longs gated by USD-basket weakness (equal-weight USD index
     from EURUSD/GBPUSD/USDCHF/USDCAD H1, ema20<ema50 on the basket).

Gold H1 = 2008-2026 (TZ-verified loaders). Indices = short history (2022+): the
holdout dominates, so index cells are labeled replication evidence (note field),
with the same gate math.
"""
import numpy as np
import pandas as pd

import discovery_engine as DE

GOLD_START = "2008-01-01"


def gold_h1():
    g = DE.frames("XAUUSD", 60)
    return g[g["ny_date"] >= GOLD_START].reset_index(drop=True)


def donch_sig(d, N, pad=0.1):
    hiN = d["high"].shift(1).rolling(N).max().to_numpy(float)
    c = d["close"].to_numpy(float)
    atr = d["atr50"].to_numpy(float)
    return c > hiN + pad * atr


def h4_gate(sym, d):
    h4 = DE.frames(sym, 240)[["timestamp_ny", "ema20", "ema50"]].copy()
    h4["h4_up"] = (h4["ema20"] > h4["ema50"]).astype(int)
    h4["timestamp_ny"] = h4["timestamp_ny"] + pd.Timedelta(minutes=240)
    m = pd.merge_asof(d[["timestamp_ny"]], h4[["timestamp_ny", "h4_up"]],
                      on="timestamp_ny", direction="backward")
    return m["h4_up"].fillna(0).to_numpy(int) == 1


def usd_basket_weak(d_gold):
    """USD equal-weight basket on H1: mean of log(USD-quote) legs. Weak-USD gate
    = basket ema20 < ema50 (computed on the basket series). Causal merge_asof."""
    legs = []
    for sym, invert in (("EURUSD", True), ("GBPUSD", True),
                        ("USDCHF", False), ("USDCAD", False)):
        f = DE.frames(sym, 60)[["timestamp_ny", "close"]].copy()
        v = np.log(f["close"].to_numpy(float))
        f["leg"] = -v if invert else v
        legs.append(f[["timestamp_ny", "leg"]].rename(columns={"leg": sym}))
    b = legs[0]
    for f in legs[1:]:
        b = pd.merge_asof(b.sort_values("timestamp_ny"), f.sort_values("timestamp_ny"),
                          on="timestamp_ny", direction="backward",
                          tolerance=pd.Timedelta(hours=3))
    b = b.dropna().reset_index(drop=True)
    b["usd"] = b[["EURUSD", "GBPUSD", "USDCHF", "USDCAD"]].mean(axis=1)
    b["usd_dn"] = (b["usd"].ewm(span=20, adjust=False).mean()
                   < b["usd"].ewm(span=50, adjust=False).mean()).astype(int)
    # available at the close of that H1 bar -> shift availability one bar
    b["timestamp_ny"] = b["timestamp_ny"] + pd.Timedelta(hours=1)
    m = pd.merge_asof(d_gold[["timestamp_ny"]], b[["timestamp_ny", "usd_dn"]],
                      on="timestamp_ny", direction="backward",
                      tolerance=pd.Timedelta(hours=6))
    return m["usd_dn"].fillna(0).to_numpy(int) == 1


def main():
    print("=" * 110)
    print("STUDY 1 — TREND/STRUCTURE DISCOVERY (gold H1 2008-2026; indices 2022+ = replication evidence)")
    print("=" * 110)

    g = gold_h1()
    cost_g = DE.COST["XAUUSD"]

    # ---------- A. VCX ----------
    print("\n[A] VCX volatility-contraction -> expansion (gold, LONG):")
    for W in (24, 48, 96):
        rng = (g["high"].shift(1).rolling(W).max()
               - g["low"].shift(1).rolling(W).min())
        tight = rng.rolling(720, min_periods=200).rank(pct=True)
        boxhi = g["high"].shift(1).rolling(W).max().to_numpy(float)
        c = g["close"].to_numpy(float); atr = g["atr50"].to_numpy(float)
        for q in (0.25, 0.35):
            sig = (tight.to_numpy(float) <= q) & (c > boxhi + 0.1 * atr)
            for rr, st in ((3.0, 2.0), (2.0, 1.5)):
                DE.gate(f"VCX gold W{W} q{q} rr{rr} stop{st}",
                        lambda m, s=sig, r=rr, so=st: DE.run_trades(
                            g, s, None, cost_g * m, stop_atr=so, rr=r,
                            max_hold=96, max_tpd=2))

    # ---------- B. PULLBACK-CONTINUATION ----------
    print("\n[B] Pullback-continuation in uptrend (gold, LONG):")
    c = g["close"]; e20, e50, e200 = g["ema20"], g["ema50"], g["ema200"]
    up = (e50 > e200) & (c > e200)
    dipped = (c.shift(1) < e20.shift(1))
    for dipbars in (1, 3):
        dip = (c.shift(1) < e20.shift(1)).rolling(dipbars).max().astype(bool)
        reclaim = (c > e20)
        sig = (up & dip & reclaim & ~(c.shift(1) > e20.shift(1))).to_numpy()
        for rr, st in ((3.0, 2.0), (2.0, 1.5)):
            DE.gate(f"PULLBACK gold dip{dipbars} rr{rr} stop{st}",
                    lambda m, s=sig, r=rr, so=st: DE.run_trades(
                        g, s, None, cost_g * m, stop_atr=so, rr=r,
                        max_hold=96, max_tpd=2))

    # ---------- C. MTF alignment ----------
    print("\n[C] H4-gated faster Donchian (gold, LONG):")
    gate_h4 = h4_gate("XAUUSD", g)
    for N in (24, 48):
        sig = donch_sig(g, N) & gate_h4
        for rr in (2.0, 3.0):
            DE.gate(f"MTF-DONCH gold N{N} H4-gated rr{rr}",
                    lambda m, s=sig, r=rr: DE.run_trades(
                        g, s, None, cost_g * m, stop_atr=2.0, rr=r,
                        max_hold=96, max_tpd=2))

    # ---------- D. adaptive exits on the deployed entries ----------
    print("\n[D] Adaptive exits — deployed DONCH-96 entry, exit variants "
          "(baseline fixed rr3 = deployed):")
    sig96 = donch_sig(g, 96)
    DE.gate("EXIT baseline DONCH96 fixed rr3 (deployed)",
            lambda m: DE.run_trades(g, sig96, None, cost_g * m, stop_atr=2.0,
                                    rr=3.0, max_hold=96, max_tpd=2))
    for trail in (3.0, 4.0, 5.0):
        DE.gate(f"EXIT DONCH96 chandelier {trail}ATR (no target)",
                lambda m, t=trail: DE.run_trades(
                    g, sig96, None, cost_g * m, stop_atr=2.0, trail_atr=t,
                    max_hold=192, max_tpd=2))
    for trail in (3.0, 4.0):
        DE.gate(f"EXIT DONCH96 trail{trail} + BE at +1R",
                lambda m, t=trail: DE.run_trades(
                    g, sig96, None, cost_g * m, stop_atr=2.0, trail_atr=t,
                    be_r=1.0, max_hold=192, max_tpd=2))

    # ---------- E. regime gate ----------
    print("\n[E] Efficiency-ratio regime gate on DONCH96 (gold, LONG):")
    erp = g["er_pctile"].to_numpy(float)
    for p, lbl in ((0.5, ">=0.5 trending"), (0.0, "baseline all")):
        sig = sig96 & (erp >= p) if p > 0 else sig96
        DE.gate(f"REGIME DONCH96 er_pctile{lbl}",
                lambda m, s=sig: DE.run_trades(g, s, None, cost_g * m,
                                               stop_atr=2.0, rr=3.0,
                                               max_hold=96, max_tpd=2))
    sig_anti = sig96 & (erp < 0.5)
    DE.gate("REGIME DONCH96 er_pctile<0.5 (anti-regime — should be worse)",
            lambda m, s=sig_anti: DE.run_trades(g, s, None, cost_g * m,
                                                stop_atr=2.0, rr=3.0,
                                                max_hold=96, max_tpd=2))

    # ---------- F. cross-asset ----------
    print("\n[F] USD-basket gate on gold longs (DONCH96):")
    weak = usd_basket_weak(g)
    DE.gate("XASSET DONCH96 + USD-basket weak",
            lambda m: DE.run_trades(g, sig96 & weak, None, cost_g * m,
                                    stop_atr=2.0, rr=3.0, max_hold=96, max_tpd=2))
    DE.gate("XASSET DONCH96 + USD-basket STRONG (control — should be worse)",
            lambda m: DE.run_trades(g, sig96 & ~weak, None, cost_g * m,
                                    stop_atr=2.0, rr=3.0, max_hold=96, max_tpd=2))

    # ---------- indices: replication of the best gold cells ----------
    print("\n[IDX] Replication on indices (2022+ short history — evidence, not proof):")
    for sym in ("SPX500", "GER40", "US30", "JPN225", "HK50"):
        try:
            d = DE.frames(sym, 60)
        except Exception as e:
            print(f"  {sym}: no data ({e})"); continue
        cost = DE.COST[sym]
        for W in (48,):
            rng = (d["high"].shift(1).rolling(W).max()
                   - d["low"].shift(1).rolling(W).min())
            tight = rng.rolling(720, min_periods=200).rank(pct=True)
            boxhi = d["high"].shift(1).rolling(W).max().to_numpy(float)
            cc = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
            sig = (tight.to_numpy(float) <= 0.35) & (cc > boxhi + 0.1 * atr)
            DE.gate(f"VCX {sym} W{W} q0.35 rr3 (short history)",
                    lambda m, s=sig, dd=d, co=cost: DE.run_trades(
                        dd, s, None, co * m, stop_atr=2.0, rr=3.0,
                        max_hold=96, max_tpd=2),
                    min_n=30, note="2022+ only")
        e20, e50, e200 = d["ema20"], d["ema50"], d["ema200"]
        up = (e50 > e200) & (d["close"] > e200)
        dip = (d["close"].shift(1) < e20.shift(1)).rolling(3).max().astype(bool)
        sig = (up & dip & (d["close"] > e20)
               & ~(d["close"].shift(1) > e20.shift(1))).to_numpy()
        DE.gate(f"PULLBACK {sym} dip3 rr3 (short history)",
                lambda m, s=sig, dd=d, co=cost: DE.run_trades(
                    dd, s, None, co * m, stop_atr=2.0, rr=3.0,
                    max_hold=96, max_tpd=2),
                min_n=30, note="2022+ only")


if __name__ == "__main__":
    main()
