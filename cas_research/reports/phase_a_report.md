# Phase-A Forensics — CAS Closing Window (2026-08-03 go-live)

**Data:** Dhan `/v2/charts/rollingoption`, 1-min, per-minute `iv/oi/volume/spot/strike`, near-ATM (fetched ATM±5, analysed near-ATM/±2).
**Sessions:** post-CAS n = **5** (Aug 3–7; Aug 4 = NIFTY weekly expiry, Aug 6 = SENSEX weekly expiry ⇒ only **3 clean non-expiry NIFTY sessions**). Pre-CAS baseline n = 29 (Jun 22 – Jul 31).
**Series:** NIFTY_WEEK, NIFTY_MONTH, BANKNIFTY_MONTH, SENSEX_WEEK. Timestamps verified UTC-epoch (+5:30 → IST); every post-CAS session delivers bars through **15:39** (385 bars/day vs 375 pre-CAS).

## Verified structural facts

**1. The extension is real and liquid.** Options print continuously 15:30→15:39. NIFTY weekly volume in 15:30–39 = **0.68–1.08×** the 15:20–29 volume (per day: 0.86, 0.70, 0.68, 1.08, 0.97). The closing 20 min now carries ~40–50% of late-afternoon (14:45+) volume vs ~26% share for the old last-10 pre-CAS — genuine volume migration into the close.

**2. The cash index feed dies at ~15:28–29.** Post-CAS, the `spot` column last changes 15:28–15:29 every session, every index. Options trade the final 10 minutes with **no live underlying print**; feed IV after 15:30 is computed against stale spot. Any strategy signal in the extension must come from the option complex itself (synthetic forward = CE−PE+K), not spot.

**3. NO auction-match jump.** The hypothesized repeatable 15:30–15:35 repricing does not exist in index option premiums. Median |1-min premium move| in 15:30–39, per day (NIFTY weekly, %/min): 1.51, 0.41, 0.89, 1.00, 0.85 — *at or below* the day's 15:20–29 level and comparable to pre-CAS 15:25–29 quiet (0.80 median). Monthly NIFTY/BANKNIFTY: 0.25–0.64%/min, dead calm. The auction equilibrium prints (15:30–35) pass through the derivatives complex without a pulse.

**4. NO IV markup into the 15:15 freeze, NO post-auction crush.** iv(15:15)−iv(15:00) on non-expiry days: −1.44…+0.25 (NIFTY W), −0.71…+0.02 (NIFTY M), −0.48…+0.10 (BN), −1.09…0.00 (SENSEX) — same mild decay as pre-CAS (median −0.17). iv(15:35)−iv(15:29): −0.20…+0.23 non-expiry. Nothing to sell into, nothing to buy ahead of.

**5. ONE real new signature: OI unwind in the extension.** Near-ATM OI change 15:29→15:39 (NIFTY weekly): +0.1%, −6.8%, −5.9%, −6.4%, **−17.9%** (Aug 7). Position squaring that used to happen by 15:29 (or overnight) now happens inside 15:30–40, and it grew through the week. This is a flow fact, not (yet) a priceable edge — the unwind produced no directional premium drift (see 3).

**6. Day-1 adjustment artifact.** Aug 3 (first CAS session): near-ATM IV spiked +8.4 vols 15:00→15:29 (11.2→19.6) with spot rallying ~200 pts into the close. Pre-CAS Mondays: −1.0…+0.1. Not repeated on Aug 5/6/7 (−1.4, −0.4, −0.5). Classic go-live repricing, already gone.

**7. Directional drift: none stable.** ATM premium net moves 15:15→15:39 are sign-unstable across the 3 clean sessions (CE: −11%, −3%, −5%/+1%; PE: −8%, +4%, −1.6%). Synthetic-forward drift 15:15→15:39: +0.7, −7.7, −7.7 pts (NIFTY) — direction disagrees with spot's last prints on 2 of 3 days, but n=3. Overnight close→open premium gap (2 clean obs): −8.9%, −9.8% — ordinary theta, no CAS gap edge visible.

## Cost-hurdle reality (why nothing here is tradeable yet)
Round trip = 0.7% of premium + spread (~1 tick ≈ 0.04–0.4%) + theta. Observed *systematic* (signed, repeatable) drift in any sub-window: indistinguishable from 0 on 3 clean sessions, while per-window noise is ±1–4%. A buying rule needs a signed expectation ≥ ~1.5–2% of premium per trade to survive the validation contract; nothing in the window shows a tenth of that with consistent sign.

## Phase-B verdict: NO deployable option-buying rule yet — documented negative
- The auction-jump trade (long straddle into 15:30) is **dead on arrival**: no jump exists (fact 3), consistent with all prior straddle failures.
- Auction-window drift trade (15:10–20 → 15:39): no stable sign (fact 7), n=3.
- Post-auction reaction (15:30→15:39): calmest part of the day (fact 3).
- Overnight CAS-close→open: 2 observations, both plain theta decay. (Weekend-Continuation extension untestable until Fridays accumulate.)

## Triggers to revisit (append data daily, re-run this analysis)
1. **OI-unwind → price**: if the 15:30–40 OI unwind (fact 5) keeps growing (>20% of near-ATM OI) and starts producing signed premium drift ≥1.5% with one sign in ≥70% of sessions (need n≥10 non-expiry), test the directional entry 15:20 → exit 15:38.
2. **Expiry-day settlement**: only 1 post-CAS NIFTY expiry so far. Collect 4+ Tuesdays before touching settlement-window variants.
3. **Synthetic-forward vs next open**: once n≥15, test whether 15:29→15:39 synthetic-forward move (the only live price in the extension) predicts the overnight gap.
4. Re-check after the **first high-VIX / large-imbalance day** (all 5 sessions so far were VIX ~10–13, |day move| small — the CAS window has not yet been stressed).

## Runbook
- `python3 fetch_cas.py --daily-update` (after 15:46 IST; mints token itself, guard refuses during market hours) appends the latest sessions to all 4 masters.
- `python3 analyze_phase_a.py` recomputes `reports/phase_a_session_metrics.csv`.
- Masters in `data/` (~150k rows/series, refetchable from scratch in ~10 min).
