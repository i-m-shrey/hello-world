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

    print("=" * 78)
    bad = [n for n, ok in RESULTS if not ok]
    print("OVERALL: ALL SECTIONS PASS" if not bad else f"OVERALL: FAIL -> {bad}")


if __name__ == "__main__":
    main()
