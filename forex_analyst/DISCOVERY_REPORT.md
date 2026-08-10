# DISCOVERY REPORT — Mandate 2 (July 2026)

All scans ran on TZ-verified data (see TZ_AUDIT_REPORT.md), real all-in costs
(live_signals.FX_SPREADS), train ≤2023 / holdout ≥2024, 2×/3× cost stress,
conservative executor (next-open entry, stop-first on same-bar collisions).
Every cell tried is in `discovery_ledger.csv` — passes and rejections.
Scripts: `discovery_engine.py`, `discover_trend.py`, `discover_fx.py`,
`discover_overlap.py`.

## RANKED SLATE

### 1. EXIT UPGRADE for XAUUSD_DONCH — chandelier trail instead of fixed 3R  ⭐ strongest result
Same entries as the deployed instance (96-bar breakout long); only the exit
changes: 2-ATR initial stop, then trail = max(trail, close − k·ATR), no target,
time exit 192 bars.

| trail k | n | avg R | net R | train | holdout | 2× | 3× | +yrs |
|---|---|---|---|---|---|---|---|---|
| fixed rr3 (deployed) | 911 | +0.138 | +125.8 | +53.0 | +72.8 | +0.100 | +0.073 | 12/19 |
| 2.5 | 840 | +0.145 | +122.1 | +66.0 | +56.1 | +0.113 | +0.082 | 12/19 |
| 3.0 | 766 | +0.193 | +147.9 | +90.0 | +57.9 | +0.160 | +0.128 | 14/19 |
| 3.5 | 718 | +0.213 | +152.7 | +99.2 | +53.5 | +0.179 | +0.146 | 14/19 |
| **4.0** | 670 | **+0.263** | **+176.5** | +112.6 | +63.9 | +0.229 | +0.195 | 15/19 |
| 4.5 | 638 | +0.307 | +196.1 | +137.9 | +58.3 | +0.271 | +0.236 | 14/19 |
| 5.0 | 615 | +0.338 | +207.6 | +160.9 | +46.7 | +0.301 | +0.265 | 13/19 |

Monotone improvement across the whole grid, both splits positive everywhere,
3×-cost immune — this is a plateau, not a tuned point. Recommend **trail 4.0**
(middle of the plateau, best holdout). ~36 trades/yr, **+0.80 R/month vs +0.57
deployed** (+40%). The same lens applied via `+BE at 1R` variants is also
positive but strictly worse than the pure trail. Concept proven: **gold's
breakout edge is bigger than a 3R target can hold — the exit was leaving R on
the table** (confirms the BOS rr-grid lesson).
Path to live: normal pipeline — live_signals variant + verify_* + user decision.

### 2. VCX — volatility-contraction → expansion breakout (gold H1) — real, but NOT additive
Box = prior 96-bar range at its tightest quartile (percentile ≤0.25 over 720
bars), close breaks box-high +0.1·ATR → long, 2-ATR stop, 3R target. **All 12
primary cells and all 27 neighbor cells pass** (avg +0.25…+0.33, 3×-immune,
14-16/19 years). BUT: open-time overlap with deployed DONCH96 is **96.5%**,
daily-R corr +0.635 — VCX is a quality-filter on the same trades, not a new
edge. Fewer trades (19/yr) at higher avg (+0.30) earn LESS total than deployed
DONCH96. **Verdict: validated concept, zero book-value as a separate instance.**
Optional use: as a tightness filter/size-up flag on existing DONCH signals.
Replication: GER40 ✓, US30 ✓, SPX500 ✗, JPN225 ✗ (train-negative), HK50 ✗ —
consistent with "some indices trend better than others", short history caveat.

### 3. MTF-DONCH — H4-aligned faster channel (gold H1, N=24, rr3) — watchlist
9/9 neighbor cells pass (avg +0.085…+0.183, 2×/3×-immune). Overlap vs DONCH96
73%, corr +0.574, corr vs VCX +0.303. Concern: R is holdout-heavy (train +48 /
holdout +98; 2012-14 were -14/-15/-10 years) — the faster channel mostly earns
in the 2024-26 bull. **Not slate-ready: park on the watchlist; revisit if it
keeps earning outside the bull.** ~55 trades/yr, +0.66 R/month if taken as-is.

### 4. PULLBACK-CONTINUATION (gold H1, rr3) — marginal pass, regime-tilted
Uptrend (ema50>ema200, close>ema200), dip below ema20, reclaim → long. Passes
at rr3 (avg +0.082/+0.084, both splits +) but train is thin (+28…+31 of +101
total) — most R is 2024+. GER40/US30/JPN225 replicate at rr3, SPX500/HK50 fail.
**Below the bar for deployment; recorded as a validated-but-weak concept.**

## REJECTIONS (with numbers — see ledger for full grids)

- **FX mean-reversion, everything tested** on the 19-year TZ-correct deep data:
  BOLL30-style fades (all 3 pairs, all windows incl. the deployed-shaped cells):
  avg −0.073…+0.002 — costs eat the thin edge in my conservative executor.
  RSI30 replications: only the deployed USDCHF short-only cell is positive
  (+0.097 avg, 15/19 yrs) and it fails 2× cost here. Range-extreme fades: 5 of 6
  cells fail. NOTE the honest tension: the deployed BOLL30/RSI30 validations
  (broker 30m files, TRUE UTC, different fill conventions) stand as validated —
  but the deep-data cross-check says this family has **no margin for error**.
  Treat every FX fade as fragile; the spread tripwires matter more than ever.
- **Regime routing (the prioritized hypothesis) — FALSIFIED both ways.**
  Trend side: gating DONCH96 to "trending" regimes (efficiency-ratio pctile
  ≥0.5) LOWERS avg R (+0.096 vs +0.138 ungated); the anti-regime cells (er<0.5)
  are the best (+0.446, n=156) — gold breakouts from QUIET ranges are the
  strongest, which is the VCX result again. Fade side: er<0.5 gating does not
  rescue any FX fade (all cells negative or cost-fragile). Routing "trend tools
  in trends, fade tools in ranges" is the wrong model on this book; what works
  is **compression → expansion**, not trend-following-in-trends.
- **Cross-asset USD-basket gate on gold longs: REJECTED** (train −19.4R; the
  USD-strong control side was BETTER +0.273 — the naive macro gate is noise).
- **SPX500 trend concepts: REJECTED** on 2022+ data (VCX avg +0.047 fails
  floor+holdout+2×; pullback +0.025 fails). HK50: everything negative.
  JPN225: VCX train-negative; pullback passes at the reduced bar (short data).

## What was discovered (concept summary)

1. **Gold's breakout edge is exit-limited, not entry-limited.** Every entry
   family (DONCH96, VCX, MTF-DONCH) improves monotonically as the exit lets
   winners run (fixed 3R → trail 4-5 ATR). The single highest-value change to
   the book is an exit, not a new signal.
2. **Compression precedes the tradable expansion.** The tighter the prior range
   percentile, the better the breakout (VCX plateau; anti-regime DONCH cells).
   "Trending regime" filters do NOT help breakouts — the good breakout is born
   in the quiet, not in an established trend.
3. **FX mean-reversion has no reserve margin.** On the deepest correct-time
   data, the fade family's edge rounds to zero after real costs in a
   conservative executor. The deployed thin fades live or die on the broker's
   actual spread — the preflight cost tripwires are the real risk control.
4. **Macro one-liners (USD weak ⇒ buy gold) don't survive contact with data.**

## Capital to $100/month — honest math (never a target, only arithmetic)

R/month at the corrected numbers, risking 1% of equity per trade
(capital = $100 / (R_month × 1%)):

| book | R/month | capital for $100/mo @1% | @0.5% |
|---|---|---|---|
| Deployed gold+index trend family (validated, corrected) | ~1.6 | ~$6,300 | ~$12,500 |
| + DONCH exit upgrade (+0.23) | ~1.8 | ~$5,600 | ~$11,100 |
| Whole 15-instance low-risk book (official numbers, rough) | ~2.5-3 | ~$3,300-4,000 | ~$6,700-8,000 |

At the current ~$150 the honest expectation is **$3-6/month** at survival-ladder
risk. The ladder is the plan: the edges are real but small; capital is the
missing factor, and no amount of scanning changes that arithmetic.
