"""DISCOVERY STUDY 5 (A3) — regime gate on the DEPLOYED fade shapes, broker files.

The deployed BOLL30 (EURUSD, disabled) and RSI30 (USDCHF, live) were validated on
the broker 30m exports — TRUE UTC (fingerprinted). Question: does an efficiency-
ratio regime gate ("pause fades when the market is trending") improve them
out-of-sample? Both the ranging gate and the trending control are shown.
"""
import os

import numpy as np
import pandas as pd

import discovery_engine as DE
import event_price_lib as epl

ROOT = os.path.dirname(os.path.abspath(__file__))


def broker_frame(path):
    df = epl._load_tab(path, "utc")
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    win = max(60, round(30 * 1440 / 30))
    df["atr_pctile"] = df["atr50"].rolling(win, min_periods=max(60, win // 4)).rank(pct=True)
    k = 48
    c = df["close"]
    net = (c - c.shift(k)).abs()
    plen = c.diff().abs().rolling(k).sum()
    df["er_pctile"] = ((net / plen).replace([np.inf, -np.inf], np.nan)
                       .rolling(win, min_periods=max(60, win // 4)).rank(pct=True))
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    df["hour"] = df["timestamp_ny"].dt.hour
    return df


def wilder_rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def main():
    Q = set(range(14, 24))
    print("=" * 110)
    print("STUDY 5 — REGIME GATE ON THE DEPLOYED FADES (broker 30m files, true UTC)")
    print("=" * 110)

    for sym, kind in (("EURUSD", "boll"), ("USDCHF", "rsi")):
        d = broker_frame(os.path.join(ROOT, f"data/{sym}30.csv"))
        print(f"\n[{sym} broker 30m: {d.timestamp_ny.min():%Y-%m-%d} -> "
              f"{d.timestamp_ny.max():%Y-%m-%d}, {len(d)} bars]")
        cost = DE.COST[sym]
        erp = d["er_pctile"].to_numpy(float)
        ok = d["hour"].isin(Q) & (d["atr_pctile"] <= 0.70)
        if kind == "boll":
            c = d["close"]; sma = c.rolling(20).mean(); sdv = c.rolling(20).std()
            sl = (ok & (c < sma - 2 * sdv)).to_numpy()
            ss = (ok & (c > sma + 2 * sdv)).to_numpy()
            tgt = sma.to_numpy(float)

            def mk(a, b, m, dd=d, t=tgt, co=cost):
                return DE.run_trades(dd, a, b, co * m, stop_atr=1.2,
                                     target_abs=t, max_hold=20, max_tpd=3)
        else:
            rsi = wilder_rsi(d["close"])
            sl = np.zeros(len(d), bool)
            ss = (ok & (rsi > 75)).to_numpy()

            def mk(a, b, m, dd=d, co=cost):
                return DE.run_trades(dd, None, b, co * m, stop_atr=1.0,
                                     rr=1.5, max_hold=24, max_tpd=3)

        DE.gate(f"{kind.upper()}30 {sym} ungated (deployed shape, broker data)",
                lambda m: mk(sl, ss, m))
        for p, lbl in ((0.5, "er<0.5 ranging"), (0.35, "er<0.35 deep range")):
            DE.gate(f"{kind.upper()}30 {sym} {lbl}",
                    lambda m, a=sl & (erp < p), b=ss & (erp < p): mk(a, b, m))
        DE.gate(f"{kind.upper()}30 {sym} er>=0.5 trending (control)",
                lambda m, a=sl & (erp >= 0.5), b=ss & (erp >= 0.5): mk(a, b, m))


if __name__ == "__main__":
    main()
