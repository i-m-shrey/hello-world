"""DISCOVERY STUDY 4 (A2) — the adaptive-exit lens applied across the trend book.

Deployed baselines (fixed-RR exits) vs chandelier trails, LIVE stop convention
(structural stop = signal_close - stop_atr*ATR), TZ-correct data, all-in costs.
Families: gold MACROSS (H4-gated), index DONCH-96 (SPX500/GER40/US30/JPN225),
gold BOS (pivot-cross, deployed rr5) and GER40 BOS (deployed rr3).
Index history is 2022+ — evidence, not 18-year proof; labeled in the note.
"""
import numpy as np
import pandas as pd

import discovery_engine as DE
from discover_trend import gold_h1, donch_sig, h4_gate


def macross_sig(d, gate):
    e20 = d["ema20"].to_numpy(float); e50 = d["ema50"].to_numpy(float)
    cross = (e20 > e50) & (np.roll(e20, 1) <= np.roll(e50, 1))
    cross[0] = False
    return cross & gate


def bos_sig(d, k=3, pad=0.1):
    """Causal pivot-high cross (concepts_wave2 q8 convention)."""
    h = d["high"].to_numpy(float); c = d["close"].to_numpy(float)
    atr = d["atr50"].to_numpy(float)
    n = len(d)
    lvl = np.full(n, np.nan)
    last = np.nan
    # pivot at p confirmed at p+k
    ph = np.zeros(n, bool)
    for p in range(k, n - k):
        w = h[p - k:p + k + 1]
        if h[p] == w.max() and (h[p] > h[p - k:p]).all():
            ph[p] = True
    for j in range(n):
        p = j - k
        if p >= 0 and ph[p]:
            last = h[p]
        lvl[j] = last
    cross = np.zeros(n, bool)
    prev_below = np.roll(c <= lvl + pad * atr, 1)
    cross = (c > lvl + pad * atr) & prev_below & np.isfinite(lvl)
    cross[0] = False
    return cross


def sweep(tag, d, sig, cost, base_rr, note="", min_n=80):
    c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
    stop_abs = c - 2.0 * atr
    DE.gate(f"{tag} FIXED rr{base_rr} (deployed shape)",
            lambda m: DE.run_trades(d, sig, None, cost * m, stop_abs=stop_abs,
                                    rr=base_rr, max_hold=96, max_tpd=2),
            note=note, min_n=min_n)
    for trail in (3.0, 4.0, 5.0):
        DE.gate(f"{tag} TRAIL {trail}ATR",
                lambda m, t=trail: DE.run_trades(d, sig, None, cost * m,
                                                 stop_abs=stop_abs, trail_atr=t,
                                                 max_hold=192, max_tpd=2),
                note=note, min_n=min_n)


def main():
    print("=" * 110)
    print("STUDY 4 — ADAPTIVE EXITS ACROSS THE TREND BOOK (live stop convention)")
    print("=" * 110)

    g = gold_h1()
    cost_g = DE.COST["XAUUSD"]
    gate4 = h4_gate("XAUUSD", g)

    print("\n[gold MACROSS, H4-gated long]")
    sweep("MACROSS gold", g, macross_sig(g, gate4), cost_g, 3.0)

    print("\n[gold BOS pivot-cross long, deployed rr5]")
    sweep("BOS gold", g, bos_sig(g), cost_g, 5.0)

    for sym in ("SPX500", "GER40", "US30", "JPN225"):
        try:
            d = DE.frames(sym, 60)
        except Exception as e:
            print(f"{sym}: no data ({e})"); continue
        print(f"\n[{sym} DONCH-96 long (2022+ evidence)]")
        sweep(f"DONCH96 {sym}", d, donch_sig(d, 96), DE.COST[sym], 3.0,
              note="2022+ only", min_n=25)

    d = DE.frames("GER40", 60)
    print("\n[GER40 BOS, deployed rr3 (2022+ evidence)]")
    sweep("BOS GER40", d, bos_sig(d), DE.COST["GER40"], 3.0,
          note="2022+ only", min_n=25)


if __name__ == "__main__":
    main()
