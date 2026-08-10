#!/usr/bin/env python3
"""Dynamic-vs-static concurrency cap backtest (rev11 candidate study).

Position-level Monte Carlo of the 26-strategy book on the $6K challenge:
signals arrive per strategy (Poisson, matrix rates), positions live for
tier-realistic holding times, trail-tier winners de-risk over the first
half of their life, and a synchronized daily adverse shock marks floating
risk to market for the daily-kill test (-3.5% incl. floating).

STATIC : admit while open_count < 4 (gold-trend cap 1, per-USD 2)
DYNAMIC: admit while open_count < 6 AND sum(remaining_risk)+1 <= 4.0R

Outputs per config: P(pass Phase1 within 60 tdays), monthly R, P(daily kill),
P(firm -5% day), extra admissions, over 3000 paths x 3 scenarios.
"""
import numpy as np
from scipy.special import ndtr

rng = np.random.default_rng(11)

# name, tr/mo, WR, avgR, tier, hold_hours_mean, style
BOOK = [
    ("S5",13.3,.450,.036,"goldi",3,"be"), ("S6R",11.8,.409,.046,"goldi",4,"fix"),
    ("S3LO",5.7,.470,.062,"goldi",3,"be"), ("HAVW_X",5.1,.380,.100,"goldi",8,"trail"),
    ("DONCH_TR",3.0,.350,.277,"goldt",60,"trail"), ("VCX_B",1.6,.330,.280,"goldt",48,"fix"),
    ("MACROSS",2.0,.330,.124,"goldt",40,"fix"), ("BOS",7.6,.194,.161,"goldt",30,"fix"),
    ("ZBPIV_X",0.9,.290,.160,"goldt",60,"fix"), ("STRAD",2.5,.330,.146,"goldt",24,"fix"),
    ("H1A",1.0,.370,.109,"goldt",24,"fix"),
    ("EUR_E",2.5,.312,.196,"eur",12,"fix"), ("GBP_E",2.3,.289,.134,"gbp",12,"fix"),
    ("GBP_P1",2.0,.490,.125,"gbp",10,"fix"), ("CHF_P1",1.0,.375,.125,"chf",10,"fix"),
    ("CAD_A",1.8,.405,.059,"cad",8,"fix"), ("CHF_A",0.6,.468,.215,"chf",8,"fix"),
    ("RSI30",0.8,.520,.245,"chf",6,"fix"), ("AVWAP",7.6,.540,.084,"gbp",16,"fix"),
    ("BOLL30R",8.0,.530,.060,"eur",5,"fix"), ("HAVW_E",1.5,.360,.277,"eur",80,"trail"),
    ("HAVW_G",1.6,.360,.221,"gbp",80,"trail"),
    ("SPX_D",3.7,.261,.044,"idx",50,"fix"), ("GER_D",3.7,.305,.220,"idx",50,"fix"),
    ("GER_B",7.9,.260,.038,"idx",30,"fix"), ("SPX_Z",0.9,.470,.200,"idx",70,"fix"),
]
HOURS_DAY = 22
P_HOUR = np.array([b[1]/21/HOURS_DAY for b in BOOK])
WR = np.array([b[2] for b in BOOK]); AVG = np.array([b[3] for b in BOOK])
WIN = (AVG + (1-WR))/WR
TIER = [b[4] for b in BOOK]; HOLD = np.array([float(b[5]) for b in BOOK])
TRAIL = np.array([b[6]=="trail" or b[6]=="be" for b in BOOK])
GOLDT = np.array([t=="goldt" for t in TIER])
FID = np.array([{"goldi":0,"goldt":0,"idx":1,"eur":2,"gbp":3,"chf":4,"cad":5}[t] for t in TIER])
MIX = np.array([{"goldi":.45,"goldt":.65,"idx":.40,"eur":.2,"gbp":.2,"chf":.2,"cad":.2}[t] for t in TIER])

DAILY_KILL = -0.035/0.0075      # -4.667 R
FIRM_DAY   = -0.050/0.0075      # -6.667 R
P1_TGT     =  0.080/0.0075      # +10.667 R
MAX_KILL   = -0.080/0.0075

def run_path(dynamic, haircut, days=60, seed=None):
    r = np.random.default_rng(seed)
    open_pos = []   # dicts: strat i, r_final, hours_left, hours_total, win
    cum = 0.0; killed_days = 0; firm_breach = False; extra_admits = 0; passed = None
    for d in range(days):
        day_realized = 0.0
        zf = r.standard_normal(6)
        # intraday worst synchronized adverse shock factor (fraction of open risk marked)
        shock = min(abs(r.normal(0, 0.40)), 1.0)
        day_blocked = False
        worst_float = 0.0
        for h in range(HOURS_DAY):
            # age positions, realize exits
            still = []
            for p in open_pos:
                p["hours_left"] -= 1
                if p["hours_left"] <= 0:
                    day_realized += p["r_final"]
                else:
                    still.append(p)
            open_pos = still
            if not day_blocked:
                fires = np.flatnonzero(r.random(len(BOOK)) < P_HOUR)
                for i in fires:
                    # existing per-strategy/per-symbol caps
                    n_goldt = sum(1 for p in open_pos if GOLDT[p["i"]])
                    if GOLDT[i] and n_goldt >= 1: continue
                    if any(p["i"]==i for p in open_pos): continue
                    n_open = len(open_pos)
                    if not dynamic:
                        if n_open >= 4: continue
                    else:
                        if n_open >= 6: continue
                        rem = sum(p["risk_now"] for p in open_pos)
                        if rem + 1.0 > 4.0: continue
                        if n_open >= 4: extra_admits += 1
                    z = MIX[i]*zf[FID[i]] + np.sqrt(1-MIX[i]**2)*r.standard_normal()
                    win = ndtr(z) < WR[i]
                    rf = (WIN[i]*(0.4+1.2*r.random()) if win else -1.0) - haircut
                    hl = max(2, int(r.exponential(HOLD[i])))
                    open_pos.append(dict(i=i, r_final=rf, hours_left=hl,
                                         hours_total=hl, risk_now=1.0))
            # update remaining risk (trail de-risk over first half of life, winners)
            for p in open_pos:
                if TRAIL[p["i"]] and p["r_final"] > 0:
                    prog = 1 - p["hours_left"]/p["hours_total"]
                    p["risk_now"] = max(0.0, 1 - 2*prog)
                elif p["r_final"] > 0:
                    p["risk_now"] = 1.0 if p["hours_left"] > p["hours_total"]*0.3 else 0.5
            worst_float = max(worst_float, shock*sum(p["risk_now"] for p in open_pos))
        # daily kill check: realized so far + marked floating
        if day_realized - worst_float <= DAILY_KILL:
            killed_days += 1
            day_realized = max(day_realized - worst_float, DAILY_KILL)  # flatten near kill
            if day_realized <= FIRM_DAY: firm_breach = True
            open_pos = []
        cum += day_realized
        if cum <= MAX_KILL: return dict(passed=False, cum=cum, kills=killed_days, firm=firm_breach, extra=extra_admits, days=d+1)
        if passed is None and cum >= P1_TGT: passed = d+1
    return dict(passed=bool(passed), cum=cum, kills=killed_days, firm=firm_breach, extra=extra_admits, days=passed or days)

def study(label, haircut, n=1500):
    for dyn in (False, True):
        res = [run_path(dyn, haircut, seed=1000+k) for k in range(n)]
        P = np.mean([x["passed"] for x in res])
        R = np.mean([x["cum"] for x in res])/ (60/21)
        K = np.mean([x["kills"] for x in res])
        F = np.mean([x["firm"] for x in res])
        E = np.mean([x["extra"] for x in res])
        print(f"  {label} {'DYNAMIC' if dyn else 'STATIC '}: P(pass P1<=60d)={P:5.1%} | "
              f"R/mo={R:+5.2f} | daily-kills/path={K:.2f} | P(firm -5% day)={F:5.2%} | extra admits/path={E:.1f}")

for lab, hc in (("base", 0.05), ("pessim", 0.08)):
    print(f"scenario {lab}:")
    study(lab, hc)
