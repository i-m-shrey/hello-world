# DELIVERY NOTES — ANALYST v2: news archive, surprise-keyed memory, replay proof
**July 15, 2026 — for the owner. Read ANALYST_REPLAY_REPORT.md alongside this.**

## What was delivered

| File | What it is |
|---|---|
| `news_archive_builder.py` + `news_archive.csv` | Real ForexFactory history 2007→2026-07 (62,683 events, USD/EUR/GBP/CHF/CAD; 44,916 with actual+forecast). Values cross-validated 100% against an independent archive on 439 NFP/CPI rows; release minutes verified (08:30/10:00/14:00 NY). Surprise z-scores are point-in-time (expanding, min 8 prior releases — no lookahead). Raw per-year scrapes in `newsarchive/` for reproducibility. |
| `event_price_lib.py` | One place for event-resolution price frames with **empirically verified timezone rules per file** (see finding below), causal panels (offline twin of the bot's `panel_for`), and outcome measurement from the T+5min decision price. |
| `case_library_builder2.py` + `case_library.csv` + `family_scales.csv` | Library v2: 2,584 signatures — 2,255 keyed on (asset, event family, surprise bucket, first-reaction direction), 329 slot-keyed (v1-style, for unscheduled shocks) — from 39,833 scored event×asset outcomes + 88,265 explosive bars, all on TZ-correct data. Reproducible; also emits the per-event table (`analyst_events.parquet`) the replay reuses. |
| `analyst_replay.py` + `ANALYST_REPLAY_REPORT.md` + `analyst_replay_trades.csv` | The replay/calibration harness: every red release walked forward with point-in-time precedent, code gates, horizon exits, REAL all-in costs, 2×/3× stress, train(≤2023)/holdout(≥2024). |
| `analyst_bot.py` (hardened, selftest green) | Surprise-keyed precedent in the packet; slot/family parity with the builders enforced in `--selftest`; `risk_usd` uses `tick_value_loss` and refuses broken tick economics; daily stop anchored to the broker clock; tolerant strict-JSON extraction; LLM-invented case citations rejected in code; every rejection logged with its reason. Demo lock, $25 risk cap, 3 trades/day, −$60 daily stop, DRY_RUN start — all unchanged. |
| `analyst_review.py` | Weekly scoreboard: decision funnel + rejection reasons, P&L vs always-NONE, confidence-bucket calibration from `decisions.jsonl` + MT5 deals (magic 98001, read-only). Writes `ANALYST_WEEKLY.md`. |

## What the replay PROVED (the honest math)

1. **No mechanical edge survives costs.** Following every first reaction loses
   −0.13…−0.29 ATR/trade after real spread+commission. Gating on the precedent
   (n≥20, continuation ≥0.60/0.65/0.70, follow AND fade, 15m/1h/4h) produces **no
   cell positive in both train and holdout**; every "good" split flips sign in the
   other. By your iron rule, the mechanical core FAILS — standing aside is nearly
   always the right answer, now with numbers attached.
2. **The precedent probabilities are overconfident noise at the cell level.**
   Cells stating 70%+ continuation realize ~49–63%; after Beta(10,10) shrinkage
   the prediction→realization curve is flat. The library is an honest *context*
   provider (typical move sizes, adverse tails, coin-flip warnings), not a
   probability engine. The bot's contract now says this to the LLM explicitly.
3. **Consequence for expectations:** any live ANALYST edge must come from LLM
   judgment beyond these keys (event nuance, cross-asset state), starting ~0.15
   ATR/trade behind on costs. The demo containment + calibration-first review is
   the right design; the prior for promotion is now measurably LOW. Judge it on
   calibration and on beating $0.00, exactly as specced — 4+ weeks minimum.

## Data-integrity finding (affects existing labs — recommend a follow-up audit)

News-spike fingerprinting (max-range bar on 114 NFP days must sit at 08:30 NY)
proved three loader/file mismatches in the repo:
- `XAU_5m_data.csv` is **broker server time (GMT+2 winter / GMT+3 summer)**;
  `sideways_lab.load_gold`'s fixed `Etc/GMT-2` parse shifts every **summer** bar
  +1h. Anything hour-windowed built on `load_gold` has summer sessions off by 1h,
  and v1 `case_library.csv` mis-slotted ~half of each year's 08:30/10:00/14:00
  events (v2 rebuild fixes the library; the labs deserve their own audit).
- `XAUUSD_M5_live.csv` and `IDX_*_M15.csv` are raw **server time**, not UTC as
  `load_mt5_export` assumes (2–3h error).
- `*15_deep.csv` are **NY wall clock +5h flat** (UTC only in winter): summer
  timestamps +1h under the UTC parse — this touches the BOLL15 quiet-hours
  validation windows. The deployed bot reads the broker feed directly and is
  unaffected; the *research* conclusions built on these files should be re-checked.
`event_price_lib.py` documents the verified rule per file; nothing in this
delivery reuses the buggy parses. `deployed_audit.py` still passes (ALL SECTIONS).

## Deployment (unchanged from the handoff, new artifacts added)

Copy to the observer desktop: `analyst_bot.py`, `ANALYST_SPEC.md`,
`case_library.csv`, **`family_scales.csv`** (new — required for surprise keying),
`analyst_review.py`. Set `TERMINAL_PATH`, run `python analyst_bot.py --selftest`
there (needs `case_library_builder2.py` + `news_archive_builder.py` present for
the parity checks, or it skips them), then 2 days DRY_RUN, then enable. Weekly:
`python analyst_review.py`.

## Not done / left honest
- No LLM-in-the-loop replay (no claude CLI in this environment): the replay
  measures the information + gates; the LLM layer is scored in demo.
- Replay exits at horizon close (no intrabar SL modeling); tail exposure is
  reported via MAE instead. Live containment is the broker-side SL.
- SPX500/GER40 event history is only 2022+ (thin n) — kept, marked, not padded.
- FOMC/ECB statements etc. have no numeric forecast → no surprise key (slot rows
  cover them). Never faked.
