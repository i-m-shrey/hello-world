"""REFINE LAB — last principled pass at making the liquidity-grab profitable.

Two levers, both selected ONLY on train 2016..2022, validated on 2023..2026-07:
  1. sweep-depth filter: only trade fake-outs whose excursion beyond the
     PDH/PDL line is >= k * ATR(M5,50) at entry (deep grab = real trap;
     shallow poke = noise). In-engine (min_depth_atr), so the 2-full-SL
     accounting stays honest.
  2. multi-day runner: the video's 600-1200 pip runners cannot happen with a
     16:55 force-flat. Reason-4 exits (runner alive at session end) are
     re-simulated holding the 20% leg across sessions on a breakeven floor
     plus optional tighten-only chandelier (k * ATR(M5,50)), capped at ~10
     sessions. The 80% T1 leg is untouched; no extra cost is charged (the
     round trip is already paid).
Also scanned: booked fraction 80% vs 50% (leg decomposition is exact for
t1-hit trades; single-leg trades are unaffected).

Base config = literal spec v2: M1, close-qualifier, body>=25%, most-recent
signal candle, T1 = M15 k=2 swing, fake-out-extreme SL, 2 full SLs per zone,
80/20 with BE runner.
"""
import os
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg

HERE = os.path.dirname(os.path.abspath(__file__))
COST = lg.COST
TRAIN_END = 2022
CAP_BARS = 14000            # ~10 sessions of M1 bars
V2 = dict(qual=0, sel=0, t1=1, run=0, att=2, sl_mode=1, body_frac=0.25,
          att_mode=1)


def build_lab():
    df = lg.add_session(lg.load_m1())
    st = lg.session_table(df)
    sess = lg.add_force_bars(lg.tradeable_sessions(st), df)
    sess = sess[sess["year"] >= 2016].reset_index(drop=True)
    return lg.Lab(df, sess)


def legs(tb, cost):
    """Decompose recorded r into (r1, r2) for t1-hit rows (exact: engine used
    r = .8*r1 + .2*r2). Single-leg rows return (nan, nan)."""
    e, t1, risk, side = (tb[k].to_numpy() for k in ("entry", "t1", "risk", "side"))
    r1 = np.where(side == -1, (e - t1) - cost, (t1 - e) - cost) / risk
    hit = (tb["t1_hit"] == 1).to_numpy()
    r = tb["r"].to_numpy()
    r2 = np.where(hit, (r - lg.BOOK_FRAC * r1) / (1 - lg.BOOK_FRAC), np.nan)
    r1 = np.where(hit, r1, np.nan)
    return r1, r2


def extend_runner(lab, tb, cost, trail_mult):
    """Re-simulate the 20% runner beyond session end for reason-4 exits.
    trail_mult <= 0: pure breakeven stop. Returns replacement r2 array
    (nan where unchanged) + holding stats."""
    o, h, l, c = lab.o, lab.h, lab.l, lab.c
    m5map, chs, chl = lab.m5_map, lab.chand_s, lab.chand_l
    n = len(o)
    r2n = np.full(len(tb), np.nan)
    held = []
    idx = np.flatnonzero((tb["reason"] == 4).to_numpy())
    for i in idx:
        row = tb.iloc[i]
        side = int(row["side"]); e = float(row["entry"]); risk = float(row["risk"])
        rs = e                                       # breakeven floor
        j = int(row["exit_j"])                       # force bar: keep holding
        end = min(n - 1, j + CAP_BARS)
        xpx = c[end]
        while j <= end:
            if trail_mult > 0:
                mi = m5map[j]
                if mi >= 0:
                    atr = (chs[mi] - chl[mi]) / 4.0
                    if np.isfinite(atr):
                        cv = (c[j] + trail_mult * atr if side == -1
                              else c[j] - trail_mult * atr)
                        # tighten-only, never worse than breakeven
                        if side == -1:
                            if cv < rs:
                                rs = cv
                        else:
                            if cv > rs:
                                rs = cv
            jn = j + 1
            if jn > end:
                break
            if side == -1:
                if h[jn] >= rs:
                    xpx = o[jn] if o[jn] > rs else rs
                    j = jn
                    break
            else:
                if l[jn] <= rs:
                    xpx = o[jn] if o[jn] < rs else rs
                    j = jn
                    break
            j = jn
        r2n[i] = ((e - xpx) - cost) / risk if side == -1 else ((xpx - e) - cost) / risk
        held.append(j - int(row["exit_j"]))
    return r2n, (np.median(held) if held else np.nan)


def recompose(tb, cost, frac, r2_new=None):
    """Total r under booked-fraction `frac` and optional runner replacement."""
    r1, r2 = legs(tb, cost)
    if r2_new is not None:
        r2 = np.where(np.isfinite(r2_new), r2_new, r2)
    hit = (tb["t1_hit"] == 1).to_numpy()
    return np.where(hit, frac * r1 + (1 - frac) * r2, tb["r"].to_numpy())


def stats(r, yr):
    tr = yr <= TRAIN_END
    va = ~tr
    return dict(n=len(r), wr=float((r > 0).mean()), avg=float(r.mean()),
                net=float(r.sum()),
                tr_n=int(tr.sum()), tr_avg=float(r[tr].mean()) if tr.any() else np.nan,
                tr_net=float(r[tr].sum()),
                va_n=int(va.sum()), va_avg=float(r[va].mean()) if va.any() else np.nan,
                va_net=float(r[va].sum()))


def main():
    lab = build_lab()
    rows = []
    books = {}
    for depth in (0.0, 3.0, 4.0, 5.0):
        for cmult, tag in ((1.0, ""), (2.0, "@2x")):
            tb = lab.run(V2["qual"], V2["sel"], V2["t1"], V2["run"], V2["att"],
                         COST * cmult, sl_mode=V2["sl_mode"],
                         body_frac=V2["body_frac"], att_mode=V2["att_mode"],
                         min_depth_atr=depth)
            books[(depth, cmult)] = tb
            yr = tb["year"].to_numpy()
            for rmode in ("sess", "extBE", "extCh2", "extCh3"):
                if rmode == "sess":
                    r2n, medhold = None, 0.0
                else:
                    tm = {"extBE": 0.0, "extCh2": 2.0, "extCh3": 3.0}[rmode]
                    r2n, medhold = extend_runner(lab, tb, COST * cmult, tm)
                for frac in (0.8, 0.5):
                    r = recompose(tb, COST * cmult, frac, r2n)
                    s = stats(r, yr)
                    rows.append(dict(cell=f"d{depth:g}-{rmode}-b{int(frac*100)}{tag}",
                                     depth=depth, runner=rmode, frac=frac,
                                     cost_mult=cmult, med_hold_bars=medhold, **s))
                    print(f"{rows[-1]['cell']:<24} n={s['n']:<5} wr={s['wr']:.2f} "
                          f"avg={s['avg']:+.3f} tr={s['tr_avg']:+.3f}/{s['tr_net']:+7.1f} "
                          f"va={s['va_avg']:+.3f}/{s['va_net']:+7.1f}", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "refine_results.csv"), index=False)

    r1x = res[res["cost_mult"] == 1.0].copy()
    r1x["sel_metric"] = r1x["tr_avg"]
    best = r1x.sort_values("sel_metric", ascending=False).iloc[0]
    print("\nbest by TRAIN avg:", best["cell"])
    # its 2x row
    twin = res[(res["cell"] == best["cell"].replace("d", "d") + "@2x")]
    print("2x-cost twin:\n", twin.to_string(index=False) if len(twin) else "n/a")

    # per-year for the best cell
    depth = float(best["depth"])
    tb = books[(depth, 1.0)]
    r2n = (None if best["runner"] == "sess" else
           extend_runner(lab, tb, COST,
                         {"extBE": 0.0, "extCh2": 2.0, "extCh3": 3.0}[best["runner"]])[0])
    r = recompose(tb, COST, float(best["frac"]), r2n)
    out = tb.copy()
    out["r_refined"] = r
    out.to_csv(os.path.join(HERE, "refined_tradebook.csv"), index=False)
    print("\nper-year net R (best cell):")
    print(pd.Series(r).groupby(tb["year"].to_numpy()).sum().round(1).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
