# PART B SLATE — new validated strategies per asset class (July 2026)

Method for every candidate: TZ-verified data, real all-in costs, train ≤2023 /
holdout ≥2024 both positive, 2×/3× cost stress, neighbor plateau, overlap vs the
deployed book. Full audit trail in `discovery_ledger.csv` (~200 cells this round).
Executor: next-open entry, stop-first collisions, live stop convention.

## DEPLOYABLE (gold — the fat-edge home delivers again)

### 1. XAUUSD DONCH-96 M30 + trail-4 exit — "the frequency engine"  → propose magic 53201
Same mechanism as the deployed H1 DONCH, one timeframe down, chandelier exit.
- n=1288 (2008–2026), **5.8 trades/mo**, WR 32.6%, avg-win +2.41R / avg-loss −0.89R (realized R:R 2.70)
- avg **+0.185R**, net +238.7R, train +164.7 / holdout +74.0, maxDD −29.6R, 16/19 years
- cost stress: 2× +0.145, 3× +0.107 — immune
- neighbors: 9/9 pass (N∈{64,96,128} × trail∈{3,4,5}), monotone in trail
- overlap vs deployed H1 DONCH96: daily-R corr +0.472, open-time 63% — related but additive
- lot 0.01 (MINLOT gold), equity gate = gold-trend ($250), verify plan: clone of
  `verify_donch_trail.py` with the M30 frame (signal set + trail path + reference n/net)

### 2. XAUUSD DONCH-96 H4 + trail-4 — "the big-leg catcher"  → propose magic 53301
- n=202, 0.9 trades/mo, WR 35.1%, avg-win +2.94R / avg-loss −0.84R (realized R:R 3.51)
- avg **+0.489R**, net +98.9R, train +49.4 / holdout +49.5 (perfectly balanced), maxDD −10.7R, 15/19 years
- cost stress: 2× +0.462, 3× +0.436 — the most cost-immune thing in the whole book
- neighbors: 8/9 pass (the N128×trail3 corner is train-flat), trail monotone
- overlap: daily-R corr vs deployed H1 DONCH +0.173 (open-time overlap is high because
  H4 holds are long — but the R stream is nearly independent); vs the M30 twin +0.077
- lot 0.01, gold-trend equity gate; same verify plan as above on the H4 frame

### 3. XAUUSD NY-session displacement continuation H1 (rr 2.5) — the session/structure slot  → propose magic 50201
Validated FX E-family mechanism ported to a trend asset: 6-bar consolidation ≤1.5·ATR,
displacement bar ≥1.2·ATR closing top-35%, 08:00–10:59 NY only, stop 1.5·ATR, TP 2.5R.
- n=196, 0.9 trades/mo, WR 36.2%, avg-win +2.39R / avg-loss −1.02R (realized R:R 2.35)
- avg **+0.217R**, net +42.5R, train +33.8 / holdout +8.8, maxDD −21.3R, 13/19 years
- cost stress: 2× +0.189, 3× +0.156 — immune; neighbors 5/5 pass
- overlap: corr vs deployed DONCH +0.107, vs M30 twin +0.104 — independent
- CAVEAT: holdout is thinner than the others and it's a conceptual cousin of S6R
  (displacement continuation); pre-deploy requirement = overlap check vs the S6R
  tradebook (its magic 60001) once copied to your machine. London session FAILED
  (−0.100 avg) — this is a NY-morning effect only, exactly like S3's window.

## EVIDENCE-GRADE (indices, 2022+ only — deployable at min-lot with that label)

| candidate | n | avg R | train | holdout | 2×/3× | note |
|---|---|---|---|---|---|---|
| GER40 DONCH-48 H4 trail4 → magic 56101 | 59 | +0.640 | +14.4 | +23.4 | +0.59/+0.54 | strongest; 3/5 yrs |
| US30 DONCH-96 H1 trail4 → magic 55801 | 146 | +0.319 | +18.8 | +27.8 | +0.29/+0.25 | 5/5 years positive |
| SPX500 DONCH-96 H1 trail3 | 183 | +0.165 | +18.7 | +11.5 | +0.08/+0.01 | 3×-fragile — watchlist |
| JPN225 (all variants) | — | — | train-neg | — | — | REJECT — bull-only artifact |
| HK50 (all variants) | — | — | train-neg | — | — | REJECT |

Four years of data is four years: these arm risk ~$2–9/trade at 0.01 lot and should
sit behind the existing index equity gates.

## HONEST NULLS (the classes you asked about that have nothing live-ready)

- **XAGUSD**: 15y true-UTC H1 retested at the house cost 0.03. H1 DONCH/VCX/short
  all fail cost stress; the ONLY passing cell is H4 DONCH-96 trail4 (avg +0.133,
  train +8.7 / holdout +11.9, 3× +0.016 — hairline). Verdict: **silver stays
  rejected** unless your spread audit measures all-in ≤0.03 during trading hours
  AND you accept a marginal edge. The 2016 law holds: costs eat silver.
- **FX pairs — no new instances.** Cross-pair replication of the validated families
  through the house's own machinery (run_A/run_E on live_signals, deployed configs,
  zero re-tuning): A-family on EURUSD/GBPUSD = noise (best +6.2R over 17 years);
  E-family on USDCHF/USDCAD = actively negative (−22 to −53R). Combined with the
  H4-fade nulls and the 19y deep-data fade nulls: the deployed FX book already
  occupies every FX edge we can prove. **The FX growth path is cost reduction
  (broker/spread), not new signals.**
- Also rejected this round: gold M15 trend (3×-cost fails), gold London-session
  displacement, index session displacement, FX H4 band-fades (all 8 cells).

## Frequency & capital honesty

Adding slate items 1–3 + the two index candidates ≈ **+8 trades/month** of validated
quality flow (book goes from ~1.5–2/day toward ~2.3–2.7/day). The 4–5/day aspiration
is NOT reachable from validated edges at today's breadth — the missing multiplier is
capital (equity gates), not filter-loosening. R/month: slate items add ~+1.3 R/mo
(M30 +1.07, H4 +0.44 × overlap discount, SDNY +0.20, indices ~+0.4 at min-lot),
taking the corrected book toward ~4 R/mo → **$100/mo at ~$2,500–3,300 (1% risk)**.

## Deployment path (unchanged discipline)
Each slate item: live_signals config + instance wiring (same pattern as
XAUUSD-DONCH-TR, all additive, ENABLE=False) → its verify_*.py → deployed_audit
green → YOU review diffs, copy, and flip ENABLE per the survival ladder.
Say the word and I'll wire slate items 1–3 the same way as the approved upgrade.
