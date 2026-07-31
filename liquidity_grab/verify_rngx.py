#!/usr/bin/env python3
"""verify_rngx.py — deployment battery for the two RNGX deploy candidates from
DISCOVERY_NEW.md (XAUUSD RNGX L rr3, USDCHF RNGX LS rr3).

Gates:
  1. REPRODUCE the published numbers exactly (n / avg / train / valid / maxdd).
  2. 3x COST STRESS (house deployment gate; the discovery run published 2x).
  3. Per-trade books -> OVERLAP vs the deployed gold tier (scout_*_trades.csv)
     + daily-R correlation vs the deployed books.
Writes: rngx_xau_tradebook.csv, rngx_chf_tradebook.csv
"""
import glob
import os

import numpy as np
import pandas as pd

import discover_new2 as d2
from discover_new import split_stats

HERE = os.path.dirname(os.path.abspath(__file__))

PUBLISHED = {
    ("XAUUSD", "L", 3.0): dict(n=458, avg=0.250, tr_net=88.2, va_net=26.2, maxdd=-20.2),
    ("USDCHF", "LS", 3.0): dict(n=223, avg=0.222, tr_net=26.5, va_net=23.1, maxdd=-14.5),
}


def maxdd(r):
    eq = r.cumsum()
    return float((eq - eq.cummax()).min())


def report(sym, sides, rr):
    print(f"\n===== RNGX {sym} sides={sides} rr={rr} =====")
    t1 = d2.rngx(sym, 1.0, sides, rr)
    s = split_stats(t1, sym)
    pub = PUBLISHED[(sym, sides, rr)]
    print(f"  reproduce: n={s['n']} (pub {pub['n']}) | avg {s['avg']:+.3f} (pub {pub['avg']:+.3f}) | "
          f"train {s['tr_net']:+.1f} (pub {pub['tr_net']:+.1f}) | valid {s['va_net']:+.1f} (pub {pub['va_net']:+.1f}) | "
          f"maxdd {maxdd(t1['r']):.1f} (pub {pub['maxdd']:.1f})")
    ok = (s['n'] == pub['n'] and abs(s['avg'] - pub['avg']) < 0.005 and
          abs(s['tr_net'] - pub['tr_net']) < 1.0 and abs(s['va_net'] - pub['va_net']) < 1.0)
    print(f"  -> REPRODUCTION {'PASS' if ok else 'FAIL'}")
    for cm in (2.0, 3.0):
        tcm = d2.rngx(sym, cm, sides, rr)
        scm = split_stats(tcm, sym)
        print(f"  {cm:.0f}x cost: n={scm['n']} avg {scm['avg']:+.3f} | train avg {scm['tr_avg']:+.3f} "
              f"net {scm['tr_net']:+.1f} | valid net {scm['va_net']:+.1f} | yrs+ {scm['yrs_pos']}")
    s3 = split_stats(d2.rngx(sym, 3.0, sides, rr), sym)
    print(f"  -> 3x STRESS {'PASS' if (s3['tr_avg'] > 0 and s3['va_net'] > 0) else 'FAIL'} "
          f"(train avg {s3['tr_avg']:+.3f}, valid net {s3['va_net']:+.1f})")
    return t1


def overlap_vs_deployed(t_new, label):
    """Share of the new strategy's in-position time overlapping each deployed
    gold book + daily-R correlation (scout books = deployed gold tier)."""
    print(f"\n  overlap of {label} vs deployed gold tier:")
    new_iv = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in zip(t_new['entry_ts'], t_new['exit_ts'])]
    tot = sum((b - a).total_seconds() for a, b in new_iv) or 1.0
    nd = pd.DataFrame({'d': pd.to_datetime(t_new['entry_ts']).dt.date, 'r': t_new['r']}).groupby('d')['r'].sum()
    for f in sorted(glob.glob(os.path.join(HERE, 'scout_*_trades.csv'))):
        name = os.path.basename(f).replace('scout_', '').replace('_trades.csv', '')
        if name.startswith('gbp'):
            continue
        b = pd.read_csv(f, parse_dates=['entry_ts', 'exit_ts'])
        biv = sorted([(r.entry_ts, r.exit_ts) for r in b.itertuples()])
        ov = 0.0
        starts = [x[0] for x in biv]
        import bisect
        for a, e in new_iv:
            k = bisect.bisect_left(starts, e)
            for s2, e2 in biv[max(0, k - 40):k]:
                lo = max(a, s2); hi = min(e, e2)
                if hi > lo:
                    ov += (hi - lo).total_seconds()
        bd = pd.DataFrame({'d': b['entry_ts'].dt.date, 'r': b['r']}).groupby('d')['r'].sum()
        join = pd.concat([nd, bd], axis=1, keys=['new', 'old']).dropna()
        corr = join['new'].corr(join['old']) if len(join) > 10 else np.nan
        print(f"    {name:12s}: time-overlap {ov / tot:5.1%} | shared days {len(join):4d} | daily-R corr {corr if corr == corr else float('nan'):+.2f}")


if __name__ == '__main__':
    t_x = report('XAUUSD', 'L', 3.0)
    t_c = report('USDCHF', 'LS', 3.0)
    t_x.to_csv(os.path.join(HERE, 'rngx_xau_tradebook.csv'), index=False)
    t_c.to_csv(os.path.join(HERE, 'rngx_chf_tradebook.csv'), index=False)
    overlap_vs_deployed(t_x, 'XAUUSD RNGX')
    print("\ntradebooks written: rngx_xau_tradebook.csv, rngx_chf_tradebook.csv")
