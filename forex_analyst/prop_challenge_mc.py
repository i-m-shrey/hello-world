#!/usr/bin/env python3
"""Monte Carlo: FundedNext Stellar 2-Step $6K challenge + funded-stage income,
driven by the rev10 enabled book's per-strategy stats (STRATEGY_MATRIX.md,
gs_battery/havw data, July 2026) under PROP_MODE rules:
  0.75%/R sizing ($45/R on $6K), daily kill -3.5% (=-4.67R incl floating),
  max kill -8% (=-10.67R permanent halt), stacking caps (1 gold trend).
Phase targets: +8% (=+10.67R), +5% (=+6.67R). ~21 trading days/month.
"""
import sys
import numpy as np
from scipy.special import ndtr, ndtri

rng = np.random.default_rng(7)

# (name, trades_per_month, win_rate, avg_R, tier)
# WR inferred from rr where matrix lacks it: WR=(avgR+1)/(rr+1). Trail exits
# modeled as lognormal-ish winners matched to avg win = (avgR+(1-WR))/WR.
BOOK = [
    # gold intraday (TZ-corrected matrix rows)
    ("S5",        13.3, 0.450, 0.036, "goldi"),
    ("S6R",       11.8, 0.409, 0.046, "goldi"),
    ("S3LO",       5.7, 0.470, 0.062, "goldi"),
    ("HAVW_XAU",   5.1, 0.380, 0.100, "goldi"),   # 370 tr / ~72mo, conservative avg
    # gold trend tier (stack-capped to 1 concurrent -> modeled 1/day max)
    ("DONCH_TR",   3.0, 0.350, 0.277, "goldt"),
    ("VCX_B",      1.6, 0.330, 0.280, "goldt"),
    ("MACROSS",    2.0, 0.330, 0.124, "goldt"),
    ("BOS",        7.6, 0.194, 0.161, "goldt"),
    ("ZBPIV_XAU",  0.9, 0.290, 0.160, "goldt"),
    ("STRAD",      2.5, 0.330, 0.146, "goldt"),
    ("H1A",        1.0, 0.370, 0.109, "goldt"),
    # FX
    ("EURUSD_E",   2.5, 0.312, 0.196, "eur"),
    ("GBPUSD_E",   2.3, 0.289, 0.134, "gbp"),
    ("GBPUSD_P1",  2.0, 0.490, 0.125, "gbp"),
    ("USDCHF_P1",  1.0, 0.375, 0.125, "chf"),
    ("USDCAD_A",   1.8, 0.405, 0.059, "cad"),
    ("USDCHF_A",   0.6, 0.468, 0.215, "chf"),
    ("RSI30_CHF",  0.8, 0.520, 0.245, "chf"),
    ("AVWAP_GBP",  7.6, 0.540, 0.084, "gbp"),
    ("BOLL30R",    8.0, 0.530, 0.060, "eur"),
    ("HAVW_EUR",   1.5, 0.360, 0.277, "eur"),
    ("HAVW_GBP",   1.6, 0.360, 0.221, "gbp"),
    # index
    ("SPX_DONCH",  3.7, 0.261, 0.044, "idx"),
    ("GER_DONCH",  3.7, 0.305, 0.220, "idx"),
    ("GER_BOS",    7.9, 0.260, 0.038, "idx"),
    ("SPX_ZBPIV",  0.9, 0.470, 0.200, "idx"),
    # US30_DONCH promoted Aug 2026 with the rev11 index $ sizer (§2f in the bot):
    # matrix n=181, 3.4 tr/mo, rr3, avg +0.151R -> WR=(0.151+1)/(3+1)=0.288.
    # Pre-rev11 it rode dust lots and was correctly excluded from this book.
    ("US30_DONCH", 3.4, 0.288, 0.151, "idx"),
]

# --baseline reproduces the July 2026 book (no US30) for A/B comparison.
if "--baseline" in sys.argv:
    BOOK = [b for b in BOOK if b[0] != "US30_DONCH"]
GOLD_STACK = 2 if "--goldstack2" in sys.argv else 1
print(f"BOOK: {len(BOOK)} strategies (gold stack cap {GOLD_STACK}) ({'baseline, no US30' if '--baseline' in sys.argv else 'rev11, with US30_DONCH'})")

DAYS_PER_MONTH = 21
R_USD = 45.0                      # 0.75% of $6000
DAILY_KILL_R = -0.035 / 0.0075    # -4.667R
MAX_KILL_R   = -0.080 / 0.0075    # -10.667R
P1_TARGET_R  =  0.080 / 0.0075    # +10.667R
P2_TARGET_R  =  0.050 / 0.0075    # +6.667R

# correlation mixing weights per tier (rank-corr via shared daily factor)
MIX = {"goldi": 0.45, "goldt": 0.65, "idx": 0.40,
       "eur": 0.20, "gbp": 0.20, "chf": 0.20, "cad": 0.20}
# gold trend and gold intraday share the gold factor; indices share; fx per ccy

names   = [b[0] for b in BOOK]
p_day   = np.array([b[1] / DAYS_PER_MONTH for b in BOOK])
wr      = np.array([b[2] for b in BOOK])
avg_r   = np.array([b[3] for b in BOOK])
tier    = [b[4] for b in BOOK]
win_r   = (avg_r + (1.0 - wr)) / wr          # avg winner size in R (loss = -1)
mixw    = np.array([MIX[t] for t in tier])
factor_id = np.array([{"goldi":0,"goldt":0,"idx":1,"eur":2,"gbp":3,"chf":4,"cad":5}[t] for t in tier])
is_goldt  = np.array([t == "goldt" for t in tier])

def sim_days(n_days, haircut, kill=True, seed_rng=rng):
    """Simulate daily realized R with intra-day kill. Returns array of daily R."""
    out = np.empty(n_days)
    for d in range(n_days):
        fires = seed_rng.random(len(BOOK)) < p_day
        # gold-trend stacking cap (PROP_MAX_STACKED_GOLD); --goldstack2 tests cap 2
        gt = np.where(fires & is_goldt)[0]
        if len(gt) > GOLD_STACK:
            keep = seed_rng.choice(gt, size=GOLD_STACK, replace=False)
            fires[gt] = False
            fires[keep] = True
        idx = np.where(fires)[0]
        if len(idx) == 0:
            out[d] = 0.0
            continue
        zf = seed_rng.standard_normal(6)             # daily tier factors (Gaussian copula)
        w = mixw[idx]
        z = w * zf[factor_id[idx]] + np.sqrt(1 - w**2) * seed_rng.standard_normal(len(idx))
        u = ndtr(z)
        # outcome: u < wr -> win of win_r (trail: draw exp-ish), else -1
        r = np.where(u < wr[idx],
                     win_r[idx] * (0.4 + 1.2 * seed_rng.random(len(idx))),  # winner dispersion, mean~=win_r
                     -1.0)
        r = r - haircut                              # live-vs-backtest haircut per trade
        seed_rng.shuffle(r)
        if kill:
            c = np.cumsum(r)
            k = np.where(c <= DAILY_KILL_R)[0]
            out[d] = DAILY_KILL_R if len(k) else c[-1]
        else:
            out[d] = r.sum()
    return out

def calibrate(target_monthly_R):
    """Find per-trade haircut so kill-free monthly mean ~= target."""
    raw = sim_days(40000, 0.0, kill=False).mean() * DAYS_PER_MONTH
    tpd = p_day.sum() * 0.93     # approx trades/day after gold cap
    return (raw - target_monthly_R) / (tpd * DAYS_PER_MONTH), raw

def run_phase(target, haircut, max_days=260):
    cum, day = 0.0, 0
    while day < max_days:
        r = sim_days(1, haircut)[0]
        cum += r; day += 1
        if cum <= MAX_KILL_R:  return False, day
        if cum >= target:      return True, max(day, 5)
    return False, day          # never halted but never hit target in a year

def run_funded(haircut, weeks=52):
    """Funded: weekly R, death at -8% cum from initial. Returns weekly net $ list."""
    cum = 0.0; out = []
    for w in range(weeks):
        wk = sim_days(5, haircut).sum()
        cum += wk
        if cum <= MAX_KILL_R:
            out.append(None); break
        out.append(wk * R_USD * 0.80 * 0.965)   # 80% split, 3.5% payout fee
    return out

N = 4000
for label, tgt in [("PESSIMISTIC 2.5R/mo", 2.5), ("BASE 4.5R/mo", 4.5), ("OPTIMISTIC 6.5R/mo", 6.5)]:
    hc, raw = calibrate(tgt)
    p1 = np.array([run_phase(P1_TARGET_R, hc) for _ in range(N)], dtype=object)
    p1_pass = np.array([x[0] for x in p1]); p1_days = np.array([x[1] for x in p1])
    p2 = np.array([run_phase(P2_TARGET_R, hc) for _ in range(N)], dtype=object)
    p2_pass = np.array([x[0] for x in p2]); p2_days = np.array([x[1] for x in p2])
    both = p1_pass.mean() * p2_pass.mean()
    # calendar time to funded (only successful paths), trading days -> weeks
    okd = p1_days[p1_pass]; okd2 = p2_days[p2_pass]
    tt = (np.percentile(okd, [50, 80]) + np.percentile(okd2, [50, 80])) / 5.0

    fund = [run_funded(hc) for _ in range(1500)]
    surv3 = np.mean([len([x for x in f if x is not None]) >= 13 for f in fund])
    surv6 = np.mean([len([x for x in f if x is not None]) >= 26 for f in fund])
    wk_all = np.array([x for f in fund for x in f if x is not None])
    # 4-week rolling average >= $40 fraction (per surviving path, first 26 weeks)
    frac40 = []
    for f in fund:
        v = [x for x in f if x is not None][:26]
        if len(v) >= 4:
            ra = np.convolve(v, np.ones(4)/4, "valid")
            frac40.append((ra >= 40).mean())
    print(f"\n=== {label} (raw {raw:.1f} -> haircut {hc:.3f}R/trade) ===")
    print(f"P(pass Phase1)={p1_pass.mean():.1%}  P(pass Phase2)={p2_pass.mean():.1%}  P(BOTH)={both:.1%}")
    print(f"time to funded (wks, p50/p80): {tt[0]:.1f} / {tt[1]:.1f}  (+~3wk to first payout)")
    print(f"funded: survive 3mo={surv3:.1%}  6mo={surv6:.1%}")
    print(f"weekly net $: mean={wk_all.mean():.0f} p25={np.percentile(wk_all,25):.0f} "
          f"median={np.percentile(wk_all,50):.0f} p75={np.percentile(wk_all,75):.0f}  "
          f"P(week>=$40)={np.mean(wk_all>=40):.1%}  P(week<0)={np.mean(wk_all<0):.1%}")
    print(f"share of 4-week periods averaging >=$40/wk: {np.mean(frac40):.1%}")
    print(f"NET P(fee -> funded AND survives 3mo): {both*surv3:.1%}")
