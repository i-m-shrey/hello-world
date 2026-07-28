"""discover_new2.py — round 2 concept families (see discover_new.py protocol).
  MR3   D1 mean-reversion: 3 consecutive lower closes with close still above
        SMA50 -> long next open (FX also mirrored short), 2*ATR stop, rr 1.5,
        max 10 days.
  RNGX  H4 range-expansion continuation: bar range >= 2*ATR closing in the
        directional quarter of its range -> continue next open, 2*ATR stop,
        fixed RR. (Both sides; distinct from the owner's H1 short-only CRASH.)
  GAPF  Weekend gap fade: Sunday open gaps >= g*ATR(D1) from Friday close ->
        fade toward Friday close (target), stop 1.5x the gap beyond the open.
"""
import itertools, os, sys
import numpy as np, pandas as pd
import liquidity_grab_lab as lg
from strategy_scout import frame, run_trades
from discover_new import COSTS, SYMS, fr, m1, split_stats

HERE = os.path.dirname(os.path.abspath(__file__))

def mr3(sym, cm, sides, rr):
    d = fr(sym, 1440); cost = COSTS[sym]*cm
    c = d["close"]; sma = c.rolling(50).mean()
    down3 = (c < c.shift(1)) & (c.shift(1) < c.shift(2)) & (c.shift(2) < c.shift(3))
    up3   = (c > c.shift(1)) & (c.shift(1) > c.shift(2)) & (c.shift(2) > c.shift(3))
    lo = (down3 & (c > sma)).to_numpy()
    hi = (up3 & (c < sma)).to_numpy()
    return run_trades(d, lo if "L" in sides else None, hi if "S" in sides else None,
                      cost, stop_atr=2.0, rr=rr, max_hold=10, max_tpd=1)

def rngx(sym, cm, sides, rr):
    d = fr(sym, 240); cost = COSTS[sym]*cm
    o=d["open"].to_numpy(float); h=d["high"].to_numpy(float)
    l=d["low"].to_numpy(float); c=d["close"].to_numpy(float)
    atr=d["atr50"].to_numpy(float); rng=h-l
    loc=np.where(rng>0,(c-l)/np.where(rng>0,rng,1),0.5)
    lo=(rng>=2.0*atr)&(c>o)&(loc>=0.75)
    hi=(rng>=2.0*atr)&(c<o)&(loc<=0.25)
    return run_trades(d, lo if "L" in sides else None, hi if "S" in sides else None,
                      cost, stop_atr=2.0, rr=rr, max_hold=30, max_tpd=1)

def gapf(sym, cm, g_atr):
    d15 = fr(sym, 15); cost = COSTS[sym]*cm
    dd = fr(sym, 1440)
    atr_d = dd.set_index(dd["timestamp_ny"].dt.date)["atr50"]
    ts = d15["timestamp_ny"]
    dow = ts.dt.dayofweek.to_numpy(); hh = ts.dt.hour.to_numpy()
    o=d15["open"].to_numpy(float); c=d15["close"].to_numpy(float)
    n=len(d15)
    sig_l=np.zeros(n,bool); sig_s=np.zeros(n,bool); tgt=np.full(n,np.nan); stp=np.full(n,np.nan)
    # Sunday first bar >= 17:00 NY
    is_sun_open=np.zeros(n,bool)
    prev_day=None
    for i in range(1,n):
        dte=ts.iloc[i].date()
        if dow[i]==6 and (ts.iloc[i-1].date()!=dte):
            is_sun_open[i]=True
    idx=np.flatnonzero(is_sun_open)
    for i in idx:
        fri_close=c[i-1]
        a=atr_d.asof(ts.iloc[i].date()) if hasattr(atr_d,'asof') else np.nan
        try: a=float(atr_d.loc[:ts.iloc[i].date()].iloc[-1])
        except Exception: continue
        gap=o[i]-fri_close
        if not np.isfinite(a) or a<=0: continue
        if abs(gap)>=g_atr*a:
            j=i  # signal on first Sunday bar; entry next bar open
            if gap>0: sig_s[j]=True; tgt[j]=fri_close; stp[j]=o[i]+1.5*abs(gap)
            else:     sig_l[j]=True; tgt[j]=fri_close; stp[j]=o[i]-1.5*abs(gap)
    return run_trades(d15, sig_l, sig_s, cost, stop_abs=stp, target_abs=tgt,
                      max_hold=96*5, max_tpd=1)

GRIDS2={
 "MR3":[dict(sides=sd, rr=rr) for sd,rr in itertools.product(("L","LS"),(1.5,2.5))],
 "RNGX":[dict(sides=sd, rr=rr) for sd,rr in itertools.product(("L","LS"),(2.0,3.0))],
 "GAPF":[dict(g_atr=g) for g in (0.3,0.5,0.8)],
}
FNS2={"MR3":mr3,"RNGX":rngx,"GAPF":gapf}

def main():
    rows=[]
    for sym in SYMS:
        print(f"== {sym} ==",flush=True)
        for fam,grid in GRIDS2.items():
            for gi,kw in enumerate(grid):
                t=FNS2[fam](sym,1.0,**kw)
                s=split_stats(t,sym)
                row=dict(sym=sym,family=fam,cell=gi,params=str(kw),**s)
                if s["n"]>=30 and np.isfinite(s["tr_avg"]) and s["tr_avg"]>0:
                    s2=split_stats(FNS2[fam](sym,2.0,**kw),sym)
                    row["tr_avg_2x"]=s2["tr_avg"]; row["va_net_2x"]=s2["va_net"]
                rows.append(row)
            sub=[r for r in rows if r["sym"]==sym and r["family"]==fam]
            best=max(sub,key=lambda r:(r.get("tr_avg") if np.isfinite(r.get("tr_avg") or np.nan) else -9) or -9)
            print(f"  {fam:5} best: n={best['n']} tr={best.get('tr_avg',float('nan')):+.3f} va={best.get('va_net',0):+.1f} {best['params']}",flush=True)
    res=pd.DataFrame(rows); res.to_csv(os.path.join(HERE,"discover_new2_results.csv"),index=False)
    print("saved", len(res))
    for (sym,fam),g in res.groupby(["sym","family"]):
        g2=g[g["n"]>=30]
        if not len(g2): continue
        plateau=float((g2["tr_avg"]>0).mean())
        b=g2.sort_values("tr_avg",ascending=False).iloc[0]
        ok=(np.isfinite(b["tr_avg"]) and b["tr_avg"]>=0.05 and b["va_net"]>0
            and np.isfinite(b.get("tr_avg_2x",np.nan)) and b["tr_avg_2x"]>0 and plateau>=0.5)
        if ok:
            print(f"PASS {sym} {fam} {b['params']} n={b['n']} tr_avg={b['tr_avg']:+.3f} va_net={b['va_net']:+.1f} 2x={b['tr_avg_2x']:+.3f} plateau={plateau:.2f}")
    return 0

if __name__=="__main__":
    sys.exit(main())
