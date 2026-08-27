# rev11 — Index Dollar-Risk Sizer (§2f) + Index-Book Triage

**Date:** Aug 14 2026 · **Status:** validated, NOT deployed (challenge copy frozen mid-run;
enters at the next phase boundary / on the new $15K accounts)

## 1. Why (the live audit)

Tick-verified reconciliation of the FundedNext Phase-2 tradebook (Aug 7–13, all 14
trades confirmed against Dukascopy ticks + index futures/cash data) showed the index
cells risk wildly different dollars for the same 1R, because the legacy sizing is
"minlot × steps" while $-per-point varies ~175× across index contracts:

| Cell | FundedNext contract | $/pt @ 0.04 lots | Live $ per 1R | vs $45 budget |
|---|---|---|---|---|
| GER40_DONCH/BOS | 10 EUR/pt | $0.46 | **$57** | 127% |
| SPX500_DONCH/ZBPIV | 10 USD/pt | $0.40 | **$8.6** | 19% |
| JPN225_DONCH | 10 JPY/pt | $0.0025 | **$1.85** | 4% |
| HK50_MACROSS | 10 HKD/pt | $0.051 | **$8.5** | 19% |

`prop_challenge_mc.py` monetizes **every** modeled R at `R_USD = $45`. Gold and FX
already enforce that budget mechanically (gold guard §2e, FX floor/cap sizing); the
index cells did not. Net damage to the modeled plan was small only by luck: GER40's
+27% overshoot roughly cancelled SPX500's −81% undershoot, and JPN225/HK50/US30 were
never in the MC book at all. The LOTS comments assumed research-feed contracts
($15–21 per 0.01 lot for the gated trio); FundedNext's are 10–40× smaller, so the
$600/$800 equity gates protect against a risk that does not exist there.

## 2. What changed

1. **§2f `INDEX_RISK_TARGET_USD` sizer** (`_index_usd_risk_lot`): index cells are
   lot-sized to the same per-trade budget as gold/FX — `lot = target / $risk-per-lot`,
   with $risk-per-lot from the broker's own `order_calc_profit` (currency conversion
   included) and a `tick_value/tick_size` fallback; floored to broker volume steps,
   min-lot bust ⇒ skip (gold-guard semantics), hard ceiling `INDEX_RISK_MAX_LOTS = 5.0`,
   drawdown throttle scales the target. **OFF by default** (target 0 ⇒ byte-identical
   legacy behavior; the $300 solo book is untouched). `PROP_MODE` sets the target to
   `PROP_ACCOUNT_SIZE × PROP_RISK_PER_R_PCT` — $45 on $6K, $112.50 on $15K, automatically.
2. **Dispatcher `_usd_risk_guard`** replaces the three `_gold_usd_risk_guard` call
   sites (zone / trend_trail / trend); the gold function itself is untouched and its
   harness still passes.
3. **Triage (owner decision, matrix-driven):**
   - `US30_DONCH` **promoted** into the sized set and the MC book — it is properly
     validated (matrix: n=181, 3.4 tr/mo, rr3, avg +0.151R, 3× stress PASS +0.133).
   - `JPN225_DONCH` **not sized** — borderline validation (train-negative window).
     Stays enabled at legacy dust lots as a zero-cost live-forward collector.
   - `HK50_MACROSS` **disabled** — never validated (matrix row "n/t"). Do not
     re-enable without a full battery pass.

## 3. Verification

- `verify_index_sizing.py` — 16/16 PASS: the four live-audit scenarios (GER40
  $57→$42.76 at 0.03; SPX500 $8.6→$42.86 at 0.20; US30 $45.00 at 0.06; JPN225
  passthrough), min-lot bust skip, 5-lot ceiling, throttle interaction, calc-profit
  fallback, no-data loud skip, gold + FX passthrough.
- `verify_gold_sizing.py` — regression green (gold path byte-identical).
- `prop_challenge_mc.py --baseline` vs rev11 book (N=4000, same seeds):

| | Baseline (26) | rev11 (+US30, 27) |
|---|---|---|
| Raw book R/mo (pre-haircut) | 9.2–9.8 | **10.0–10.2** (+~10%) |
| P(pass both), pess/base/opt | 35.5 / 42.2 / 46.9% | 35.9 / 41.0 / 48.6% |
| NET P(fee→funded→3mo), base/opt | 26.0 / 29.6% | 23.8 / 32.1% |

Scenario anchors calibrate monthly R to fixed targets, so a book addition mostly
redistributes within noise (±1–2pp at N=4000); the honest claims are: **+~10% raw
book R** from a stress-validated cell, and — the actual point — **live index dollars
now equal what the MC has been assuming all along.** Worst-case concurrency is
unchanged by construction: 4-cap × $45 = $180 < $210 daily kill < $300 firm line.

## 4. Deployment checklist (phase boundary / new accounts only)

1. Merge into the prop copy **only at a phase boundary** (freeze discipline, handoff §2).
2. On the $15K accounts: set `PROP_ACCOUNT_SIZE = 15000.0` — budget and index target
   become $112.50 automatically; verify the startup log prints the INDEX SIZED line
   on the first index entry and the risk ≈ target.
3. Confirm `SYMBOL_OVERRIDE` mapping per broker (GER30/JP225/HK50/US30 names) before
   first run; `order_calc_profit` prices whatever symbol it is given.
4. Rollback = `INDEX_RISK_TARGET_USD = 0.0` (legacy fixed lots, no other effect).
