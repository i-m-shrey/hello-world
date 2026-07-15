# BOOK UPGRADE REPORT — approved items + Part A/B follow-through (July 2026)

## 1. XAUUSD_DONCH exit upgrade — BUILT, verified, awaiting your approval to enable

Additive-only changes (deployed strategies untouched; diffs attached in chat):
- `live_signals.py`: new config `XAUUSD-DONCH-TR` (same `signal_DONCH` N=96 entries,
  `trail_atr=4.0`, no rr, max_hold 192).
- `live_mt5_bot.py`: instance `XAUUSD_DONCH_TR` (magic **53101**, `exit="trail"`,
  `risk_mode="trend_trail"`, same equity gate as gold trend), **ENABLE=False**;
  a `LIVE_TRAIL_BAR` closed-bar cache; a no-TP order path; and a chandelier
  SL-raise in `manage_positions` (SL → max(SL, close − 4·ATR) per closed H1 bar,
  monotonic, broker-side SL executes).
- `verify_donch_trail.py`: **ALL SECTIONS PASS** — reference numbers reproduce
  exactly (n=661, +182.8R, train +116.8 / holdout +66.0 — re-derived under the
  LIVE stop convention signal_close−2·ATR after the verify caught my original
  entry-relative convention; honest note: the verify script did its job),
  signal set identical to deployed DONCH, 221/221 sampled trades' trail paths
  reproduce exit bar+R exactly, mutual-exclusion guard in place.
- `deployed_audit.py`: still **OVERALL: ALL SECTIONS PASS**.

To go live YOU flip `ENABLE["XAUUSD_DONCH"]=False` + `ENABLE["XAUUSD_DONCH_TR"]=True`
(same entries — never both). Expected: +0.144→+0.277 avg R/trade on the same signals.

## 2. S3LO clean validation (your item 3) — the edge is real IN ITS WINDOW, not like S4

Deployed rules exactly (eval_s3 semantics: session 09:00–11:55, bias5=+1,
displacement, FVG touch+confirm, stop=swing_low−0.30, rr2, BE+1R, 1–30pt risk,
2/day), smc_engine labels, TZ-correct time, 0.60pts cost:

| window | n | net | avg | WR | PF | train | holdout | +yrs |
|---|---|---|---|---|---|---|---|---|
| official 2020-08→2025-04 | 318 | **+19.8R** | +0.062 | 47% | 1.19 | +10.4 | +9.4 | 5/6 |
| full 2008→2025 | 1271 | −3.0R | −0.002 | 42% | 0.99 | −12.5 | +9.4 | 10/18 |
| full @2× cost | 1286 | −49.2R | | | 0.89 | | | 6/18 |

Verdict: S3LO is **not** an S4 (it reproduces positively, both splits, in its
validated window) — but the edge only exists in the modern gold regime
(2020+; 2010–2015 bleeds) and has no margin at 2× cost over full history.
Honest label: **regime-young, keep with eyes open**; it will show its hand in
the live reconciliation. Note: on engine labels the OLD strategy_3 backtest
(−6.2R full-window) differs from Lux-label official (+26.6R) — the deployed
eval_s3 rules validated here are the live truth, and they hold in-window.

## 3. A2 — adaptive exits across the trend book (live stop convention)

| family | deployed exit | best trail | verdict |
|---|---|---|---|
| gold DONCH96 | rr3: avg +0.144 | **trail4: +0.277** (grid 2.5–5 monotone) | UPGRADE built (item 1) |
| gold MACROSS | rr3: +0.165 | trail3 +0.200 / trail4 +0.154 / trail5 +0.278 | NON-monotone → no change (keep rr3) |
| gold BOS | rr5: +0.161 | trails +0.116…+0.177 | deployed rr5 already optimal ✓ |
| SPX500 DONCH | rr3 FAILS floor (+0.044) | trail3/4 pass (+0.165/+0.168) | evidence (2022+) — candidate |
| GER40 DONCH | rr3 +0.220 | trail5 +0.404, monotone | evidence (2022+) — candidate |
| US30 DONCH | rr3 +0.151 | trail4 +0.319, 5/5 yrs | evidence (2022+) — candidate |
| JPN225 DONCH | all variants train-negative | — | no change |
| GER40 BOS | rr3 +0.038 (fails floor) | trail4 +0.132 | evidence (2022+) — candidate |

The exit lens generalizes: everywhere gold/index trend entries exist, letting
winners run beats fixed targets — EXCEPT gold BOS (whose rr5 grid was already
exit-optimized) and MACROSS (mixed). Index trails rest on 4 years of data —
worth adopting only at min-lot with that label, your call after more forward data.

## 4. A3 — regime routing: comprehensively FALSIFIED, closing the question

Tested on 19y deep FX data, broker 30m files, and the gold trend book:
fade+ranging-gate never rescues a fade (EURUSD broker-data fade is negative even
ungated — consistent with your BOLL30 disable); RSI30's signals are ~99% in
"trending" states so the gate is inapplicable (n=1); gold breakouts get WORSE
when gated to trending regimes and BETTER from quiet ranges (the VCX/compression
result). The concept that survives is **compression→expansion**, already
captured by VCX/STRAD-style boxes. Regime routing goes to the rejected list
with ~40 cells of evidence.

## 5. A1 — true-cost tooling (runs on your terminal) + break-even table

- `spread_audit.py --collect` (a week, read-only, creds via regex) then
  `--report`: NY-hour spread buckets per symbol + per-strategy expectancy at the
  MEASURED all-in cost using `strategy_cost_sensitivity.json` (validated
  avg@1×/2× pairs; expectancy is linear in cost).
- Break-even cost multiples (edge → 0) from the sensitivity pairs:
  DONCH_TR ~8.9×, DONCH ~6.5×, BOS gold ~5.4×, MACROSS ~5.1×, GER40 DONCH ~4.8×,
  US30 ~10×, JPN225 ~2.7×, SPX500 ~1.7×, **RSI30 USDCHF ~2.3×** — the gold/index
  trend book is nearly cost-immune; the FX fades are the fragile ones, and your
  ~3× weekend readings would kill them if they held during trading hours.
  The collector settles that question with data.
- Also honest: the broker 30m files only span **2018–2026** (100k bars), not
  2010+ as their first row suggests — the BOLL30/RSI30 validations rest on ~8
  years, thinner than labeled.

## 6. Book math after this round (aspiration arithmetic, unchanged discipline)

DONCH exit upgrade adds ~+0.2 R/month at zero new risk budget. Corrected book
≈ 2.7–3.2 R/month → $100/mo needs ~$3,100–3,700 at 1% risk/trade. The 4–5
quality-trades/day aspiration: the current book takes ~1.5–2 trades/day across
23 instances; honest breadth additions from this round (index DONCH trails at
min-lot) add ~0.3/day. Frequency grows with capital (equity gates) and future
validated breadth — not from loosening anything.
