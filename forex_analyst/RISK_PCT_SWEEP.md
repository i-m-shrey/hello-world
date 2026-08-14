# Risk-% Sweep v2 — evidence-based per-trade risk (rev11 companion)

**Date:** Aug 14 2026 (v2, same day — v1 review fixes below) · **Tool:** `risk_pct_sweep_mc.py`

**v2 changes after review:** (1) full table — v1's report omitted the 0.70%/0.85% rows
even though they were simulated; (2) gold stop-$ distribution refit from n=7 live
stops to **tiered lognormals anchored on n=369 backtest stops** (HAVW gold-H1
tradebook, log-σ 0.317) scaled to 2026 ATR and validated against live fills+skips;
(3) **global cross-tier correlation stress** added (`--gcorr`) — v1 correlated trades
within a tier (Gaussian copula, gold w=0.45/0.65, idx 0.40, fx 0.20) but drew the
gold/index/FX tier factors independently, optimistic for macro-shock days;
(4) recovery-time claim derived + measured (new `P2now_td` column); (5) the −42/−62R
drawdown figures attributed correctly (throttle-on vs raw).

## Main table ($6K, base scenario, N=3000 phases / 1200 funded paths, gcorr 0)

| risk% | P(P1) | P(P2) | P(P2 from $5,920) | med td | P(both) | P1+P2 med td | sv13/26wk | wk$ | plan | gold skip |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.40% | 76.1% | 79.5% | 73.5% | 36 | 60.6% | 83 | 89/82% | $18 | 53.7% | **37.9%** |
| 0.50% | 71.2% | 77.4% | 69.1% | 22 | 55.1% | 48 | 78/73% | $25 | 43.2% | 23.6% |
| 0.60% | 68.6% | 74.0% | 66.8% | 15 | 50.8% | 33 | 72/65% | $30 | 36.7% | 11.4% |
| 0.70% | 67.6% | 72.6% | 65.7% | 12 | 49.0% | 27 | 68/62% | $39 | 33.5% | 5.8% |
| 0.75% | 63.8% | 72.4% | 62.9% | 10 | 46.2% | 22 | 67/61% | $46 | 31.2% | 4.0% |
| 0.85% | 65.0% | 70.0% | 63.3% | 8 | 45.5% | 21 | 66/61% | $54 | 30.0% | 1.5% — *illegal funded @cap4* |
| 1.00% | 64.3% | 69.9% | 59.9% | 7 | 44.9% | 14 | 62/57% | $72 | 27.9% | 0.5% — *illegal funded @cap4* |

**Correlation stress (gcorr 0.35, all tiers share a global factor):** at 0.75% —
P(both) 46.2→44.5% (−1.7pp), funded sv13 67.4→60.9% (−6.5pp), plan 31.2→27.1%.
The reviewer was right that funded survival is the correlation-sensitive number;
the *ranking* across risk% is unchanged under stress (orderings hold at every row),
so the decision survives, but treat funded survival as 55–67% band, not a point.

**$15K:** same shape; gold skips vanish (0.5% at 0.40%), wk$ ≈ 2.4× (e.g. $117/wk
at 0.75%).

## What v2 changed materially — the stop refit hurts LOW risk

With the tiered fit (gold-trend median stop ≈ $28/0.01-lot at 2026 ATR — the three
logged PROP skips at $33.7–39.5 sit at p72–p86 of it, live fills $26.9–27 near
median), the low-risk rows lose much more of the gold book than v1 showed:
**at $6K/0.40%, 37.9% of gold trades can't be sized at all** (v1 said 12.7%).
P(both) at 0.40% fell 66.7%→60.6% accordingly. The "safe" end of the sweep was
partly an artifact of the thin n=7 fit; with real stop data it is even less
attractive on a small account. On $15K the effect disappears — low risk% is a
*large-account* option, not a small-account one.

## Recovery-time claim — derivation + measurement (was asserted in v1)

Derivation: to recover a fixed dollar/percent distance D at risk r and size
multiplier m, the distance in R is D/(r·m) while drift per day in R (edge per
trade) is unchanged, so **E[days] ≈ D/(r·m·μ_R) — linear in 1/m**: halving size
doubles expected recovery time. *Assumption: stationary edge* — if the edge has
decayed, smaller size is loss-limiting, not recovery-delaying; a 14-trade live
sample cannot yet distinguish these, which is what the mid-Aug calibration gate
and monthly refits are for. Measured (P2 from $5,920, `P2now_td` median):
10 tdays at 0.75% → 22 at 0.50% → 36 at 0.40%, while P(pass|now) rises
62.9%→69.1%→73.5%. The trade is ~+10pp of pass probability for ~3.6× the time.

## The −42/−62R drawdown figures, attributed (was ambiguous in v1)

−62.0R = the RAW 2020–25 book max drawdown; **−42.1R = the same book with the
−20R/0.5× throttle active** (the throttle is live in the bot: −30% tail DD for
−21% profit, net/DD 7.3→8.4). The DD axis has been searched before this sweep:
concurrency cap 4→3 cuts maxDD only −47.8R→−45.8R while costing −11.6R of profit
(bot §governor comments), and the owner's dynamic-cap idea was backtested and
rejected (−1–2pp pass, July study). Conclusion stands with attribution: the
throttle is the accepted DD lever and is already in every number here; further
slot-cutting buys ~2R of DD for ~12R of profit and stays rejected.

## Decision (v2 wording — honest about what is data vs rule)

- **Challenge phases: 0.75%** (0.70–0.75% are statistically indistinguishable at
  N=3000, ±2pp; 0.75% is the incumbent and time-optimal; nothing in v2 argues for
  a change in either direction).
- **Funded: 0.70% with cap 4.** Plainly: **this is a rule-geometry choice, not a
  sim-selected one** — 4×0.70% = 2.8% keeps 0.2pp of headroom under FundedNext's
  3% open-risk rule against SL-attach slippage. The sim's job here was to confirm
  it costs nothing measurable vs 0.75% (it does: all deltas inside noise) and that
  the alternative fork (cap 3) costs real R (July study). "Derived from evidence"
  in v1 overstated it; "rule-derived, evidence-cleared" is the correct claim.
- **Never ≥0.85% anywhere** (illegal at funded under cap 4; worse P(both) anyway).
- **No mid-phase change to the live P2** — now with the derivation and the
  measured column above instead of an assertion.

Caveats that remain: MC noise ±2pp; scenario anchor = base 4.5R/mo with the
haircut held fixed across the sweep; the goldi (M5) stop fit still leans on few
live points (the goldt tier, which actually binds the budget, is the n=369 one);
cross-tier correlation 0.35 is a stress guess, not an estimate — fitting it from
the daily backtest equity curves is the natural next refinement.
