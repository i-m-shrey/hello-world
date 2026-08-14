# Risk-% Sweep — evidence-based per-trade risk (rev11 companion)

**Date:** Aug 14 2026 · **Tool:** `risk_pct_sweep_mc.py` (same BOOK/correlation/kill
model as `prop_challenge_mc.py`; barriers re-derived in R per risk%; min-lot
quantization modeled — gold lognormal stop-$ fit to the live FundedNext stops,
index cells in per-0.01-lot dollar steps, FX ~0.97 fill).

## Headline numbers ($6K, base scenario, N=3000 phases / 1200 funded paths)

| risk% | P(P1) | P(P2) | P(P2 from $5,920) | P(both) | med tdays P1+P2 | funded sv 13/26wk | wk$ | P(both)×sv13 |
|---|---|---|---|---|---|---|---|---|
| 0.40% | 79.1% | 84.3% | 72.4% | **66.7%** | 76 | 90/85% | $21 | 60.1% |
| 0.50% | 73.8% | 76.2% | 70.9% | 56.2% | 50 | 82/75% | $26 | 46.0% |
| 0.60% | 69.4% | 75.2% | 65.7% | 52.2% | 34 | 73/67% | $33 | 38.1% |
| **0.75%** | 65.7% | 72.4% | **65.2%** | 47.6% | **22** | 66/59% | $46 | 31.3% |
| 0.85% | 64.8% | 71.1% | 63.4% | 46.1% | 21 | 67/62% | $52 | 30.8% — **illegal funded @cap4** |
| 1.00% | 65.0% | 68.3% | 63.4% | 44.4% | 14 | 60/55% | $70 | 26.7% — **illegal funded @cap4** |

$15K sweep: same shape, quantization pain gone (gold skips 12.7%→0.1% at 0.4%),
weekly $ scales ~2.5× (e.g. $116/wk at 0.75%).

## What the evidence actually says

1. **Lower risk buys pass probability with time, not for free.** No time limit ⇒
   P(pass both) rises monotonically as risk falls (47.6% → 66.7% from 0.75% → 0.40%),
   but median trading time to funded stretches 22 → 76 tdays (~1 month → ~3.6 months).
   A failed attempt costs $137 and restarts; a slow attempt costs months of the
   ladder's compounding. Expected calendar-to-funded ≈ attempts × duration:
   ~2.2 months at 0.75% vs ~4.3 months at 0.50%. **Time is the scarce resource for
   the $2–3K/mo goal; the retry fee is not.**
2. **The funded stage caps risk by RULE, not by preference.** FundedNext funded
   accounts: total open risk ≤3% of initial. At the 4-position cap that means
   ≤0.75%/trade; 0.85–1.0% would require cap 3, and the July concurrency study
   already showed admission-cutting costs book R. Funded extraction EV within the
   legal band rises with risk ($494 → $893 expected per 26 weeks from 0.40% → 0.75%)
   because payouts front-run account death — the extraction-vehicle logic.
3. **Quantization sets the floor.** At $6K/0.40% the budget is $24 and 12.7% of gold
   trades can't be sized at all (0.01 lot > budget) — the "safe" setting quietly
   deletes part of the edge. Mean deployed fill is only ~0.75–0.82 of intended risk
   at any setting (gold rounding + index steps); on $15K the floor effectively
   disappears. Ultra-low risk% is not actually available on small accounts.
4. **Drawdown context** (`streak_dd_mc.py`): the book's median *monthly*
   peak-to-trough DD is ~13R, p99 ~25R. At 0.75% that is 9.8%/19% — the firm's 10%
   static line sits at 13.3R. No feasible risk% makes the 5-year backtest maxDD
   (−42…−62R) fit inside 10%; immortality would need ≤0.15%/trade, below the gold
   min-lot floor and economically pointless. **Accounts are extraction vehicles;
   survival of the plan comes from the ladder + fee-from-payouts discipline.**

## Decision (owner-approved framework, numbers now derived not asserted)

- **Challenge phases (every account, 6K and 15K): `PROP_RISK_PER_R_PCT = 0.0075`.**
  Time-optimal; the safety bought by 0.5% costs ~2 extra months per funded account
  and its pass-probability gain (+8.6pp) is worth less than the time.
- **Funded stage: `PROP_RISK_PER_R_PCT = 0.0070`, keep `PROP_MAX_TOTAL = 4`.**
  4 × 0.70% = 2.8% ≤ 3% firm rule with real headroom for SL-attach slippage —
  resolves the handoff's "cap 3 OR risk 0.0070" fork in favor of keeping admissions
  (the cap study says cuts cost R; 0.05pp of risk does not).
- **Never ≥0.85% anywhere:** illegal at funded under cap 4, and P(both) is worse
  anyway — there is no upside case.
- **Live Phase 2 right now: NO change.** From $5,920.53 the pass probability at the
  current 0.75% is ~65%; dropping to 0.5% adds ~6pp at the cost of weeks and a
  mid-run config change the freeze discipline exists to prevent.
- **The $2–3K/mo goal is a capital problem, not a risk% problem:** $46/wk on 6K vs
  $116/wk on 15K at identical risk. The ladder (merge → scale-ups → $75–100K) is
  the lever; risk% is now set where the evidence puts it.

Caveats: MC noise ±2pp at these sample sizes; the gold stop-$ distribution is fit
to 7 live stops (refit after a month of live data); scenario anchor = base 4.5R/mo
with the haircut held fixed across the sweep so risk% is the only variable.
