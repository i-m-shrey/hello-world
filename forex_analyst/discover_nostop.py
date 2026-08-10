"""DISCOVERY STUDY 8 — NO-STOP HUNT: structural cost-bypass for silver + FX.

Owner directive: don't return flat nulls — find structure that beats the cost
drag. The structural levers tested here (all causal):
  - TIMEFRAME: D1 models (cost is a tiny fraction of a daily move),
  - VOL-EXPANSION filters (only trade when ranges dwarf the spread),
  - SESSION filters (only liquid hours),
  - SWEEP/structure fades at H4 (owner-requested revisit at a new TF).
New breadth: AUDUSD / NZDUSD / USDJPY H1+D1 (2010-2026 true-UTC exports).
Costs for the new pairs are conservative all-in estimates (flagged: must be
confirmed by the live spread audit before anything goes live).
"""
import numpy as np
import pandas as pd

import discovery_engine as DE
import event_price_lib as epl

NEW_COSTS = {"AUDUSD": 0.00012, "NZDUSD": 0.00016, "USDJPY": 0.012,
             "XAGUSD": 0.03}
DE.COST.update(NEW_COSTS)

PAIRS_ALL = ("EURUSD", "GBPUSD", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDJPY")


def h1(sym):
    if sym in ("EURUSD", "GBPUSD", "USDCHF", "USDCAD"):
        return DE.frames(sym, 60)
    df = epl._load_tab(f"data/{sym}60.csv", "utc")
    return _feat(df, 60)


def _feat(df, tf):
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    win = max(60, round(30 * 1440 / tf))
    df["atr_pctile"] = df["atr50"].rolling(win, min_periods=max(60, win // 4)).rank(pct=True)
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    df["hour"] = df["timestamp_ny"].dt.hour
    return df


def d1(sym, src=None):
    """FX daily bars on the 17:00-NY session cut (the FX day convention)."""
    df = src if src is not None else h1(sym)[["timestamp_ny", "open", "high", "low", "close"]]
    g = (df.set_index("timestamp_ny")
         .resample("1D", offset="17h"))
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()}
                       ).dropna().reset_index()
    return _feat(out, 1440)


def donch_sig(d, N, pad=0.1):
    hiN = d["high"].shift(1).rolling(N).max().to_numpy(float)
    return d["close"].to_numpy(float) > hiN + pad * d["atr50"].to_numpy(float)


def main():
    print("=" * 110)
    print("STUDY 8 — NO-STOP HUNT (silver D1/filtered, FX D1 MR, new pairs, H4 sweeps)")
    print("=" * 110)

    # ---------------- A. SILVER, structurally filtered ----------------
    print("\n[A] XAGUSD — D1 models + vol/session-filtered H4/H1 (cost 0.03):")
    s_h1 = _feat(epl._load_tab("data/XAGUSD60.csv", "utc"), 60)
    s_d1 = d1("XAGUSD", s_h1[["timestamp_ny", "open", "high", "low", "close"]])
    c = s_d1["close"].to_numpy(float); a = s_d1["atr50"].to_numpy(float)
    for N in (20, 55):
        sig = donch_sig(s_d1, N)
        DE.gate(f"XAG D1 DONCH{N} trail3",
                lambda m, s=sig: DE.run_trades(s_d1, s, None, 0.03 * m,
                                               stop_abs=c - 2 * a, trail_atr=3.0,
                                               max_hold=60, max_tpd=1), min_n=50)
    # D1 mean reversion
    sma = s_d1["close"].rolling(20).mean(); sd = s_d1["close"].rolling(20).std()
    sl = (s_d1["close"] < sma - 2 * sd).to_numpy()
    ss = (s_d1["close"] > sma + 2 * sd).to_numpy()
    DE.gate("XAG D1 band-fade sd2 -> SMA20",
            lambda m, A=sl, B=ss: DE.run_trades(s_d1, A, B, 0.03 * m, stop_atr=1.5,
                                                target_abs=sma.to_numpy(float),
                                                max_hold=15, max_tpd=1), min_n=50)
    # H4 vol-expansion filter
    s_h4 = _feat(s_h1.set_index("timestamp_ny").resample("240min")
                 .agg(open=("open", "first"), high=("high", "max"),
                      low=("low", "min"), close=("close", "last"))
                 .dropna().reset_index(), 240)
    c4 = s_h4["close"].to_numpy(float); a4 = s_h4["atr50"].to_numpy(float)
    vol_ok = s_h4["atr_pctile"].to_numpy(float) >= 0.5
    sig = donch_sig(s_h4, 96) & vol_ok
    DE.gate("XAG H4 DONCH96 trail4 + vol-expansion (atrp>=0.5)",
            lambda m, s=sig: DE.run_trades(s_h4, s, None, 0.03 * m,
                                           stop_abs=c4 - 2 * a4, trail_atr=4.0,
                                           max_hold=96, max_tpd=1), min_n=50)
    # H1 session filter (NY liquid hours only)
    c1 = s_h1["close"].to_numpy(float); a1 = s_h1["atr50"].to_numpy(float)
    ny_hours = s_h1["hour"].isin(range(8, 16)).to_numpy()
    sig = donch_sig(s_h1, 96) & ny_hours
    DE.gate("XAG H1 DONCH96 trail4 + NY-hours filter",
            lambda m, s=sig: DE.run_trades(s_h1, s, None, 0.03 * m,
                                           stop_abs=c1 - 2 * a1, trail_atr=4.0,
                                           max_hold=192, max_tpd=1), min_n=50)

    # ---------------- B. FX D1 mean reversion (the untried TF) ----------------
    print("\n[B] FX D1 band-fade (16y, cost tiny at D1):")
    for sym in PAIRS_ALL:
        dd = d1(sym)
        cost = DE.COST[sym]
        sma = dd["close"].rolling(20).mean(); sd = dd["close"].rolling(20).std()
        sl = (dd["close"] < sma - 2 * sd).to_numpy()
        ss = (dd["close"] > sma + 2 * sd).to_numpy()
        DE.gate(f"D1 band-fade {sym} sd2 -> SMA20",
                lambda m, A=sl, B=ss, D=dd, t=sma.to_numpy(float), co=cost:
                DE.run_trades(D, A, B, co * m, stop_atr=1.5, target_abs=t,
                              max_hold=15, max_tpd=1), min_n=60)

    # ---------------- C. new pairs H1: fades + trend check ----------------
    print("\n[C] AUDUSD/NZDUSD/USDJPY H1 (2010-2026, costs = estimates pending audit):")
    Q = set(range(14, 24))
    for sym in ("AUDUSD", "NZDUSD", "USDJPY"):
        dd = h1(sym)
        cost = DE.COST[sym]
        cc = dd["close"]; sma = cc.rolling(20).mean(); sd = cc.rolling(20).std()
        ok = dd["hour"].isin(Q) & (dd["atr_pctile"] <= 0.70)
        sl = (ok & (cc < sma - 2 * sd)).to_numpy()
        ss = (ok & (cc > sma + 2 * sd)).to_numpy()
        DE.gate(f"BOLL-H1 {sym} quiet-hours fade",
                lambda m, A=sl, B=ss, D=dd, t=sma.to_numpy(float), co=cost:
                DE.run_trades(D, A, B, co * m, stop_atr=1.2, target_abs=t,
                              max_hold=20, max_tpd=3))
        sig = donch_sig(dd, 96)
        ca = dd["close"].to_numpy(float); aa = dd["atr50"].to_numpy(float)
        DE.gate(f"DONCH96-H1 {sym} trail4 (law check: FX should fail)",
                lambda m, s=sig, D=dd, sa=ca - 2 * aa, co=cost:
                DE.run_trades(D, s, None, co * m, stop_abs=sa, trail_atr=4.0,
                              max_hold=192, max_tpd=2))

    # ---------------- D. H4 sweep-fade (owner-requested revisit) ----------------
    print("\n[D] H4 liquidity-sweep fade, all 7 pairs (revisit at a NEW timeframe):")
    for sym in PAIRS_ALL:
        dd = (DE.frames(sym, 240) if sym in ("EURUSD", "GBPUSD", "USDCHF", "USDCAD")
              else _feat(h1(sym).set_index("timestamp_ny").resample("240min")
                         .agg(open=("open", "first"), high=("high", "max"),
                              low=("low", "min"), close=("close", "last"))
                         .dropna().reset_index(), 240))
        cost = DE.COST[sym]
        lo48 = dd["low"].shift(1).rolling(48).min()
        hi48 = dd["high"].shift(1).rolling(48).max()
        mid = ((hi48 + lo48) / 2).to_numpy(float)
        # sweep: bar takes out the extreme but CLOSES back inside
        sl = ((dd["low"] < lo48) & (dd["close"] > lo48)).to_numpy()
        ss = ((dd["high"] > hi48) & (dd["close"] < hi48)).to_numpy()
        DE.gate(f"H4 sweep-fade {sym} 48-bar extremes -> mid",
                lambda m, A=sl, B=ss, D=dd, t=mid, co=cost:
                DE.run_trades(D, A, B, co * m, stop_atr=1.5, target_abs=t,
                              max_hold=30, max_tpd=1), min_n=60)


if __name__ == "__main__":
    main()
