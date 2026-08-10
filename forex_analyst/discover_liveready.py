"""DISCOVERY STUDY 7 — the LIVE-READY hunt, per asset class (owner directive).

  A. XAGUSD (silver) — the rejected asset, retried honestly at its real all-in
     cost (0.03, the house number from multi_symbol_lab; 2x/3x stress shown) on
     15 YEARS of true-UTC H1: metal trend family (DONCH rr3 / trail4, VCX, H4).
  B. FX pairs — cross-pair REPLICATION of the validated live families using the
     HOUSE machinery itself (fx_h1_backtest.run_A / run_E on live_signals
     functions, deployed configs, NO re-tuning): A-family on GBPUSD/EURUSD,
     E-family on USDCHF/USDCAD.
  C. Gold: F4/F5/F6 finalists already validated (see PART_B_SLATE).
  D. Indices: consolidation of the H1/H4 trail candidates (2022+ grade).

Everything -> discovery_ledger.csv. A null stays a null.
"""
import sys
import types

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

import discovery_engine as DE
import event_price_lib as epl
import live_signals as LS
import fx_h1_backtest as FXB
from discover_breadth import donch_sig, vcx_sig

XAG_COST = 0.03


def silver_frame(tf):
    df = epl._load_tab("data/XAGUSD60.csv", "utc")
    if tf != 60:
        g = df.set_index("timestamp_ny").resample(f"{tf}min")
        df = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                           "low": g["low"].min(), "close": g["close"].last()}
                          ).dropna().reset_index()
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    df["hour"] = df["timestamp_ny"].dt.hour
    return df


def main():
    print("=" * 110)
    print("STUDY 7 — LIVE-READY HUNT PER ASSET CLASS")
    print("=" * 110)

    # ---------------- A. SILVER ----------------
    print("\n[A] XAGUSD, 2011-2026 true-UTC H1, cost 0.03 all-in:")
    s1 = silver_frame(60)
    c = s1["close"].to_numpy(float); a = s1["atr50"].to_numpy(float)
    stop_abs = c - 2.0 * a
    for name, sig in (("DONCH96", donch_sig(s1, 96)),
                      ("VCX W96 q0.25", vcx_sig(s1, 96, 0.25))):
        DE.gate(f"XAG H1 {name} rr3",
                lambda m, s=sig: DE.run_trades(s1, s, None, XAG_COST * m,
                                               stop_abs=stop_abs, rr=3.0,
                                               max_hold=96, max_tpd=2))
        DE.gate(f"XAG H1 {name} trail4",
                lambda m, s=sig: DE.run_trades(s1, s, None, XAG_COST * m,
                                               stop_abs=stop_abs, trail_atr=4.0,
                                               max_hold=192, max_tpd=2))
    s4 = silver_frame(240)
    c4 = s4["close"].to_numpy(float); a4 = s4["atr50"].to_numpy(float)
    sig = donch_sig(s4, 96)
    DE.gate("XAG H4 DONCH96 trail4",
            lambda m, s=sig: DE.run_trades(s4, s, None, XAG_COST * m,
                                           stop_abs=c4 - 2 * a4, trail_atr=4.0,
                                           max_hold=96, max_tpd=1))
    # short side too — silver crashes hard (house CRASH analogue)
    lo96 = s1["low"].shift(1).rolling(96).min().to_numpy(float)
    sig_dn = c < lo96 - 0.1 * a
    DE.gate("XAG H1 DONCH96-DOWN short trail4",
            lambda m, s=sig_dn: DE.run_trades(s1, None, s, XAG_COST * m,
                                              stop_abs=c + 2 * a, trail_atr=4.0,
                                              max_hold=192, max_tpd=2))

    # ---------------- B. FX cross-pair replication ----------------
    print("\n[B] FX family replication (house machinery, deployed configs, no re-tuning):")

    def fx_frame(sym):
        d60 = epl._load_tab(f"data/{sym}60.csv", "utc")
        d60["volume"] = np.nan
        g = d60.set_index("timestamp_ny").resample("240min")
        d240 = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                             "low": g["low"].min(), "close": g["close"].last(),
                             "volume": g["volume"].sum()}).dropna().reset_index()
        e = LS.prep_h1_frame(d60, d240)
        if "ny_date" not in e.columns:
            e["ny_date"] = e["timestamp_ny"].dt.date.astype(str)
        e["year"] = e["timestamp_ny"].dt.year
        return e

    def rep(tag, trades):
        t = pd.DataFrame(trades)
        if not len(t):
            print(f"{tag}: no trades"); return
        r = t["result_r"]
        tr = t.loc[t.year <= 2023, "result_r"].sum()
        ho = t.loc[t.year >= 2024, "result_r"].sum()
        ys = t.groupby("year")["result_r"].sum()
        print(f"{tag:<46} n={len(t):<5} net={r.sum():+7.1f}R avg={r.mean():+.3f} "
              f"WR={(r > 0).mean() * 100:.0f}% | tr={tr:+7.1f} ho={ho:+6.1f} | "
              f"+yrs {(ys > 0).sum()}/{len(ys)}")

    frames = {s: fx_frame(s) for s in ("EURUSD", "GBPUSD", "USDCHF", "USDCAD")}
    for target in ("EURUSD", "GBPUSD"):
        for src_cfg in ("USDCAD-A", "USDCHF-A"):
            cfg = LS.FX_STRATS[src_cfg]
            for sides in (("bullish", "bearish"), ("bearish",)):
                lbl = "both" if len(sides) == 2 else "short-only"
                rep(f"A({src_cfg}) on {target} {lbl}",
                    FXB.run_A(frames[target], target, f"A-{target}", cfg,
                              LS.FX_SPREADS[target], sides=sides))
    for target in ("USDCHF", "USDCAD"):
        cfg = LS.FX_STRATS["GBPUSD-E"]
        rep(f"E(GBPUSD-E cfg) on {target}",
            FXB.run_E(frames[target], target, f"E-{target}", cfg,
                      LS.FX_SPREADS[target]))
        cfg2 = dict(LS.FX_STRATS["EURUSD-E"])
        rep(f"E(EURUSD-E cfg, hours) on {target}",
            FXB.run_E(frames[target], target, f"E2-{target}", cfg2,
                      LS.FX_SPREADS[target]))


if __name__ == "__main__":
    main()
