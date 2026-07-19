"""VERIFY GS BATTERY — proof harness for gs_battery_lab.py (July 2026).

Sections:
  [1] causality      — truncation test: signals on a shortened frame identical
  [2] pivot_k=5      — synthetic proof pivots confirm exactly K bars late
  [3] costs          — raising cost strictly lowers avg_r on the same events
  [4] split          — every trade lands in exactly one of train/holdout
  [5] limit fills    — pessimistic same-bar stop+target => loss (synthetic)
  [6] trail          — chandelier trail is closed-bar (can't exit on its own bar)
  [7] reproduce      — flagship matrix cells reproduce from scratch
"""
import sys
import types

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))
sys.path.insert(0, ".")
import gs_battery_lab as G  # noqa: E402

RESULTS = []


def section(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")


def hdr(t):
    print("=" * 78 + f"\n[{t}]\n" + "=" * 78)


def main():
    df = G.prep(G.load_any("XAUUSD", "H1"))
    months = max((df["timestamp_ny"].iloc[-1] - df["timestamp_ny"].iloc[0]).days, 1) / 30.44

    hdr("1: CAUSALITY — truncation invariance")
    cut = len(df) - 500
    dcut = G.prep(G.load_any("XAUUSD", "H1").iloc[:cut].reset_index(drop=True))
    for name, fn in [("GS02T", lambda d: G.ev_gs02(d, "XAUUSD", 0.5, 1.0, "opp")),
                     ("GS06", lambda d: G.ev_gs06(d, "XAUUSD")),
                     ("HAVW", lambda d: G.ev_havw(d, "XAUUSD")),
                     ("SMC1", lambda d: G.ev_smc1(d, "XAUUSD"))]:
        full = [(e["i"], e["side"]) for e in fn(df) if e["i"] < cut - 60]
        part = [(e["i"], e["side"]) for e in fn(dcut) if e["i"] < cut - 60]
        section(f"{name} truncation-invariant", full == part,
                f"{len(full)} events identical with 500 future bars removed")

    hdr("2: PIVOT_K=5 — confirmation lag proof")
    n = 40
    h = np.full(n, 10.0); l = np.full(n, 9.0)
    h[15] = 12.0; l[15] = 8.5                      # extreme at bar 15
    from concepts_rank_lab import pivot_levels
    hi, lo = pivot_levels(h, l, G.PIVOT_K)
    first_hi = next((t for t in range(n) if np.isfinite(hi[t]) and hi[t] == 12.0), None)
    section("pivot high confirmed exactly K=5 bars after the extreme",
            first_hi == 15 + 5, f"extreme@15, level first visible@{first_hi}")

    hdr("3: COSTS — monotone cost damage")
    evs = G.ev_havw(df, "XAUUSD")
    a0 = G.run_events(df, evs, 0.0)["r"].mean()
    a1 = G.run_events(df, evs, G.COSTS["XAUUSD"])["r"].mean()
    a3 = G.run_events(df, evs, G.COSTS["XAUUSD"] * 3)["r"].mean()
    section("avg_r strictly decreases as cost rises", a0 > a1 > a3,
            f"cost0 {a0:+.4f} > cost1 {a1:+.4f} > cost3 {a3:+.4f}")

    hdr("4: SPLIT — train/holdout partition")
    tb = G.run_events(df, evs, G.COSTS["XAUUSD"])
    tr = tb[tb["ny_date"] <= G.TRAIN_END]; ho = tb[tb["ny_date"] > G.TRAIN_END]
    section("every trade in exactly one split", len(tr) + len(ho) == len(tb),
            f"{len(tr)} train + {len(ho)} holdout = {len(tb)}")

    hdr("5: LIMIT FILLS — pessimistic same-bar rule")
    sy = pd.DataFrame({
        "timestamp_ny": pd.date_range("2020-01-01", periods=60, freq="1h",
                                      tz="America/New_York"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0})
    sy.loc[30, ["open", "high", "low", "close"]] = [100.0, 106.0, 88.0, 100.0]
    sy = G.prep(G.add_ist(sy))
    ev = [dict(i=25, side=1, entry="limit", limit=99.5, expiry=10,
               stop=98.0, rr=2.0, max_hold=20)]
    out = G.run_events(sy, ev, 0.0)
    section("fill bar touching stop AND target counts as the LOSS",
            len(out) == 1 and out["r"].iloc[0] < 0,
            f"r={out['r'].iloc[0]:+.2f} on the ambiguous bar" if len(out) else "no fill")

    hdr("6: TRAIL — closed-bar chandelier")
    sy2 = pd.DataFrame({
        "timestamp_ny": pd.date_range("2020-01-01", periods=80, freq="1h",
                                      tz="America/New_York"),
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0})
    for k in range(40, 60):
        base = 100 + (k - 40) * 0.5
        sy2.loc[k, ["open", "high", "low", "close"]] = [base, base + 0.6, base - 0.4,
                                                        base + 0.5]
    sy2.loc[60, ["open", "high", "low", "close"]] = [110.0, 130.0, 109.5, 129.0]
    sy2 = G.prep(G.add_ist(sy2))
    ev2 = [dict(i=41, side=1, stop=95.0, trail_mult=3.0, max_hold=40)]
    out2 = G.run_events(sy2, ev2, 0.0)
    section("trail never exits on the bar that raised it",
            len(out2) == 1 and out2["r"].iloc[0] > 0,
            f"r={out2['r'].iloc[0]:+.2f}" if len(out2) else "no trade")

    hdr("7: REPRODUCE — flagship matrix cells")
    mx = pd.read_csv("gs_battery_matrix.csv")
    for cid, sym, tf, gen, kw in [
            ("HAVW-XAUUSD-H1", "XAUUSD", "H1", G.ev_havw, {}),
            ("GS06-XAUUSD-H1", "XAUUSD", "H1", G.ev_gs06, {}),
            ("HAVW-EURUSD-H4", "EURUSD", "H4", G.ev_havw, {})]:
        d = df if (sym, tf) == ("XAUUSD", "H1") else G.prep(G.load_any(sym, tf))
        mo = max((d["timestamp_ny"].iloc[-1] - d["timestamp_ny"].iloc[0]).days, 1) / 30.44
        st = G.stats(G.run_events(d, gen(d, sym, **kw), G.COSTS[sym]), mo)
        row = mx[mx["id"] == cid].iloc[0]
        ok = (st["n"] == row["n"] and abs(st["avg_r"] - row["avg_r"]) < 1e-9)
        section(f"{cid} reproduces", ok,
                f"n={st['n']} avg={st['avg_r']:+.4f} vs saved n={row['n']} "
                f"avg={row['avg_r']:+.4f}")

    hdr("8: LIVE PARITY — deployed signal_HAVW == lab ev_havw")
    import live_signals as LS
    for sym, tf, ckey in [("XAUUSD", "H1", "XAUUSD-HAVW"),
                          ("EURUSD", "H4", "EURUSD-HAVW"),
                          ("GBPUSD", "H4", "GBPUSD-HAVW")]:
        d = df if (sym, tf) == ("XAUUSD", "H1") else G.prep(G.load_any(sym, tf))
        cfg = LS.FX_STRATS[ckey]
        ev_map = {e["i"]: e for e in G.ev_havw(d, sym)}
        sig_bars = sorted(ev_map)[-40:]
        good = 0
        for i in sig_bars:
            res = LS.signal_HAVW(d, i, cfg)
            e = ev_map[i]
            want = "long" if e["side"] == 1 else "short"
            if res and res["direction"] == want and abs(res["stop"] - e["stop"]) < 1e-6:
                good += 1
        rng = np.random.default_rng(7)
        ctrl = rng.choice([i for i in range(200, len(d) - 1) if i not in ev_map],
                          300, replace=False)
        ff = sum(1 for i in ctrl if LS.signal_HAVW(d, int(i), cfg) is not None)
        section(f"{ckey} live path parity", good == len(sig_bars) and ff == 0,
                f"{good}/{len(sig_bars)} signals reproduced, {ff} false fires in 300 controls")

    hdr("9: WIRING SAFETY — deployed HAVW instances")
    from unittest.mock import MagicMock
    sys.modules["MetaTrader5"] = MagicMock()
    import importlib
    import live_mt5_bot as B
    importlib.reload(B)
    for k in ("XAUUSD_HAVW", "EURUSD_HAVW", "GBPUSD_HAVW"):
        inst = B.INSTANCES[k]
        checks = (k in B.LOTS and k in B.ENABLE
                  and inst["risk_mode"] == "trend_trail" and inst["exit"] == "trail"
                  and inst["cfg"]["trail_basis"] == "hh22"
                  and inst["cfg"]["trail_atr"] == 3.0 and inst["cfg"]["stop_atr"] == 3.0
                  and inst.get("equity_min", 0) >= 250)
        section(f"{k} wired (lots/enable/trail_basis/gates)", bool(checks),
                f"magic={inst['magic']} feed={inst['feed']} equity_min={inst.get('equity_min')}")
    fx_caps = (B.INSTANCES["EURUSD_HAVW"].get("fx_max_risk_usd") == 15.0
               and B.INSTANCES["GBPUSD_HAVW"].get("fx_max_risk_usd") == 15.0
               and B.INSTANCES["XAUUSD_HAVW"].get("fx_max_risk_usd") is None)
    section("FX H4 instances carry the $15 per-instance cap; gold rides the $ guard",
            fx_caps)
    section("H4 feeds registered", all(f in B.SYMBOLS for f in ("EURUSD_H4", "GBPUSD_H4")),
            "EURUSD_H4 + GBPUSD_H4 bar_min=240")

    print("=" * 78)
    bad = [n for n, ok in RESULTS if not ok]
    print("OVERALL: ALL SECTIONS PASS" if not bad else f"OVERALL: FAIL -> {bad}")


if __name__ == "__main__":
    main()
