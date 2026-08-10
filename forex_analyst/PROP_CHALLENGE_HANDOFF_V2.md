# HANDOFF BRIEF v2 — Prop-Firm Challenge Project (from Capy session, Aug 2026)

Read this whole file before doing anything. It continues `prop_challenge_handoff.md`
(July 2026 session). The owner is NOT a beginner being sold a dream — he asked for
probability-based truth. Give it to him straight, always. Say a hard thing once,
plainly, then respect his decision.

---

## 0. STATE AT HANDOFF (Aug 4, 2026 — evening IST)

**The challenge is LIVE and nearly through Phase 1.**

| Item | Value |
|---|---|
| Firm / plan | FundedNext Stellar 2-Step, $6K, swap-free, VPS+EA add-on |
| Bought | Jul 30 2026, $71.80 (code UPDATEDR), owner-funded (loan money) |
| Account | login **14154376**, server **`FundedNext-Server 2`** (SPACE before the 2 — the credential email omits it; bot config must include it), MT5 |
| Bot | `live_mt5_bot_PROP.py` in `C:\code\mt5_live\fundednext\` — rev10 + 4 config edits (see §2). Live (DRY_RUN=False) since Sun Aug 2 night; shadow-ran Jul 30–Aug 1 clean |
| Status | Balance **$6,349.39 (+5.82% of the 8% target; ~$130.61 to go)**, ~+$270 floating on remaining positions, **2 of 5 minimum trading days done** |
| First live trades | Aug 3–4: SPX500 long (D1 ZBPIV), GER30 long ×2 (DONCH + BOS — stacked pair, by design), US30 long; several hit 3R targets Aug 4 |
| Competition (separate) | FundedNext August Competition '26, $100K acct **34571910**, Aug 1–14, MANUAL ONLY (EAs banned there). Lot-size calculator Excel delivered. Side amusement only |
| Owner's live $300 book | Eightcap/StarTrader, rev6 "solo", untouched by this project |

**Immediate sequence from here:** 3 more trading days accrue (bot's normal pace)
→ phase assessment at server reset → account pauses → **KYC opens in dashboard**
(passport/Aadhaar, name exactly "Shrey Jain", 3 attempts, ~24–48h, renews every
90 days) → Phase 2 credentials arrive → SAME file, new login/password in
`CREDENTIALS["standard"]`, target +5%, nothing else changes → pass → funded
(see §5 for the two funded-stage config changes) → first payout eligible 21 days
after funding (USDT TRC20 → Trust Wallet; fee refunded with 1st reward).

---

## 1. THE OWNER — situation and views (hold him to these; he asked for it)

- Shrey Jain, India. Financially weak; funded the fee with borrowed money. Wants
  income fast but explicitly works on probability math and wants correction when
  he drifts. Target restated this session: **$2,000–3,000/month** (see §6 ladder).
- Accepted: $40–80/wk honest range on $6K; first money 6–10 weeks out; KYC at
  payout unavoidable; ~1-in-5 full-plan odds per attempt.
- **Took one manual trade on the challenge account (Jul 30, +$31.35)** — was told
  plainly why never again (pattern-mixing scrutiny, bot can't see manual positions,
  corrupts risk budget). He agreed: **zero manual trades on 14154376, permanently.**
  His manual itch is redirected to the competition account.
- Keeps forwarding Instagram prop-firm ads ($5–17 offers). Standing verdict: all
  fail the rules filter (§7). The answer stays no until a firm beats FundedNext on
  RULES, not price.
- Understands: no payout exists for passing Phase 1 anywhere legitimate.

## 2. THE PROP BOT CONFIG (exact, verified working)

Base: rev10 `live_mt5_bot_FINAL.py` (byte-identical to repo
`i-m-shrey/hello-world` branch `capy/tz-audit-discovery`, folder `forex_analyst/`).
The prop copy differs ONLY by:

1. `PROP_MODE = True` (re-anchors: $45/trade = 0.75% of $6K; FX 0.17 lots,
   gold 0.02, indices 0.04; daily kill −3.5% incl. floating → flatten + block to
   next broker day; max kill −8% → flatten + permanent halt; caps 1 gold-trend /
   2 per-USD / 4 total)
2. `DRY_RUN = False` (was True for the Jul 30–Aug 1 shadow)
3. `CREDENTIALS["standard"]` = 14154376 / owner's reset password / `FundedNext-Server 2`
   / terminal `C:\Program Files\MetaTrader 5 FundedNext\terminal64.exe`
4. `SYMBOL_SUFFIX = ".s"` + `SYMBOL_OVERRIDE = {"GER40": "GER30.s", "US30": "US30.s"?,
   "JPN225": "JP225.s"?, "HK50": "HK50.s"?}` — owner mapped the last three from
   Market Watch himself; preflight shows all 10 symbols resolving (GER30, JP225,
   HK50, US30 names on FundedNext)

All 29 strategies armed at $6K (survival-ladder gates 250/300/600/800 all cleared —
log line proves it). Broker TZ auto-detected UTC+3 = dashboard reset clock; bot's
daily kill anchors to the same midnight as FundedNext's daily reset. Telegram
notifications working. HEDGING account type OK.

**Freeze discipline: the challenge copy gets NO code changes mid-run.** Improvements
go to research branches and enter only at phase boundaries, with validation.

Operational rules learned live:
- Never open the bot's CSVs in Excel (WinError 5 file locks; copy first). One
  Windows Defender exclusion for the bot folder is advisable; exactly ONE
  python.exe must run this bot (duplicate processes = double orders).
- `PROP-GATE (no new entries)` in log = kill-switch working, not a bug.
- `SKIP — SL risk $X > $45` on gold trend = the risk cap doing its job (wide-ATR
  gold signals get skipped by design; the 5–7R/mo estimate already nets these out).
- Dry-run "repeated signals" every bar = shadow-mode artifact (no position recorded
  → condition re-logs). Live dedup is mechanical: one position per strategy magic.
- Index DONCH/BOS/ZBPIV are `exit="fixed"` (3R-ish targets, NO trailing). Trailing
  exists only on gold DONCH_TR, HAVW×3, S5 runner, S3LO breakeven move. Never
  manually move SLs to BE — it destroys the validated rr3 statistics. Account-level
  protection = daily-kill anchor ratchets at broker midnight to max(balance, equity).
- Time caps: GER30/US30 trades ≤96 H1 bars (~4–5 tdays); SPX500 ZBPIV ≤30 D1 bars.
- Spreads verified good (Sun-open readings): EURUSD 0.1p, GBPUSD 0.3p vs 0.8–1.0
  assumed; gold $0.50 at open (2× assumed $0.23 — expected to compress in-session;
  watch). `FX_SPREADS` is stop-pads + 3× preflight warning ONLY — never an entry
  filter; the bot trades regardless of spread. **Spread audit still pending**: owner
  has `spread_audit.py` + `strategy_cost_sensitivity.json` (delivered in chat; also
  in forex_analyst/), needs `--collect` for 2–3 days alongside the bot then
  `--report` → per-strategy expectancy at measured cost. Disable thresholds:
  EURUSD_BOLL30R if >1.0 pip all-in; USDCHF_RSI30 if ~2.3 pips; gold intraday tier
  if session-average >$0.7–0.8.

## 3. RULES VERIFIED THIS SESSION (FundedNext, July–Aug 2026)

- Challenge unchanged: 8%/5% targets, 5% daily / 10% max (static, incl. floating,
  from initial balance), no time limit, 5 min trading days per phase (min 1
  trade/day; a day counts only when a trade happens), news OK, EAs OK (EA
  permission now a PAID add-on at checkout — owner bought VPS & EA $10), weekend
  holds OK in evaluation.
- **No penalty for fast passes.** Target early + days pending = keep trading until
  5 days log. Stopping the bot would freeze the phase (no trades = no days).
- **Funded-stage 3% rule (new since prior handoff):** total open risk across all
  positions (by SL distance, vs initial balance, stacked idea counted together)
  ≤3% at any time + every trade needs SL within 3 min (bot attaches SL at entry —
  compliant by design). Challenge phases: visibility only, no penalties. **At
  funded: set `PROP_MAX_TOTAL = 3` (or `PROP_RISK_PER_R_PCT = 0.0070`).**
- Funded weekend ban → flip `PROP_WEEKEND_FLAT = True` at funding. News-window
  profits capped at 40% share on funded — re-read policy then.
- KYC: after passing BOTH phases (account pauses until approved); 90-day renewals;
  3 attempts; India fine.
- Payouts: USDT (TRC20/ERC20), 24h guarantee ($1K compensation), fee up to 3.5% +
  gateway; **base split 80%** (95% is a paid upgrade / scale-tier); first reward
  21 days after funding, then bi-weekly. **15% challenge-phase reward (~$117) is
  now tied to meeting Scale-Up criteria** (Jan 12 2026 policy), not paid at funding.
- Scale-up: +40% account every 4 months if ≥10% accumulated disbursed growth,
  ≥2 payouts, last cycle profitable (book's expected 13–18%/4mo clears it). Pro
  track: +25%/cycle after 4 rewards with 4%+ cycles.
- Copy-trading policy: allowed between own CHALLENGE accounts (≤$300K, master
  designated; VPS copiers OK). PROHIBITED the moment a FUNDED account is involved,
  even same person. **Merging funded accounts allowed (≤$300K) — that's the legal
  path to running one bot on combined capital.** Never mirror bot signals onto the
  competition account (not on the allow-list + EA-ban there; detection is
  pattern-based).

## 4. PROBABILITY WORK (all committed to repo)

MC built from the 26-strategy matrix stats, prop rules simulated exactly
(`forex_analyst/prop_challenge_mc.py`, commit 279d3be):

| | Pessimistic 2.5R/mo | Base 4.5R/mo | Optimistic 6.5R/mo |
|---|---|---|---|
| P(pass Phase 1) | 56–57% | 63–64% | 66–74% |
| P(pass both) | 36–37% | **42–46%** | 47–58% |
| P(pass P2 alone) | ~64% | ~67–72% | ~74–79% |
| Funded survives 3mo | 52–59% | 62–65% | 63–76% |
| Mean weekly net ($6K, 80%, fees) | $23–32 | **$37–53** | $56–63 |
| P(first funded quarter avgs ≥$40/wk) | 34% | 44–46% | 53–55% |

Full-plan compound (fee → funded → ≥$40/wk first quarter): **~19–21% base,
12–28% range.** ~45% of individual weeks are negative even when healthy — judge
monthly/quarterly, never weekly. Live-tradebook calibration (July, 36 trades):
composition-corrected book ≈ +1.2R ex-S5-runner over 23 days; benched BOLL15/30
family caused −11.15R of the −10R month (bench vindicated; prop copy ships with
them off); loss discipline excellent (avg −1.025R, worst −1.13R). Sample too
small to move scenario weights. **Two weeks of live challenge data (mid-Aug) is
the next calibration gate.**

**Dynamic concurrency cap (owner's idea, backtested, REJECTED):**
position-level MC A/B (`forex_analyst/dynamic_cap_mc.py`): admits ~1 extra
position/month, P(pass) −1–2pp in BOTH scenarios, nothing improves. Static 4-cap
stays. Mechanism: freed budget appears late in trends; extra admissions are
correlated late entries. The 4-cap keeps worst-case concurrent loss ($180) under
the daily kill ($210) under the firm line ($300).

## 5. FUNDED-STAGE TRANSITION CHECKLIST (when Phase 2 passes)

1. KYC approved → funded account credentials → same file, new creds.
2. `PROP_WEEKEND_FLAT = True` (their funded weekend ban; Friday 16:30 NY flatten).
3. `PROP_MAX_TOTAL = 3` (3% open-risk rule; or risk 0.0070 with 4 — pick ONE).
4. Re-read their news-profit (40%) policy current text.
5. First payout request at 21 days: KYC current, USDT TRC20, expect ~3.5% fee;
   fee refund rides with 1st reward. Withdraw meaningful profit but leave buffer
   above the −8% halt line (payout drops balance AND the max-loss floor is static
   on initial — removing profit removes cushion).

## 6. THE $2–3K/MONTH LADDER (agreed plan)

Needs ~$75–100K funded at the book's ~2.6–3.9%/mo net. Self-funding ladder:
pass $6K (now) → payouts Sep–Oct → buy $25K (~$180) from payouts Oct → pass →
**merge** funded accounts (~$31K) → $50K challenge + scale-up (+40%/4mo) →
$75–100K+ by **Feb–Apr 2027 if everything first-try (6–8 months); realistic
median 9–12 months**; pessimistic book → 18+ months and fix the book first.
Rules: every fee after the first comes from payouts (loan exposure capped at
what's spent + originally budgeted retries); risk stays 0.75% forever (capital
scales, risk doesn't); mid-Aug live data gates the optional second $6K
(FundedNext allows same-bot parallel challenge accounts, see §3 copy policy;
merge or split books at funded). Counterparty diversification later: FTMO Swing
$10K (~€155, no bot changes needed) once payouts exist. October budget
candidates needing a full rule battery before purchase: FXIFY $39, Hola Prime
$49, E8 (~$40) — pre-screened headline-OK only.

## 7. FIRM-SHOPPING VERDICTS (all verified this session; don't re-litigate)

REJECTED for the bot: **FundingPips** (news banned in eval), **The5ers** (±2min
news rule; viable only after a news-blackout filter is built+validated),
**Atmos** ($5 bait; ±2min news soft-breach strips profits both phases; worse-of
balance/equity daily), **Blue Guardian** ($10 instant = trailing DD),
**GOAT Funded** ($17; ±5min news profit cap 1% both phases; 4% daily on that
model; Trustpilot 3.4 with guideline-breach flag; Goat-Guard split cuts),
**FundedElite** ($6 + $175 activation after pass; 3% daily < our kill; scalping
ban vs gold M5 tier), **Moneta Funded** (7 months old, consistency/duration
review clauses, $2.3M total allocated). **Standing filter: daily ≥5%, static DD,
news unrestricted (at least all of evaluation, tolerable funded), EAs permitted,
no scalping/consistency clauses, Trustpilot ≥4.4 at scale.** Cheapest legitimate
bracket is $25–50, not $5–10 — at $5–10 the fee is the product.

## 8. STRATEGY RESEARCH VERDICTS (this session; artifacts committed)

The owner's 8-strategy table came from `liquidity_grab/DISCOVERY_NEW.md`
(branch `capy/liquidity-grab-backtest`). Battery run on fresh Dukascopy data
(`liquidity_grab/verify_rngx.py`, commit f6e4955):

- **XAUUSD RNGX (H4 range-expansion L rr3): real** — reproduces (n=457 vs 458),
  3× stress PASS (train +0.184, valid +27.6R, 15/19y) — **but redundant**: 71%
  time-overlap with BOS (daily-R corr +0.65), 46% with DONCH_TR. Do NOT add to
  the current book; earmark for the two-account/merged era as breadth.
- **XAUUSD TSMOM (55d break, trail): watchlist** — reproduces, essentially
  cost-immune (+0.907 avg at 3×), but n=57 < house n≥80 bar.
- **XAUUSD PULL (EMA20 dip rr3): bench** — reproduces but 3× stress borderline
  (train avg +0.047), cost-fragile tier.
- **USDCHF RNGX: REJECTED** — fails reproduction on fresh data (n=401 vs 223,
  avg −0.046 vs +0.222); the discovery run's FX dataset was sparse; edge was a
  data artifact. **This poisons the other FX cells** (USDJPY PULL/TSMOM/MR3,
  USDCAD TSMOM) until re-run on fresh data (~1h job if ever wanted).
- Nothing enters any account now. Challenge copy frozen regardless.

## 9. COMPETITION SIDE-QUEST (expires Aug 14)

$100K account 34571910, manual only, his own ideas ONLY (never bot mirrors —
account-linking risk to the challenge). Rules: 5% daily ($5K incl. floating),
10% max, max lots 5 FX / 3 indices+metals, ≤5 positions, ≤50 trades/day,
swap-free, $1/lot FX commission, EAs banned. Delivered:
`competition_lot_calculator.xlsx` (symbol dropdown + SL → lot size with firm
caps; DayTracker with −$4,000 soft stop; GER30/JP225/HK50/US30 point values
need MT5-Specification verification before first use). Prize reality: 1st =
$5K + $20K Instant (needs ~+40–100% in 9 days ≈ gambler odds); top-100
~+12–20%; ranks 101–600 → RNG draw for 50× $2K Instant accounts (~+5–10%) —
the rational target. Real value = 14 days of honest manual-logic data.
Leaderboard tab shows live cutoffs — calibrate from day 2–3.

## 10. SEPARATE PROJECT TOUCHED (not prop): NIFTY options bot

`tradex_buyer_e2e.py` (his Indian options buyer, Shoonya orders + Dhan data,
DRY_RUN): patched and delivered in chat — mid-session Dhan 401 now triggers
PIN+TOTP re-mint + retry once; on mint failure a 20-min circuit breaker demotes
Dhan (Shoonya fallback, single Telegram alert, self-heals). Behavioral tests
passed. Known separate issue his runner already guards: Shoonya index-echo
glitch (spot price returned for option tokens — quote-hygiene filter discards).
Deployment status of the patch: sent to owner, not confirmed deployed.

## 11. LOOSE ENDS / OPEN ITEMS

1. **Spread audit not yet collected** on the FundedNext feed (files delivered;
   needs 2–3 days of `--collect` + `--report` review). Gold session-average is
   the number to check (<$0.45–0.50 = fine).
2. Trading days 2/5 at handoff — phase completes ~Thu/Fri Aug 6–7 if book keeps
   trading daily.
3. Mid-Aug: two-weeks-live calibration → decides optional second $6K purchase.
4. STRAD $30 cap on the LIVE $300 book (not prop): proposed July, never
   confirmed by owner. Raised once more this session. Do not nag again.
5. rev11 ideas: dynamic cap REJECTED (archived). News-blackout filter = the
   prerequisite for The5ers/Atmos-class second firms — not built, medium project,
   only worth it if diversification beyond FundedNext/FTMO is wanted.
6. USDJPY/USDCAD discovery cells: unproven, need fresh-data re-run before any use.
7. The owner's Phase 2 will need the SAME onboarding moment: new credentials into
   the file, verify server string from the terminal (not the email), preflight
   log check. Keep the `FundedNext-Server 2` space lesson in mind.

---

## PROMPT FOR THE NEW SESSION (owner: paste everything below this line)

I am continuing my FundedNext prop-challenge project. The full updated handoff
is the attached MD file — read it completely first. Current state: my $6K
Stellar 2-Step challenge account 14154376 is LIVE with my 29-strategy MT5 bot
(rev10 + PROP_MODE), Phase 1 is ~$130 from the +8% target with 2 of 5 minimum
trading days done. Hold me to the honest numbers (base case P(pass both) ~44%,
$37–53/week on $6K funded, ~1-in-5 for the full first-quarter plan) and correct
me when I drift. My rules: no manual trades on the challenge account ever, the
challenge bot code is frozen mid-run, every future fee comes from payouts not
loans, risk stays 0.75%/trade, and cheap prop-firm ads get judged by the rules
filter in §7 before anything else. Next milestones: 3 more trading days →
KYC (docs ready) → Phase 2 (same config, +5% target) → funded (flip
PROP_WEEKEND_FLAT=True and set PROP_MAX_TOTAL=3) → first payout at 21 days →
mid-August second-account decision from live data. Walk those with me.
