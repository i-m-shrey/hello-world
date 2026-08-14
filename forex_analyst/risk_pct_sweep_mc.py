#!/usr/bin/env python3
"""Risk-percent sweep MC (rev11 companion, Aug 2026).

Question (owner): is 0.75%/trade the right risk, or should the backtest evidence
(win rate, RR, drawdown) pick a different number? This sweep reuses the exact
BOOK stats / correlation / kill model from prop_challenge_mc.py and re-derives
every barrier in R for each candidate risk%:
    P1 target +8%/r, P2 target +5%/r, daily kill -3.5%/r, max halt -8%/r
so LOWER risk = farther barriers = slower but safer, HIGHER risk = the reverse.

It also models what the flat-R MC ignores: MIN-LOT QUANTIZATION.
  * gold rides 0.01-lot steps ($1/pt per 0.01): stop-$ drawn lognormal fit to the
    live FundedNext stops (9.1..27, median ~$14.5); ceiling follows the PROP
    gold_steps chain (round(mult/2)); skip when even 0.01 lot busts the budget.
  * index cells (rev11 sizer) quantize in per-0.01-lot dollar steps: SPX $2.1,
    GER $14.2, US30 $7.5 (FundedNext contract specs).
  * FX quantizes finely (~$1/step) — modeled as a 0.97 fill factor.
Effective risk multiplies the trade's R outcome; a skip removes the trade.

Run:  python risk_pct_sweep_mc.py [--account 15000] [--fast]
"""
import sys
import numpy as np
from scipy.special import ndtr

rng = np.random.default_rng(7)

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
    ("US30_DONCH", 3.4, 0.288, 0.151, "idx"),   # rev11 promotion
]
DAYS_PER_MONTH = 21
MIX = {"goldi": 0.45, "goldt": 0.65, "idx": 0.40,
       "eur": 0.20, "gbp": 0.20, "chf": 0.20, "cad": 0.20}
IDX_STEP_USD = {"SPX_DONCH": 2.1, "SPX_ZBPIV": 2.1, "GER_DONCH": 14.2,
                "GER_BOS": 14.2, "US30_DONCH": 7.5}   # $ per 0.01 lot at live stops

ACCOUNT = 15000.0 if "--account" in sys.argv and "15000" in sys.argv else 6000.0
FAST = "--fast" in sys.argv
N_PHASE = 1500 if FAST else 3000
N_FUND = 600 if FAST else 1200

names   = [b[0] for b in BOOK]
p_day   = np.array([b[1] / DAYS_PER_MONTH for b in BOOK])
wr      = np.array([b[2] for b in BOOK])
avg_r   = np.array([b[3] for b in BOOK])
tier    = [b[4] for b in BOOK]
win_r   = (avg_r + (1.0 - wr)) / wr
mixw    = np.array([MIX[t] for t in tier])
factor_id = np.array([{"goldi":0,"goldt":0,"idx":1,"eur":2,"gbp":3,"chf":4,"cad":5}[t] for t in tier])
is_goldt  = np.array([t == "goldt" for t in tier])
is_gold   = np.array([t in ("goldi", "goldt") for t in tier])
is_idx    = np.array([t == "idx" for t in tier])
idx_step  = np.array([IDX_STEP_USD.get(n, 0.0) for n in names])

# gold stop-$ per 0.01 lot: TIERED lognormals (v2, review fix — was a single
# n=7 live fit). Shape from the n=369 backtest HAVW gold-H1 tradebook
# (havw_gold_h1_trades.csv risk column: median $14.4, log-sigma 0.317), scaled
# to 2026 ATR and split by tier:
#   goldi (M5 scalps): median ~$12 — the live M5 stops (9.1-14.3) sit here.
#   goldt (H1 trend):  median ~$28 — anchored on live H1 fills ($26.9-27) and
#     the three logged PROP skips ($33.7-39.5/0.01 = p72-p86 of this fit).
GOLDI_MU, GOLDI_SIGMA = np.log(12.0), 0.30
GOLDT_MU, GOLDT_SIGMA = np.log(28.0), 0.32

# --gcorr G adds a GLOBAL market factor shared by ALL tiers (review fix: v1
# correlated trades within a tier but drew gold/index/FX tier factors
# independently — optimistic for macro-shock days). g^2 + w^2 must stay <= 1.
GCORR = 0.0
if "--gcorr" in sys.argv:
    GCORR = float(sys.argv[sys.argv.index("--gcorr") + 1])

def gold_ceiling_steps(budget):
    """PROP chain: mult = budget/10.5, gold_steps = max(1, round(mult/2)) 0.01-lots."""
    return max(1, int(round(budget / 10.5 / 2)))

def eff_risk(i, budget, seed_rng):
    """Realized risk as a fraction of 1R for trade on BOOK row i, after broker
    lot quantization. 0.0 = trade skipped (min lot busts the budget)."""
    if is_gold[i]:
        if is_goldt[i]:
            stop = float(np.exp(GOLDT_MU + GOLDT_SIGMA * seed_rng.standard_normal()))
        else:
            stop = float(np.exp(GOLDI_MU + GOLDI_SIGMA * seed_rng.standard_normal()))
        if stop > budget:
            return 0.0                              # even 0.01 lot over budget -> skip
        k = min(int(budget / stop), gold_ceiling_steps(budget))
        return max(k, 1) * stop / budget
    if is_idx[i]:
        step = idx_step[i]
        if step > budget:
            return 0.0
        return (int(budget / step) * step) / budget
    return 0.97                                     # FX: ~$1 steps, near-perfect fill

def sim_days(n_days, haircut, risk_pct, kill=True, seed_rng=rng, collect_eff=None):
    budget = ACCOUNT * risk_pct
    daily_kill = -0.035 / risk_pct
    out = np.empty(n_days)
    for d in range(n_days):
        fires = seed_rng.random(len(BOOK)) < p_day
        gt = np.where(fires & is_goldt)[0]
        if len(gt) > 1:
            keep = seed_rng.choice(gt)
            fires[gt] = False
            fires[keep] = True
        idx = np.where(fires)[0]
        if len(idx) == 0:
            out[d] = 0.0
            continue
        zf = seed_rng.standard_normal(6)
        zg = seed_rng.standard_normal()
        w = mixw[idx]
        z = (GCORR * zg + w * zf[factor_id[idx]]
             + np.sqrt(np.maximum(1 - w**2 - GCORR**2, 0.0))
             * seed_rng.standard_normal(len(idx)))
        u = ndtr(z)
        r = np.where(u < wr[idx],
                     win_r[idx] * (0.4 + 1.2 * seed_rng.random(len(idx))),
                     -1.0)
        r = r - haircut
        eff = np.array([eff_risk(i, budget, seed_rng) for i in idx])
        if collect_eff is not None:
            collect_eff.extend(eff.tolist())
        r = r * eff
        seed_rng.shuffle(r)
        if kill:
            c = np.cumsum(r)
            k = np.where(c <= daily_kill)[0]
            out[d] = daily_kill if len(k) else c[-1]
        else:
            out[d] = r.sum()
    return out

def run_phase(target_pct, haircut, risk_pct, cum0_pct=0.0, max_days=260):
    """Barriers in account-% converted to R at this risk. Returns (passed, days)."""
    cum = cum0_pct / risk_pct
    target = target_pct / risk_pct
    halt = -0.080 / risk_pct
    day = 0
    while day < max_days:
        cum += sim_days(1, haircut, risk_pct)[0]
        day += 1
        if cum <= halt:
            return False, day
        if cum >= target:
            return True, max(day, 5)
    return False, day

def run_funded(haircut, risk_pct, weeks=26):
    cum, out = 0.0, []
    halt = -0.080 / risk_pct
    for w in range(weeks):
        wk = sim_days(5, haircut, risk_pct).sum()
        cum += wk
        if cum <= halt:
            out.append(None)
            break
        out.append(wk * ACCOUNT * risk_pct * 0.80 * 0.965)
    return out

# ---- calibrate the live-cost haircut ONCE at the current config (0.75%, base
# 4.5R/mo) and hold it fixed across the sweep, so risk% is the only variable.
_eff = []
raw = sim_days(20000, 0.0, 0.0075, kill=False, collect_eff=_eff).mean() * DAYS_PER_MONTH
tpd = p_day.sum() * 0.93
HAIRCUT = (raw - 4.5) / (tpd * DAYS_PER_MONTH)
print(f"account ${ACCOUNT:.0f} | gcorr {GCORR} | calibration: raw {raw:.1f}R/mo @0.75% quantized "
      f"(mean fill {np.mean(_eff):.2f}) -> haircut {HAIRCUT:.3f}R/trade | "
      f"N_phase={N_PHASE} N_funded={N_FUND}")
# --mu-only: print the kill-free drift (monthly R) per risk%, isolating the
# size-dependent quantization effect that breaks linear-in-1/risk recovery
# scaling at low budgets (review fix, Aug 14).
if "--mu-only" in sys.argv:
    print("\nkill-free drift by risk% (quantization included):")
    for rp in (0.004, 0.005, 0.006, 0.007, 0.0075, 0.0085, 0.010):
        mu = sim_days(15000, HAIRCUT, rp, kill=False).mean() * DAYS_PER_MONTH
        print(f"  {rp*100:.2f}%: {mu:5.2f} R/mo")
    sys.exit(0)

print(f"{'risk%':>6} {'$bud':>6} | {'P(P1)':>6} {'P(P2)':>6} {'P(P2|now)':>9} {'P(both)':>7} "
      f"{'med_td':>6} {'P2now_td':>8} | {'sv13':>5} {'sv26':>5} {'wk$':>5} {'4w>=40':>6} | "
      f"{'plan':>5} | {'goldskip':>8} {'fill':>5} {'fundcap':>7}")

CURRENT_DD_PCT = (5920.53 - 6000.0) / 6000.0    # live Phase-2 state, Aug 13 2026

for rp in (0.004, 0.005, 0.006, 0.007, 0.0075, 0.0085, 0.010):
    budget = ACCOUNT * rp
    p1 = [run_phase(0.080, HAIRCUT, rp) for _ in range(N_PHASE)]
    p2 = [run_phase(0.050, HAIRCUT, rp) for _ in range(N_PHASE)]
    p2n = [run_phase(0.050 + 0, HAIRCUT, rp, cum0_pct=CURRENT_DD_PCT) for _ in range(N_PHASE // 2)]
    p1p = np.mean([x[0] for x in p1]); p2p = np.mean([x[0] for x in p2])
    p2np = np.mean([x[0] for x in p2n])
    p2n_med = np.median([x[1] for x in p2n if x[0]]) if any(x[0] for x in p2n) else float("nan")
    both = p1p * p2p
    med_td = np.median([x[1] for x in p1 if x[0]]) + np.median([x[1] for x in p2 if x[0]])
    fund = [run_funded(HAIRCUT, rp) for _ in range(N_FUND)]
    sv13 = np.mean([len([x for x in f if x is not None]) >= 13 for f in fund])
    sv26 = np.mean([len([x for x in f if x is not None]) >= 26 for f in fund])
    wk_all = np.array([x for f in fund for x in f if x is not None])
    frac40 = []
    for f in fund:
        v = [x for x in f if x is not None][:26]
        if len(v) >= 4:
            ra = np.convolve(v, np.ones(4) / 4, "valid")
            frac40.append((ra >= 40).mean())
    # quantization stats at this budget
    e = []
    sim_days(600, HAIRCUT, rp, kill=False, collect_eff=e)
    e = np.array(e)
    gt = np.exp(GOLDT_MU + GOLDT_SIGMA * rng.standard_normal(4000))
    gi = np.exp(GOLDI_MU + GOLDI_SIGMA * rng.standard_normal(4000))
    gold_skip = 0.55 * np.mean(gt > budget) + 0.45 * np.mean(gi > budget)
    fundcap = "OK" if 4 * rp <= 0.03 + 1e-9 else "cap3!"
    plan = both * sv13
    print(f"{rp*100:5.2f}% {budget:6.1f} | {p1p:6.1%} {p2p:6.1%} {p2np:9.1%} {both:7.1%} "
          f"{med_td:6.0f} {p2n_med:8.0f} | {sv13:5.1%} {sv26:5.1%} {np.mean(wk_all):5.0f} "
          f"{np.mean(frac40) if frac40 else 0:6.1%} | {plan:5.1%} | "
          f"{gold_skip:8.1%} {e[e > 0].mean():5.2f} {fundcap:>7}")
