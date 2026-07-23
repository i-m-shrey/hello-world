# STRATEGY SCOUT — three validated strategies, independently replicated

The prior forex_analyst research (PR #2/#3 branches) contains a battery of iron-gated strategies (train/holdout both positive, 2x-3x cost stress, neighbor plateaus, some live-deployed). `strategy_scout.py` + `scout_p1.py` re-implement the three strongest diverse candidates from scratch and re-run them on THIS project's independent Dukascopy feed (M1-derived frames, all-in house costs). Split convention matches the originals: train ≤2023 / holdout ≥2024.

## 1. XAUUSD DONCH-TR — gold H1 Donchian-96 trend breakout (long-only)
Rules: H1 close breaks above the prior-96-bar high +0.1×ATR50 → buy next open; stop = signal close − 2×ATR; NO take-profit — chandelier trail raises the stop to close − 5×ATR on every closed bar; time exit 192 bars; max 2 trades/day.
- Official (2008–26, broker feed): n=609, +205.8R, avg +0.338, train +157.4 / holdout +48.5, 3× cost PASS.
- **This feed (Dukascopy 2008–26): n=616, +211.7R, avg +0.344, WR 33%, PF 1.54, train +164.6 / holdout +47.1, 14/19 years positive, maxDD −33R; at 3× cost still +162.6R.** Replication within 3% — cross-feed CONFIRMED.
- Trail-4.0 twin (officially the stronger holdout cell): +190.5R, holdout +61.3, DD −28R — confirmed too.

## 2. XAUUSD STRAD — gold H1 consolidation-box breakout (long-only, close-confirmed)
Rules: 24-bar box (excluding current bar); tradeable when box width is 1–3×ATR50; H1 close above box high +0.1×ATR → buy next open; stop = box low; TP = entry + 2× box width; max hold 48 bars; max 2/day; skip the 17:00 rollover bar.
- Official: +43.6R (TZ-audit re-run +81.4R), PF 1.78, 13/18 years, survives 3×.
- **This feed: n=242, +39.0R, avg +0.161, WR 50%, PF 1.38, train +22.5 / holdout +16.5, 12/19 years, maxDD −9.3R; 3× cost +29.4R.** CONFIRMED (low frequency, ~1 trade/week).

## 3. GBPUSD P1 — H1 opposing-FVG reversal (both sides)
Rules: a displacement fair-value-gap (bar range ≥1.2×ATR, gap vs 2 bars back) followed within 30 bars by an opposing displacement FVG whose close breaks the prior 20-bar swing → LIMIT order at the near edge of the two FVGs' overlap zone (wait up to 30 bars for the retrace fill); stop beyond the far edge +0.1×ATR; TP = 2× risk; max hold 60 bars; max 2/day.
- Official (18.5y): +42R, PF 1.91, WR 49%, 12/17 years, cost-IMMUNE (3×: +43R), all parameter neighbors positive.
- **This feed (2016+ window, re-implemented executor incl. limit-fill semantics): n=77, +18.7R, avg +0.243, WR 44%, train +5.8 / holdout +12.9, 8/11 years; at 3× cost +20.4R.** CONFIRMED on the partial window (rules-level reimplementation; official validation remains the primary evidence).

## Rejected during scouting (full disclosure)
- **GBPUSD-BOLL15** (M15 Bollinger fade, official +409R): **FAILS on this feed** — −154.9R on 2016+ Dukascopy at 1× cost, all splits negative. The official matrix already flagged the family as feed-sensitive (USDCHF broker +35R vs deep-data +101R); this replication confirms the edge does not survive a different feed and it is NOT recommended.
- E/A-family session strategies (EURUSD_E +55/+37 official) not replicable here — they depend on the smc_engine H4-bias frame not present in these branches; left to the official validation.

## Notes for use
- All three are R-based (risk a fixed fraction per trade; R = risk incl. costs). Expected cadence is low: DONCH-TR ~2–3 trades/mo, STRAD ~1/mo, P1 ~0.6/mo — these are patience edges, the opposite profile of the M1 liquidity-grab.
- DONCH-TR and STRAD both hold gold-long breakouts and will partially overlap; treat them as one correlated sleeve when sizing. P1 is FX two-sided and independent.
- The two gold strategies are long-only by design (gold's structural uptrend; official short-side tests bleed). A prolonged gold bear market is the known failure regime — the official CRASH short exists as the book's insurance leg.
