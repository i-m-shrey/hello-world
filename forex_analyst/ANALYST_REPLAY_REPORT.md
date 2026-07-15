# ANALYST REPLAY REPORT — mechanical core, walked forward

Scored event-x-asset rows: **18138** (distinct releases: 4532) | span 2007-01-17 -> 2026-07-01 | train < 2024-01-01 <= holdout

Policy: at T+5min after a red release, query the point-in-time precedent cell (asset, family, surprise bucket, reaction direction). FOLLOW the reaction when prior continuation >= threshold (n>=20); FADE when prior continuation <= 1-threshold; else NONE. Exit at horizon close. Costs: real all-in round-trip (live_signals.FX_SPREADS), in ATR units of each event's ATR.

NOT modeled: the LLM layer (no CLI here) and intrabar stops (horizon-close exits; MAE tail reported instead). The always-NONE baseline is 0.00 by construction.

## VERDICT (read this first)

- **No policy cell passes the iron rule.** Across follow/fade x {15m,1h,4h} x {0.60,0.65,0.70}, not one is meaningfully positive in BOTH train (<=2023) and holdout (>=2024) after real costs; the few positive splits flip sign in the other split (noise).
- **The precedent probabilities are not calibrated**: cells stating 0.70+ continue ~0.49-0.63 of the time; after Beta(10,10) shrinkage the prediction-vs-realization curve is flat (see the shrinkage test) — cell differences are sampling noise.
- **Costs decide everything**: the ungated baseline loses -0.13..-0.29 ATR/trade purely to the spread+commission.
- Consequence for the ANALYST: 'stand aside' is not just the default, it is nearly always the mathematically right answer. Any live edge must come from LLM context judgment BEYOND these keys, and it starts ~0.15 ATR/trade behind on costs. The demo containment and calibration-first review are exactly right; expectations of promotion should be low.

## Baseline — follow every reaction, no gates (this must be ~0/negative)

| horizon | split | n | avg ATR | total ATR | win% |
|---|---|---|---|---|---|
| 15m | train | 15611 | -0.149 | -2320.5 | 0.442 |
| 15m | holdout | 2527 | -0.218 | -551.8 | 0.421 |
| 1h | train | 15611 | -0.134 | -2095.7 | 0.463 |
| 1h | holdout | 2527 | -0.194 | -489.7 | 0.461 |
| 4h | train | 15611 | -0.259 | -4036.0 | 0.475 |
| 4h | holdout | 2527 | -0.285 | -721.1 | 0.485 |

## Gated policies (the ANALYST's mechanical core)

| mode | horizon | thr | split | trades | avg ATR | total ATR | win% | avg@2x cost | avg@3x cost |
|---|---|---|---|---|---|---|---|---|---|
| follow | 15m | 0.60 | train | 525 | -0.014 | -7.2 | 0.478 | -0.153 | -0.292 |
| follow | 15m | 0.60 | holdout | 173 | 0.002 | 0.3 | 0.509 | -0.135 | -0.271 |
| follow | 15m | 0.65 | train | 296 | -0.024 | -7.0 | 0.480 | -0.161 | -0.298 |
| follow | 15m | 0.65 | holdout | 71 | -0.002 | -0.1 | 0.549 | -0.154 | -0.306 |
| follow | 15m | 0.70 | train | 127 | 0.069 | 8.8 | 0.520 | -0.064 | -0.197 |
| follow | 15m | 0.70 | holdout | 19 | -0.183 | -3.5 | 0.632 | -0.347 | -0.510 |
| follow | 1h | 0.60 | train | 444 | -0.079 | -34.9 | 0.480 | -0.219 | -0.359 |
| follow | 1h | 0.60 | holdout | 158 | -0.132 | -20.8 | 0.500 | -0.266 | -0.400 |
| follow | 1h | 0.65 | train | 213 | -0.272 | -58.0 | 0.460 | -0.428 | -0.583 |
| follow | 1h | 0.65 | holdout | 58 | -0.377 | -21.9 | 0.500 | -0.519 | -0.660 |
| follow | 1h | 0.70 | train | 55 | -0.325 | -17.9 | 0.382 | -0.451 | -0.576 |
| follow | 1h | 0.70 | holdout | 23 | 0.972 | 22.3 | 0.696 | 0.857 | 0.743 |
| follow | 4h | 0.60 | train | 407 | 0.074 | 30.1 | 0.504 | -0.053 | -0.180 |
| follow | 4h | 0.60 | holdout | 139 | 0.452 | 62.8 | 0.525 | 0.314 | 0.176 |
| follow | 4h | 0.65 | train | 140 | -0.425 | -59.5 | 0.436 | -0.560 | -0.695 |
| follow | 4h | 0.65 | holdout | 53 | 1.319 | 69.9 | 0.585 | 1.185 | 1.050 |
| follow | 4h | 0.70 | train | 45 | -0.527 | -23.7 | 0.422 | -0.657 | -0.786 |
| follow | 4h | 0.70 | holdout | 14 | 1.414 | 19.8 | 0.500 | 1.312 | 1.210 |
| fade | 15m | 0.60 | train | 773 | -0.004 | -2.9 | 0.519 | -0.149 | -0.294 |
| fade | 15m | 0.60 | holdout | 237 | -0.043 | -10.2 | 0.527 | -0.194 | -0.344 |
| fade | 15m | 0.65 | train | 479 | 0.014 | 6.9 | 0.520 | -0.128 | -0.271 |
| fade | 15m | 0.65 | holdout | 81 | 0.278 | 22.5 | 0.568 | 0.123 | -0.033 |
| fade | 15m | 0.70 | train | 189 | -0.121 | -22.9 | 0.513 | -0.269 | -0.416 |
| fade | 15m | 0.70 | holdout | 23 | 0.493 | 11.3 | 0.783 | 0.315 | 0.137 |
| fade | 1h | 0.60 | train | 625 | -0.134 | -83.5 | 0.488 | -0.278 | -0.422 |
| fade | 1h | 0.60 | holdout | 182 | -0.203 | -36.9 | 0.527 | -0.347 | -0.490 |
| fade | 1h | 0.65 | train | 279 | -0.123 | -34.2 | 0.480 | -0.257 | -0.391 |
| fade | 1h | 0.65 | holdout | 56 | -0.012 | -0.7 | 0.518 | -0.157 | -0.301 |
| fade | 1h | 0.70 | train | 69 | -0.539 | -37.2 | 0.406 | -0.666 | -0.793 |
| fade | 1h | 0.70 | holdout | 16 | -1.278 | -20.4 | 0.500 | -1.459 | -1.640 |
| fade | 4h | 0.60 | train | 619 | 0.197 | 122.2 | 0.520 | 0.056 | -0.086 |
| fade | 4h | 0.60 | holdout | 199 | -0.416 | -82.9 | 0.472 | -0.568 | -0.720 |
| fade | 4h | 0.65 | train | 233 | 0.240 | 56.0 | 0.519 | 0.099 | -0.042 |
| fade | 4h | 0.65 | holdout | 72 | -0.869 | -62.6 | 0.431 | -1.019 | -1.170 |
| fade | 4h | 0.70 | train | 75 | -0.415 | -31.1 | 0.440 | -0.561 | -0.708 |
| fade | 4h | 0.70 | holdout | 7 | 0.463 | 3.2 | 0.429 | 0.282 | 0.101 |

## Calibration — is the precedent's stated probability real?

For every taken trade, 'stated' = the point-in-time continuation rate of the cited cell; 'realized' = the fraction that actually continued (before costs). A calibrated system sits near the diagonal.


### follow (thr 0.60 pool, all horizons)

| conf bucket | n | stated | realized (pre-cost) | net win% | avg pnl ATR |
|---|---|---|---|---|---|
| **train** | | | | | |
| 0.60-0.65 | 727 | 0.62 | 0.535 | 0.506 | +0.155 |
| 0.65-0.70 | 422 | 0.68 | 0.498 | 0.462 | -0.217 |
| 0.70-1.01 | 227 | 0.85 | 0.493 | 0.467 | -0.145 |
| **holdout** | | | | | |
| 0.60-0.65 | 288 | 0.62 | 0.528 | 0.490 | -0.020 |
| 0.65-0.70 | 126 | 0.68 | 0.548 | 0.508 | +0.074 |
| 0.70-1.01 | 56 | 0.85 | 0.625 | 0.625 | +0.690 |

### fade (thr 0.60 pool, all horizons)

| conf bucket | n | stated | realized (pre-cost) | net win% | avg pnl ATR |
|---|---|---|---|---|---|
| **train** | | | | | |
| 0.60-0.65 | 1026 | 0.62 | 0.529 | 0.511 | +0.007 |
| 0.65-0.70 | 658 | 0.68 | 0.555 | 0.526 | +0.182 |
| 0.70-1.01 | 333 | 0.85 | 0.498 | 0.474 | -0.274 |
| **holdout** | | | | | |
| 0.60-0.65 | 409 | 0.62 | 0.535 | 0.511 | -0.218 |
| 0.65-0.70 | 163 | 0.68 | 0.472 | 0.472 | -0.214 |
| 0.70-1.01 | 46 | 0.85 | 0.630 | 0.630 | -0.128 |

## Where the edge lives (per family x asset, follow thr 0.60, 1h)

| mode | family | asset | n | avg ATR | total ATR | win% |
|---|---|---|---|---|---|---|
| fade | CPI_YY | GBPUSD | 80 | +0.309 | +24.8 | 0.525 |
| fade | PPI_MM | USDCHF | 23 | +0.899 | +20.7 | 0.696 |
| follow | RETAIL | XAUUSD | 71 | +0.248 | +17.6 | 0.535 |
| fade | PMI_FLASH | EURUSD | 23 | +0.604 | +13.9 | 0.522 |
| follow | ISM_MFG | GBPUSD | 11 | +1.228 | +13.5 | 0.727 |
| fade | CPI_YY | USDCAD | 53 | +0.202 | +10.7 | 0.528 |
| follow | RETAIL | USDCAD | 43 | +0.214 | +9.2 | 0.512 |
| fade | RETAIL | GBPUSD | 17 | +0.452 | +7.7 | 0.588 |
| fade | NFP | XAUUSD | 11 | +0.648 | +7.1 | 0.727 |
| follow | PPI_MM | GBPUSD | 23 | +0.266 | +6.1 | 0.609 |
| fade | RETAIL | USDCAD | 48 | +0.111 | +5.3 | 0.646 |
| follow | CLAIMS | GBPUSD | 14 | +0.249 | +3.5 | 0.429 |
| fade | CLAIMS | USDCAD | 28 | +0.107 | +3.0 | 0.571 |
| fade | CPI_MM | USDCAD | 42 | +0.069 | +2.9 | 0.571 |
| fade | UNRATE | USDCAD | 13 | +0.119 | +1.6 | 0.538 |
| follow | PPI_MM | EURUSD | 19 | +0.080 | +1.5 | 0.579 |
| fade | ISM_MFG | XAUUSD | 22 | +0.059 | +1.3 | 0.591 |
| fade | CLAIMS | GBPUSD | 43 | +0.003 | +0.1 | 0.512 |
| follow | CPI_MM | USDCAD | 11 | -0.170 | -1.9 | 0.455 |
| fade | ISM_SVC | USDCHF | 16 | -0.145 | -2.3 | 0.375 |
| follow | PPI_MM | USDCAD | 14 | -0.190 | -2.7 | 0.500 |
| follow | PMI_FLASH | EURUSD | 83 | -0.039 | -3.3 | 0.518 |
| follow | CPI_YY | XAUUSD | 13 | -0.384 | -5.0 | 0.385 |
| follow | CLAIMS | EURUSD | 21 | -0.252 | -5.3 | 0.333 |
| fade | CPI_MM | GBPUSD | 23 | -0.241 | -5.5 | 0.435 |
| follow | CONF | GBPUSD | 13 | -0.510 | -6.6 | 0.538 |
| follow | RETAIL | GBPUSD | 74 | -0.114 | -8.4 | 0.473 |
| follow | CPI_YY | GBPUSD | 11 | -0.908 | -10.0 | 0.273 |
| follow | CPI_YY | EURUSD | 13 | -0.794 | -10.3 | 0.615 |
| fade | ISM_SVC | EURUSD | 21 | -0.644 | -13.5 | 0.476 |
| follow | CLAIMS | XAUUSD | 10 | -1.694 | -16.9 | 0.300 |
| fade | RETAIL | USDCHF | 29 | -0.620 | -18.0 | 0.379 |
| fade | CLAIMS | XAUUSD | 19 | -0.964 | -18.3 | 0.368 |
| fade | CPI_YY | USDCHF | 42 | -0.452 | -19.0 | 0.476 |
| fade | PPI_MM | XAUUSD | 11 | -1.735 | -19.1 | 0.364 |
| follow | RETAIL | USDCHF | 15 | -1.448 | -21.7 | 0.267 |
| fade | CPI_MM | XAUUSD | 32 | -0.941 | -30.1 | 0.500 |
| follow | RETAIL | EURUSD | 56 | -0.592 | -33.1 | 0.429 |
| fade | CPI_YY | XAUUSD | 44 | -1.112 | -48.9 | 0.364 |

## Tail exposure (MAE of taken trades, follow+fade thr 0.60, 1h)

- median adverse: -4.57 ATR | p90: -14.41 | worst: -59.44 ATR (24h window). The live bot's broker-side SL caps this; the replay's horizon exit does not.


## Shrinkage test — do the cell probabilities predict at all?

Point-in-time cell continuation rates shrunk with a Beta(10,10) prior, bucketed by prediction, versus realized continuation (1h horizon, all events with n>=20):

| split | shrunk pred bucket | n | mean pred | realized |
|---|---|---|---|---|
| train | 0.00-0.42 | 335 | 0.395 | 0.490 |
| train | 0.42-0.46 | 568 | 0.442 | 0.496 |
| train | 0.46-0.50 | 869 | 0.479 | 0.517 |
| train | 0.50-0.54 | 1007 | 0.515 | 0.468 |
| train | 0.54-0.58 | 369 | 0.556 | 0.461 |
| train | 0.58-1.00 | 265 | 0.604 | 0.513 |
| holdout | 0.00-0.42 | 95 | 0.398 | 0.463 |
| holdout | 0.42-0.46 | 212 | 0.440 | 0.448 |
| holdout | 0.46-0.50 | 299 | 0.479 | 0.445 |
| holdout | 0.50-0.54 | 313 | 0.516 | 0.508 |
| holdout | 0.54-0.58 | 148 | 0.559 | 0.514 |
| holdout | 0.58-1.00 | 93 | 0.604 | 0.527 |

Reading: realized continuation stays pinned near the ~0.47-0.53 base rate whatever the cell predicts — even after shrinkage there is no monotone relation in train and only a weak one in holdout. The per-cell differences are sampling noise, not signal.


## Expected live activity (follow+fade, thr 0.65, 1h)

- 606 qualifying trades over 19.5 years = ~2.6 trades/month across all symbols. Standing aside is, as designed, the usual answer.

