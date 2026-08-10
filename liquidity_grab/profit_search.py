"""PROFIT SEARCH v2 (2016+) — literal spec-v2 backtest + structural tweak scan.

Spec v2 (user's detailed rules, differs from the first brief):
  * SL at the EXTREME of the whole fake-out move (sl_mode=1), not the signal
    candle's high;
  * signal candle should have a visible body (body_frac);
  * max TWO FULL stop losses per zone; winners/BE runners don't count
    (att_mode=1, max_att=2);
  * T1 = most recent MAJOR swing (M15 k=2 fractal), 80% booked, 20% runner
    to session end with SL at breakeven (CTC).

Anti-overfit protocol, stated up front:
  * selection happens ONLY on train = 2016..2022;
  * valid = 2023..2026-07 is untouched by selection and reported as-is;
  * every screened cell is counted (multiplicity visible in the CSV);
  * survivors must also be train-positive at 2x the $0.23 all-in cost.

Structural levers: execution TF 1/5/15m, NY entry window, min-risk floor,
sl_mode, body filter, T1 mode, runner mode, attempt scheme.
"""
import itertools
import os
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "profit_search_results.csv")
START_YEAR = 2016
TRAIN_END = 2022
COST = lg.COST

WINDOWS = {"all": (0, 1440), "ldnny": (120, 720), "nyam": (420, 720)}
FLOORS = [0.0, 1.0]
MINBARS = {1: 500, 5: 100, 15: 33}
ATT_SCHEMES = {"A2sl": (2, 1), "A3e": (3, 0)}     # (max_att, att_mode)
T1S = (1, 2, 3)                                    # m15k2 / rr3 / rr5
RUNS = (0, 2)                                      # sess-end BE / chandelier

_LABS = {}


def build_lab(tf):
    if tf in _LABS:
        return _LABS[tf]
    df = lg.load_m1() if tf == 1 else lg.resample_ny(lg.load_m1(), tf)
    df = lg.add_session(df)
    lg.MIN_BARS_SESSION = MINBARS[tf]
    st = lg.session_table(df)
    sess = lg.add_force_bars(lg.tradeable_sessions(st), df)
    sess = sess[sess["year"] >= START_YEAR].reset_index(drop=True)
    _LABS[tf] = lg.Lab(df, sess)
    return _LABS[tf]


def stats(tb):
    if tb is None or not len(tb):
        return dict(n=0, net=0.0, avg=np.nan, wr=np.nan,
                    tr_n=0, tr_net=0.0, tr_avg=np.nan,
                    va_n=0, va_net=0.0, va_avg=np.nan, maxdd=np.nan)
    r = tb["r"]
    tr = tb["year"] <= TRAIN_END
    va = ~tr
    eq = r.cumsum()
    return dict(n=len(tb), net=float(r.sum()), avg=float(r.mean()),
                wr=float((r > 0).mean()),
                tr_n=int(tr.sum()), tr_net=float(r[tr].sum()),
                tr_avg=float(r[tr].mean()) if tr.any() else np.nan,
                va_n=int(va.sum()), va_net=float(r[va].sum()),
                va_avg=float(r[va].mean()) if va.any() else np.nan,
                maxdd=float((eq - eq.cummax()).min()))


def describe(tag, tb):
    s = stats(tb)
    r = tb["r"]
    yr = tb.groupby("year")["r"].sum().round(1)
    hit = tb[tb["t1_hit"] == 1]
    print(f"\n== {tag} ==")
    print(f"n={s['n']}  wr={s['wr']:.1%}  avg={s['avg']:+.3f}R  "
          f"net={s['net']:+.1f}R  maxdd={s['maxdd']:+.1f}R")
    print(f"train 16-22: n={s['tr_n']} net={s['tr_net']:+.1f} avg={s['tr_avg']:+.3f} | "
          f"valid 23-26: n={s['va_n']} net={s['va_net']:+.1f} avg={s['va_avg']:+.3f}")
    print(f"T1 hit rate {(tb['t1_hit'] == 1).mean():.1%}; planned RR at T1 "
          f"median {tb['rr_t1_planned'].median():.2f} "
          f"(banked winners avg {hit['rr_t1_planned'].mean():.2f})")
    print(f"full-SL rate {((tb['reason'] == 1) & (tb['t1_hit'] == 0)).mean():.1%}; "
          f"per-year: {yr.to_dict()}")
    return s


def main():
    lab1 = build_lab(1)

    # ── literal spec v2 on M1 ────────────────────────────────────────────────
    v2 = dict(qual=0, sel=0, t1=1, run=0, att=2, sl_mode=1, body_frac=0.25,
              att_mode=1)
    tb = lab1.run(v2["qual"], v2["sel"], v2["t1"], v2["run"], v2["att"], COST,
                  sl_mode=v2["sl_mode"], body_frac=v2["body_frac"],
                  att_mode=v2["att_mode"])
    describe("LITERAL SPEC v2 (M1, fake-out SL, body>=25%, 2 full SLs/zone, "
             "T1=major swing, 80/20 BE runner)", tb)
    tb.to_csv(os.path.join(HERE, "specv2_tradebook.csv"), index=False)
    for label, mult in (("2x cost", 2.0), ("frictionless", 0.0)):
        t = lab1.run(v2["qual"], v2["sel"], v2["t1"], v2["run"], v2["att"],
                     COST * mult, sl_mode=v2["sl_mode"],
                     body_frac=v2["body_frac"], att_mode=v2["att_mode"])
        s = stats(t)
        print(f"   [{label}] n={s['n']} avg={s['avg']:+.3f} net={s['net']:+.1f} "
              f"tr={s['tr_net']:+.1f} va={s['va_net']:+.1f}")

    # ── structural grid ─────────────────────────────────────────────────────
    rows = []
    for tf in (15, 5, 1):
        lab = build_lab(tf)
        print(f"\n-- TF M{tf}: {len(lab.sess)} sessions, {len(lab.df)} bars --",
              flush=True)
        it = itertools.product(WINDOWS.items(), FLOORS, (0, 1), (0.0, 0.25),
                               T1S, RUNS, ATT_SCHEMES.items())
        for (wname, (elo, ehi)), floor, slm, bf, t1, run, (aname, (att, am)) in it:
            tb = lab.run(0, 0, t1, run, att, COST, ent_lo=elo, ent_hi=ehi,
                         min_risk=floor, sl_mode=slm, body_frac=bf, att_mode=am)
            s = stats(tb)
            name = (f"M{tf}-{wname}-f{floor:g}-sl{slm}-b{bf:g}-"
                    f"T1{lg.T1_N[t1]}-R{lg.RUN_N[run]}-{aname}")
            rows.append(dict(cell=name, tf=tf, window=wname, floor=floor,
                             sl_mode=slm, body=bf, t1=t1, run=run,
                             att_scheme=aname, **s))
        print(f"   cells so far: {len(rows)}", flush=True)
    res = pd.DataFrame(rows)

    # stage 2: 2x-cost re-run for train-screen survivors only
    screen = (res["tr_n"] >= 120) & (res["tr_avg"] >= 0.05)
    print(f"\nscreened {len(res)} cells; train-screen survivors: "
          f"{int(screen.sum())}", flush=True)
    res["tr_avg_2x"] = np.nan
    res["va_avg_2x"] = np.nan
    for i in res.index[screen]:
        row = res.loc[i]
        elo, ehi = WINDOWS[row["window"]]
        att, am = ATT_SCHEMES[row["att_scheme"]]
        tb2 = build_lab(int(row["tf"])).run(
            0, 0, int(row["t1"]), int(row["run"]), att, COST * 2,
            ent_lo=elo, ent_hi=ehi, min_risk=float(row["floor"]),
            sl_mode=int(row["sl_mode"]), body_frac=float(row["body"]),
            att_mode=am)
        s2 = stats(tb2)
        res.loc[i, "tr_avg_2x"] = s2["tr_avg"]
        res.loc[i, "va_avg_2x"] = s2["va_avg"]
    res["pass"] = (screen & (res["va_net"] > 0) & (res["va_avg"] >= 0.03)
                   & (res["tr_avg_2x"] > 0))
    res.sort_values("tr_avg", ascending=False).to_csv(OUT, index=False)
    print(f"wrote {OUT}")

    cols = ["cell", "n", "wr", "tr_n", "tr_avg", "tr_net", "va_n", "va_avg",
            "va_net", "tr_avg_2x", "va_avg_2x", "pass"]
    print("\n== top 15 by TRAIN avg R (selection metric); validation as-is ==")
    print(res.sort_values("tr_avg", ascending=False).head(15)[cols]
          .to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    npass = int(res["pass"].sum())
    print(f"\nPASS cells (train screen & valid+ & 2x-cost train+): "
          f"{npass} / {len(res)}")
    if npass:
        print(res[res["pass"]].sort_values("va_avg", ascending=False)[cols]
              .head(25).to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
