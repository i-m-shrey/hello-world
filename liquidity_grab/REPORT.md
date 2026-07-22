# LIQUIDITY GRAB (PDH/PDL sweep-reversal) — XAUUSD M1 backtest

Generated 2026-07-22 13:15Z by `liquidity_grab_lab.py` (deterministic; every figure below comes from the run that wrote this file). Strategy per the video brief: sweep of the previous day's high/low, signal-candle stop entry back through the level, 80% booked at the prior swing, breakeven runner into session end.

## 1. Data provenance

- Source: Dukascopy via `dukascopy-node` (`npx -y dukascopy-node -i xauusd -from Y-M-D -to Y-M-D -t m1 -f csv -v true`), yearly chunks with retries — `download_data.py`. BID series is the trade price; ASK downloaded for the spread audit. Timestamps are epoch ms UTC (bar open), converted per-timestamp to America/New_York (never a fixed offset). `-v true` matters: without it dukascopy-node pads closed/tickless minutes with flat candles (see D18) — the loader enforces volume>0 and refuses padded input.
- Coverage: **2007-12-31 19:00:00-05:00 → 2026-07-21 19:59:00-04:00** (6,589,094 real M1 bars; 0 duplicate, 0 malformed and 0 zero-volume rows dropped from 6,589,094 raw).
- Earliest-year probe: 2008 is already dense (361,997 bars) — no forward walk needed; coverage starts at the brief's first candidate year.
- Bars per year: 2007: 149, 2008: 361,997, 2009: 362,050, 2010: 364,109, 2011: 362,590, 2012: 362,146, 2013: 352,307, 2014: 351,440, 2015: 353,746, 2016: 354,364, 2017: 352,788, 2018: 353,923, 2019: 353,290, 2020: 355,495, 2021: 354,346, 2022: 354,633, 2023: 352,969, 2024: 355,892, 2025: 349,362, 2026: 181,498.
- Raw CSVs live in `liquidity_grab/data/` (gitignored); re-fetch with `python3 download_data.py`.

## 2. Timezone verification (house NFP fingerprint) — **PASSED**

Epoch-ms-UTC → NY conversion is verified empirically, not assumed: on first-Friday (NFP) sessions the max-range M1 bar of the session must cluster at exactly 08:30 NY in BOTH DST-summer and winter (a fixed-offset mistake shifts one season by an hour). The lab refuses to run otherwise.

**Summer** — 138 first-Friday sessions, max-range M1 bar mode **08:30** (58.0% of days):

| NY time of session max-range M1 bar | days |
|---|---|
| 08:30 | 80 |
| 08:31 | 6 |
| 08:33 | 4 |
| 08:35 | 2 |
| 08:34 | 2 |
| 08:32 | 2 |
| 10:00 | 2 |
| 08:39 | 1 |

**Winter** — 79 first-Friday sessions, max-range M1 bar mode **08:30** (45.6% of days):

| NY time of session max-range M1 bar | days |
|---|---|
| 08:30 | 36 |
| 08:31 | 5 |
| 08:57 | 4 |
| 10:00 | 3 |
| 08:43 | 2 |
| 08:37 | 2 |
| 08:32 | 2 |
| 10:19 | 1 |

Non-08:30 entries are dominated by shifted/cancelled NFP months (holiday first-Fridays, pandemic months) and genuine non-NFP volatility; the sharp 08:30 mode in BOTH seasons is the fingerprint that matters. A +1h parse error would move one season's mode to 07:30/09:30 — it does not.

## 3. Spread measurement vs. house cost

ASK−BID on matched M1 closes, 2024-01-01 → 2026-07-21 (884,112 matched minutes):

| window | median | p90 |
|---|---|---|
| all hours | $0.520 | $0.780 |
| NY 08:00–12:00 | $0.510 | $0.770 |
| 2024 (all hours) | $0.380 | $0.447 |
| 2025 (all hours) | $0.580 | $0.767 |
| 2026 (all hours) | $0.700 | $0.960 |

Mean $0.549, p99 $1.340; 0.0% of minutes print a transiently negative top-of-book (raw feed artifact). SANITY CHECK, stated honestly: the measured Dukascopy median spread ($0.520, widening with the gold price from $0.38 in 2024 to $0.70 in 2026) is substantially WIDER than the $0.16 spread inside the house all-in round trip of **$0.23/oz** (0.16 spread + 0.07 commission, from `live_signals.FX_SPREADS` on capy/tz-audit-discovery, measured from live fills on a raw-spread retail account). The house $0.23 is therefore treated as the OPTIMISTIC baseline cost; executing at Dukascopy's own top-of-book would cost ≈$0.52+commission ≈ 2.5× that, i.e. the mandated 2× stress row approximates Dukascopy-median execution and 3× covers news-time widening (p99 above). Every headline figure charges $0.23 per round trip; risk includes cost, so a stop-out is exactly −1R.

## 4. Sessions

- NY 17:00→17:00 sessions in range: 4798 — valid (≥500 M1 bars): 4784, skipped thin/holiday/weekend-stub: 14, tradeable (valid + fresh previous valid session ≤5 days for PDH/PDL): 4782.
- Bars per valid session: p5 1359 / p25 1379 / median 1380 / p75 1380 / max 1440 — the 1380 median is the full 23h Dukascopy gold day (daily 17:00–18:00 NY closure sits exactly on the session boundary).
- Intra-session gaps (valid sessions): largest-gap median 1 min, p90 6 min, p99 23 min; 6 sessions contain a gap >60 min (daily maintenance break ~17:00 NY accounts for the typical gap).

## 5. Rule formalization — every disambiguation made

The brief leaves real degrees of freedom; each was resolved ONCE, conservatively, and applies to every variant identically:

**D1.** Bid series is the trade price. All-in round trip $0.23 charged per unit (≡ cost/2 adverse each side). Risk = |entry−SL| + cost → a straight SL exit is exactly −1R; targets expressed in R use this risk (so cost stress legitimately moves 3R/5R target prices and the 0.5R floor).

**D2.** Trading day = NY 17:00→17:00, session labelled by END date (Sun 17:00→Mon 17:00 = Monday). PDH/PDL = high/low of the most recent VALID (≥500 bars) session with session-date gap ≤5 calendar days (Fri→Mon = 3; longer ⇒ session untradeable). Monday's previous day is Friday by construction.

**D3.** Forced flat at the first bar ≥16:55 NY — an open trade exits at that bar's OPEN; if a session has no ≥16:55 bar, at the last bar's close. No entries on/after the force bar. Pending stops die with the session.

**D4.** Arming is intrabar and strict (high > PDH). Signal candle: red (close<open strict; doji never qualifies) with close > PDH (strict). Reset to unarmed on close < PDH only while NO signal is pending.

**D5.** Signal invalidation: a later bar's HIGH exceeding the signal high cancels the pending stop (mirror for longs). The brief says 'new session high above the signal candle high'; the implemented superset also covers the case where the SL level is breached pre-entry while an earlier session extreme still stands — keeping a sell stop whose SL was already violated is not executable. Re-selection follows normal rules (the invalidating bar itself may qualify as the new signal).

**D6.** Trigger is strict (bar low < signal low / high > signal high) and is evaluated BEFORE invalidation within the bar (conservative: you get filled, and if the bar also touches SL you are stopped same-bar for exactly −1R; stop-before-target on every bar, house rule).

**D7.** Entry fill = signal low, or the bar's open if it gaps through (min(open, sig_low) short / max(open, sig_high) long — never better than the stop price). Later-bar SL fills honor gaps the same way (worse of open vs level). T1 fills exactly at the level even on favorable gaps (conservative).

**D8.** One open trade at a time globally. A trigger that fires while a trade is open (or on the bar the trade exits) is MISSED: the pending stop is cancelled — no fantasy fill, no queueing; the zone may re-select later. No same-bar re-entry after an exit.

**D9.** Signal candles may FORM while a trade is open (formation ≠ trigger); zone state machines run on every bar.

**D10.** Attempt = actual entry; MAX_ATTEMPTS caps entries per zone per session regardless of outcome (re-setup after wins allowed). Both zones triggering in one bar: short processed first (deterministic; never observed in practice).

**D11.** Fractal swings are strict extremes (k bars each side; ties disqualify). M1 k=5 usable from bar i+6 (confirm bar i+5 CLOSED before the entry bar). M15 k=2 usable once the 2nd following M15 bar closed at/before the entry bar's open. Swing window = current + previous (PDH-source) session.

**D12.** T1 selection: most recent confirmed swing strictly beyond entry; if none, or the most recent one is closer than 0.5R, fall back to fixed 3R (no deeper scan).

**D13.** 80% booked at T1; runner stop = breakeven (raw entry) ACTIVE FROM THE BAR AFTER the T1 bar (a stop created mid-bar cannot be triggered by that bar's pre-existing extremes). Runner BE exit pays the round-trip cost (−cost/risk in R). Baseline has NO BE move before T1, as pinned by the brief.

**D14.** Chandelier variant: runner stop = min(BE, close_M5 + 2×ATR(M5,50)) for shorts (mirror longs), ratcheting only tighter, updated once per CLOSED M5 bar (last M5 bar whose close time ≤ current M1 open — fully causal), active from the bar after T1.

**D15.** Qualifier variant: the brief's literal 'entire body beyond line (min(open,close) > PDH)' is mathematically identical to the baseline for a RED candle (red ⇒ close<open ⇒ min(open,close)=close), and likewise for green candles at PDL. To make the dimension real, the strict variant requires the FULL candle beyond the line (low > PDH short / high < PDL long, wicks included).

**D16.** Cost stress (2×/3×) re-runs the entire simulation: risk-derived targets and the 0.5R swing floor move with cost, as they would for a trader actually paying it.

**D17.** MFE/MAE are price excursions from entry over the trade's bars (entry-bar extremes may pre-date the fill moment — MAE is therefore conservative), divided by risk; no cost subtracted.

**D18.** Dukascopy minutes with no ticks are ABSENT: dukascopy-node without `-v true` pads closed/tickless periods with flat carried-forward candles (verified on 2024: 441,810 padded rows vs 355,892 real; the closed Sat-17:00→Sun-17:00 NY day arrives as 100% flat filler, which would fabricate a degenerate PDH=PDL for Mondays). The lab therefore downloads with `-v true`, keeps only volume>0 bars, and REFUSES padded input. No padding or interpolation anywhere; sessions <500 bars are skipped entirely rather than papered over.

**D19.** R accounting for the split: R = 0.8·R(T1 piece) + 0.2·R(runner piece), each piece paying the full per-unit cost.

**D20.** Executor invariants are asserted in `--selftest` (same-bar −1R, split accounting, arming/reset, BE-from-next-bar, long mirror) and swing availability arrays are asserted causal at load (avail > pivot index).

## 6. Baseline results — `Qclose-Srecent-T1m1k5-Rsess-A3`

11131 trades over 2008–2026 (2026 through 07-21). All figures in R; risk includes the $0.23 cost.

| metric | value |
|---|---|
| n trades | 11131 |
| win rate (R>0) | 20.1% |
| avg R | -0.1677 |
| median R | -1.0000 |
| net R | -1866.3 |
| profit factor | 0.790 |
| max drawdown | -1928.4R |
| longest losing streak | 53 |
| T1 hit rate | 18.9% |
| avg RR banked at T1 (hit trades) | 3.34R |
| swing→3R fallback share | 0.8% |
| train ≤2023 | -1593.1R net (avg -0.1663) |
| holdout ≥2024 | -273.1R net (avg -0.1762) |
| long / short | 5054 tr -699.7R / 6077 tr -1166.5R |
| attempts 1/2/3 | 4051 tr -485.0R / 3687 tr -684.8R / 3393 tr -696.5R |
| entry buckets | Asia 17–01: 4568 tr -745.8R · London 02–07: 2993 tr -749.4R · NY 08–16: 3570 tr -371.0R |

**Cost stress (full re-simulation at every level, including the frictionless attribution runs):**

| cost | avg R | net R | train | holdout |
|---|---|---|---|---|
| 0× (frictionless) | +0.2091 | +2327.9 | +2354.4 | -26.5 |
| 0.5× ($0.115) | -0.0314 | -349.5 | -179.6 | -169.9 |
| 1× ($0.23) | -0.1677 | -1866.3 | -1593.1 | -273.1 |
| 2× ($0.46) | -0.3358 | -3737.2 | | -430.7 |
| 3× ($0.69) | -0.4390 | -4885.9 | | |

The frictionless run is the tell: +0.209R/trade gross, but +2354.4R of it sits in the train era and the ≥2024 holdout is -26.5R before ANY cost. Break-even all-in cost ≈ $0.10/oz (interpolated) — half the house cost and ~a fifth of Dukascopy's measured median spread.

Conservatism bound: 1521 trades (13.7%) are same-bar instant stop-outs created by the worst-case fill-ordering rule (D6); treating every one as a free scratch instead would still leave net -345.3R at 1× cost — the conservative executor is not what kills this.

Independent audit: 400 randomly sampled baseline trades re-derived structurally from raw bars (PDH/PDL, signal-candle qualification, no missed trigger/invalidation, entry/SL/risk arithmetic, fractal-T1 confirmed-before-entry and most-recent selection, exit touches) — **0 violations**.

**Iron gate: reject** — failed: avg>=0.05,train+,holdout+,2x_cost_avg>0 (n≥80, avg≥0.05R, train>0, holdout>0, 2×-cost avg>0).

**Per-year net R (baseline):**

| year | net R | | year | net R |
|---|---|---|---|---|
| 2008 | -43.1 | | 2018 | -161.2 |
| 2009 | -165.5 | | 2019 | -269.2 |
| 2010 | -83.4 | | 2020 | -69.0 |
| 2011 | -31.6 | | 2021 | -97.5 |
| 2012 | +0.4 | | 2022 | -98.2 |
| 2013 | +77.4 | | 2023 | -197.9 |
| 2014 | -75.3 | | 2024 | -93.8 |
| 2015 | -94.9 | | 2025 | -155.1 |
| 2016 | -121.4 | | 2026 | -24.3 |
| 2017 | -162.7 | |  | |

**Realized-R distribution:** p10 -1.00 · p25 -1.00 · median -1.00 · p75 -1.00 · p90 +2.31 · max +38.84; share ≥2R 11.2%, ≥3R 7.8%, ≥5R 3.7%.

**Entry hour (NY) breakdown:**

| NY hour | n | net R | | NY hour | n | net R |
|---|---|---|---|---|---|---|
| 00 | 338 | -151.0 | | 12 | 225 | -0.4 |
| 01 | 406 | -169.0 | | 13 | 182 | -75.1 |
| 02 | 625 | -234.9 | | 14 | 255 | -68.4 |
| 03 | 698 | -67.5 | | 15 | 142 | -49.8 |
| 04 | 569 | -145.9 | | 16 | 42 | +1.0 |
| 05 | 364 | -138.6 | | 17 | 44 | +9.0 |
| 06 | 345 | -78.8 | | 18 | 871 | +57.1 |
| 07 | 392 | -83.7 | | 19 | 550 | -112.8 |
| 08 | 942 | -76.1 | | 20 | 787 | -141.4 |
| 09 | 723 | -1.0 | | 21 | 802 | -138.7 |
| 10 | 676 | -96.9 | | 22 | 459 | -99.4 |
| 11 | 383 | -4.3 | | 23 | 311 | +0.5 |

**Exit reasons:**

| reason | n | share | net R |
|---|---|---|---|
| sl | 8872 | 79.7% | -8901.8 |
| runner_stop | 1407 | 12.6% | +2719.9 |
| sessend_runner | 697 | 6.3% | +3957.3 |
| sessend_pre_t1 | 155 | 1.4% | +358.4 |

**MFE / CTC evaluation** (baseline books 80% at T1 and only then moves the runner stop to BE — no BE move before T1, as the brief pins; these stats let the close-to-close framing be judged):

- CTC win rate (T1 banked, or R>0): **20.2%** vs raw win rate 20.1%; 1375 trades banked T1 then scratched the runner at BE (wins under CTC).
- 'BE-scratch' candidates a 1R-BE rule would rescue: **2845** trades (25.6% of all) reached ≥+1R MFE without hitting T1 and still finished ≤−0.9R. Reported, not modeled — the baseline is pinned.
- MFE of eventual losers (R<0): median +0.56R, p75 +1.28R, p90 +2.36R — 32.2% of losers saw ≥+1R at some point.
- Risk per trade (entry−SL incl. cost): median $0.85, p90 $2.20, max $46.27.

## 7. Variants matrix (96 cells — `variants_matrix.csv`)

Executor, costs and gate identical everywhere; only the five declared dimensions move. Top 12 and bottom 5 by net R:

| variant | n | wr | avg R | net R | train | holdout | 2× avg | gate |
|---|---|---|---|---|---|---|---|---|
| Qfullcandle-Srecent-T1m15k2-Rsess-A1 | 4106 | 13.0% | -0.074 | -302.8 | -233.6 | -69.2 | -0.258 | reject |
| Qfullcandle-Sfirst-T1m15k2-Rsess-A1 | 4105 | 13.4% | -0.078 | -319.8 | -241.8 | -78.0 | -0.256 | reject |
| Qclose-Sfirst-T1m15k2-Rsess-A1 | 4132 | 13.6% | -0.086 | -355.3 | -251.4 | -104.0 | -0.262 | reject |
| Qclose-Srecent-T1m15k2-Rsess-A1 | 4134 | 12.9% | -0.089 | -367.6 | -264.2 | -103.3 | -0.270 | reject |
| Qfullcandle-Sfirst-T1m15k2-Rnone-A1 | 4177 | 13.4% | -0.094 | -394.1 | -299.1 | -95.0 | -0.270 | reject |
| Qfullcandle-Srecent-T1m15k2-Rnone-A1 | 4177 | 12.9% | -0.096 | -399.2 | -313.4 | -85.8 | -0.275 | reject |
| Qfullcandle-Sfirst-T1m15k2-Rchand-A1 | 4173 | 13.4% | -0.097 | -404.2 | -312.8 | -91.4 | -0.272 | reject |
| Qfullcandle-Srecent-T1m15k2-Rchand-A1 | 4173 | 12.9% | -0.097 | -404.4 | -322.3 | -82.1 | -0.276 | reject |
| Qclose-Sfirst-T1m15k2-Rnone-A1 | 4209 | 13.6% | -0.097 | -408.4 | -298.0 | -110.3 | -0.271 | reject |
| Qfullcandle-Sfirst-T1rr5-Rsess-A1 | 4105 | 16.4% | -0.100 | -412.1 | -341.2 | -70.9 | -0.253 | reject |
| Qclose-Sfirst-T1m15k2-Rchand-A1 | 4205 | 13.6% | -0.100 | -420.2 | -312.0 | -108.2 | -0.273 | reject |
| Qfullcandle-Srecent-T1rr5-Rsess-A1 | 4106 | 16.0% | -0.103 | -422.9 | -360.2 | -62.7 | -0.255 | reject |
| Qclose-Srecent-T1m1k5-Rnone-A3 | 11700 | 20.3% | -0.182 | -2133.0 | -1811.9 | -321.1 | -0.349 | reject |
| Qclose-Srecent-T1m1k5-Rchand-A3 | 11673 | 20.2% | -0.185 | -2165.0 | -1835.2 | -329.8 | -0.351 | reject |
| Qclose-Srecent-T1rr3-Rchand-A3 | 11765 | 22.2% | -0.185 | -2172.5 | -1908.8 | -263.7 | -0.343 | reject |
| Qfullcandle-Srecent-T1rr3-Rnone-A3 | 11741 | 22.1% | -0.186 | -2180.9 | -1976.6 | -204.3 | -0.340 | reject |
| Qclose-Srecent-T1rr3-Rnone-A3 | 11833 | 22.0% | -0.192 | -2275.2 | -2028.7 | -246.4 | -0.347 | reject |

**Dimension marginals** (mean net R across all cells sharing the option):

| dimension | options (mean net R) |
|---|---|
| qual | close: -1205.5 · fullcandle: -1104.7 |
| sel | recent: -1204.1 · first: -1106.1 |
| t1_mode | m1k5: -1231.2 · m15k2: -931.5 · rr3: -1351.1 · rr5: -1106.7 |
| runner | sess: -1027.6 · none: -1220.4 · chand: -1217.3 |
| max_attempts | 1: -545.3 · 3: -1764.9 |

**Gate outcome: 0/96 variants pass the iron gate.**

Reading the matrix: (i) nothing is close to positive — the best of 96 cells (`Qfullcandle-Srecent-T1m15k2-Rsess-A1`) still loses 302.8R over 18.5 years at -0.074R/trade, the worst (`Qclose-Srecent-T1rr3-Rnone-A3`) loses 2275.2R, and every cell fails train, holdout and 2×-cost simultaneously. (ii) The marginals all point the same way: coarser/closer M15-swing targets beat M1-swing and fixed-RR targets (mean avg-R −0.112 vs −0.150 / −0.172 for rr3); keeping the session-end runner beats cashing 100% at T1 and beats the chandelier (the session-end runner leg, +5.7R average on baseline, is the single most profitable component of the whole system); 1 attempt loses less than 3 (attempts 2–3 run −0.19/−0.21R/trade on baseline vs −0.12 for attempt 1); the qualifier and selection dimensions are nearly inert. (iii) i.e. the gradient runs AWAY from the video's aggressive re-entry / big-RR formulation — trade less, target closer, keep the tail — and even the least-bad corner of the grid is a clear loser after costs.

## 8. The video's claims, tested

- **“Win rate ~50%”** — baseline raw win rate is **20.1%** (CTC framing 20.2%); across all 96 variants win rate spans 12.1%–22.7%. NOT SUPPORTED for the mechanical rule set: 79.7% of baseline trades stop out. With a one-candle stop under a several-R target the hit rate is capped far below 50% by construction; ~50% is only conceivable with discretionary targets well inside 1R — which contradicts the 1:5–1:10 claim.
- **“RR often 1:5 to 1:10”** — with SL at the signal candle's extreme and T1 at the most recent M1 swing, the PLANNED T1 multiple is median 3.81R (p90 8.35R); 33.4% of trades offer ≥5R to T1 and 5.6% offer ≥10R. REALIZED: 3.7% of trades finish ≥+5R and 0.7% ≥+10R (best +38.8R). HALF TRUE, in the direction that doesn't pay: the offered geometry is real and banked winners average 3.34R at T1, but the video quotes the OFFER, not the expectancy — paying −1R 79.7% of the time for that offer is a losing exchange at every cost level tested.

## 9. Honest conclusion

**Reject: the edge does not survive costs — and in the holdout it does not exist even before costs.**

- At the house $0.23 all-in cost, ALL 96 variants are negative on train AND holdout (best cell -0.074R/trade; holdout nets span -329.8R to -62.7R). The iron gate passes 0/96; 2×/3× cost stress only deepens it.
- Cost attribution (full re-sims): frictionless baseline makes +0.209R/trade (+2327.9R) — but the train era (≤2023) holds +2354.4R of it while the ≥2024 holdout is -26.5R EVEN AT ZERO COST. Break-even all-in cost ≈ $0.10/oz (interpolated 0×→0.5×) — well under the house $0.23, and a fraction of the measured 2024–26 Dukascopy median spread ($0.52). With a median risk of $0.85/oz (one M1 signal candle + cost), every round trip burns ~27% of a stop: at minute granularity this rule set is a cost machine by construction.
- The conservative executor is not the verdict's source: even scratching every same-bar instant stop-out (13.7% of trades, the worst-case fill-ordering rule) leaves -345.3R at 1× cost.
- The simulation is faithful: 400 randomly sampled trades were re-derived independently from raw bars (PDH/PDL, signal-candle qualification, trigger/invalidations, fractal-T1 confirmation, exits) with 0 violations; the TZ passed the NFP 08:30 fingerprint in both DST regimes; padded feed data was detected and refused.
- What is genuinely there: PDH/PDL sweeps do reverse into multi-R moves 18.9% of the time, and the session-end runner captures real tails. A follow-up worth running is the same setup built on M15 structure with closer targets and one attempt — the least-bad corner here — but nothing in this grid is deployable, and the decay of even the frictionless edge after 2023 says minute-level sweep-reversal on gold has been arbitraged away.

---
*Repro: `python3 download_data.py && python3 liquidity_grab_lab.py` (numba JIT; outputs `variants_matrix.csv`, `baseline_tradebook.csv`, this report). Nothing in this file is hand-entered.*
