# PROFIT SEARCH (2016 → 2026-07) — spec v2 + structural tweak scan

Generated 2026-07-22 by `profit_search.py` from the same verified Dukascopy M1 data as REPORT.md. Mandate: restrict to 2016+, apply the user's detailed spec v2, and tweak freely to find a profitable configuration — under an honest protocol.

## Spec v2 rule changes vs the first backtest

- **SL at the extreme of the whole fake-out move** (not the signal candle's extreme) — `sl_mode=1`.
- **Signal candle needs a visible body** (body ≥ 25% of range) — `body_frac=0.25`.
- **Max 2 FULL stop losses per zone**; winners and CTC/breakeven-runner exits don't count — `att_mode=1, max_att=2`.
- T1 = most recent major swing (M15 k=2 fractal), 80% booked, SL→breakeven, 20% runner to session end. Engine changes are regression-tested: the original baseline still reproduces 11,131 trades / −1,866.3R exactly, and synthetic-bar tests cover the three new modes.

## Literal spec v2, XAUUSD M1, 2016-01 → 2026-07

- All trades: n=4526, net -457.2R, avg -0.101R, wr 16.4%, maxDD -516.0R
- Train 2016–22: n=3013, net -227.2R, avg -0.075R, wr 17.6%   |   Valid 2023–26: n=1513, net -230.0R, avg -0.152R, wr 14.1%
- T1 hit rate 12.5%; planned RR at T1 median 6.09 (banked winners avg 5.01) — the video's 1:6–1:7 offer is REAL; the hit rate is not.
- Full-SL rate 83.2%. Win rate 16.4% vs the claimed ~50%.
- Cost sensitivity: frictionless +0.180R avg (+814.5R; but +767.5R of it is ≤2022 — 2023+ is +47.0R over 1,513 trades ≈ zero); 2× cost −0.246R avg. The wider fake-out stop makes v2 half as bad as v1 (−0.101 vs −0.226 avg 2016+), still negative.

## Long vs short (spec v2)

- Train: long n=1378 avg -0.019 | short n=1635 avg -0.123
- Valid: long n=645 avg -0.074 | short n=868 avg -0.210
- Shorts (fading gold's daily highs in a secular bull market) are the bigger bleed, but longs are negative in BOTH halves too — no side-only rescue.

## Structural tweak grid — 864 cells, honest protocol

Levers: execution TF (M1/M5/M15 — wider signal candles), NY entry windows (all / London+NY 02:00–12:00 / NY-AM 07:00–12:00), min-risk floors ($0/$1), both SL modes, body filter on/off, T1 (major swing / 3R / 5R), runner (session-end BE / 2×ATR chandelier trail), attempt schemes (2 full SLs / 3 entries).
Protocol: selection ONLY on train 2016–22 (need n≥120, avg ≥ +0.05R); valid 2023–26 untouched; survivors must stay train-positive at 2× cost.

**Result: 0 of 864 cells pass the train screen; 0 pass overall.** Best train cell: `M1-all-f1-sl0-b0.25-T1rr5-Rsess-A2sl` at train +0.021R/trade → valid -0.152R/trade. Every top-10 train cell is validation-negative:

| cell | n | train avg R | valid avg R |
|---|---|---|---|
| M1-all-f1-sl0-b0.25-T1rr5-Rsess-A2sl | 3945 | +0.021 | -0.152 |
| M1-all-f1-sl0-b0-T1rr5-Rsess-A2sl | 4004 | +0.014 | -0.142 |
| M1-all-f1-sl0-b0.25-T1m15k2-Rsess-A2sl | 3967 | +0.013 | -0.170 |
| M1-all-f1-sl1-b0-T1rr5-Rsess-A2sl | 4386 | +0.002 | -0.116 |
| M5-all-f0-sl1-b0.25-T1rr5-Rsess-A3e | 5043 | -0.007 | -0.067 |
| M1-all-f1-sl0-b0-T1m15k2-Rsess-A2sl | 4015 | -0.007 | -0.137 |
| M5-all-f1-sl0-b0.25-T1rr5-Rsess-A3e | 4966 | -0.009 | -0.060 |
| M1-all-f1-sl1-b0.25-T1rr5-Rsess-A2sl | 4317 | -0.016 | -0.128 |
| M5-all-f0-sl1-b0.25-T1rr5-Rsess-A2sl | 3898 | -0.017 | -0.049 |
| M5-all-f1-sl1-b0.25-T1rr5-Rsess-A2sl | 3802 | -0.019 | -0.037 |

## Verdict

The corrected spec v2 rules are materially better than the first literal reading (wider fake-out stop halves the bleed) and the claimed 1:6–7 planned RR is confirmed — but the strategy is still unprofitable on 2016+ data at any tested setting, and it is NOT a cost artifact: the 2023–2026 out-of-sample period is ≈ zero even frictionless. 960 total configurations tested across both scans; none survive out-of-sample. Chasing further parameter combinations would be curve-fitting, not discovery: the selection metric (train 2016–22) already fails to transfer to 2023+ everywhere, which is the signature of a dead edge, not an under-tuned one.

## Refinement pass (`refine_lab.py`) — depth filter + multi-day runner

Two final levers, selected on train 2016–22 only:

1. **Sweep-depth filter** (only trade fake-outs ≥ k×ATR(M5,50) beyond the line, k ∈ {3,4,5}, implemented in-engine so 2-full-SL accounting stays honest). A tradebook *conditional* analysis suggested deep sweeps (>4 ATR) were positive in both halves (+0.05/+0.06 R). Implemented as a live filter it does NOT reproduce: blocking shallow triggers changes which entries exist at all (zones re-signal deeper, shallow losers no longer consume SL slots), and every depth cell is train-negative (d4: −0.138 avg vs unfiltered −0.075). The conditional result was a path-selection illusion, not an executable edge.
2. **Multi-day runner** (reason-4 runners re-simulated across sessions on a breakeven floor ± tighten-only chandelier, cap ~10 sessions; booked fraction 80% vs 50%). This genuinely helps — best cell `d0-extBE-b50` (no depth filter, hold runner at breakeven across days, book only 50% at T1) reaches train −0.000 avg (−1.4R over 3,013 trades) — but validation 2023–26 is still −0.112 avg (−169R), and 2× cost is −0.196. Median extended hold ≈ 2,800 M1 bars (~2 sessions), so the video's multi-day runner picture is real; the profits still aren't.

One cell (`d5-extBE-b50`) shows +78R on validation — with −261R on train. Selecting it would be selecting on the out-of-sample period, i.e. cheating; it is reported for completeness, not recommended.

**Final verdict after 1,024 configurations across four scans: no honestly-selected configuration of this strategy is profitable on 2016–2026 XAUUSD data.** The best achievable is breakeven-before-validation, and the out-of-sample period fails everywhere the training period doesn't. The mechanical pattern has no surviving edge; any profitable manual implementation must derive its edge from discretionary trade selection outside these rules.

## Max-SL invalidation rule (spec v3 addition)

The final spec version adds: skip the trade when the required SL is excessively large (70–90 pips ≈ $7–9/oz on gold). Tested as an in-engine cap (max_risk ∈ {3,5,7,9,12} $/oz, filtered triggers consume the signal) on spec v2, M1 gold 2016+, crossed with the multi-day-runner exits (`maxrisk_results.csv`):

- The rule is nearly inert where the spec puts it: the median M1 stop is $0.85/oz, so a $7–9 cap removes ~0.3% of trades (n 4,526 → 4,510) and changes nothing (train −0.081, valid −0.127 at cap $7).
- Even the aggressive $3 cap (removing 3% of trades) combined with the best exit found (multi-day BE runner, 50% booked) reaches train +0.001R — and validation is still −0.049R avg (−69R).

No change to the verdict: the oversized-stop invalidation addresses a failure mode this strategy doesn't have. Its losses come from ordinary-sized stops being swept 83% of the time, not from rare monster stops.

## Daily-trend gate (final lever)

Gate each side by the causal daily trend (momentum of completed-session closes, lookback k ∈ {3,5,10}; "with" = fade sweeps only against the trap direction, "counter" = opposite), crossed with the best exits (`trendgate_results.csv`, 24 cells):

- Honest train-selection picks `k5-with-extBE-b50` (train +0.165R avg) → **valid −0.166R**. Fails.
- One cell is positive in both halves (`k10-counter-extBE-b50`: train +0.044, valid +0.024) — but it ranks 4th on train (selection wouldn't choose it), its k3/k5 neighbors are strongly negative (no plateau), the trend sign flips with lookback (noise signature), and 24 screened cells make one marginal both-positive expected by chance. Rejected per house replication rules; recorded, not recommended.

This closes the last standard structural lever. Cumulative: **1,324 configurations, 0 honest survivors.**
