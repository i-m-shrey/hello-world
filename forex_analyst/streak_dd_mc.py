#!/usr/bin/env python3
"""Losing-streak & max-drawdown MC for the rev10 prop book.
Reuses the exact BOOK stats / correlation / kill model from prop_challenge_mc.py,
but tracks per-trade sequences to answer:
  - distribution of longest consecutive-loss streak (per month, per phase)
  - distribution of max peak-to-trough drawdown in R / $ (kills active)
  - P(daily kill fires) and P(-8% halt)
"""
import numpy as np
from scipy.special import ndtr

rng = np.random.default_rng(11)

BOOK = [
    ("S5",        13.3, 0.450, 0.036, "goldi"),
    ("S6R",       11.8, 0.409, 0.046, "goldi"),
    ("S3LO",       5.7, 0.470, 0.062, "goldi"),
    ("HAVW_XAU",   5.1, 0.380, 0.100, "goldi"),
    ("DONCH_TR",   3.0, 0.350, 0.277, "goldt"),
    ("VCX_B",      1.6, 0.330, 0.280, "goldt"),
    ("MACROSS",    2.0, 0.330, 0.124, "goldt"),
    ("BOS",        7.6, 0.194, 0.161, "goldt"),
    ("ZBPIV_XAU",  0.9, 0.290, 0.160, "goldt"),
    ("STRAD",      2.5, 0.330, 0.146, "goldt"),
    ("H1A",        1.0, 0.370, 0.109, "goldt"),
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
    ("SPX_DONCH",  3.7, 0.261, 0.044, "idx"),
    ("GER_DONCH",  3.7, 0.305, 0.220, "idx"),
    ("GER_BOS",    7.9, 0.260, 0.038, "idx"),
    ("SPX_ZBPIV",  0.9, 0.470, 0.200, "idx"),
]
DAYS_PER_MONTH = 21
R_USD = 45.0
DAILY_KILL_R = -0.035 / 0.0075
MAX_KILL_R   = -0.080 / 0.0075
MIX = {"goldi": 0.45, "goldt": 0.65, "idx": 0.40,
       "eur": 0.20, "gbp": 0.20, "chf": 0.20, "cad": 0.20}

p_day  = np.array([b[1] / DAYS_PER_MONTH for b in BOOK])
wr     = np.array([b[2] for b in BOOK])
avg_r  = np.array([b[3] for b in BOOK])
tier   = [b[4] for b in BOOK]
win_r  = (avg_r + (1.0 - wr)) / wr
mixw   = np.array([MIX[t] for t in tier])
factor_id = np.array([{"goldi":0,"goldt":0,"idx":1,"eur":2,"gbp":3,"chf":4,"cad":5}[t] for t in tier])
is_goldt  = np.array([t == "goldt" for t in tier])

# book-level blended per-trade win rate (freq-weighted)
tpm = np.array([b[1] for b in BOOK])
blended_wr = float((tpm * wr).sum() / tpm.sum())

def day_trades(haircut):
    """One day's trade R outcomes (list, in execution order), correlated."""
    fires = rng.random(len(BOOK)) < p_day
    gt = np.where(fires & is_goldt)[0]
    if len(gt) > 1:
        keep = rng.choice(gt)
        fires[gt] = False
        fires[keep] = True
    idx = np.where(fires)[0]
    if len(idx) == 0:
        return []
    zf = rng.standard_normal(6)
    w = mixw[idx]
    z = w * zf[factor_id[idx]] + np.sqrt(1 - w**2) * rng.standard_normal(len(idx))
    u = ndtr(z)
    r = np.where(u < wr[idx],
                 win_r[idx] * (0.4 + 1.2 * rng.random(len(idx))),
                 -1.0)
    r = r - haircut
    rng.shuffle(r)
    # daily kill truncation
    c = np.cumsum(r)
    k = np.where(c <= DAILY_KILL_R)[0]
    if len(k):
        return list(r[:k[0]+1]), True
    return list(r), False

def sim_horizon(n_days, haircut):
    """Return (trade_rs, daily_kills, halted, equity_path_R)."""
    trades, kills = [], 0
    cum = 0.0
    path = [0.0]
    halted = False
    for d in range(n_days):
        out = day_trades(haircut)
        if not out:
            continue
        rs, killed = out
        kills += killed
        for r in rs:
            cum += r
            path.append(cum)
        trades.extend(rs)
        if cum <= MAX_KILL_R:
            halted = True
            break
    return trades, kills, halted, np.array(path)

def max_streak(rs):
    s = mx = 0
    for r in rs:
        s = s + 1 if r < 0 else 0
        mx = max(mx, s)
    return s if False else mx

def max_dd(path):
    peak = np.maximum.accumulate(path)
    return float((peak - path).max()) if len(path) else 0.0

def calibrate(target_monthly_R):
    global rng
    rng = np.random.default_rng(11)
    raws = []
    for _ in range(4000):
        fires = np.random.default_rng().random(0)
    # reuse quick approach: simulate kill-free month mean
    # (kill-free: just don't truncate; approximate with raw sum)
    # simpler: run sim without kill by huge kill threshold
    return None

SCENARIOS = [("PESSIMISTIC 2.5R/mo", 0.0093), ("BASE 4.5R/mo", 0.0), ("OPTIMISTIC 6.5R/mo", -0.0093)]
# haircut values: base raw output of the model was calibrated by original script;
# we recompute haircuts properly below instead of hardcoding.

def calibrate_hc(target):
    """Haircut so that kill-free monthly mean R ~= target (mirrors original)."""
    r2 = np.random.default_rng(3)
    tot, n_tr = 0.0, 0
    N = 40000
    for _ in range(N):
        fires = r2.random(len(BOOK)) < p_day
        gt = np.where(fires & is_goldt)[0]
        if len(gt) > 1:
            keep = r2.choice(gt)
            fires[gt] = False
            fires[keep] = True
        idx = np.where(fires)[0]
        if len(idx) == 0:
            continue
        zf = r2.standard_normal(6)
        w = mixw[idx]
        z = w * zf[factor_id[idx]] + np.sqrt(1 - w**2) * r2.standard_normal(len(idx))
        u = ndtr(z)
        r = np.where(u < wr[idx], win_r[idx] * (0.4 + 1.2 * r2.random(len(idx))), -1.0)
        tot += r.sum(); n_tr += len(r)
    raw_month = tot / N * DAYS_PER_MONTH
    tpd = n_tr / N
    return (raw_month - target) / (tpd * DAYS_PER_MONTH)

print(f"blended per-trade win rate (freq-weighted): {blended_wr:.1%}")
print(f"trades/day ~{p_day.sum()*0.93:.1f}   loss prob per trade ~{1-blended_wr:.1%}")

for label, tgt in [("PESSIMISTIC 2.5R/mo", 2.5), ("BASE 4.5R/mo", 4.5), ("OPTIMISTIC 6.5R/mo", 6.5)]:
    hc = calibrate_hc(tgt)
    N = 3000
    mstreak_m, mdd_m, kills_m, halts, all_wr = [], [], [], 0, []
    for _ in range(N):
        tr, k, halted, path = sim_horizon(DAYS_PER_MONTH, hc)
        if not tr:
            continue
        mstreak_m.append(max_streak(tr))
        mdd_m.append(max_dd(path))
        kills_m.append(k)
        halts += halted
        all_wr.append(np.mean([1 if r > 0 else 0 for r in tr]))
    ms = np.array(mstreak_m); dd = np.array(mdd_m); km = np.array(kills_m)
    print(f"\n=== {label} (haircut {hc:.3f}R/trade) — 1 month (21 tdays, ~{np.mean([len(sim_horizon(1,hc)[0]) for _ in range(200)])*21:.0f} trades) ===")
    print(f"longest loss streak in a month: median={np.median(ms):.0f}  p75={np.percentile(ms,75):.0f}  p90={np.percentile(ms,90):.0f}  p99={np.percentile(ms,99):.0f}  max={ms.max()}")
    print(f"P(streak>=5 in month)={np.mean(ms>=5):.0%}  P(>=7)={np.mean(ms>=7):.0%}  P(>=10)={np.mean(ms>=10):.0%}  P(>=12)={np.mean(ms>=12):.0%}")
    print(f"max drawdown in month (R): median={np.median(dd):.1f}  p75={np.percentile(dd,75):.1f}  p90={np.percentile(dd,90):.1f}  p99={np.percentile(dd,99):.1f}")
    print(f"max drawdown in month ($45/R): median=${np.median(dd)*R_USD:.0f}  p90=${np.percentile(dd,90)*R_USD:.0f}  p99=${np.percentile(dd,99)*R_USD:.0f}")
    print(f"daily kills/month: mean={km.mean():.2f}  P(>=1)={np.mean(km>=1):.0%}   P(-8% halt in month)={halts/N:.1%}")
    print(f"realized win rate distribution: mean={np.mean(all_wr):.1%}")
