# TIMEZONE AUDIT — deployed-strategy exposure & TZ-correct re-runs

Generated 2026-07-15 14:53Z. Live execution is unaffected (the bot trades the broker feed and self-verifies its TZ at startup); this audit is about whether each VALIDATION still stands on correctly-timed history. `verify_*.py` cannot catch this class of bug — they prove live==backtest on the SAME (mis-parsed) frame.

## Exposure matrix (all 23 live instances)

| instance | validation data | file TZ-buggy? | clock-conditioned? | exposed? |
|---|---|---|---|---|
| XAUUSD_S5 | XAU_5m (GMT+2 parse) | YES (+1h summer) | blocked_hours (7,8,20-23) | **YES** |
| XAUUSD_S6 | XAU_5m (GMT+2 parse) | YES (+1h summer) | blocked_hours (3-7,9) | **YES** |
| XAUUSD_S4 | XAU_5m (GMT+2 parse) | YES (+1h summer) | session boxes 06-12 | **YES** |
| XAUUSD_S3LO | XAU_5m (GMT+2 parse) | YES (+1h summer) | NY-AM session 09:00-11:55 | **YES** |
| EURUSD_BOLL15 | EURUSD15_deep (UTC parse) | YES (+1h summer) | hours 14-24 | **YES** (benched) |
| GBPUSD_BOLL15 | GBPUSD15_deep (UTC parse) | YES (+1h summer) | hours 14-24 | **YES** (benched) |
| USDCHF_BOLL15 | USDCHF15_deep (UTC parse) | YES (+1h summer) | hours 14-24 | **YES** (benched) |
| XAUUSD_H1A | XAU_5m->H1/H4 (GMT+2) | YES (+1h summer) | H4-bias bins (1h!=4h multiple) | partial — H4 bins |
| XAUUSD_MACROSS | XAU_5m->H1/H4 (GMT+2) | YES (+1h summer) | H4-bias gate | partial — H4 bins |
| XAUUSD_CRASH | XAU_5m->H1/H4 (GMT+2) | YES (+1h summer) | H4-bias gate | partial — H4 bins |
| XAUUSD_STRAD | XAU_5m->H1 (GMT+2) | YES (+1h summer) | no (structure; day cap only) | no — re-run anyway |
| XAUUSD_DONCH | XAU_5m->H1 (GMT+2) | YES (+1h summer) | no (structure; day cap only) | no — re-run anyway |
| XAUUSD_BOS | XAU_5m->H1 (GMT+2) | YES (+1h summer) | no (structure; day cap only) | no (class-covered) |
| EURUSD_E | EURUSD60 (UTC) | no — true UTC | session hours | no |
| GBPUSD_E | GBPUSD60 (UTC) | no — true UTC | session hours | no |
| USDCAD_A | USDCAD60 (UTC) | no — true UTC | no | no |
| USDCHF_A | USDCHF60 (UTC) | no — true UTC | no | no |
| GBPUSD_P1 | GBPUSD60 (UTC) | no — true UTC | no | no |
| EURUSD_P1_30 | EURUSD30 (UTC) | no — true UTC | no | no |
| EURUSD_BOLL30 | EURUSD30 (UTC) | no — true UTC | hours 14-24 | no (data correct) |
| USDCHF_RSI30 | USDCHF30 (UTC) | no — true UTC | hours 14-24 | no (data correct) |
| GBPUSD_AVWAP | GBPUSD60 (UTC) | no — true UTC | hours + NY-day anchor | no (data correct) |
| SPX500/GER40/US30/JPN225/HK50 trend | IDX M15->H1 (UTC parse) | YES (server time) | no (structure; whole-hour shift) | no — labels only |

## Re-runs — original lab code, original (buggy) parse vs corrected parse

Columns: n / net R / train R (<=2023) / holdout R (>=2024). The 'old' run must reproduce the official number (harness fidelity), then the ONLY change is the timestamp parse.

### Gold M5 session strategies

| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |
|---|---|---|---|---|---|---|---|---|
| S4 (NY manipulation) | 23 | +7.0 | +2.0 | +5.0 | 9 | +3.0 | -1.0 | +4.0 | (official {'trades': 23, 'net_r': 7.0})
| S6 (HF displacement) | 1351 | -8.0 | -20.7 | +12.8 | 1423 | -72.4 | -71.3 | -1.1 | (official {'trades': 1351, 'net_r': -8.0})
| S5 (engine labels) | 769 | +28.3 | +15.5 | +12.7 | 745 | +27.1 | +16.3 | +10.8 |
| S3 (engine labels) | 655 | -6.2 | -5.8 | -0.4 | 615 | -6.8 | -5.1 | -1.7 |

### Gold H1 family (H4-bias bins / day-cap exposure)

| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |
|---|---|---|---|---|---|---|---|---|
| H4-bias agreement old-vs-fixed (DST months) | | 94.2% of H1 bars agree | | | | | | |
| H1A (official +23.8R) | 235 | +24.2 | +16.8 | +7.5 | 233 | +25.5 | +18.0 | +7.5 |
| MACROSS H4-gated long (official +49.8R) | 454 | +49.8 | +35.0 | +14.7 | 439 | +54.5 | +37.8 | +16.7 |
| DONCH N96 long (official +95.4R) | 825 | +95.4 | +65.4 | +30.0 | 825 | +95.4 | +65.4 | +30.0 |
| CRASH short (official +63.1R) | 596 | +63.1 | +75.1 | -12.1 | 610 | +46.1 | +60.1 | -14.1 |
| STRAD W24 edge M2 (official +43.6R) | 555 | +82.4 | +77.0 | +5.5 | 556 | +81.4 | +77.0 | +4.5 |

### S6R — the deployed rehab cell (s6_rehab_lab pipeline, disp 2.4x, bias5)

| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |
|---|---|---|---|---|---|---|---|---|
| S6R deployed (bias5 + 2.4x disp) | 596 | +54.6 | +42.2 | +12.4 | 660 | +30.5 | +17.8 | +12.7 |

### BOLL15 trio (deep-file NY+5 bug; BENCHED July 14 — audit anyway)

| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |
|---|---|---|---|---|---|---|---|---|
| EURUSD-BOLL15 long | 2954 | +206.1 | +172.4 | +33.7 | 3037 | +170.3 | +163.8 | +6.5 |
| GBPUSD-BOLL15 both | 5746 | +409.1 | +362.1 | +46.9 | 5965 | +416.1 | +377.0 | +39.2 |
| USDCHF-BOLL15 both | 5178 | +363.5 | +307.9 | +55.6 | 5386 | +303.2 | +306.6 | -3.3 |


## Anchor caveats (honesty notes)

- **S5/S3 absolute levels**: the official S5 (+75.9R) / S3LO (+26.6R) numbers were
  validated on the LuxAlgo-label candles; the audit runs both parses through the
  smc_engine-label pipeline (rebaseline_engine flow), where S5 shows +28.3R and S3
  shows -6.2R BEFORE any TZ change. The TZ deltas (S5 -1.2R, S3 -0.6R) are small —
  but the S3 label-source sensitivity (Lux +26.6 vs engine -6.2) is its own
  validation question, independent of timezones, and deserves a follow-up since
  the LIVE bot runs engine labels.
- **STRAD anchor**: this audit's old-parse run of straddle_lab.straddle(W24, edge,
  M2) gives +82.4R vs the official +43.6R (the official straddle validation used
  a different cost/window convention inside the lab's main()). The old-vs-fixed
  DELTA (-1.0R) is the TZ-relevant result; the absolute level is not re-stated.

## VERDICTS

| instance | TZ-correct verdict |
|---|---|
| XAUUSD_S4 | **VOID — edge not confirmed.** 23 -> 9 trades, +7.0 -> +3.0R, train -1.0R. The session-boxed pattern as validated does not exist on true NY time. Recommend: disable pending a fresh validation on corrected data. |
| XAUUSD_S6 (S6R) | **WEAKENED ~44%.** +54.6R (tr +42.2/ho +12.4) -> +30.5R (tr +17.8/ho +12.7). Still positive both splits, but the validated margin was inflated by the summer shift. Recommend: keep enabled at reduced expectation, or re-tune blocked_hours on corrected data via the normal pipeline. |
| XAUUSD_S5 | SURVIVES (+28.3 -> +27.1R engine-label pipeline, both splits +). |
| XAUUSD_S3LO | TZ-delta negligible (-0.6R) — but see the label-source caveat above. |
| XAUUSD_H1A | SURVIVES (+24.2 -> +25.5R). H4-bias agreement 94.2% in DST months. |
| XAUUSD_MACROSS | SURVIVES (+49.8 -> +54.5R — slightly better on true time). |
| XAUUSD_DONCH | IMMUNE (byte-identical +95.4R — structural, as predicted). |
| XAUUSD_STRAD | IMMUNE (delta -1.0R). |
| XAUUSD_CRASH | WEAKENED (+63.1 -> +46.1R; holdout was already negative by design — insurance). Character unchanged, expectation lower. |
| EURUSD_BOLL15 | Benched — rightly. Holdout +33.7 -> **+6.5R** on corrected time: the validated holdout margin was mostly the TZ artifact. |
| GBPUSD_BOLL15 | Benched, but the edge is REAL on corrected time (+409 -> +416R, ho +39.2). The strongest re-enable candidate of the trio. |
| USDCHF_BOLL15 | Benched — rightly. Holdout +55.6 -> **-3.3R** on corrected time: fails the house rule. Do not re-enable. |
| All FX 5/15/30/60m-validated instances | CLEAN — files fingerprinted true UTC. |
| Index trend family | CLEAN — structural; server-time labels shift whole hours only. |

**Bottom line: one deployed instance (S4) fails on corrected data, one (S6R) is
roughly half as strong as validated, CRASH is ~27% weaker; everything else
survives. The owner decides on S4/S6R — nothing here was changed in the live bot.**
