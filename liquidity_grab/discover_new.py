"""discover_new.py — from-scratch discovery of NEW strategy families, none of
which exist in the owner's deployed bot (live_mt5_bot_FINAL.py) or its research
battery (Donchian/EMA-cross/BOS/VCX/STRAD/CRASH/BOLL/P1/AVWAP/HAVW/ZBPIV/A/E/
RSI/S-series are all EXCLUDED by construction).

Families (each a different mechanism):
  ORB      session opening-range breakout (London 02:00 / NY 08:00 NY-time,
           M15 exec): first `rng_min` minutes set the range; a close beyond
           range edge + pad*ATR before the cutoff enters with the stop at the
           opposite edge; fixed-RR target.
  PULL     H1 EMA-pullback trend continuation: price above/below EMA200, bar
           dips to touch EMA20 and closes back in the trend direction ->
           continuation entry, ATR stop, fixed-RR target.
  TSMOM    D1 (midnight-NY candles) time-series momentum: close breaks the
           prior N-day extreme -> position with a k*ATR(D1) chandelier trail,
           long+short.
  AFADE    Asia-range reversion at London: at 02:00-04:00 NY, close stretched
           >= k*ATR from the 17:00-02:00 Asia midpoint -> fade toward the
           midpoint (target = midpoint), ATR stop, out by midday.
  HANDOFF  London->NY momentum handoff: London session move (02:00->07:45)
           >= k*ATR in one direction -> enter WITH it at the 08:00 open,
           ATR stop, fixed-RR, out by session end.
  IBX      H4 inside-bar compression breakout: bar i-1 inside bar i-2; bar i
           breaks the inside bar's extreme -> continuation entry, stop at the
           inside bar's other extreme, fixed-RR.

Protocol: per family x symbol a SMALL parameter grid (labelled; every cell
recorded to discover_new_results.csv). Selection on TRAIN only (gold 2008-23,
FX 2016-22), validation untouched (gold >=2024, FX >=2023), house all-in costs
with 2x/3x stress, plateau = majority of the family's cells train-positive.
Executor = strategy_scout.run_trades (validated mirror of the house executor).
"""
import itertools
import os
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg
from multi_asset import load_pair
from strategy_scout import frame, run_trades

HERE = os.path.dirname(os.path.abspath(__file__))
COSTS = {"XAUUSD": 0.23, "EURUSD": 0.00008, "GBPUSD": 0.00010,
         "USDCHF": 0.00010, "USDCAD": 0.00014,
         "USDJPY": 0.012, "AUDUSD": 0.00010}
SYMS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
TRAIN_END = {"XAUUSD": 2023}          # FX defaults to 2022 (2016+ data)
_M1 = {}
_FR = {}


def m1(sym):
    if sym not in _M1:
        _M1[sym] = lg.load_m1() if sym == "XAUUSD" else load_pair(sym)
    return _M1[sym]


def fr(sym, tf):
    key = (sym, tf)
    if key not in _FR:
        _FR[key] = frame(m1(sym), tf)
    return _FR[key]


def split_stats(t, sym):
    te = TRAIN_END.get(sym, 2022)
    if t is None or not len(t):
        return dict(n=0, net=0.0, avg=np.nan, wr=np.nan, tr_n=0, tr_net=0.0,
                    tr_avg=np.nan, va_n=0, va_net=0.0, va_avg=np.nan,
                    maxdd=np.nan, yrs_pos="0/0")
    r = t["r"]
    tr = t["year"] <= te
    va = ~tr
    eq = r.cumsum()
    ys = t.groupby("year")["r"].sum()
    return dict(n=len(t), net=float(r.sum()), avg=float(r.mean()),
                wr=float((r > 0).mean()),
                tr_n=int(tr.sum()), tr_net=float(r[tr].sum()),
                tr_avg=float(r[tr].mean()) if tr.any() else np.nan,
                va_n=int(va.sum()), va_net=float(r[va].sum()),
                va_avg=float(r[va].mean()) if va.any() else np.nan,
                maxdd=float((eq - eq.cummax()).min()),
                yrs_pos=f"{int((ys > 0).sum())}/{len(ys)}")


# ── family implementations (all: signal arrays on the exec frame) ────────────
def orb(sym, cm, open_min, rng_min, pad, rr, cutoff_min):
    d = fr(sym, 15)
    cost = COSTS[sym] * cm
    mins = d["ny_min"] if "ny_min" in d else None
    wall = d["timestamp_ny"].dt.hour * 60 + d["timestamp_ny"].dt.minute
    day = d["ny_date"].to_numpy()
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
    in_rng = (wall >= open_min) & (wall < open_min + rng_min)
    g = pd.DataFrame({"day": day, "h": np.where(in_rng, h, np.nan),
                      "l": np.where(in_rng, l, np.nan)})
    orh = g.groupby("day")["h"].transform("max").to_numpy()
    orl = g.groupby("day")["l"].transform("min").to_numpy()
    live = (wall >= open_min + rng_min) & (wall < cutoff_min)
    lo_sig = live & np.isfinite(orh) & (c > orh + pad * atr)
    hi_sig = live & np.isfinite(orl) & (c < orl - pad * atr)
    # first breakout per day per side only: consecutive-first via groupby cumsum
    first_l = pd.Series(lo_sig).groupby(day).cumsum().to_numpy() == 1
    first_s = pd.Series(hi_sig).groupby(day).cumsum().to_numpy() == 1
    return run_trades(d, lo_sig & first_l, hi_sig & first_s, cost,
                      stop_abs=np.where(lo_sig, orl, orh), rr=rr,
                      max_hold=int((1050 - open_min - rng_min) / 15), max_tpd=2)


def pull(sym, cm, rr, stop_atr, sides):
    d = fr(sym, 60)
    cost = COSTS[sym] * cm
    c = d["close"]
    e20 = c.ewm(span=20, adjust=False).mean().to_numpy()
    e200 = c.ewm(span=200, adjust=False).mean().to_numpy()
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float); cl = c.to_numpy(float)
    up = (cl > e200) & (l <= e20) & (cl > o) & (cl > e20)
    dn = (cl < e200) & (h >= e20) & (cl < o) & (cl < e20)
    return run_trades(d, up if "L" in sides else None,
                      dn if "S" in sides else None, cost,
                      stop_atr=stop_atr, rr=rr, max_hold=96, max_tpd=2)


def tsmom(sym, cm, N, trail, sides):
    d = fr(sym, 1440)
    cost = COSTS[sym] * cm
    hiN = d["high"].shift(1).rolling(N).max().to_numpy(float)
    loN = d["low"].shift(1).rolling(N).min().to_numpy(float)
    cl = d["close"].to_numpy(float)
    lo_sig = cl > hiN
    hi_sig = cl < loN
    return run_trades(d, lo_sig if "L" in sides else None,
                      hi_sig if "S" in sides else None, cost,
                      stop_atr=2.0, trail_atr=trail, max_hold=100, max_tpd=1)


def afade(sym, cm, k, stop_atr):
    d = fr(sym, 15)
    cost = COSTS[sym] * cm
    wall = (d["timestamp_ny"].dt.hour * 60 + d["timestamp_ny"].dt.minute).to_numpy()
    # session date (17:00 anchor) so the 17:00->02:00 Asia range stays one group
    day = (d["timestamp_ny"].dt.tz_localize(None)
           + pd.Timedelta(hours=7)).dt.date.astype(str).to_numpy()
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float); atr = d["atr50"].to_numpy(float)
    asia = (wall >= 17 * 60) | (wall < 2 * 60)
    g = pd.DataFrame({"day": day, "h": np.where(asia, h, np.nan),
                      "l": np.where(asia, l, np.nan)})
    mid = ((g.groupby("day")["h"].transform("max")
            + g.groupby("day")["l"].transform("min")) / 2).to_numpy()
    win = (wall >= 2 * 60) & (wall < 4 * 60)
    dev = c - mid
    hi_sig = win & np.isfinite(mid) & (dev >= k * atr)      # stretched up -> short
    lo_sig = win & np.isfinite(mid) & (dev <= -k * atr)     # stretched down -> long
    first_s = pd.Series(hi_sig).groupby(day).cumsum().to_numpy() == 1
    first_l = pd.Series(lo_sig).groupby(day).cumsum().to_numpy() == 1
    return run_trades(d, lo_sig & first_l, hi_sig & first_s, cost,
                      stop_atr=stop_atr, target_abs=mid, max_hold=40, max_tpd=2)


def handoff(sym, cm, k, rr, stop_atr):
    d = fr(sym, 15)
    cost = COSTS[sym] * cm
    wall = (d["timestamp_ny"].dt.hour * 60 + d["timestamp_ny"].dt.minute).to_numpy()
    day = d["ny_date"].to_numpy()
    o = d["open"].to_numpy(float); c = d["close"].to_numpy(float)
    atr = d["atr50"].to_numpy(float)
    ldn = (wall >= 2 * 60) & (wall < 8 * 60)
    g = pd.DataFrame({"day": day,
                      "first_o": np.where(ldn, o, np.nan),
                      "last_c": np.where(ldn, c, np.nan)})
    fo = g.groupby("day")["first_o"].transform(lambda s: s.dropna().iloc[0]
                                               if s.notna().any() else np.nan).to_numpy()
    move = c - fo
    at_open = (wall >= 8 * 60 - 15) & (wall < 8 * 60)       # signal on 07:45 bar
    lo_sig = at_open & np.isfinite(fo) & (move >= k * atr)
    hi_sig = at_open & np.isfinite(fo) & (move <= -k * atr)
    return run_trades(d, lo_sig, hi_sig, cost, stop_atr=stop_atr, rr=rr,
                      max_hold=36, max_tpd=1)


def ibx(sym, cm, rr, sides):
    d = fr(sym, 240)
    cost = COSTS[sym] * cm
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    inside = np.zeros(len(d), bool)
    inside[1:] = (h[1:] < h[:-1]) & (l[1:] > l[:-1])
    prev_inside = np.roll(inside, 1); prev_inside[0] = False
    ib_h = np.roll(h, 1); ib_l = np.roll(l, 1)
    lo_sig = prev_inside & (c > ib_h)
    hi_sig = prev_inside & (c < ib_l)
    return run_trades(d, lo_sig if "L" in sides else None,
                      hi_sig if "S" in sides else None, cost,
                      stop_abs=np.where(lo_sig, ib_l, ib_h), rr=rr,
                      max_hold=30, max_tpd=1)


GRIDS = {
    "ORB": [dict(open_min=om, rng_min=rm, pad=0.1, rr=rr, cutoff_min=720)
            for om, rm, rr in itertools.product((120, 480), (30, 60), (2.0, 3.0))],
    "PULL": [dict(rr=rr, stop_atr=sa, sides=sd)
             for rr, sa, sd in itertools.product((2.0, 3.0), (1.5, 2.5),
                                                 ("L", "LS"))],
    "TSMOM": [dict(N=N, trail=tr, sides=sd)
              for N, tr, sd in itertools.product((20, 55), (3.0, 4.0),
                                                 ("L", "LS"))],
    "AFADE": [dict(k=k, stop_atr=sa)
              for k, sa in itertools.product((1.5, 2.0, 2.5), (1.2, 2.0))],
    "HANDOFF": [dict(k=k, rr=rr, stop_atr=1.5)
                for k, rr in itertools.product((1.5, 2.0, 2.5), (1.5, 2.5))],
    "IBX": [dict(rr=rr, sides=sd)
            for rr, sd in itertools.product((2.0, 3.0), ("L", "LS"))],
}
FNS = {"ORB": orb, "PULL": pull, "TSMOM": tsmom, "AFADE": afade,
       "HANDOFF": handoff, "IBX": ibx}


def main():
    rows = []
    for sym in SYMS:
        print(f"== {sym} ==", flush=True)
        for fam, grid in GRIDS.items():
            for gi, kw in enumerate(grid):
                t = FNS[fam](sym, 1.0, **kw)
                s = split_stats(t, sym)
                row = dict(sym=sym, family=fam, cell=gi, params=str(kw), **s)
                # 2x cost only when train looks alive (saves time, recorded honestly)
                if s["n"] >= 40 and np.isfinite(s["tr_avg"]) and s["tr_avg"] > 0:
                    s2 = split_stats(FNS[fam](sym, 2.0, **kw), sym)
                    s3 = split_stats(FNS[fam](sym, 3.0, **kw), sym)
                    row["tr_avg_2x"] = s2["tr_avg"]; row["va_net_2x"] = s2["va_net"]
                    row["tr_avg_3x"] = s3["tr_avg"]; row["va_net_3x"] = s3["va_net"]
                rows.append(row)
            sub = [r for r in rows if r["sym"] == sym and r["family"] == fam]
            alive = sum(1 for r in sub if np.isfinite(r.get("tr_avg", np.nan))
                        and r["tr_avg"] > 0)
            best = max(sub, key=lambda r: (r.get("tr_avg") or -9) if np.isfinite(r.get("tr_avg") or np.nan) else -9)
            print(f"  {fam:8} cells={len(sub)} train+={alive} "
                  f"best: n={best['n']} tr_avg={best.get('tr_avg', float('nan')):+.3f} "
                  f"va_net={best.get('va_net', 0):+.1f} [{best['params']}]",
                  flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "discover_new_results.csv"), index=False)
    print(f"\nwrote discover_new_results.csv ({len(res)} cells)")

    # gate: train-selected, validation confirm, 2x cost, plateau
    out = []
    for (sym, fam), g in res.groupby(["sym", "family"]):
        g = g[g["n"] >= 40]
        if not len(g):
            continue
        plateau = float((g["tr_avg"] > 0).mean())
        best = g.sort_values("tr_avg", ascending=False).iloc[0]
        ok = (np.isfinite(best["tr_avg"]) and best["tr_avg"] >= 0.05
              and best["va_net"] > 0
              and np.isfinite(best.get("tr_avg_2x", np.nan))
              and best["tr_avg_2x"] > 0 and plateau >= 0.5)
        out.append(dict(sym=sym, family=fam, plateau=plateau,
                        verdict="PASS" if ok else "reject", **{
                            k: best[k] for k in ("params", "n", "wr", "avg",
                                                 "tr_avg", "tr_net", "va_avg",
                                                 "va_net", "maxdd", "yrs_pos")},
                        tr_avg_2x=best.get("tr_avg_2x", np.nan),
                        va_net_2x=best.get("va_net_2x", np.nan)))
    ver = pd.DataFrame(out).sort_values(["sym", "verdict", "tr_avg"],
                                        ascending=[True, True, False])
    ver.to_csv(os.path.join(HERE, "discover_new_verdicts.csv"), index=False)
    print(ver.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
