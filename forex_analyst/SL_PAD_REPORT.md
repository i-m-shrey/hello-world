# SL-Pad Experiment — "widen every stop a little" (owner request, Aug 17 2026)

**Hypothesis (owner):** stops keep getting hit right before reversals; padding every
SL by ~0.1–0.2% of price (or a small ATR fraction) should improve results.

**Method:** exact `live_signals` conditions replayed on 2 years of proxy data
(GC=F, ES=F, YM=F, NIY=F, ^GDAXI, EURUSD=X, GBPUSD=X — yahoo 1h depth limit).
Fixed trade cohort per cell (baseline signals), exits re-simulated per pad:
baseline, +0.10×ATR, +0.25×ATR, +0.1% price, +0.2% price. R measured on the
widened risk (live sizers keep $ risk constant, so wider stop = smaller lot).
Both TP conventions tested (rr-scaled = bot semantics; tp-fixed = pure extra room).
Conservative same-bar rule (SL before TP). Out of scope: trail exits (different
mechanism), gold M5 SMC tier + A/P1 (need smc_engine), 30m fades (data depth).
Run: `python sl_pad_lab.py` (needs numpy/pandas/yfinance).

## Result: NO systematic improvement. The hypothesis is not supported.

Avg R by pad (rr-scaled variant), 13 cells, n=54–607 each:

- Improves monotonically: **SPX500_DONCH only** (+0.113 → +0.218 at +0.2%px, n=440).
- Degrades monotonically: **GER40_DONCH** (+0.688 → +0.560), US30_DONCH (+0.306 → +0.180),
  XAUUSD_VCX_B, XAUUSD_STRAD.
- Noise-level either way: JPN225_DONCH, GER40_BOS, XAUUSD_BOS (+0.25×ATR best by +0.03),
  XAUUSD_ZBPIV, SPX500_ZBPIV (n=57), MACROSS (approx bias, outlier-driven).
- **The motivating case, EURUSD_E: the owner's proposed +0.1% pad flips it from
  +0.198R to −0.004R** (11.6 pips ≈ 0.6×ATR — the padded TP moves so far that
  winners stop reaching it). GBPUSD_E same direction (−0.097 at +0.1%px).

Mechanism: with dollar-normalized sizing, a wider stop shrinks the position, so
every winner pays less per trade; the saved-by-the-pad trades must outnumber that
drag AND the still-losers' identical dollar loss. Across the book they don't —
the "stopped then reversed" cases are salient but not the majority. Baseline wins
or ties in 11 of 13 cells.

## Disposition

1. **No stop changes anywhere.** The felt pattern is salience bias; the data says
   current structural-stop placement is at or near optimal for this book.
2. **One earmark:** SPX500_DONCH's monotonic improvement is a legitimate candidate —
   park it for the full-history validation battery (16y data on the owner's machine,
   train/holdout + 3× cost stress, house n≥80 bar) at a phase boundary. Not before.
3. Caveats: 2-year window (yahoo depth), proxy feeds (futures/cash vs FundedNext CFD),
   ±0.05–0.10 avg-R noise at these sample sizes; conclusions are about the book-wide
   direction, which is consistent across both TP conventions.
