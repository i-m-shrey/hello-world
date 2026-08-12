# ============================================================================
# FINAL PRODUCTION FILE (July 22 2026 rev10 -- PROP-FIRM CHALLENGE MODE).
# rev9 base unchanged. New section 2d: PROP_MODE=True re-anchors the book to
# a prop challenge account (default $6K FundedNext-style): ~0.75%/trade
# sizing, HARD daily kill at -3.5% (flatten + block entries till next broker
# day), HARD max kill at -8% (flatten + permanent halt), stacking caps cut to
# prop-safe 1 gold / 2 per-USD / 4 total (firms treat stacked positions as one
# trade idea), optional PROP_WEEKEND_FLAT for funded-stage weekend bans.
# Kill-switch anchors follow prop convention: daily = max(balance,equity) at
# broker midnight incl. FLOATING losses; max = initial account size (static).
# Default ships PROP_MODE=False -- byte-identical to rev9 until you opt in.
# Fill the placeholders in CREDENTIALS (+ Telegram), save as live_mt5_bot.py.
# ============================================================================
"""
================================================================================
 LIVE MT5 EXECUTION ENGINE — MULTI-SYMBOL PORTFOLIO
================================================================================
 Gold (XAUUSD, 5m + 15m bias):
     S5  long-only  (runner exit)   — shorts bleed on gold; long-only validated better
     S6  long-only  (fixed exit)    — displacement continuation, gold-bull regime bet
     S4  two-sided  (fixed exit)    — NY manipulation reversal
 FX (H1 + H4 bias)  — signals via live_signals.py, PROVEN == backtest (verify_live_fx.py):
     EURUSD-E  two-sided  (fixed, BE +1.5R)   session-open momentum   +48.8R
     GBPUSD-E  two-sided  (fixed, BE +1.5R)   session-open momentum   +42.5R
     USDCAD-A  two-sided  (fixed, no BE)      S5-port sweep->CHoCH->FVG  +21.2R
     USDCHF-A  SHORT-ONLY (fixed, no BE)      S5-port, short side only   +24.8R

 Signal logic = smc_engine.py + live_signals.py (the SAME code the backtests run).
 Evaluated ONLY on closed bars. FX risk bounds are ATR-relative (0.55..8.0 x ATR50).

 !! READ BEFORE GOING LIVE !!
 1. DRY_RUN starts True. Shadow-run new symbols ~2 weeks; compare signals to backtest.
 2. VERIFY BROKER_TZ at startup (banner). Wrong NY conversion => wrong session filters.
 3. VERIFY the FX symbol names match your broker EXACTLY (some use "EURUSD." with a suffix).
 4. Lots default 0.01 each (per-strategy-per-symbol below). Scale only after tracking.
================================================================================
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FATAL: pip install MetaTrader5")
    sys.exit(1)

import smc_engine
from smc_engine import STRAT
import live_signals as LS

# ============================== 1. CREDENTIALS ==============================
# TWO named credential sets - one per broker/terminal. Which one THIS process
# uses is decided by BROKER_PROFILE (section 2a):
#   solo / standard / both-parent -> "standard" set
#   swapfree                      -> "swapfree" set
# The "both" supervisor spawns one child per set; each child logs into its OWN
# terminal (two separate MT5 installs - the API allows one terminal per process).
CREDENTIALS = {
    "standard": dict(
        account=0,                          # <<<PASTE-STANDARD-ACCOUNT-NUMBER>>>
        password="<<<PASTE-STANDARD-PASSWORD>>>",
        server="<<<PASTE-STANDARD-SERVER>>>",
        terminal="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    ),
    "swapfree": dict(                       # fill when the two-account split happens
        account=0,                          # <<< PASTE SWAP-FREE ACCOUNT NUMBER
        password="<<<PASTE-SWAPFREE-PASSWORD>>>",
        server="<<<PASTE-SWAPFREE-SERVER>>>",
        terminal="C:\\Program Files\\MetaTrader 5 - SwapFree\\terminal64.exe",
    ),
}


# ====================== 2. PER-STRATEGY-PER-SYMBOL LOT SIZES =================
# >>> EDIT THESE: one lot size per strategy per symbol. <<<
LOTS = {
    "XAUUSD_S5":  0.01,
    "XAUUSD_S6":  0.01,
    "XAUUSD_S4":  0.01,
    "XAUUSD_H1A": 0.01,     # gold H1 long-only (A family) — 12/18 years positive
    "XAUUSD_STRAD": 0.01,   # gold H1 breakout, long-only close-confirmed — PF 1.78, 13/18 yrs
    "XAUUSD_S3LO": 0.01,    # NY-morning FVG long — +26.6R PF 1.21, daily-corr to S5 only +0.26
    "EURUSD_E":   0.04,
    "EURUSD_BOLL30": 0.03,   # 30m quiet-hours fade — ~118 trades/yr, low-cost edge
    "EURUSD_P1_30": 0.03,    # 30m opposing-FVG reversal (limit entry) — ho +10R
    "GBPUSD_P1":   0.04,     # H1 opposing-FVG reversal (limit entry) — PF 1.91, cost-immune
    "GBPUSD_E":   0.04,
    "USDCAD_A":   0.04,
    "USDCHF_A":   0.04,
    "USDCHF_RSI30": 0.04,    # 30m RSI fade, SHORT-only — PF 1.62, 9/9 yrs, corr to A -0.03
    "XAUUSD_DONCH":  0.01,   # gold Donchian breakout LONG — +95R avg+0.116, corr to book +0.14
    "XAUUSD_MACROSS":0.01,   # gold EMA20x50 momentum LONG — +50R avg+0.110, corr +0.16
    "SPX500_DONCH":  0.01,   # S&P Donchian LONG — +41.8R WR33%, cross-feed verified, ~$2/trade
    "GER40_DONCH":   0.01,   # DAX Donchian LONG — +62.9R WR32%, cross-feed verified, ~$9/trade
    "XAUUSD_CRASH":  0.01,   # gold crash-insurance SHORT — +63.1R, pays in every bear window
    "GBPUSD_AVWAP":  0.04,   # daily-AVWAP stretch fade SHORT — +123R/16y, avg +0.084, replaces
                             # the benched BOLL15 fades with a 2x fatter per-trade edge
    "XAUUSD_BOS":    0.01,   # structure-break long rr5 — +267R/18y avg +0.170, 3x-cost immune
    "GER40_BOS":     0.01,   # DAX structure-break long rr3 — +51.6R/7y avg +0.070
    "US30_DONCH":    0.01,   # EQUITY-GATED ($600): validated, ~$15/trade at min lot
    "JPN225_DONCH":  0.01,   # EQUITY-GATED ($800): validated, ~$17-21/trade at min lot
    "HK50_MACROSS":  0.01,   # EQUITY-GATED ($800): validated, ~$15-20/trade at min lot
    "XAUUSD_DONCH_TR": 0.01, # DONCH exit-upgrade twin (chandelier trail) — rides min lot
    "XAUUSD_VCX_A":  0.01,   # VCX gold cell A (q0.20 pad0.2 stop2.5) — min lot
    "XAUUSD_VCX_B":  0.01,   # VCX gold cell B (q0.25 pad0.1 stop2.0) — min lot
    "XAUUSD_ZBPIV":  0.01,   # H4 pivot(K=5) zone breakout — +0.16 avg/18y, 3x +98.8
    "XAGUSD_ZBBOX":  0.01,   # SILVER H1 Darvas-box breakout — first validated XAG edge
    "SPX500_ZBPIV":  0.01,   # S&P D1 pivot(K=5) breakout — WR 47%, ~$4-8/trade min lot
    "EURUSD_BOLL30R": 0.04,  # refined M30 fade (long-only, atrp<=0.50) — live-cost PASS
    "XAUUSD_HAVW": 0.01,     # H1 Heikin-Ashi+VW-MACD trend — 36/36 plateau, corr<=0.05
    "EURUSD_HAVW": 0.04,     # H4 HAVW — n=320/18y avg+0.277, sized down by $15 cap
    "GBPUSD_HAVW": 0.04,     # H4 HAVW — n=335/18y avg+0.221, sized down by $15 cap
    "USDCHF_P1":  0.04,      # H1 opposing-FVG reversal — +16R avg+0.125, corr to CHF book -0.01
    "EURUSD_BOLL15": 0.03,   # 15m BB fade LONG-only — +206R/18.5y, PF 1.15, 16/19 yrs
    "GBPUSD_BOLL15": 0.03,   # 15m BB fade — +409R/18.5y, PF 1.15, 17/19 yrs, 3x-cost-immune
    "USDCHF_BOLL15": 0.03,   # 15m BB fade — +363R/18.5y, 19/19 yrs (feed-sensitive level)
}
# FAIL-FAST (July 16 2026, after a live KeyError): every INSTANCES key MUST have a
# LOTS entry — checked at import so a missing lot can never crash a live preflight.
# (The assert itself lives right after INSTANCES is defined, below.)
# Enable / disable each strategy-symbol independently.
ENABLE = {
    "XAUUSD_S5":  True,
    "XAUUSD_HAVW": True,       # ENABLED July 18 2026 (owner go-live): H1 Heikin-Ashi
                               # flip + RSI pullback + VW-MACD, chandelier trail. 7/7
                               # verify + 16-generator forward-bias audit clean. Gated $250.
    "EURUSD_HAVW": True,       # ENABLED July 18 2026 (owner go-live): H4 twin, gated $300;
                               # per-instance $15 risk cap (3xATR H4 stop > book $10.50).
    "GBPUSD_HAVW": True,       # ENABLED July 18 2026 (owner go-live): H4 twin, gated $300.
    "EURUSD_BOLL30R": True,    # ENABLED July 16 2026 (owner go-live): refit survivor at
                               # audited live cost (ho +27.4R). COST-FRAGILE — disable if
                               # EURUSD all-in spread exceeds ~1.0 pip.
    "XAUUSD_ZBPIV": True,      # ENABLED July 16 2026 (owner go-live): H4 pivot breakout,
                               # gated $250; the $20 XAUUSD risk cap will skip most
                               # signals while H4 ATR is $30-40 (logged when it does).
    "XAGUSD_ZBBOX": False,     # ZONE BREAKOUT silver: ships OFF. NOTE: broker silver
                               # symbol must exist (XAGUSD / check SYMBOL_OVERRIDE).
    "SPX500_ZBPIV": True,      # ENABLED July 16 2026 (owner go-live): D1 pivot breakout
                               # WR 47%, gated $250 (~$4-8 risk/trade).
    "XAUUSD_VCX_A": False,     # OWNER-SELECTED VCX cell A (q0.20 pad0.2 stop2.5 rr3).
                               # ~96% open-time overlap with XAUUSD_DONCH and VCX_B —
                               # these STACK the same gold longs (cap = MAX_STACKED_GOLD_LONGS).
    "XAUUSD_VCX_B": True,      # ENABLED July 16 2026 (owner go-live): the MC-preferred
                               # VCX cell (DONCH_TR+VCX_B best marginal ratio). Gated $250.
                               # VCX_A stays OFF (96% overlap — never run both).
    "XAUUSD_DONCH_TR": True,   # ENABLED July 16 2026 (owner go-live): replaces DONCH.
                               # Gated $250 — arms automatically when equity crosses.
    "XAUUSD_S6":  True,     # RE-ENABLED as S6-R (July 2026): structure-gated rehab —
                            # bias5==+1 + disp 2.4xATR flips it to +54.6R, PF 1.18,
                            # maxDD -19.5R, 6/6 years (s6_rehab_lab.py). See S6R_* vars.
    "XAUUSD_S4":  False,    # DISABLED July 16 2026: TZ audit VOID — the session-boxed
                            # pattern does not exist on true NY time (23->9 trades,
                            # train -1.0R). Do not re-enable without fresh validation.
    "XAUUSD_H1A": True,
    "XAUUSD_STRAD": True,
    "XAUUSD_S3LO": True,
    "EURUSD_E":   True,
    "EURUSD_BOLL30": False,  # DISABLED July 2026: at TRUE all-in cost (spread+commission)
                             # lifetime edge collapses +44R -> +10R (~0.1 R/mo) and it is
                             # redundant with EURUSD_BOLL15. Re-enable only if costs drop.
    "EURUSD_P1_30": False,   # DISABLED July 2026: +21R -> +3R at true costs (~0). The H1
                             # GBPUSD_P1 (cost-immune) stays live.
    "GBPUSD_P1":   True,
    "GBPUSD_E":   True,
    "GBPUSD_AVWAP": True,   # wired July 14 2026 on user's word after full battery + overlap
    "XAUUSD_BOS": True,     # wired July 15 2026 on user's word (exit grid: rr5)
    "GER40_BOS": True,      # wired July 15 2026 on user's word (rr3 — DAX doesn't extend)
    # The three below are ENABLED but EQUITY-GATED (see equity_min in INSTANCES): they
    # arm themselves automatically when account equity crosses the threshold. At $150
    # capital their $15-21/trade risk is 10-14% per trade — the gate is the risk rule.
    "US30_DONCH": True,
    "JPN225_DONCH": True,
    "HK50_MACROSS": True,
    "USDCAD_A":   True,
    "USDCHF_A":   True,
    "USDCHF_RSI30": True,
    "XAUUSD_DONCH": False,  # SWAPPED July 16 2026 for XAUUSD_DONCH_TR (same entries,
                            # validated chandelier-trail exit: avg R +0.116 -> +0.338).
                            # MUTUAL EXCLUSION: never enable both DONCH and DONCH_TR.
    "XAUUSD_MACROSS": True,
    "SPX500_DONCH": True,
    "GER40_DONCH": True,
    "XAUUSD_CRASH": False,
    "USDCHF_P1": True,
    # BOLL15 family BENCHED July 14 2026 (user decision, lab agrees): thin +0.04R/trade
    # edge, recent 4y broker window ~zero at true costs, ~$5/mo expected at current size
    # vs most of the book's daily loss-noise. 18.5y edge intact (+94/+184/+220R) so this
    # is regime allocation, NOT a rejection. RE-ENABLE TRIGGER: observer ledger scores
    # R1/R2 fades >55% for 2+ consecutive weeks (or the July 23+ review says so).
    "EURUSD_BOLL15": False,
    "GBPUSD_BOLL15": False,
    "USDCHF_BOLL15": False,
}

# ===================== 2a. BROKER PROFILE (July 21 2026) ====================
# >>> ONE switch decides WHICH SLICE of the book THIS running copy trades. <<<
# The same file runs on two MT5 terminals / two accounts; only this line differs:
#   "solo"     -> single-account mode: everything ENABLE says (today's default).
#   "standard" -> swap-charging broker (Eightcap): FX + indices + INTRADAY gold.
#                 The gold OVERNIGHT tier is auto-disabled here - it lives on the
#                 swap-free account (gold long swap measured -$70.51/lot/night).
#   "swapfree" -> swap-free broker: ONLY the gold overnight tier. FX/indices are
#                 auto-disabled (that broker's ~3-pip FX spreads kill those edges).
#   "both"     -> ONE command runs BOTH accounts: this process becomes a
#                 supervisor that spawns one "standard" child and one "swapfree"
#                 child (each owns its own terminal), restarts a crashed child
#                 after 60s, and stops both on Ctrl+C. The role reaches each
#                 child through an INTERNAL env var - you never pass parameters.
BROKER_PROFILE = "solo"

_ROLE = os.environ.get("MT5_BOT_ROLE", "")
if _ROLE:                     # set only by the 'both' supervisor for its children
    BROKER_PROFILE = _ROLE

# Gold strategies that hold overnight (1-10 nights) and bleed long swap on the
# standard broker - the slice that moves to the swap-free account at the split:
GOLD_OVERNIGHT_STRATS = {
    "XAUUSD_DONCH_TR", "XAUUSD_DONCH", "XAUUSD_VCX_A", "XAUUSD_VCX_B",
    "XAUUSD_MACROSS", "XAUUSD_BOS", "XAUUSD_ZBPIV", "XAUUSD_STRAD",
    "XAUUSD_H1A", "XAGUSD_ZBBOX",
}
# Deliberately NOT in the set:
#   XAUUSD_S5/S6/S3LO/S4/HAVW - intraday gold (median holds in hours; validated
#     at the standard broker's tighter spread; rare overnights cost less than
#     paying +$0.14 wider spread on every trade).
#   XAUUSD_CRASH - SHORT-only: gold shorts EARN +$0.29/night swap on the
#     standard broker; moving it would throw income away.

def _apply_broker_profile():
    """Flip ENABLE flags for this instance's role. A disabled-by-profile strategy
    logs as ':off' exactly like a hand-disabled one - no new code paths."""
    if BROKER_PROFILE in ("solo", "both"):
        return                # 'both' parent never trades - workers filter themselves
    if BROKER_PROFILE == "standard":
        for k in GOLD_OVERNIGHT_STRATS:
            if k in ENABLE:
                ENABLE[k] = False
        return
    if BROKER_PROFILE == "swapfree":
        for k in ENABLE:
            if k not in GOLD_OVERNIGHT_STRATS:
                ENABLE[k] = False
        return
    raise SystemExit(f"BROKER_PROFILE must be solo/standard/swapfree/both, got {BROKER_PROFILE!r}")

_apply_broker_profile()

# Resolve THIS process's credentials + keep worker files separate. solo keeps the
# unsuffixed filenames (state/tradebook continuity with everything logged so far).
_CRED_KEY = "swapfree" if BROKER_PROFILE == "swapfree" else "standard"
MT5_ACCOUNT = CREDENTIALS[_CRED_KEY]["account"]
MT5_PASSWORD = CREDENTIALS[_CRED_KEY]["password"]
MT5_SERVER = CREDENTIALS[_CRED_KEY]["server"]
MT5_TERMINAL_PATH = CREDENTIALS[_CRED_KEY]["terminal"]
_FILE_SUFFIX = "" if BROKER_PROFILE in ("solo", "both") else f"_{BROKER_PROFILE}"
_LOG_TAG = {"standard": "[STD] ", "swapfree": "[SWF] "}.get(BROKER_PROFILE, "")

# ================== 2c. CAPITAL-PROPORTIONAL SIZING (July 21 2026) ==========
# The whole book was CALIBRATED at ~$300 equity: FX 0.04 lots / $10.50 risk cap,
# gold+indices 0.01 min lot. These switches scale that calibration as capital
# grows, so risk stays a constant FRACTION of equity instead of shrinking away.
#   SIZING_MODE "off"    -> exactly today's fixed sizes (default).
#               "manual" -> multiplier = SIZING_MANUAL_CAPITAL / SIZING_BASE_CAPITAL.
#               "auto"   -> multiplier = live account equity at startup / base
#                           (re-read on every restart; restart after big equity moves).
# FX pairs: lots AND the $ risk caps scale continuously (0.04 -> 0.08 at 2x).
# Indices:  min-lot instruments scale in WHOLE lot-steps (0.01 -> 0.02 at 2x).
# XAUUSD:   scales ONLY if SCALE_XAUUSD=True (default False - gold stops/targets
#           are large; you chose to keep gold fixed until you say otherwise).
#           When True, gold lots scale in whole steps and the $1-$20 gold risk
#           guard scales with them (else every scaled trade would be skipped).
# Multiplier is clamped to [1.0, SIZING_MAX_MULT]: sizes never DROP below the
# calibration, and never jump more than the sanity ceiling in one go.
# The drawdown throttle still applies ON TOP of whatever this produces.
SIZING_MODE = "off"            # "off" | "manual" | "auto"
SIZING_BASE_CAPITAL = 300.0    # equity at which current LOTS/caps were calibrated
SIZING_MANUAL_CAPITAL = 300.0  # used only when SIZING_MODE = "manual"
SIZING_MAX_MULT = 4.0          # sanity ceiling (4x = calibrated book at $1200)
SCALE_XAUUSD = False           # True -> gold lots + gold risk guard scale too
SCALE_INDICES = True           # index CFDs scale in whole lot-steps


def _apply_capital_scaling(equity: float):
    """Mutates LOTS + the $ risk caps once at startup. Logged loudly so the
    active sizes are always visible in the first screen of the log."""
    global FX_MAX_RISK_USD, XAUUSD_MAX_RISK_USD
    if SIZING_MODE == "off":
        log("SIZING: mode=off - calibrated fixed sizes (FX 0.04 / $10.50 cap, minlot 0.01)")
        return
    ref = SIZING_MANUAL_CAPITAL if SIZING_MODE == "manual" else equity
    mult = max(1.0, min(ref / SIZING_BASE_CAPITAL, SIZING_MAX_MULT))
    steps = max(1, int(mult))              # whole-lot factor for min-lot symbols
    fx_syms = ("EURUSD", "GBPUSD", "USDCAD", "USDCHF")
    for k, inst in INSTANCES.items():
        s = inst["symbol"]
        if s in fx_syms:
            LOTS[k] = round(max(0.01, round(LOTS[k] * mult / 0.01) * 0.01), 2)
        elif s == "XAUUSD" and SCALE_XAUUSD:
            LOTS[k] = round(LOTS[k] * steps, 2)
        elif s not in ("XAUUSD", "XAGUSD") and SCALE_INDICES:
            LOTS[k] = round(LOTS[k] * steps, 2)
        if inst.get("fx_max_risk_usd"):
            inst["fx_max_risk_usd"] = round(inst["fx_max_risk_usd"] * mult, 2)
    FX_MAX_RISK_USD = round(FX_MAX_RISK_USD * mult, 2)
    if SCALE_XAUUSD:
        XAUUSD_MAX_RISK_USD = round(XAUUSD_MAX_RISK_USD * steps, 2)
    log(f"SIZING: mode={SIZING_MODE} ref=${ref:.0f} base=${SIZING_BASE_CAPITAL:.0f} "
        f"-> mult x{mult:.2f} (minlot steps x{steps}) | FX cap ${FX_MAX_RISK_USD:.2f}"
        f" | gold {'SCALED, guard $' + format(XAUUSD_MAX_RISK_USD, '.2f') if SCALE_XAUUSD else 'FIXED 0.01'}"
        f" | ex: EURUSD_E {LOTS.get('EURUSD_E')} lots, XAUUSD_S5 {LOTS.get('XAUUSD_S5')} lots")


# ==================== 2d. PROP-FIRM CHALLENGE MODE (July 22 2026) ===========
# Turns the book into a prop-challenge-compliant machine (FundedNext/The5ers/
# FTMO style rules). What it does when PROP_MODE=True:
#   * sizes every trade to ~PROP_RISK_PER_R_PCT of PROP_ACCOUNT_SIZE (via the
#     2c scaling machinery for FX/indices; gold gets its own conservative step
#     factor and the $ risk guard is re-anchored to the same per-trade budget)
#   * HARD DAILY STOP: if equity (incl. floating) drops PROP_DAILY_STOP_PCT
#     below the day's anchor (max of balance/equity at broker midnight), it
#     FLATTENS everything, cancels pendings, and blocks entries until the next
#     broker day - a buffer under the firm's 4-5% daily loss limit.
#   * HARD MAX STOP: equity below PROP_ACCOUNT_SIZE*(1-PROP_MAX_STOP_PCT)
#     flattens and HALTS permanently (manual restart required) - buffer under
#     the firm's 6-10% max loss.
#   * stacking caps drop to prop-safe values (firms treat stacked positions as
#     ONE trade idea with per-idea risk caps: 4 stacked gold longs = breach).
#   * optional PROP_WEEKEND_FLAT closes the book Friday 16:30 NY (FundedNext
#     bans weekend holds on FUNDED accounts; The5ers allows them - flip as needed).
PROP_MODE = False
PROP_ACCOUNT_SIZE = 6000.0      # the challenge account size
PROP_RISK_PER_R_PCT = 0.0075    # ~0.75% of the account per trade
PROP_DAILY_STOP_PCT = 0.035     # self-imposed daily kill (firm limit usually 4-5%)
PROP_MAX_STOP_PCT = 0.08        # self-imposed max kill (firm limit usually 10%)
PROP_WEEKEND_FLAT = False       # True -> flatten Fri 16:30 NY + no entries till Sunday
PROP_MAX_STACKED_GOLD = 1
PROP_MAX_PER_USD = 2
PROP_MAX_TOTAL = 4

_PROP = {"blocked_until": None, "halted": False, "day": None, "baseline": None}


def _apply_prop_mode():
    """Re-anchors sizing + caps to the prop account. Called at import when
    PROP_MODE is on; overrides SIZING_* so 2c does the FX/index scaling."""
    global SIZING_MODE, SIZING_MANUAL_CAPITAL, SIZING_MAX_MULT, SCALE_XAUUSD, SCALE_INDICES
    global MAX_STACKED_GOLD_LONGS, MAX_CONCURRENT_TOTAL, MAX_CONCURRENT_PER_USD
    global XAUUSD_MAX_RISK_USD
    if not PROP_MODE:
        return
    risk_usd = PROP_ACCOUNT_SIZE * PROP_RISK_PER_R_PCT          # per-trade budget
    mult = risk_usd / 10.50                                     # FX cap calibration
    SIZING_MODE = "manual"
    SIZING_MANUAL_CAPITAL = SIZING_BASE_CAPITAL * mult
    SIZING_MAX_MULT = max(SIZING_MAX_MULT, mult)
    SCALE_XAUUSD = False                                        # gold handled below
    SCALE_INDICES = True
    gold_steps = max(1, int(round(mult / 2)))                   # deliberately conservative:
    for k, inst in INSTANCES.items():                           # keeps median gold stops
        if inst["symbol"] == "XAUUSD":                          # inside the $ guard below
            LOTS[k] = round(LOTS[k] * gold_steps, 2)
    XAUUSD_MAX_RISK_USD = round(risk_usd, 2)
    MAX_STACKED_GOLD_LONGS = PROP_MAX_STACKED_GOLD
    MAX_CONCURRENT_TOTAL = PROP_MAX_TOTAL
    MAX_CONCURRENT_PER_USD = PROP_MAX_PER_USD


def _prop_flatten(reason):
    """Close every bot position and cancel every bot pending order. Best-effort
    with one retry pass; broker-side SLs remain as the backstop."""
    for _ in range(2):
        open_any = False
        for key2, inst2 in INSTANCES.items():
            for pos in positions_for(inst2):
                open_any = True
                close_position(inst2, pos, reason)
            for od in pending_for(inst2):
                cancel_order(key2, od.ticket)
        if not open_any:
            break
        time.sleep(2)


def _prop_guard(state) -> bool:
    """Returns True when NEW ENTRIES are blocked. Flattens on breach of the
    self-imposed daily/max stops. Anchors follow prop convention: daily anchor
    = max(balance, equity) at broker midnight; max anchor = initial account."""
    if not PROP_MODE:
        return False
    ps = state.setdefault("prop", {})
    if ps.get("halted"):
        return True
    acc2 = mt5.account_info()
    if acc2 is None:
        return True                                       # fail-safe: no data, no entries
    now_b = datetime.now(timezone.utc).astimezone(BTZ)
    bday = str(now_b.date())
    if ps.get("day") != bday:
        ps["day"] = bday
        ps["baseline"] = max(acc2.balance, acc2.equity)
        ps.pop("blocked_today", None)
        log(f"PROP: new broker day {bday} - daily anchor ${ps['baseline']:.2f} "
            f"(kill at ${ps['baseline'] * (1 - PROP_DAILY_STOP_PCT):.2f})")
    if acc2.equity <= PROP_ACCOUNT_SIZE * (1 - PROP_MAX_STOP_PCT):
        log(f"!!! PROP MAX-LOSS KILL: equity ${acc2.equity:.2f} <= "
            f"{PROP_MAX_STOP_PCT:.0%} under ${PROP_ACCOUNT_SIZE:.0f} - flattening, HALTED")
        _prop_flatten("prop_max_kill")
        ps["halted"] = True
        notify(f"PROP HALT: max-loss kill at ${acc2.equity:.2f}. Bot stopped entering; "
               f"manual review required.")
        return True
    if ps.get("blocked_today"):
        return True
    base = ps.get("baseline") or max(acc2.balance, acc2.equity)
    if acc2.equity <= base * (1 - PROP_DAILY_STOP_PCT):
        log(f"!! PROP DAILY KILL: equity ${acc2.equity:.2f} <= "
            f"{PROP_DAILY_STOP_PCT:.1%} under today's anchor ${base:.2f} - "
            f"flattening, no entries until the next broker day")
        _prop_flatten("prop_daily_kill")
        ps["blocked_today"] = True
        notify(f"PROP daily stop hit at ${acc2.equity:.2f} - book flattened, "
               f"entries resume next broker day.")
        return True
    if PROP_WEEKEND_FLAT:
        ny_now = datetime.now(timezone.utc).astimezone(NY)
        if (ny_now.weekday() == 4 and (ny_now.hour, ny_now.minute) >= (16, 30))                 or ny_now.weekday() == 5 or (ny_now.weekday() == 6 and ny_now.hour < 17):
            for _k, _i in INSTANCES.items():
                if positions_for(_i):
                    log("PROP: weekend-flat window - closing remaining positions")
                    _prop_flatten("prop_weekend_flat")
                    break
            return True
    return False


# (called below, after INSTANCES/caps exist - see the line after MAGIC2KEY)

DRY_RUN = False   # !! starts True: shadow-mode. Flip to False ONLY after the shadow phase. !!

# ====================== 2b2. SURVIVAL LADDER (equity gates) =================
# Big-ticket strategies arm THEMSELVES when account equity reaches these thresholds —
# change the numbers HERE, nothing else to edit. 0 = always armed. Basis: mc_capital.py
# Monte Carlo (July 2026, $150 start): full book = 20% chance of dipping under $50 in
# 30 days; gated book = 0.4%. Below the first gate the 15 small-risk strategies run.
EQUITY_GATE_GOLD_TREND = 250   # XAUUSD DONCH + MACROSS + BOS rr5 (~$8-12 risk/trade)
EQUITY_GATE_DAX_TREND  = 300   # GER40 DONCH + BOS               (~$9-10 risk/trade)
EQUITY_GATE_US30       = 600   # US30 DONCH                      (~$15 risk/trade)
EQUITY_GATE_ASIA       = 800   # JPN225 DONCH + HK50 MACROSS     (~$15-21 risk/trade)

# ====================== 2c. BROKER SYMBOL NAMES ============================
# The bot uses LOGICAL names (XAUUSD/EURUSD/GBPUSD/USDCAD/USDCHF) internally. If your
# broker appends a suffix to the tradeable symbol (e.g. "EURUSD.r", "XAUUSD.m",
# "GBPUSD.d"), set SYMBOL_SUFFIX ONCE and it is applied to every symbol. For a single
# odd name, put the EXACT broker string in SYMBOL_OVERRIDE (it wins over the suffix).
# Find the exact names in MT5: Market Watch -> right-click -> "Symbols".
SYMBOL_SUFFIX = ""                  # e.g.  ".r"   ".d"   ".m"   ".pro"   ".raw"
SYMBOL_OVERRIDE = {                 # exact per-symbol broker names (override the suffix)
    # "XAUUSD": "GOLD",
    "EURUSD": "EURUSD.i",
    "GBPUSD": "GBPUSD.i",
    "USDCAD": "USDCAD.i",
    "USDCHF": "USDCHF.i",
}


def broker_sym(logical: str) -> str:
    """Translate a logical symbol to the broker's exact tradeable name (suffix/override)."""
    return SYMBOL_OVERRIDE.get(logical, logical + SYMBOL_SUFFIX)


# ====================== 2b. EXIT MODE (gold S5 runner only) =================
# >>> MASTER TOGGLE for S5's trailing-stop "runner" exit. <<<
#   True  = runner (P5): NO take-profit; SL -> breakeven at +1R; trail 1xATR after +2R.
#           Co-validated long-only: +45.6R, PF 1.233, holdout +26.2R (best holdout).
#   False = fixed (P0): take-profit at rr (2.0) + breakeven at +1.5R.
#           Co-validated long-only: +35.7R, PF 1.191, holdout +24.7R.
# Both are positive on both splits; runner has the stronger edge. Scoped to gold S5 ONLY
# (the only strategy with trailing-lab evidence — S6/S4/FX always use fixed exits).
SL_TRAILING_S5 = True

# Runner trail parameters (used only when SL_TRAILING_S5 = True):
RUNNER_BE_R = 1.0                 # move SL to breakeven at +1R
RUNNER_TRAIL_START_R = 2.0        # begin trailing once +2R is reached
RUNNER_TRAIL_ATR_MULT = 2.0       # trail distance = 2.0 x ATR50(entry). Sweep (M1-resolved,
                                  # S5 long-only): 2.0x = +51.4R PF 1.26 ho +33.3 vs the old
                                  # 1.0x = +45.6R ho +26.2; smooth plateau 1.5-3.0 all better
                                  # than 1.0 -> tight trails cap gold's bull legs (user's catch).
RUNNER_MIN_SL_STEP = 0.05         # only send SL changes larger than this (price units)

# ====================== 2d. S6-R REHAB PARAMETERS ==========================
# S6 was disabled at PF 0.99; the July-2026 rehab (s6_rehab_lab.py) fixed it with TWO
# changes, validated train +42.2 / holdout +12.4, 6/6 years, plateau disp 2.3-2.6:
S6R_DISP_ATR_MULT = 2.4    # displacement bar must be >= 2.4 x ATR50 (was 2.2)

# ====================== 2e. GOLD-TREND $ RISK SIZER (Aug 2026, owner) ========
# Per-trade $ budget for every XAUUSD instance in the "trend"/"trend_trail"/
# "zone" risk modes (DONCH / DONCH_TR / VCX / MACROSS / CRASH / BOS / ZBPIV;
# $1 of gold move = $1 P&L per 0.01 lot). OWNER DECISION Aug 2026: the guard
# now SIZES the lot DOWN (in broker volume steps, from the configured lot as
# ceiling) so the trade risks AT MOST XAUUSD_MAX_RISK_USD — mirroring the FX
# dollar-risk sizing — instead of skipping the trade outright. A trade is
# skipped ONLY when even the broker-minimum 0.01 lot would risk more than the
# cap, or the sized risk falls under the MIN floor. (Pre-Aug-2026 behavior:
# hard skip on any breach at the configured lot; that skipped wide-ATR
# gold-trend entries the backtests count — often the big trend winners.)
XAUUSD_MIN_RISK_USD = 1.0
XAUUSD_MAX_RISK_USD = 20.0
S6R_REQUIRE_BIAS5 = True   # 5m swing_bias must be +1 (structure gate — THE fix)

# ============================ 3. SAFETY SETTINGS ============================
# TIMEZONE — the bot converts broker bar times to NY for ALL session filters. Most MT5
# brokers run UTC+2 (winter) / UTC+3 (summer), so a FIXED offset breaks twice a year.
# BROKER_TZ_AUTO=True auto-detects the broker's current UTC offset from live data each day
# and on every DST shift (forcing a clean cache rebuild) — so the filters never drift.
BROKER_TZ_AUTO = True             # auto-detect & track the broker offset (recommended)
BROKER_TZ = "Etc/GMT-3"           # manual fallback, used only when BROKER_TZ_AUTO=False
DEVIATION_POINTS = 30
# NOTE: the drawdown kill-switch has been REMOVED — the bot runs 24/7 until YOU stop it.
# There is no automatic halt or auto-close on drawdown. Monitor equity yourself.
POLL_SECONDS = 5
FULL_RESYNC_BARS = 288
STATE_FILE = f"live_bot_state{_FILE_SUFFIX}.json"
LOG_FILE = f"live_bot{_FILE_SUFFIX}.log"
TRADEBOOK_CSV = f"live_tradebook{_FILE_SUFFIX}.csv"
POSITIONS_CSV = f"live_positions{_FILE_SUFFIX}.csv"
PNL_DAILY_CSV = f"live_pnl_daily{_FILE_SUFFIX}.csv"

# ====================== PHONE NOTIFICATIONS (Telegram) =====================
# Get a phone push whenever a trade opens/closes. Setup (5 min, free):
#   1. In Telegram, message @BotFather -> /newbot -> follow prompts -> copy the TOKEN.
#   2. Message @userinfobot (or your new bot) -> it replies with your numeric chat id.
#   3. Paste both below and set NOTIFY_ENABLED = True. Install Telegram on your phone.
# A notification failure NEVER affects trading — it is fire-and-forget with a short timeout.
NOTIFY_ENABLED = True            # flip True after filling token + chat id
TELEGRAM_TOKEN = "<<<PASTE-YOUR-TELEGRAM-TOKEN>>>"               # e.g. "1234567890:AA...."  from @BotFather
TELEGRAM_CHAT_ID = "<<<PASTE-YOUR-CHAT-ID>>>"             # e.g. "987654321"           from @userinfobot
NOTIFY_ON_OPEN = True             # ping when a new trade is placed
NOTIFY_ON_CLOSE = True            # ping when a trade closes (with P&L)

# ====================== PENDING LIMIT ORDERS (P1 zones) ====================
# P1 strategies enter with a broker-side LIMIT order in the FVG-overlap zone.
# The order carries SL/TP and expires after LIMIT_EXPIRY_BARS bars of the strategy's
# timeframe (server-side ORDER_TIME_SPECIFIED; if the broker rejects that, the bot
# falls back to GTC and cancels it itself). Matches the backtest's 30-bar wait window.
LIMIT_EXPIRY_BARS = 30

# ====================== GOLD STACKING GOVERNOR =============================
# S5, H1A and STRAD are all gold-LONG strategies; backtest overlap analysis shows they
# hold simultaneous positions ~14% of in-position time (max 3 at once) — moments where
# gold exposure silently doubles/triples. This cap SKIPS a new gold-long entry when the
# count of open gold-long positions (+ pending gold buy orders) is already at the limit.
# Pure risk control — does not alter any strategy's signals.
MAX_STACKED_GOLD_LONGS = 4   # raised 3->4 (July 2026 re-check after adding DONCH+MACROSS =
                             # 7 gold-long strategies): cap4 = +188.2R/maxDD -47.8 (-$419 @0.01
                             # lot) R/DD 3.94 vs cap3 = +176.6/-45.8 R/DD 3.86; cap5+ adds
                             # nothing (max concurrency 5, rarely reached). Worst simultaneous
                             # all-stop loss ~$118 (3-4 large-ATR gold longs at once).

# ====================== BOOK-WIDE CONCURRENCY GOVERNOR =====================
# Correlation protection (user, July 2026): EURUSD/GBPUSD/XAU move OPPOSITE to USDCAD/USDCHF,
# so a single USD shock can fire many aligned trades at once. Backtest (all 18 strategies):
# max 7 concurrent overall, max 6 betting the SAME USD direction. Caps below limit that:
#   MAX_CONCURRENT_TOTAL   : hard ceiling on ALL simultaneously-open positions.
#   MAX_CONCURRENT_PER_USD : ceiling on open positions betting the SAME USD direction
#                            (long EUR/GBP/XAU or short CAD/CHF = "USD-down"; the mirror =
#                            "USD-up"). This is the real shock-limiter.
# Sweep: total=6 & per-USD=4 keeps 98% of backtest R while capping any USD shock to 4 trades
# (worst simultaneous FX loss ~4x$8=$32 vs 6x=$48 uncapped). per-USD=3 costs 10% -> too tight.
# 0 disables either cap. Gold-long stacking is ALSO still bounded by MAX_STACKED_GOLD_LONGS.
MAX_CONCURRENT_TOTAL = 6
MAX_CONCURRENT_PER_USD = 4

# ====================== FX DOLLAR-RISK SIZING (MIN floor + MAX cap) ========
# FX entries (NOT gold) are lot-sized from the trade's own stop distance:
#   FX_MIN_RISK_USD  > 0 : size the lot UP so the trade risks AT LEAST this many $.
#   FX_MAX_RISK_USD  > 0 : size the lot DOWN so the trade risks AT MOST this many $.
# Both use $risk-per-lot from mt5.order_calc_profit; result is clamped to the broker's
# volume_step / volume_min / volume_max. If BOTH are set, the cap wins on wide-stop trades
# and the floor lifts tiny-stop trades — as long as MIN <= MAX they never conflict.
# User change (July 2026): switched from a $7 FLOOR to a $8 CAP so no single FX trade can
# lose more than ~$8. NOTE: the broker minimum lot is 0.01 — if a stop is so wide that even
# 0.01 lot risks more than the cap, the trade is SKIPPED when FX_MAX_RISK_SKIP=True
# (backtest: this skips <2% of trades; verified not to dent the edge).
FX_MIN_RISK_USD = 0.0   # floor OFF (was 7.0) — replaced by the MAX cap below
FX_MAX_RISK_USD = 10.5  # raised 8.0 -> 10.5 July 16 2026 with the 0.04 lot step-up
FX_MAX_RISK_SKIP = True # skip an FX trade if even 0.01 lot would exceed FX_MAX_RISK_USD
# GOLD note: gold rides the 0.01-lot broker minimum and CANNOT be sized below it, so a
# high-ATR gold trade can still risk ~$25-35. Capping gold would mean SKIPPING those
# high-volatility entries (often the big trend winners) — left uncapped by design.

# ====================== BOOK DRAWDOWN THROTTLE + ALERTS =====================
# Backtested July 2026 on the combined 17-strategy book (2020-2025, daily equity):
#   baseline: +449.7R, maxDD -62.0R  ->  this rule: +355.1R, maxDD -42.1R
#   (gives up ~21% of profit to cut the worst drawdown ~30%; net/DD 7.3 -> 8.4;
#   every swept neighbor rule improved the ratio — plateau, not knife-edge).
# Mechanism: realized book R (sum of tradebook r_multiple) vs its high-water mark.
# When book DD < RISK_THROTTLE_DD_R -> new trades sized x RISK_THROTTLE_MULT
# (FX lots + FX_MIN_RISK_USD scale; gold already rides broker-minimum 0.01 lots and
# cannot shrink further). Full size restores when DD recovers above RESTORE_R.
# Telegram + log alerts fire at every ALERT level crossing and on throttle on/off.
RISK_THROTTLE_ENABLED = True
RISK_THROTTLE_DD_R = -20.0        # throttle when realized book DD is worse than this
RISK_THROTTLE_MULT = 0.5          # size multiplier while throttled
RISK_THROTTLE_RESTORE_R = -10.0   # restore full size when DD recovers above this
RISK_ALERT_LEVELS_R = (-20.0, -40.0, -55.0)   # phone alerts at these book-DD levels
_RISK_MULT = {"m": 1.0}           # runtime cache (rebuilt from the tradebook at startup)

# Gold deep-history stitching (FX brokers serve plenty of H1, so FX needs no baseline)
BASELINE_5M_CSV = "data/latest/XAUUSD5.csv"
BASELINE_15M_CSV = "data/latest/XAUUSD15.csv"
STITCH_PATTERN_BARS = 96
STITCH_MATCH_OK = 0.50
STITCH_MATCH_MARGIN = 0.30

NY = ZoneInfo("America/New_York")
BTZ = ZoneInfo(BROKER_TZ)
LIVE_ATR = {}   # symbol -> latest ATR50 of its trade TF (runner-trail fallback after restarts)
LIVE_TRAIL_BAR = {}  # feed -> dict(close, atr) of the last CLOSED bar (exit="trail")


def _half(sym_spread):  # stop pad = half the round-trip spread (mirrors the backtest)
    return round(sym_spread / 2, 6)


# ============================ 4. INSTANCE TABLE ============================
# Every tradeable (symbol, strategy). magic must be GLOBALLY UNIQUE.
# risk_mode: "points" (gold; min/max in price points) or "atr" (FX; 0.55..8.0 x ATR50).
# exit: "runner" (gold S5) or "fixed" (TP at rr, optional BE at be_r).
INSTANCES = {
    "XAUUSD_S5": dict(symbol="XAUUSD", strat="S5", engine="gold", magic=50001, eval="s5",
                      exit="runner" if SL_TRAILING_S5 else "fixed",
                      rr=STRAT["S5"]["rr"], be_r=STRAT["S5"]["be_trigger_r"],
                      long_only=True, risk_mode="points",
                      min_risk=STRAT["S5"]["min_risk"], max_risk=STRAT["S5"]["max_risk"],
                      stop_pad=0.30, max_hold_bars=STRAT["S5"]["max_hold_bars"],
                      max_tpd=STRAT["S5"]["max_trades_per_day"], bar_seconds=300),
    "XAUUSD_S6": dict(symbol="XAUUSD", strat="S6", engine="gold", magic=60001, eval="s6",
                      exit="fixed", rr=STRAT["S6"]["rr"], be_r=0.0, risk_mode="points",
                      min_risk=STRAT["S6"]["min_risk"], max_risk=STRAT["S6"]["max_risk"],
                      stop_pad=0.30, max_hold_bars=STRAT["S6"]["max_hold_bars"],
                      max_tpd=STRAT["S6"]["max_trades_per_day"], bar_seconds=300),
    "XAUUSD_S4": dict(symbol="XAUUSD", strat="S4", engine="gold", magic=40001, eval="s4",
                      exit="fixed", rr=STRAT["S4"]["rr"], be_r=0.0, risk_mode="points",
                      min_risk=STRAT["S4"]["min_risk"], max_risk=STRAT["S4"]["max_risk"],
                      stop_pad=0.30, max_hold_bars=STRAT["S4"]["max_hold_bars"],
                      max_tpd=STRAT["S4"]["max_trades_per_day"], bar_seconds=300),
    "EURUSD_E": dict(symbol="EURUSD", strat="E", engine="fx", magic=80001, eval="fx",
                     cfg=LS.FX_STRATS["EURUSD-E"], exit="fixed",
                     rr=LS.FX_STRATS["EURUSD-E"]["rr"], be_r=LS.FX_STRATS["EURUSD-E"]["be_r"],
                     risk_mode="atr", stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                     max_hold_bars=LS.FX_STRATS["EURUSD-E"]["max_hold"], max_tpd=LS.MAX_TPD,
                     bar_seconds=3600),
    "GBPUSD_E": dict(symbol="GBPUSD", strat="E", engine="fx", magic=90001, eval="fx",
                     cfg=LS.FX_STRATS["GBPUSD-E"], exit="fixed",
                     rr=LS.FX_STRATS["GBPUSD-E"]["rr"], be_r=LS.FX_STRATS["GBPUSD-E"]["be_r"],
                     risk_mode="atr", stop_pad=_half(LS.FX_SPREADS["GBPUSD"]),
                     max_hold_bars=LS.FX_STRATS["GBPUSD-E"]["max_hold"], max_tpd=LS.MAX_TPD,
                     bar_seconds=3600),
    "USDCAD_A": dict(symbol="USDCAD", strat="A", engine="fx", magic=70001, eval="fx",
                     cfg=LS.FX_STRATS["USDCAD-A"], exit="fixed",
                     rr=LS.FX_STRATS["USDCAD-A"]["rr"], be_r=LS.FX_STRATS["USDCAD-A"]["be_r"],
                     risk_mode="atr", stop_pad=_half(LS.FX_SPREADS["USDCAD"]),
                     max_hold_bars=LS.FX_STRATS["USDCAD-A"]["max_hold"], max_tpd=LS.MAX_TPD,
                     bar_seconds=3600),
    "USDCHF_A": dict(symbol="USDCHF", strat="A", engine="fx", magic=71001, eval="fx",
                     cfg=LS.FX_STRATS["USDCHF-A"], exit="fixed",   # SHORT-ONLY via cfg["sides"]
                     rr=LS.FX_STRATS["USDCHF-A"]["rr"], be_r=LS.FX_STRATS["USDCHF-A"]["be_r"],
                     risk_mode="atr", stop_pad=_half(LS.FX_SPREADS["USDCHF"]),
                     max_hold_bars=LS.FX_STRATS["USDCHF-A"]["max_hold"], max_tpd=LS.MAX_TPD,
                     bar_seconds=3600),
    # Gold on its OWN H1 feed (second gold timeframe -> separate "feed"). LONG-ONLY A family:
    # +23.8R, PF 1.212, maxDD -9.6R, positive 12/18 years (sideways_lab.py).
    "XAUUSD_H1A": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="H1A", engine="fx",
                       magic=51001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-H1A"], exit="fixed",
                       rr=LS.FX_STRATS["XAUUSD-H1A"]["rr"], be_r=LS.FX_STRATS["XAUUSD-H1A"]["be_r"],
                       risk_mode="atr", stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                       max_hold_bars=LS.FX_STRATS["XAUUSD-H1A"]["max_hold"], max_tpd=LS.MAX_TPD,
                       bar_seconds=3600),
    # EURUSD 30m quiet-hours Bollinger fade (fade 2-sigma band touch toward the 20-SMA).
    # +54.9R, PF 1.10, 8/9 years positive, ~118 trades/yr. STRICTLY a low-cost edge —
    # DISABLE if the broker widens EURUSD spreads (dies at ~1.2 pip).
    "EURUSD_BOLL30": dict(symbol="EURUSD", feed="EURUSD_30", strat="BOLL30", engine="fx",
                          magic=81001, eval="fx", cfg=LS.FX_STRATS["EURUSD-BOLL30"],
                          exit="fixed", rr=None, be_r=None, risk_mode="boll",
                          stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                          max_hold_bars=LS.FX_STRATS["EURUSD-BOLL30"]["max_hold"],
                          max_tpd=LS.FX_STRATS["EURUSD-BOLL30"]["max_tpd"], bar_seconds=1800),
    # Gold H1 consolidation-breakout, LONG-only, close-confirmed (user's straddle idea,
    # validated: +43.6R, PF 1.78, maxDD -5.7R, 13/18 years). Shares the XAUUSD_H1 feed.
    "XAUUSD_STRAD": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="STRAD", engine="fx",
                         magic=52001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-STRAD"],
                         exit="fixed", rr=None, be_r=None, risk_mode="strad",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                         max_hold_bars=LS.FX_STRATS["XAUUSD-STRAD"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-STRAD"]["max_tpd"], bar_seconds=3600),
    # S3 long-only: NY-morning (09:00-11:55) bull-FVG retest with displacement + bias align.
    # +26.6R, PF 1.21, train +18.9/ho +7.6, maxDD -13.7R; daily-R corr to S5 just +0.263
    # (overlap check July 2026) -> genuine diversification. BE at +1R, TP 2R.
    "XAUUSD_S3LO": dict(symbol="XAUUSD", strat="S3LO", engine="gold", magic=30001, eval="s3",
                        exit="fixed", rr=2.0, be_r=1.0, risk_mode="points",
                        min_risk=1.0, max_risk=30.0, stop_pad=0.30, max_hold_bars=96,
                        max_tpd=2, bar_seconds=300),
    # Opposing-FVG reversal (P1): LIMIT entry in the FVG-overlap zone, SL/TP attached to
    # the pending order (fully broker-side), expires after LIMIT_EXPIRY_BARS bars.
    "GBPUSD_P1": dict(symbol="GBPUSD", strat="P1", engine="fx", magic=91001, eval="fx",
                      cfg=LS.FX_STRATS["GBPUSD-P1"], exit="fixed",
                      rr=LS.FX_STRATS["GBPUSD-P1"]["rr"], be_r=None, risk_mode="p1",
                      stop_pad=_half(LS.FX_SPREADS["GBPUSD"]),
                      max_hold_bars=LS.FX_STRATS["GBPUSD-P1"]["max_hold"],
                      max_tpd=LS.FX_STRATS["GBPUSD-P1"]["max_tpd"], bar_seconds=3600),
    "EURUSD_P1_30": dict(symbol="EURUSD", feed="EURUSD_30", strat="P1", engine="fx",
                         magic=82001, eval="fx", cfg=LS.FX_STRATS["EURUSD-P1-30"],
                         exit="fixed", rr=LS.FX_STRATS["EURUSD-P1-30"]["rr"], be_r=None,
                         risk_mode="p1", stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                         max_hold_bars=LS.FX_STRATS["EURUSD-P1-30"]["max_hold"],
                         max_tpd=LS.FX_STRATS["EURUSD-P1-30"]["max_tpd"], bar_seconds=1800),
    # BOLL15 family: quiet-hours Bollinger fade at M15 (m15_deep_validation.py, 18.5y
    # HistData M15, train <=2023 spans 5 macro regimes). Same signal machinery as BOLL30.
    # LOW-COST edges — preflight spread warning is the tripwire (GBP alone survives 3x).
    "EURUSD_BOLL15": dict(symbol="EURUSD", feed="EURUSD_15", strat="BOLL15", engine="fx",
                          magic=83001, eval="fx", cfg=LS.FX_STRATS["EURUSD-BOLL15"],
                          exit="fixed", rr=None, be_r=None, risk_mode="boll",
                          stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                          max_hold_bars=LS.FX_STRATS["EURUSD-BOLL15"]["max_hold"],
                          max_tpd=LS.FX_STRATS["EURUSD-BOLL15"]["max_tpd"], bar_seconds=900),
    "GBPUSD_BOLL15": dict(symbol="GBPUSD", feed="GBPUSD_15", strat="BOLL15", engine="fx",
                          magic=92001, eval="fx", cfg=LS.FX_STRATS["GBPUSD-BOLL15"],
                          exit="fixed", rr=None, be_r=None, risk_mode="boll",
                          stop_pad=_half(LS.FX_SPREADS["GBPUSD"]),
                          max_hold_bars=LS.FX_STRATS["GBPUSD-BOLL15"]["max_hold"],
                          max_tpd=LS.FX_STRATS["GBPUSD-BOLL15"]["max_tpd"], bar_seconds=900),
    "USDCHF_BOLL15": dict(symbol="USDCHF", feed="USDCHF_15", strat="BOLL15", engine="fx",
                          magic=73001, eval="fx", cfg=LS.FX_STRATS["USDCHF-BOLL15"],
                          exit="fixed", rr=None, be_r=None, risk_mode="boll",
                          stop_pad=_half(LS.FX_SPREADS["USDCHF"]),
                          max_hold_bars=LS.FX_STRATS["USDCHF-BOLL15"]["max_hold"],
                          max_tpd=LS.FX_STRATS["USDCHF-BOLL15"]["max_tpd"], bar_seconds=900),
    # GOLD TREND strategies (July 2026, gold_discovery_lab.py — gold TRENDS where FX
    # mean-reverts). Both LONG-only, share the XAUUSD_H1 feed, risk_mode="trend" (structural
    # stop = signal_close - 2xATR, TP = entry + 3xrisk, time exit 96 bars, no BE). Corr to
    # the existing gold book +0.14/+0.16, positive across all regimes, 3x-cost-immune.
    # SURVIVAL LADDER (July 15 2026, mc_capital.py): at $150 equity the $9-11/trade trend
    # instances give ~20% odds of dipping under $50 within 30 days (full-book MC, 4000
    # paths, 2019+ data). Gated at $250 (gold) / $300 (DAX); they ARM THEMSELVES when the
    # low-risk book earns the buffer. Flip equity_min to 0 only by explicit user decision.
    "XAUUSD_DONCH": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="DONCH", engine="fx",
                         magic=53001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-DONCH"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]), equity_min=EQUITY_GATE_GOLD_TREND,
                         max_hold_bars=LS.FX_STRATS["XAUUSD-DONCH"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-DONCH"]["max_tpd"], bar_seconds=3600),
    # EXIT-UPGRADE twin (July 2026): identical DONCH-96 entries, chandelier 5xATR trail
    # (owner-selected cell) instead of the fixed 3R target (+205.8R vs +128.7R on
    # TZ-correct 2008-2026, both splits +, 3x-cost immune; verify_donch_trail.py).
    # exit="trail": no TP at entry; manage_positions raises the SL to close - 5xATR on
    # every CLOSED H1 bar (monotonic; the broker-side SL does the exiting).
    # DISABLED by default - mutually exclusive with XAUUSD_DONCH (same entries).
    "XAUUSD_DONCH_TR": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="DONCH", engine="fx",
                            magic=53101, eval="fx", cfg=LS.FX_STRATS["XAUUSD-DONCH-TR"],
                            exit="trail", rr=None, be_r=None, risk_mode="trend_trail",
                            stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                            equity_min=EQUITY_GATE_GOLD_TREND,
                            max_hold_bars=LS.FX_STRATS["XAUUSD-DONCH-TR"]["max_hold"],
                            max_tpd=LS.FX_STRATS["XAUUSD-DONCH-TR"]["max_tpd"],
                            bar_seconds=3600),
    # VCX cells (July 2026, owner-selected from the discovery ledger): compression
    # box breakout, fixed rr3 target -> plain "trend" machinery, no new code paths.
    # OVERLAP: ~96% with XAUUSD_DONCH / each other (they stack the same longs).
    "XAUUSD_VCX_A": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="VCX", engine="fx",
                         magic=53401, eval="fx", cfg=LS.FX_STRATS["XAUUSD-VCX-A"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                         equity_min=EQUITY_GATE_GOLD_TREND,
                         max_hold_bars=LS.FX_STRATS["XAUUSD-VCX-A"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-VCX-A"]["max_tpd"], bar_seconds=3600),
    "XAUUSD_VCX_B": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="VCX", engine="fx",
                         magic=53501, eval="fx", cfg=LS.FX_STRATS["XAUUSD-VCX-B"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                         equity_min=EQUITY_GATE_GOLD_TREND,
                         max_hold_bars=LS.FX_STRATS["XAUUSD-VCX-B"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-VCX-B"]["max_tpd"], bar_seconds=3600),
    "XAUUSD_MACROSS": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="MACROSS", engine="fx",
                           magic=54001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-MACROSS"],
                           exit="fixed", rr=None, be_r=None, risk_mode="trend",
                           stop_pad=_half(LS.FX_SPREADS["XAUUSD"]), equity_min=EQUITY_GATE_GOLD_TREND,
                           max_hold_bars=LS.FX_STRATS["XAUUSD-MACROSS"]["max_hold"],
                           max_tpd=LS.FX_STRATS["XAUUSD-MACROSS"]["max_tpd"], bar_seconds=3600),
    # CRASH-INSURANCE SHORT (July 2026, metal_short_hunt.py): 2xATR red bar closing in its
    # bottom 25% + H4 bias bearish -> short. Job = defend the 7-strategy gold-long stack in
    # a bear regime (2011-15 +42R, 2013 +23R, 2022 +10R); costs ~-10R/yr in strong bulls.
    "XAUUSD_CRASH": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="CRASH", engine="fx",
                         magic=57001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-CRASH"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                         max_hold_bars=LS.FX_STRATS["XAUUSD-CRASH"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-CRASH"]["max_tpd"], bar_seconds=3600),
    # INDEX TREND (July 2026): Donchian-long on S&P 500 + DAX. Same signal_DONCH/risk_mode=
    # "trend" machinery as gold. Cross-feed verified (HistData), 18/18 neighbors, 2x-cost
    # immune. Indices ride min 0.01 lot (like gold) and are USD-NEUTRAL for the governor.
    "SPX500_DONCH": dict(symbol="SPX500", strat="DONCH", engine="fx", magic=55001,
                         eval="fx", cfg=LS.FX_STRATS["SPX500-DONCH"], exit="fixed",
                         rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["SPX500"]),
                         max_hold_bars=LS.FX_STRATS["SPX500-DONCH"]["max_hold"],
                         max_tpd=LS.FX_STRATS["SPX500-DONCH"]["max_tpd"], bar_seconds=3600),
    "GER40_DONCH": dict(symbol="GER40", strat="DONCH", engine="fx", magic=56001,
                        eval="fx", cfg=LS.FX_STRATS["GER40-DONCH"], exit="fixed",
                        rr=None, be_r=None, risk_mode="trend", equity_min=EQUITY_GATE_DAX_TREND,
                        stop_pad=_half(LS.FX_SPREADS["GER40"]),
                        max_hold_bars=LS.FX_STRATS["GER40-DONCH"]["max_hold"],
                        max_tpd=LS.FX_STRATS["GER40-DONCH"]["max_tpd"], bar_seconds=3600),
    # USDCHF 30m quiet-hours RSI(14) overbought fade, SHORT-ONLY (side-split validated
    # July 2026): +23.5R, PF 1.62, WR 52%, maxDD -4.5R, positive 9/9 years, survives 3x
    # cost. Overlap vs USDCHF-A: 1% of trades concurrent, daily-R corr -0.03 -> independent.
    # AVWAP FADE (July 2026): daily-AVWAP stretch fade on GBPUSD H1, SHORT-only. Reuses the
    # "boll" risk_mode verbatim (entry-relative stop, absolute target = the AVWAP value).
    "GBPUSD_AVWAP": dict(symbol="GBPUSD", feed="GBPUSD", strat="AVWAP", engine="fx",
                         magic=58001, eval="fx", cfg=LS.FX_STRATS["GBPUSD-AVWAP"],
                         exit="fixed", rr=None, be_r=None, risk_mode="boll",
                         stop_pad=_half(LS.FX_SPREADS["GBPUSD"]),
                         max_hold_bars=LS.FX_STRATS["GBPUSD-AVWAP"]["max_hold"],
                         max_tpd=LS.FX_STRATS["GBPUSD-AVWAP"]["max_tpd"], bar_seconds=3600),
    # STRUCTURE-BREAK CONTINUATION (July 2026, concepts_wave2_lab): pivot-high cross ->
    # momentum long. Gold rr5 (exit grid), DAX rr3. Same "trend" machinery as DONCH.
    "XAUUSD_BOS": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="BOS", engine="fx",
                       magic=59001, eval="fx", cfg=LS.FX_STRATS["XAUUSD-BOS"],
                       exit="fixed", rr=None, be_r=None, risk_mode="trend",
                       stop_pad=_half(LS.FX_SPREADS["XAUUSD"]), equity_min=EQUITY_GATE_GOLD_TREND,
                       max_hold_bars=LS.FX_STRATS["XAUUSD-BOS"]["max_hold"],
                       max_tpd=LS.FX_STRATS["XAUUSD-BOS"]["max_tpd"], bar_seconds=3600),
    "GER40_BOS": dict(symbol="GER40", feed="GER40", strat="BOS", engine="fx",
                      magic=59501, eval="fx", cfg=LS.FX_STRATS["GER40-BOS"],
                      exit="fixed", rr=None, be_r=None, risk_mode="trend",
                      stop_pad=_half(LS.FX_SPREADS["GER40"]), equity_min=EQUITY_GATE_DAX_TREND,
                      max_hold_bars=LS.FX_STRATS["GER40-BOS"]["max_hold"],
                      max_tpd=LS.FX_STRATS["GER40-BOS"]["max_tpd"], bar_seconds=3600),
    # EQUITY-GATED index watchlist: validated but $15-21 risk/trade at min lot. The
    # equity_min gate arms each one automatically when account equity crosses it.
    "US30_DONCH": dict(symbol="US30", feed="US30", strat="DONCH", engine="fx",
                       magic=55501, eval="fx", cfg=LS.FX_STRATS["US30-DONCH"],
                       exit="fixed", rr=None, be_r=None, risk_mode="trend",
                       stop_pad=_half(LS.FX_SPREADS["US30"]), equity_min=EQUITY_GATE_US30,
                       max_hold_bars=LS.FX_STRATS["US30-DONCH"]["max_hold"],
                       max_tpd=LS.FX_STRATS["US30-DONCH"]["max_tpd"], bar_seconds=3600),
    "JPN225_DONCH": dict(symbol="JPN225", feed="JPN225", strat="DONCH", engine="fx",
                         magic=55601, eval="fx", cfg=LS.FX_STRATS["JPN225-DONCH"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["JPN225"]), equity_min=EQUITY_GATE_ASIA,
                         max_hold_bars=LS.FX_STRATS["JPN225-DONCH"]["max_hold"],
                         max_tpd=LS.FX_STRATS["JPN225-DONCH"]["max_tpd"], bar_seconds=3600),
    "HK50_MACROSS": dict(symbol="HK50", feed="HK50", strat="MACROSS", engine="fx",
                         magic=55701, eval="fx", cfg=LS.FX_STRATS["HK50-MACROSS"],
                         exit="fixed", rr=None, be_r=None, risk_mode="trend",
                         stop_pad=_half(LS.FX_SPREADS["HK50"]), equity_min=EQUITY_GATE_ASIA,
                         max_hold_bars=LS.FX_STRATS["HK50-MACROSS"]["max_hold"],
                         max_tpd=LS.FX_STRATS["HK50-MACROSS"]["max_tpd"], bar_seconds=3600),
    # ── ZONE BREAKOUT family (zone_breakout_lab.py July 2026, magics 541xx-543xx).
    # BOTH directions, entry-relative 2*ATR stop, fixed rr TP (risk_mode="zone").
    # PIVOT_K=5 house rule enforced inside live_signals._pivot_arrays. All ship
    # ENABLE=False. Gold instance sits under the XAUUSD_MIN/MAX_RISK_USD guard —
    # at 2026 H4 ATR ($30-40) most gold H4 signals will be SKIPPED by the $20 cap.
    "XAUUSD_ZBPIV": dict(symbol="XAUUSD", feed="XAUUSD_H4", strat="ZBPIV", engine="fx",
                         magic=54101, eval="fx", cfg=LS.FX_STRATS["XAUUSD-ZBPIV"],
                         exit="fixed", rr=None, be_r=None, risk_mode="zone",
                         stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                         equity_min=EQUITY_GATE_GOLD_TREND,
                         max_hold_bars=LS.FX_STRATS["XAUUSD-ZBPIV"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAUUSD-ZBPIV"]["max_tpd"], bar_seconds=14400),
    "XAGUSD_ZBBOX": dict(symbol="XAGUSD", feed="XAGUSD", strat="ZBBOX", engine="fx",
                         magic=54201, eval="fx", cfg=LS.FX_STRATS["XAGUSD-ZBBOX"],
                         exit="fixed", rr=None, be_r=None, risk_mode="zone",
                         stop_pad=_half(LS.FX_SPREADS["XAGUSD"]),
                         equity_min=400,   # ~$15-30 risk/trade at 0.01 lot (50oz)
                         max_hold_bars=LS.FX_STRATS["XAGUSD-ZBBOX"]["max_hold"],
                         max_tpd=LS.FX_STRATS["XAGUSD-ZBBOX"]["max_tpd"], bar_seconds=3600),
    "SPX500_ZBPIV": dict(symbol="SPX500", feed="SPX500_D1", strat="ZBPIV", engine="fx",
                         magic=54301, eval="fx", cfg=LS.FX_STRATS["SPX500-ZBPIV"],
                         exit="fixed", rr=None, be_r=None, risk_mode="zone",
                         stop_pad=_half(LS.FX_SPREADS["SPX500"]),
                         equity_min=250,   # ~$4-8 risk/trade at 0.01 lot on D1 ATR
                         max_hold_bars=LS.FX_STRATS["SPX500-ZBPIV"]["max_hold"],
                         max_tpd=LS.FX_STRATS["SPX500-ZBPIV"]["max_tpd"], bar_seconds=86400),
    # ── HAVW family (gs_battery_lab.py July 2026, magics 611xx-613xx). Heikin-Ashi
    # flip + RSI pullback + VW-MACD cross, BOTH directions, entry-relative 3*ATR stop,
    # 3-ATR chandelier trail from the 22-bar extreme (trail_basis=hh22 — manage_positions
    # raises/lowers the broker SL on every CLOSED bar; no TP). Validated July 18 2026:
    # verify_gs_battery 7/7, truncation audit on all 16 generators, 36/36 plateau
    # neighbors positive, daily-R corr to the whole gold book <= +0.05.
    "XAUUSD_HAVW": dict(symbol="XAUUSD", feed="XAUUSD_H1", strat="HAVW", engine="fx",
                        magic=61101, eval="fx", cfg=LS.FX_STRATS["XAUUSD-HAVW"],
                        exit="trail", rr=None, be_r=None, risk_mode="trend_trail",
                        stop_pad=_half(LS.FX_SPREADS["XAUUSD"]),
                        equity_min=EQUITY_GATE_GOLD_TREND,
                        max_hold_bars=LS.FX_STRATS["XAUUSD-HAVW"]["max_hold"],
                        max_tpd=LS.FX_STRATS["XAUUSD-HAVW"]["max_tpd"], bar_seconds=3600),
    "EURUSD_HAVW": dict(symbol="EURUSD", feed="EURUSD_H4", strat="HAVW", engine="fx",
                        magic=61201, eval="fx", cfg=LS.FX_STRATS["EURUSD-HAVW"],
                        exit="trail", rr=None, be_r=None, risk_mode="trend_trail",
                        stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                        equity_min=300, fx_max_risk_usd=15.0,
                        max_hold_bars=LS.FX_STRATS["EURUSD-HAVW"]["max_hold"],
                        max_tpd=LS.FX_STRATS["EURUSD-HAVW"]["max_tpd"], bar_seconds=14400),
    "GBPUSD_HAVW": dict(symbol="GBPUSD", feed="GBPUSD_H4", strat="HAVW", engine="fx",
                        magic=61301, eval="fx", cfg=LS.FX_STRATS["GBPUSD-HAVW"],
                        exit="trail", rr=None, be_r=None, risk_mode="trend_trail",
                        stop_pad=_half(LS.FX_SPREADS["GBPUSD"]),
                        equity_min=300, fx_max_risk_usd=15.0,
                        max_hold_bars=LS.FX_STRATS["GBPUSD-HAVW"]["max_hold"],
                        max_tpd=LS.FX_STRATS["GBPUSD-HAVW"]["max_tpd"], bar_seconds=14400),
    # REFINED BOLL30 (boll15_refit_lab July 2026): EURUSD M30 long-only quiet-hours
    # Bollinger fade, calm filter atrp<=0.50 (vs legacy 0.70/both-sides magic 81001).
    # The only live-cost survivor of the BOLL15/30 refit — see lab header for numbers.
    "EURUSD_BOLL30R": dict(symbol="EURUSD", feed="EURUSD_30", strat="BOLL30R", engine="fx",
                           magic=55101, eval="fx", cfg=LS.FX_STRATS["EURUSD-BOLL30R"],
                           exit="fixed", rr=None, be_r=None, risk_mode="boll",
                           stop_pad=_half(LS.FX_SPREADS["EURUSD"]),
                           max_hold_bars=LS.FX_STRATS["EURUSD-BOLL30R"]["max_hold"],
                           max_tpd=LS.FX_STRATS["EURUSD-BOLL30R"]["max_tpd"], bar_seconds=1800),
    "USDCHF_RSI30": dict(symbol="USDCHF", feed="USDCHF_30", strat="RSI30", engine="fx",
                         magic=72001, eval="fx", cfg=LS.FX_STRATS["USDCHF-RSI30"],
                         exit="fixed", rr=LS.FX_STRATS["USDCHF-RSI30"]["rr"], be_r=None,
                         risk_mode="rsi", stop_pad=_half(LS.FX_SPREADS["USDCHF"]),
                         max_hold_bars=LS.FX_STRATS["USDCHF-RSI30"]["max_hold"],
                         max_tpd=LS.FX_STRATS["USDCHF-RSI30"]["max_tpd"], bar_seconds=1800),
    # USDCHF H1 opposing-FVG reversal (P1 pattern, cost-immune like GBPUSD-P1). Uses the
    # default USDCHF H1 feed; LIMIT entry in the FVG-overlap zone via the existing p1 path.
    "USDCHF_P1": dict(symbol="USDCHF", strat="P1", engine="fx", magic=74001, eval="fx",
                      cfg=LS.FX_STRATS["USDCHF-P1"], exit="fixed",
                      rr=LS.FX_STRATS["USDCHF-P1"]["rr"], be_r=None, risk_mode="p1",
                      stop_pad=_half(LS.FX_SPREADS["USDCHF"]),
                      max_hold_bars=LS.FX_STRATS["USDCHF-P1"]["max_hold"],
                      max_tpd=LS.FX_STRATS["USDCHF-P1"]["max_tpd"], bar_seconds=3600),
}
MAGIC2KEY = {v["magic"]: k for k, v in INSTANCES.items()}
_apply_prop_mode()      # PROP_MODE re-anchoring (needs INSTANCES + caps above)

# Per-FEED data config. A feed = one (market, timeframe-pair) stream; keys are feed names.
# "market" is the broker symbol (defaults to the feed name) — lets one symbol have TWO feeds
# (XAUUSD M5+M15 for S5/S6/S4  AND  XAUUSD H1+H4 for the H1A strategy).
SYMBOLS = {
    "XAUUSD": dict(engine="gold", tf="M5", bias_tf="M15", bars=12500, bias_bars=4600,
                   bar_min=5, bias_min=15, baseline=BASELINE_5M_CSV, baseline_bias=BASELINE_15M_CSV),
    "XAUUSD_H1": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                      bar_min=60, bias_min=240, baseline=None, baseline_bias=None,
                      market="XAUUSD"),
    # ZONE BREAKOUT feeds (July 2026). ZBPIV/ZBBOX ignore htf_bias/atr_pctile, so the
    # bias feed is only merge fodder; H4/D1 use themselves as bias (cheapest warm).
    "XAUUSD_H4": dict(engine="fx", tf="H4", bias_tf="H4", bars=2500, bias_bars=2500,
                      bar_min=240, bias_min=240, baseline=None, baseline_bias=None,
                      market="XAUUSD"),
    "XAGUSD": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "SPX500_D1": dict(engine="fx", tf="D1", bias_tf="D1", bars=1500, bias_bars=1500,
                      bar_min=1440, bias_min=1440, baseline=None, baseline_bias=None,
                      market="SPX500"),
    "EURUSD_30": dict(engine="fx", tf="M30", bias_tf="H4", bars=3600, bias_bars=2500,
                      bar_min=30, bias_min=240, baseline=None, baseline_bias=None,
                      market="EURUSD", pctile_win=1440),
    "EURUSD": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "GBPUSD": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    # H4 feeds for the HAVW family (July 2026): H4 bars with themselves as bias.
    "EURUSD_H4": dict(engine="fx", tf="H4", bias_tf="H4", bars=2500, bias_bars=2500,
                      bar_min=240, bias_min=240, baseline=None, baseline_bias=None,
                      market="EURUSD"),
    "GBPUSD_H4": dict(engine="fx", tf="H4", bias_tf="H4", bars=2500, bias_bars=2500,
                      bar_min=240, bias_min=240, baseline=None, baseline_bias=None,
                      market="GBPUSD"),
    "USDCAD": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "USDCHF": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "USDCHF_30": dict(engine="fx", tf="M30", bias_tf="H4", bars=3600, bias_bars=2500,
                      bar_min=30, bias_min=240, baseline=None, baseline_bias=None,
                      market="USDCHF", pctile_win=1440),
    # M15 feeds for the BOLL15 family. pctile_win = 30 days of M15 bars = 2880;
    # cache 6000 bars (~62 days) keeps the percentile window fully warmed.
    "EURUSD_15": dict(engine="fx", tf="M15", bias_tf="H4", bars=6000, bias_bars=2500,
                      bar_min=15, bias_min=240, baseline=None, baseline_bias=None,
                      market="EURUSD", pctile_win=2880),
    "GBPUSD_15": dict(engine="fx", tf="M15", bias_tf="H4", bars=6000, bias_bars=2500,
                      bar_min=15, bias_min=240, baseline=None, baseline_bias=None,
                      market="GBPUSD", pctile_win=2880),
    "USDCHF_15": dict(engine="fx", tf="M15", bias_tf="H4", bars=6000, bias_bars=2500,
                      bar_min=15, bias_min=240, baseline=None, baseline_bias=None,
                      market="USDCHF", pctile_win=2880),
    # Index feeds (H1 signals + H4 bias; plain broker names, no .i suffix)
    "SPX500": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "GER40": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                  bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "US30": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                 bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "JPN225": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                   bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
    "HK50": dict(engine="fx", tf="H1", bias_tf="H4", bars=2500, bias_bars=2500,
                 bar_min=60, bias_min=240, baseline=None, baseline_bias=None),
}
# Symbols that trade at the broker-minimum 0.01 lot (cannot be dollar-risk-sized like FX):
# gold + index CFDs. Exempt from FX_MIN/MAX_RISK sizing and from the USD-direction cap.
MINLOT_SYMBOLS = ("XAUUSD", "XAGUSD", "SPX500", "GER40", "US30", "JPN225", "HK50")
TF_MAP = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
          "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}


def feed_of(inst):
    return inst.get("feed", inst["symbol"])


def market_of(feed):
    return SYMBOLS[feed].get("market", feed)


# only manage feeds that have at least one enabled instance
_missing_lots = [k for k in INSTANCES if k not in LOTS]
assert not _missing_lots, f"config error: INSTANCES without LOTS entry: {_missing_lots}"
_missing_enable = [k for k in INSTANCES if k not in ENABLE]
assert not _missing_enable, f"config error: INSTANCES without ENABLE entry: {_missing_enable}"

ACTIVE_SYMBOLS = sorted({feed_of(i) for k, i in INSTANCES.items() if ENABLE.get(k)})


# ============================== INFRASTRUCTURE ==============================
def log(msg: str):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z | {_LOG_TAG}{msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(msg: str):
    """Fire-and-forget phone push via Telegram. NEVER raises — a failed notification
    (network down, bad token) must not affect trading. Short timeout, silent on error."""
    if not (NOTIFY_ENABLED and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=data)
        urllib.request.urlopen(req, timeout=8).read()
    except Exception as exc:  # noqa: BLE001
        log(f"notify failed (ignored): {type(exc).__name__}")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
                st.setdefault("open_trades", {})   # ticket -> entry/SL/TP for the tradebook
                st.setdefault("pending", {})       # magic -> pending limit-order meta
                return st
        except (OSError, json.JSONDecodeError):
            pass
    return {"last_deal_poll": None, "runner": {}, "open_trades": {}, "pending": {}}


def save_state(st: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)


def mt5_connect() -> bool:
    kwargs = dict(login=MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)
    ok = mt5.initialize(MT5_TERMINAL_PATH, **kwargs) if MT5_TERMINAL_PATH else mt5.initialize(**kwargs)
    if not ok:
        log(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    for sym in sorted({market_of(f) for f in ACTIVE_SYMBOLS}):
        bsym = broker_sym(sym)
        if not mt5.symbol_select(bsym, True):
            log(f"FATAL: symbol {bsym} not available: {mt5.last_error()} "
                f"(set SYMBOL_SUFFIX / SYMBOL_OVERRIDE near the top — your broker may use '{sym}.r' etc.)")
            return False
    return True


def ensure_connection() -> bool:
    ti = mt5.terminal_info()
    if ti is not None and ti.connected:
        return True
    log("Connection lost — reconnecting...")
    mt5.shutdown()
    for attempt in range(1, 13):
        time.sleep(min(5 * attempt, 60))
        if mt5_connect():
            log("Reconnected.")
            return True
        log(f"Reconnect attempt {attempt} failed.")
    return False


def server_epoch_now():
    """Current time expressed in the broker's rates-epoch basis (MT5 'time' fields are
    epoch seconds of SERVER wall-clock). Used for bar-staleness checks."""
    try:
        off = BTZ.utcoffset(datetime.utcnow())
        return datetime.now(timezone.utc).timestamp() + (off.total_seconds() if off else 0)
    except Exception:
        try:
            t = mt5.symbol_info_tick(broker_sym(market_of(ACTIVE_SYMBOLS[0])))
            return float(t.time) if t else None
        except Exception:
            return None


def detect_broker_offset_minutes():
    """METHOD 1 (measure): broker server clock minus true UTC, to the nearest 15 minutes =
    the broker's CURRENT UTC offset. Works for ANY offset — UTC+2/+3, +6, +7, negative, and
    even :30/:45 zones — because it is measured, never assumed.
    July 15 2026 fix: a just-launched terminal can serve an HOURS-OLD cached tick before the
    quote stream syncs (this measured a bogus UTC-05:45 live). A stale tick's clock does NOT
    advance, a live stream's does — so we now require the tick time to ADVANCE before
    trusting it. Returns None (keep current/fallback TZ) when no live tick is available."""
    try:
        bsym = broker_sym(market_of(ACTIVE_SYMBOLS[0]))
        t1 = mt5.symbol_info_tick(bsym)
        if t1 is None or not t1.time:
            return None
        t2 = None
        deadline = time.time() + 12.0                                  # gold ticks ~every sec when open
        while time.time() < deadline:
            time.sleep(1.5)
            t2 = mt5.symbol_info_tick(bsym)
            if t2 is not None and t2.time and t2.time > t1.time:
                break
        if t2 is None or not t2.time or t2.time <= t1.time:
            log("TZ measure: tick clock NOT advancing (cached quote / market closed) — refusing "
                "to measure an offset from a stale tick")
            return None
        broker_now = pd.to_datetime(t2.time, unit="s")                 # broker wall clock (naive)
        utc_now = pd.Timestamp.utcnow().tz_localize(None)              # true UTC (naive)
        off_min = int(round((broker_now - utc_now).total_seconds() / 60.0 / 15.0)) * 15
        return off_min if -12 * 60 <= off_min <= 14 * 60 else None     # sanity band
    except Exception:  # noqa: BLE001
        return None


def _fmt_off(off_min):
    s = "+" if off_min >= 0 else "-"
    return f"UTC{s}{abs(off_min)//60:02d}:{abs(off_min)%60:02d}"


def verify_tz_via_weekend(df, label):
    """METHOD 2 (cross-check, broker-INDEPENDENT): the FX/gold market itself closes Friday
    ~17:00 New York. So the last bar before each weekend gap MUST CLOSE around Friday
    ~16:00-17:00 NY when the offset is right — regardless of what timezone the broker
    uses. If the measured offset is wrong, these land on the wrong weekday/hour and we
    scream. Robust to holidays (uses the majority of weekend-sized gaps, not a single one).
    July 16 2026 fix: compares bar CLOSE (open + bar span), not OPEN, against the 15-17
    window. Bars are timestamped at OPEN, so a coarse H4 bar covering 13:00-17:00 NY has
    an open hour of 13 — checking the open against 15-17 falsely failed every H4 feed
    (XAUUSD_H4 tripped a global TIMEZONE CROSS-CHECK FAILED that gated the ENTIRE book's
    entries for hours despite every other feed reading CONSISTENT OK). Sub-hourly/hourly
    bars are unaffected (their close time barely differs from open)."""
    try:
        t = df["timestamp_ny"].reset_index(drop=True)
        d = t.diff()
        big = list(d[d > pd.Timedelta(hours=20)].index)        # weekend-sized gaps
        if not big:
            return None
        span = d[d < pd.Timedelta(hours=20)].median()           # typical bar spacing
        if pd.isna(span) or span <= pd.Timedelta(0):
            span = pd.Timedelta(minutes=1)
        opens = t.iloc[[gi - 1 for gi in big]]
        if span >= pd.Timedelta(hours=2):
            # COARSE bars (H4+): a resampler's grid phase doesn't reliably label the
            # pre-weekend bar's OPEN in 15-17 (e.g. an H4 bar opening 13:00 legitimately
            # covers the 17:00 NY close). Alignment-invariant check instead: does this
            # bar's [open, open+span] window straddle Friday 17:00 NY? July 16 2026 fix
            # — XAUUSD_H4 falsely tripped a global TIMEZONE CROSS-CHECK FAILED that gated
            # the ENTIRE book's entries for hours despite every other feed reading OK.
            good = sum(1 for o in opens if o.weekday() == 4
                      and o - pd.Timedelta(minutes=1)
                      <= o.normalize() + pd.Timedelta(hours=17)
                      <= o + span + pd.Timedelta(minutes=1))
        else:
            # Sub-hourly/hourly bars: open-hour check (unchanged, proven in production;
            # the 15-17 tolerance already absorbs holiday early-closes at this granularity).
            good = sum(1 for o in opens if o.weekday() == 4 and 15 <= o.hour <= 17)
        frac = good / len(big)
        sample = opens.iloc[-1]
        ok = frac >= 0.7
        log(f"TZ VERIFY [{label}]: {good}/{len(big)} weekend gaps end on Fri 16-17 NY "
            f"(latest: {sample:%a %Y-%m-%d %H:%M} NY) -> "
            f"{'CONSISTENT OK' if ok else 'MISMATCH !! check timezone before trading'}")
        return ok
    except Exception as exc:  # noqa: BLE001
        log(f"TZ VERIFY [{label}] failed: {exc}")
        return None


def refresh_broker_tz() -> bool:
    """Update global BTZ/BROKER_TZ from the MEASURED broker offset (any offset). Returns True
    if it CHANGED so the caller can force a clean cache rebuild. No-op when BROKER_TZ_AUTO is
    False (then the manual BROKER_TZ string is used)."""
    global BTZ, BROKER_TZ
    if not BROKER_TZ_AUTO:
        return False
    off_min = detect_broker_offset_minutes()
    if off_min is None:
        log(f"Broker TZ auto-detect unavailable (market closed?) — keeping {BROKER_TZ}")
        return False
    zone = timezone(timedelta(minutes=off_min))          # exact fixed offset (any zone)
    label = _fmt_off(off_min)
    changed = label != str(BROKER_TZ)
    if changed:
        log(f"!! BROKER TZ measured as {label} — was {BROKER_TZ}. NY session filters realigned.")
    BTZ = zone
    BROKER_TZ = label
    return changed


def fetch_closed_bars(symbol, timeframe, count: int, min_rows: int = 50) -> pd.DataFrame | None:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 1)
    if rates is None or len(rates) < min_rows:
        return None
    df = pd.DataFrame(rates)
    t = pd.to_datetime(df["time"], unit="s").dt.tz_localize(BTZ, nonexistent="shift_forward",
                                                            ambiguous=True)
    df["timestamp_ny"] = t.dt.tz_convert(NY)
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["timestamp_ny", "open", "high", "low", "close", "volume"]].iloc[:-1].reset_index(drop=True)


def load_baseline(path: str, rows: int) -> pd.DataFrame | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        if ";" in first:
            df = pd.read_csv(path, sep=";")
            df.columns = [c.lower() for c in df.columns]
            df = df.tail(rows).copy()
            dt = pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M")
        else:
            df = pd.read_csv(path, sep="\t", header=None)
            ncols = df.shape[1]
            df.columns = ["date", "open", "high", "low", "close"] + [f"x{i}" for i in range(ncols - 5)]
            df = df.tail(rows).copy()
            dt = pd.to_datetime(df["date"], format="%Y-%m-%d %H:%M")
            df["volume"] = np.nan
            for c in [c for c in df.columns if c.startswith("x")]:
                vals = pd.to_numeric(df[c], errors="coerce")
                if vals.nunique() > 50 and vals.max() > 50:
                    df["volume"] = vals
                    break
        df["timestamp_ny"] = dt.dt.tz_localize(BTZ, nonexistent="shift_forward",
                                               ambiguous=True).dt.tz_convert(NY)
        if "volume" not in df.columns:
            df["volume"] = np.nan
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["timestamp_ny", "open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]).reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        log(f"baseline {path} unreadable: {exc}")
        return None


def pattern_match_offset(baseline, broker, bar_minutes):
    m = STITCH_PATTERN_BARS
    if len(broker) < m + 5 or len(baseline) < m + 50:
        return None, np.inf
    pat = broker["close"].to_numpy(float)[:m]
    base = baseline["close"].to_numpy(float)
    windows = np.lib.stride_tricks.sliding_window_view(base, m)
    score = np.abs(windows - pat).mean(axis=1)
    best_i = int(np.argmin(score)); best = float(score[best_i])
    mask = np.ones(len(score), bool); mask[max(0, best_i - 3):best_i + 4] = False
    runner = float(score[mask].min()) if mask.any() else np.inf
    if best > STITCH_MATCH_OK or runner - best < STITCH_MATCH_MARGIN:
        return None, best
    delta = baseline["timestamp_ny"].iloc[best_i] - broker["timestamp_ny"].iloc[0]
    snapped = timedelta(minutes=round(delta.total_seconds() / 60 / bar_minutes) * bar_minutes)
    if abs(snapped.total_seconds()) > 12 * 3600:
        return None, best
    return snapped, best


class BarCache:
    """Rolling window of CLOSED bars (per symbol+timeframe). Broker-first; gold tops up from a
    baseline CSV via OHLC pattern-match when the broker's deep history is thin. FX needs no
    baseline (brokers serve ample H1/H4)."""

    def __init__(self, symbol, timeframe, count, csv_path, baseline_path, bar_minutes):
        self.symbol = symbol
        self.tf = timeframe
        self.count = count
        self.csv_path = csv_path
        self.baseline_path = baseline_path
        self.bar_minutes = bar_minutes
        self.df = None
        self.bars_since_resync = 0

    def _from_csv(self):
        if not os.path.exists(self.csv_path):
            return None
        try:
            df = pd.read_csv(self.csv_path)
            df["timestamp_ny"] = pd.to_datetime(df["timestamp_ny"], utc=True).dt.tz_convert(NY)
            return df
        except Exception as exc:  # noqa: BLE001
            log(f"{self.csv_path}: cache unreadable ({exc}) — ignoring")
            return None

    def _save(self):
        tmp = self.csv_path + ".tmp"
        self.df.to_csv(tmp, index=False)
        os.replace(tmp, self.csv_path)

    def full_sync(self) -> bool:
        fresh = fetch_closed_bars(self.symbol, self.tf, self.count, min_rows=50)
        if fresh is None:
            return False
        if len(fresh) >= self.count - 5 or self.baseline_path is None:
            self.df = fresh.tail(self.count).reset_index(drop=True)
            self.bars_since_resync = 0
            self._save()
            return True
        log(f"{self.csv_path}: broker served only {len(fresh)} bars — stitching...")
        foundation, source = self._from_csv(), "live cache"
        if foundation is None or len(foundation) < 500:
            foundation = load_baseline(self.baseline_path, self.count + 3000)
            source = f"baseline {self.baseline_path}"
            if foundation is not None:
                corr, quality = pattern_match_offset(foundation, fresh, self.bar_minutes)
                if corr is not None and corr != timedelta(0):
                    foundation = foundation.copy()
                    foundation["timestamp_ny"] = foundation["timestamp_ny"] - corr
                    log(f"{self.csv_path}: baseline shifted {-corr} onto broker clock "
                        f"(match {quality:.3f}).")
        if foundation is None:
            self.df = fresh
            self.bars_since_resync = 0
            self._save()
            return True
        first_live = fresh["timestamp_ny"].iloc[0]
        merged = (pd.concat([foundation[foundation["timestamp_ny"] < first_live], fresh])
                  .drop_duplicates(subset="timestamp_ny", keep="last")
                  .sort_values("timestamp_ny").tail(self.count).reset_index(drop=True))
        log(f"{self.csv_path}: stitched {len(merged)} bars ({source} + {len(fresh)} live).")
        self.df = merged
        self.bars_since_resync = 0
        self._save()
        return True

    def update(self):
        if self.df is None or self.bars_since_resync >= FULL_RESYNC_BARS:
            return self.df if self.full_sync() else None
        tail = fetch_closed_bars(self.symbol, self.tf, 12, min_rows=5)
        if tail is None or tail.empty:
            return None
        if self.df["timestamp_ny"].iloc[-1] < tail["timestamp_ny"].iloc[0]:
            log(f"{self.csv_path}: gap detected — full resync")
            return self.df if self.full_sync() else None
        new_rows = tail[tail["timestamp_ny"] > self.df["timestamp_ny"].iloc[-1]]
        if len(new_rows):
            self.df = pd.concat([self.df, new_rows]).tail(self.count).reset_index(drop=True)
            self.bars_since_resync += len(new_rows)
            self._save()
        return self.df


# ============================== FRAME BUILDING ==============================
def build_gold_frame(df5, df15):
    e5 = smc_engine.build_smc_frame(df5)
    e5 = smc_engine.add_regime_columns(e5)
    prev_c = e5["close"].shift(1)
    tr = pd.concat([e5["high"] - e5["low"], (e5["high"] - prev_c).abs(),
                    (e5["low"] - prev_c).abs()], axis=1).max(axis=1)
    e5["atr50_tr"] = tr.rolling(50, min_periods=20).mean()
    e5["atr_pctile_tr"] = e5["atr50_tr"].rolling(8640, min_periods=2000).rank(pct=True)
    e5["vol_ma50"] = e5["volume"].rolling(50, min_periods=20).mean()
    e5["atr50_rng"] = e5["atr50"]
    v = e5["atr50"].iloc[-1]
    if np.isfinite(v):
        LIVE_ATR["XAUUSD"] = round(float(v), 5)
    e15 = smc_engine.build_smc_frame(df15)
    return e5, e15


# ============================== GOLD SIGNALS ==============================
def _last_event_bars(e, col, values, window):
    out = {}
    tail = e[col].iloc[-window - 5:]
    for off, v in zip(tail.index, tail.values):
        if isinstance(v, str):
            out[v] = off
    return out


def eval_s5(e5, e15, long_only=True):
    p = STRAT["S5"]
    i = len(e5) - 1
    row = e5.iloc[i]
    if not (row["atr_pctile"] > p["min_atr_pctile"]):
        return None, "vol-regime off"
    if row["hour"] in p["blocked_hours"]:
        return None, "blocked hour"
    ev = _last_event_bars(e5, "internal_event", {"bullish_choch", "bearish_choch"}, p["sweep_valid_bars"] + 5)
    sw = _last_event_bars(e5, "sweep_direction", {"bullish", "bearish"}, p["sweep_valid_bars"] + 5)
    htf_bias = int(e15["swing_bias"].iloc[-1])
    for direction, choch_key, sweep_key, need_bias in (
            ("long", "bullish_choch", "bullish", 1), ("short", "bearish_choch", "bearish", -1)):
        if long_only and direction == "short":
            continue
        ci = ev.get(choch_key); si = sw.get(sweep_key)
        if ci is None or i - ci > p["choch_valid_bars"]:
            continue
        if si is None or si > ci or i - si > p["sweep_valid_bars"]:
            continue
        if htf_bias != need_bias:
            continue
        if direction == "short" and p["short_require_ltf_bias"] and int(row["swing_bias"]) != -1:
            continue
        top = row["bull_fvg_top"] if direction == "long" else row["bear_fvg_top"]
        bot = row["bull_fvg_bottom"] if direction == "long" else row["bear_fvg_bottom"]
        age = row["bull_fvg_age"] if direction == "long" else row["bear_fvg_age"]
        if pd.isna(top) or pd.isna(bot) or not (age > 0):
            continue
        if not (row["low"] <= top and row["high"] >= bot):
            continue
        if direction == "long":
            stop = min(row["last_swing_low"], bot) if pd.notna(row["last_swing_low"]) else bot
        else:
            stop = max(row["last_swing_high"], top) if pd.notna(row["last_swing_high"]) else top
        return dict(direction=direction, stop=float(stop), atr=float(row["atr50"])), f"SIGNAL {direction}"
    return None, "waiting (CHoCH/sweep/FVG)"


def eval_s6(e5):
    """S6-R: displacement continuation, STRUCTURE-GATED (mirrors s6_rehab_lab EXACTLY):
    range >= S6R_DISP_ATR_MULT * ATR50 bar closing in the top 25%, volume > MA50,
    atr_pctile > 0.25, 5m swing_bias == +1 (the rehab fix), blocked hours unchanged."""
    p = STRAT["S6"]
    i = len(e5) - 1
    row = e5.iloc[i]
    if not (row["atr_pctile_tr"] > p["min_atr_pctile"]):
        return None, "vol-regime off"
    if row["hour"] in p["blocked_hours"]:
        return None, "blocked hour"
    rng = row["high"] - row["low"]
    if rng <= 0 or not (rng >= S6R_DISP_ATR_MULT * row["atr50_tr"]):
        return None, "no displacement"
    if not (row["volume"] > row["vol_ma50"]):
        return None, "volume below avg"
    if S6R_REQUIRE_BIAS5 and int(row["swing_bias"]) != 1:
        return None, "bias not long"
    if row["close"] > row["open"] and (row["close"] - row["low"]) / rng >= p["close_loc"]:
        return dict(direction="long", stop=float(row["low"])), "SIGNAL long"
    return None, "no displacement close"


def eval_s3(e5):
    """S3 long-only (mirrors strategy_3_ny_am_fvg/backtest.py with long_only=True EXACTLY):
    NY-morning session 09:00-11:55, 5m swing_bias == +1, bullish displacement within the
    last 24 bars (body >= 60% of range, range >= 1.4*ATR50-range), bull-FVG touch with a
    bullish confirm close; stop = last_swing_low."""
    i = len(e5) - 1
    row = e5.iloc[i]
    nt = row["ny_time"]
    if not ("09:00" <= nt <= "11:55"):
        return None, "outside session"
    if int(row["swing_bias"]) != 1:
        return None, "bias not long"
    o = e5["open"].to_numpy(float)[-25:]; c = e5["close"].to_numpy(float)[-25:]
    h = e5["high"].to_numpy(float)[-25:]; l = e5["low"].to_numpy(float)[-25:]
    a = e5["atr50"].to_numpy(float)[-25:]
    disp_ok = False
    for k in range(len(o) - 1, -1, -1):
        rng = h[k] - l[k]
        if rng <= 0 or not np.isfinite(a[k]):
            continue
        if c[k] > o[k] and abs(c[k] - o[k]) / rng >= 0.60 and rng / a[k] >= 1.4:
            disp_ok = True
            break
    if not disp_ok:
        return None, "no displacement"
    top, bot_, age = row["bull_fvg_top"], row["bull_fvg_bottom"], row["bull_fvg_age"]
    if pd.isna(top) or pd.isna(bot_) or not (age > 0):
        return None, "no FVG"
    if not (row["low"] <= top and row["high"] >= bot_):
        return None, "no FVG touch"
    if not (row["close"] > row["open"]):
        return None, "no confirm"
    stop = row["last_swing_low"]
    if pd.isna(stop):
        return None, "no swing low"
    return dict(direction="long", stop=float(stop)), "SIGNAL long"


def eval_s4(e5):
    p = STRAT["S4"]
    i = len(e5) - 1
    row = e5.iloc[i]
    if not (p["act_start"] <= row["ny_time"] <= p["act_end"]):
        return None, "outside window"
    today = e5[e5["ny_date"] == row["ny_date"]]
    box = today[(today["ny_time"] >= p["acc_start"]) & (today["ny_time"] <= p["acc_end"])]
    if len(box) < 12:
        return None, "no accumulation box"
    acc_hi, acc_lo = box["high"].max(), box["low"].min()
    if (acc_hi - acc_lo) > p["tight_mult"] * row["atr50_rng"]:
        return None, "box not tight"
    if row["low"] < acc_lo and row["close"] > acc_lo and row["close"] > row["open"]:
        return dict(direction="long", stop=float(row["low"])), "SIGNAL long (manip low)"
    if row["high"] > acc_hi and row["close"] < acc_hi and row["close"] < row["open"]:
        return dict(direction="short", stop=float(row["high"])), "SIGNAL short (manip high)"
    return None, "tight box, waiting"


# ============================== EXECUTION ==============================
def filling_mode(symbol):
    info = mt5.symbol_info(symbol)
    fm = info.filling_mode if info else 0
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def positions_for(inst):
    poss = mt5.positions_get(symbol=broker_sym(inst["symbol"])) or []
    return [p for p in poss if p.magic == inst["magic"]]


def round_price(symbol, x):
    return round(x, mt5.symbol_info(symbol).digits)


def _gold_usd_risk_guard(key, inst, risk_points):
    """OWNER RULE (July 2026; DOLLAR-SIZING owner decision Aug 2026): XAUUSD
    trend-family trades are sized from the SL distance in dollars, mirroring
    fx_lot_for_min_risk. $1 of gold move = $1 P&L per 0.01 lot, so
    risk_$ == SL points * (lot / 0.01). The configured lot (LOTS[key], after
    the drawdown throttle) is the CEILING; when it would risk more than
    XAUUSD_MAX_RISK_USD the lot is stepped DOWN in broker volume steps until
    the risk fits the cap. A trade is SKIPPED only when even the broker
    minimum lot busts the cap, or the sized risk is under XAUUSD_MIN_RISK_USD.
    Returns (skip_reason, lot): skip_reason is None when the trade may
    proceed; lot is None for non-gold instances (caller keeps its own sizing)."""
    if inst["symbol"] != "XAUUSD":
        return None, None
    sym = broker_sym("XAUUSD")
    info = mt5.symbol_info(sym)
    step = getattr(info, "volume_step", 0.01) or 0.01
    vmin = getattr(info, "volume_min", 0.01) or 0.01
    base_lot = throttled_base_lot(key, sym)
    risk_per_001 = float(risk_points)      # $ risk at 0.01 lot ($1 move = $1)
    if risk_per_001 <= 0:
        return f"invalid gold risk {risk_points}", None
    # largest lot (in whole broker steps) whose $ risk stays inside the cap
    max_lot = int((XAUUSD_MAX_RISK_USD / risk_per_001) * 0.01 / step + 1e-9) * step
    lot = round(min(base_lot, max_lot), 2)
    if lot < vmin:
        risk_at_min = risk_per_001 * (vmin / 0.01)
        log(f"{key}: SKIP — SL risk ${risk_at_min:.2f} even at minimum {vmin:.2f} lot > "
            f"XAUUSD_MAX_RISK_USD ${XAUUSD_MAX_RISK_USD:.2f} (no trade taken)")
        return f"risk ${risk_at_min:.2f} at min lot > ${XAUUSD_MAX_RISK_USD:.2f} cap — skipped", None
    risk_usd = risk_per_001 * (lot / 0.01)
    if risk_usd < XAUUSD_MIN_RISK_USD:
        log(f"{key}: SKIP — SL risk ${risk_usd:.2f} at {lot:.2f} lot < "
            f"XAUUSD_MIN_RISK_USD ${XAUUSD_MIN_RISK_USD:.2f} (no trade taken)")
        return f"risk ${risk_usd:.2f} < ${XAUUSD_MIN_RISK_USD:.2f} floor — skipped", None
    if lot < base_lot:
        log(f"{key}: SIZED DOWN {base_lot:.2f} -> {lot:.2f} lot — SL risk "
            f"${risk_per_001 * (base_lot / 0.01):.2f} at {base_lot:.2f} lot > "
            f"${XAUUSD_MAX_RISK_USD:.2f} cap; trade proceeds risking ${risk_usd:.2f}")
    else:
        log(f"{key}: risk guard OK — SL risk ${risk_usd:.2f} at {lot:.2f} lot within "
            f"[${XAUUSD_MIN_RISK_USD:.2f}, ${XAUUSD_MAX_RISK_USD:.2f}]")
    return None, lot


def is_runner(inst):
    return inst["exit"] == "runner"


def _record_open(state, key, inst, ticket, direction, lot, entry, sl, tp, atr=None):
    """Store the trade's entry/SL/TP/risk/ATR (tradebook + RESTART-PROOF runner memory)
    and push a phone notification."""
    if state is not None and ticket is not None:
        state.setdefault("open_trades", {})[str(ticket)] = dict(
            open_time_ny=datetime.now(NY).strftime("%Y-%m-%d %H:%M"),
            symbol=inst["symbol"], strategy=key, direction=direction, lots=lot,
            entry=round(entry, 5), sl=round(sl, 5), tp=(round(tp, 5) if tp else None),
            risk=round(abs(entry - sl), 5), atr=(round(float(atr), 5) if atr else None))
        save_state(state)
    if NOTIFY_ON_OPEN:
        tp_s = f" TP {tp:.5f}" if tp else " (runner)"
        notify(f"OPEN  {key}  {direction.upper()} {lot} {inst['symbol']} @ {entry:.5f}"
               f" | SL {sl:.5f}{tp_s}")


def send_market(key, inst, direction, lot, sl, rr, atr=None, state=None, tp_abs=None):
    symbol = broker_sym(inst["symbol"])
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        log(f"{key}: no symbol info/tick — abort entry")
        return False
    if DRY_RUN:
        log(f"{key}: DRY_RUN — would {direction} {lot} {symbol}, SL {sl:.5f} (rr {rr})")
        if NOTIFY_ON_OPEN:
            notify(f"[DRY] would OPEN {key} {direction.upper()} {lot} {symbol} SL {sl:.5f}")
        return True
    order_type = mt5.ORDER_TYPE_BUY if direction == "long" else mt5.ORDER_TYPE_SELL
    req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=lot, type=order_type,
               deviation=DEVIATION_POINTS, magic=inst["magic"], comment=f"{key}",
               type_time=mt5.ORDER_TIME_GTC, type_filling=filling_mode(symbol),
               sl=round_price(symbol, sl))
    result = None
    for attempt in range(3):
        result = mt5.order_send(req)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            break
        log(f"{key}: order_send attempt {attempt+1} failed: "
            f"{getattr(result, 'retcode', None)} {getattr(result, 'comment', mt5.last_error())}")
        time.sleep(1)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return False
    pos = []
    for _ in range(6):
        pos = positions_for(inst)
        if pos:
            break
        time.sleep(0.5)
    fill = float(pos[-1].price_open) if pos else float(result.price or 0.0)
    if fill <= 0:
        log(f"{key}: ENTERED {direction} {lot} but fill price UNKNOWN — TP not set. SL {sl:.5f} active.")
        return True
    risk = (fill - sl) if direction == "long" else (sl - fill)
    if risk <= 0:
        log(f"{key}: fill {fill:.5f} vs SL {sl:.5f} -> non-positive risk; TP not set, SL active.")
        return True
    ticket = pos[-1].ticket if pos else None
    if is_runner(inst):
        if pos and state is not None:
            state.setdefault("runner", {})[str(ticket)] = {
                "risk": round(risk, 5), "atr": round(float(atr), 5) if atr else None, "best": fill}
            save_state(state)
        _record_open(state, key, inst, ticket, direction, lot, fill, sl, None, atr=atr)
        log(f"{key}: ENTERED {direction} {lot} @ {fill:.5f} SL {sl:.5f} RUNNER (no TP)")
        return True
    if inst.get("exit") == "trail":
        # chandelier-trail instance: SL only; manage_positions raises it per closed bar.
        _record_open(state, key, inst, ticket, direction, lot, fill, sl, None, atr=atr)
        log(f"{key}: ENTERED {direction} {lot} @ {fill:.5f} SL {sl:.5f} TRAIL (no TP)")
        return True
    if tp_abs is not None:
        tp = tp_abs                       # absolute target (e.g. BOLL fade -> SMA20)
    else:
        tp = fill + rr * risk if direction == "long" else fill - rr * risk
    if pos:
        mod = dict(action=mt5.TRADE_ACTION_SLTP, symbol=symbol, position=ticket,
                   sl=round_price(symbol, sl), tp=round_price(symbol, tp))
        for attempt in range(3):
            r2 = mt5.order_send(mod)
            if r2 is not None and r2.retcode == mt5.TRADE_RETCODE_DONE:
                break
            log(f"{key}: TP modify attempt {attempt+1} failed ({getattr(r2, 'retcode', None)}); SL set")
            time.sleep(1)
    _record_open(state, key, inst, ticket, direction, lot, fill, sl, tp, atr=atr)
    log(f"{key}: ENTERED {direction} {lot} @ {fill:.5f} SL {sl:.5f} TP {tp:.5f}")
    return True


def pending_for(inst):
    """Open pending orders belonging to this strategy (by magic)."""
    ords = mt5.orders_get(symbol=broker_sym(inst["symbol"])) or []
    return [o for o in ords if o.magic == inst["magic"]]


def gold_long_stack_count():
    """Open gold LONG positions + pending gold BUY orders across all gold strategies."""
    cnt = 0
    buy_pend = {getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2), getattr(mt5, "ORDER_TYPE_BUY_STOP", 4)}
    seen_mag = set()
    for k2, i2 in INSTANCES.items():
        if i2["symbol"] != "XAUUSD" or i2["magic"] in seen_mag:
            continue
        seen_mag.add(i2["magic"])
        for p in positions_for(i2):
            if p.type == mt5.POSITION_TYPE_BUY:
                cnt += 1
        for o2 in pending_for(i2):
            if getattr(o2, "type", None) in buy_pend:
                cnt += 1
    return cnt


def throttled_base_lot(key, sym_broker):
    """LOTS[key] scaled by the drawdown throttle, floored at the broker minimum."""
    m = _RISK_MULT["m"] if RISK_THROTTLE_ENABLED else 1.0
    lot = LOTS[key]
    if m >= 1.0:
        return lot
    info = mt5.symbol_info(sym_broker)
    step = getattr(info, "volume_step", 0.01) or 0.01
    vmin = getattr(info, "volume_min", 0.01) or 0.01
    return max(round(round(lot * m / step) * step, 2), vmin)


def fx_lot_for_min_risk(key, inst, direction, entry, stop):
    """FX lot sizing (never gold): start from the drawdown-throttled base lot, lift it UP to
    FX_MIN_RISK_USD (if set) and cap it DOWN to FX_MAX_RISK_USD (if set). Returns the lot, or
    None to SKIP the trade when even the broker-minimum lot would exceed FX_MAX_RISK_USD and
    FX_MAX_RISK_SKIP is True. Uses the broker's own P&L calc for $risk-per-lot."""
    throttle_m = _RISK_MULT["m"] if RISK_THROTTLE_ENABLED else 1.0
    lot = throttled_base_lot(key, broker_sym(inst["symbol"]))
    if inst["symbol"] in MINLOT_SYMBOLS or (FX_MIN_RISK_USD <= 0 and FX_MAX_RISK_USD <= 0):
        return lot                      # gold + indices ride the broker-minimum lot
    sym = broker_sym(inst["symbol"])
    per_lot = None
    try:
        otype = mt5.ORDER_TYPE_BUY if direction == "long" else mt5.ORDER_TYPE_SELL
        p = mt5.order_calc_profit(otype, sym, 1.0, entry, stop)
        if p is not None:
            per_lot = abs(float(p))
    except Exception:  # noqa: BLE001
        pass
    if not per_lot:
        risk = abs(entry - stop)                       # fallback: standard 100k contract
        per_lot = risk * 100000.0 if inst["symbol"].endswith("USD")             else risk * 100000.0 / max(entry, 1e-9)
    if per_lot <= 0:
        return lot
    import math
    info = mt5.symbol_info(sym)
    step = getattr(info, "volume_step", 0.01) or 0.01
    vmin = getattr(info, "volume_min", 0.01) or 0.01
    vmax = getattr(info, "volume_max", 100.0) or 100.0
    sized = lot
    if FX_MIN_RISK_USD > 0:                             # lift small-stop trades UP to the floor
        target = FX_MIN_RISK_USD * throttle_m
        sized = max(sized, math.ceil(target / per_lot / step - 1e-9) * step)
    fx_cap = float(inst.get("fx_max_risk_usd") or FX_MAX_RISK_USD)  # instance override (HAVW H4)
    if fx_cap > 0:                                      # size wide-stop trades DOWN to the cap
        cap_lot = math.floor(fx_cap / per_lot / step + 1e-9) * step
        if cap_lot < vmin:                              # cannot fit the cap even at min lot
            if FX_MAX_RISK_SKIP:
                log(f"{key}: SKIP — stop too wide, 0.01 lot risks "
                    f"${per_lot * vmin:.2f} > cap ${fx_cap:.2f}")
                return None
            sized = vmin                                # accept the overage at broker minimum
        else:
            sized = min(sized, cap_lot)
    sized = min(max(round(sized, 2), vmin), vmax)
    log(f"{key}: lot {lot} -> {sized} (~${per_lot * sized:.2f} at stop"
        f"{' [THROTTLED]' if throttle_m < 1 else ''})")
    return sized


def _usd_side(symbol, is_long):
    """+1 = trade profits if USD FALLS (long EUR/GBP/XAU or short CAD/CHF); -1 = USD rises.
    0 = USD-neutral (equity indices are beta plays, not USD-direction bets — excluded
    from the per-USD concurrency cap; the TOTAL cap still applies to them)."""
    if symbol in ("SPX500", "GER40", "US30", "JPN225", "HK50"):
        return 0
    base_up_is_usd_down = symbol in ("EURUSD", "GBPUSD", "XAUUSD", "XAGUSD")
    d = 1 if is_long else -1
    return d if base_up_is_usd_down else -d


def open_position_count():
    """Total open positions across ALL enabled strategies (book-wide concurrency)."""
    n = 0
    seen = set()
    for k2, i2 in INSTANCES.items():
        if not ENABLE.get(k2) or i2["magic"] in seen:
            continue
        seen.add(i2["magic"])
        n += len(positions_for(i2))
    return n


def usd_aligned_count(usd):
    """Open positions currently betting the same USD direction (`usd` = +1 or -1)."""
    cnt = 0
    seen = set()
    for k2, i2 in INSTANCES.items():
        if not ENABLE.get(k2) or i2["magic"] in seen:
            continue
        seen.add(i2["magic"])
        for p in positions_for(i2):
            if _usd_side(i2["symbol"], p.type == mt5.POSITION_TYPE_BUY) == usd:
                cnt += 1
    return cnt


def cancel_order(key, ticket):
    if DRY_RUN:
        log(f"{key}: DRY_RUN — would cancel pending #{ticket}")
        return True
    r = mt5.order_send(dict(action=mt5.TRADE_ACTION_REMOVE, order=ticket))
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    log(f"{key}: pending #{ticket} {'cancelled' if ok else f'cancel FAILED ({getattr(r, chr(39)+chr(114)+chr(101)+chr(116)+chr(99)+chr(111)+chr(100)+chr(101)+chr(39), None)})'}")
    return ok


def send_limit(key, inst, direction, lot, price, sl, tp, expiry_s, state):
    """Broker-side LIMIT order with SL/TP attached and server-side expiration.
    Falls back to GTC (bot-managed expiry via manage_pending) if the broker rejects
    ORDER_TIME_SPECIFIED. Mirrors the backtest: fill AT the zone price or not at all."""
    symbol = broker_sym(inst["symbol"])
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log(f"{key}: no tick — limit not placed")
        return False
    if DRY_RUN:
        log(f"{key}: DRY_RUN — would place {direction.upper()} LIMIT {lot} @ {price:.5f} "
            f"SL {sl:.5f} TP {tp:.5f} (expires {expiry_s//60} min)")
        if NOTIFY_ON_OPEN:
            notify(f"[DRY] LIMIT {key} {direction.upper()} {lot} @ {price:.5f}")
        return True
    otype = mt5.ORDER_TYPE_BUY_LIMIT if direction == "long" else mt5.ORDER_TYPE_SELL_LIMIT
    base = dict(action=mt5.TRADE_ACTION_PENDING, symbol=symbol, volume=lot, type=otype,
                price=round_price(symbol, price), sl=round_price(symbol, sl),
                tp=round_price(symbol, tp), magic=inst["magic"], comment=f"{key}",
                type_filling=filling_mode(symbol))
    req = dict(base, type_time=mt5.ORDER_TIME_SPECIFIED,
               expiration=int(tick.time) + int(expiry_s))
    result = None
    for attempt in range(3):
        result = mt5.order_send(req)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            break
        rc = getattr(result, "retcode", None)
        if rc in (getattr(mt5, "TRADE_RETCODE_INVALID_EXPIRATION", 10022), 10022):
            log(f"{key}: broker rejected server-side expiry — falling back to GTC "
                f"(bot will cancel after {expiry_s//60} min)")
            req = dict(base, type_time=mt5.ORDER_TIME_GTC)
            continue
        log(f"{key}: limit attempt {attempt+1} failed: {rc} "
            f"{getattr(result, 'comment', mt5.last_error())}")
        time.sleep(1)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return False
    expire_at = (datetime.now(timezone.utc) + timedelta(seconds=expiry_s)).isoformat()
    state.setdefault("pending", {})[str(inst["magic"])] = dict(
        key=key, ticket=int(result.order), direction=direction, lot=lot,
        price=round(price, 5), sl=round(sl, 5), tp=round(tp, 5), expire_at=expire_at)
    save_state(state)
    log(f"{key}: LIMIT placed #{result.order} {direction} {lot} @ {price:.5f} "
        f"SL {sl:.5f} TP {tp:.5f} (expires {expiry_s//60} min)")
    if NOTIFY_ON_OPEN:
        notify(f"LIMIT {key} {direction.upper()} {lot} {inst['symbol']} @ {price:.5f} "
               f"| SL {sl:.5f} TP {tp:.5f}")
    return True


def manage_pending(state):
    """Lifecycle of pending limit orders: detect FILLS (-> tradebook + notify), enforce
    bot-side expiry (covers the GTC fallback), and clean up cancelled/expired orders."""
    pend = state.setdefault("pending", {})
    if not pend:
        return
    changed = False
    for mkey, meta in list(pend.items()):
        inst = INSTANCES.get(meta.get("key"))
        if inst is None:
            pend.pop(mkey); changed = True; continue
        live = {o.ticket for o in pending_for(inst)}
        if meta["ticket"] in live:
            if datetime.now(timezone.utc) >= pd.Timestamp(meta["expire_at"]).to_pydatetime():
                cancel_order(meta["key"], meta["ticket"])
                pend.pop(mkey); changed = True
            continue
        # ticket no longer pending: either it FILLED (position exists) or it expired
        poss = positions_for(inst)
        if poss:
            p = poss[-1]
            state.setdefault("open_trades", {})[str(p.ticket)] = dict(
                open_time_ny=datetime.now(NY).strftime("%Y-%m-%d %H:%M"),
                symbol=inst["symbol"], strategy=meta["key"], direction=meta["direction"],
                lots=meta["lot"], entry=round(float(p.price_open), 5),
                sl=meta["sl"], tp=meta["tp"])
            log(f"{meta['key']}: LIMIT FILLED -> position #{p.ticket} @ {p.price_open:.5f}")
            if NOTIFY_ON_OPEN:
                notify(f"FILLED {meta['key']} {meta['direction'].upper()} "
                       f"{inst['symbol']} @ {p.price_open:.5f}")
        else:
            log(f"{meta['key']}: pending #{meta['ticket']} expired/cancelled unfilled")
        pend.pop(mkey); changed = True
    if changed:
        save_state(state)


def close_position(inst, pos, reason):
    symbol = broker_sym(inst["symbol"])
    if DRY_RUN:
        log(f"{MAGIC2KEY.get(pos.magic,'?')}: DRY_RUN — would close #{pos.ticket} ({reason})")
        return
    tick = mt5.symbol_info_tick(symbol)
    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
    req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=pos.volume, type=order_type,
               position=pos.ticket, price=price, deviation=DEVIATION_POINTS, magic=pos.magic,
               comment=f"exit_{reason}", type_filling=filling_mode(symbol))
    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"close #{pos.ticket} FAILED: {getattr(r,'retcode',None)} — retry next cycle")
    else:
        log(f"{MAGIC2KEY.get(pos.magic,'?')}: closed #{pos.ticket} ({reason})")


def _modify_sl(key, symbol, pos, new_sl, label):
    if DRY_RUN:
        log(f"{key}: DRY_RUN — would move SL to {new_sl:.5f} ({label}) on #{pos.ticket}")
        return
    r = mt5.order_send(dict(action=mt5.TRADE_ACTION_SLTP, symbol=symbol, position=pos.ticket,
                            sl=round_price(symbol, new_sl), tp=pos.tp))
    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"{key}: SL -> {new_sl:.5f} ({label}) on #{pos.ticket}")
    else:
        log(f"{key}: SL modify failed ({getattr(r, 'retcode', None)}) on #{pos.ticket}")


def _risk_from_order_history(pos, is_buy):
    """Recover the ORIGINAL risk from the broker's own records: the order that opened this
    position permanently stores the SL it was placed with. Survives any state-file loss."""
    try:
        hist = mt5.history_orders_get(position=pos.ticket) or []
        for od in hist:
            sl0 = float(getattr(od, "sl", 0.0) or 0.0)
            if sl0 and ((is_buy and sl0 < pos.price_open) or (not is_buy and sl0 > pos.price_open)):
                return round(abs(pos.price_open - sl0), 5)
    except Exception:  # noqa: BLE001
        pass
    return None


def manage_runner(key, inst, pos, state):
    symbol = broker_sym(inst["symbol"])
    rst = state.setdefault("runner", {})
    info = rst.get(str(pos.ticket))
    is_buy = pos.type == mt5.POSITION_TYPE_BUY
    if info is None:
        # RESTART-PROOF rebuild: recover risk & ATR from the open_trades record saved at
        # fill (survives restarts). Fallbacks: loss-side SL for risk; live ATR for trail.
        rec = state.get("open_trades", {}).get(str(pos.ticket), {})
        risk0 = rec.get("risk")
        if not risk0 and rec.get("sl") and rec.get("entry"):
            risk0 = round(abs(float(rec["entry"]) - float(rec["sl"])), 5)
        if not risk0:
            loss_side = (pos.sl and ((is_buy and pos.sl < pos.price_open)
                                     or (not is_buy and pos.sl > pos.price_open)))
            risk0 = round(abs(pos.price_open - pos.sl), 5) if loss_side else None
        if not risk0:
            risk0 = _risk_from_order_history(pos, is_buy)   # broker's original order SL
        atr0 = rec.get("atr") or LIVE_ATR.get(inst["symbol"])
        info = {"risk": risk0, "atr": atr0, "best": pos.price_open}
        rst[str(pos.ticket)] = info
        log(f"{key}: runner state for #{pos.ticket} rebuilt (risk={risk0}, "
            f"atr={'%.5f' % atr0 if atr0 else 'unknown -> trailing off'}, BE on)")
    if not info.get("atr") and LIVE_ATR.get(inst["symbol"]):
        info["atr"] = LIVE_ATR[inst["symbol"]]
        state_msg = "trailing re-armed" if info.get("risk") else "risk still unknown — repairing"
        log(f"{key}: runner ATR recovered from live frame ({info['atr']:.5f}) — {state_msg}")
    if not info.get("risk"):
        rec = state.get("open_trades", {}).get(str(pos.ticket), {})
        r0 = rec.get("risk")
        if not r0 and rec.get("sl") and rec.get("entry"):
            r0 = round(abs(float(rec["entry"]) - float(rec["sl"])), 5)
        if not r0:
            r0 = _risk_from_order_history(pos, is_buy)
        if r0:
            info["risk"] = r0
            log(f"{key}: runner RISK recovered ({r0}) on #{pos.ticket} — runner fully active")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return
    cur = tick.bid if is_buy else tick.ask
    info["best"] = max(info["best"], cur) if is_buy else min(info["best"], cur)
    risk = info.get("risk")
    if not risk:
        return
    entry = pos.price_open
    progress = (info["best"] - entry) if is_buy else (entry - info["best"])
    target_sl = entry if progress >= RUNNER_BE_R * risk else None
    if info.get("atr") and progress >= RUNNER_TRAIL_START_R * risk:
        trail = (info["best"] - RUNNER_TRAIL_ATR_MULT * info["atr"]) if is_buy \
            else (info["best"] + RUNNER_TRAIL_ATR_MULT * info["atr"])
        target_sl = trail if target_sl is None else (max(target_sl, trail) if is_buy else min(target_sl, trail))
    if target_sl is None:
        return
    cur_sl = pos.sl or (entry - 10 * risk if is_buy else entry + 10 * risk)
    improved = (target_sl > cur_sl + RUNNER_MIN_SL_STEP) if is_buy else (target_sl < cur_sl - RUNNER_MIN_SL_STEP)
    if improved:
        _modify_sl(key, symbol, pos, target_sl, "runner")


def manage_positions(now_utc, state):
    open_keys = set()
    for key, inst in INSTANCES.items():
        for pos in positions_for(inst):
            open_keys.add(str(pos.ticket))
            open_utc = (pd.Timestamp(pos.time, unit="s").tz_localize(BTZ)
                        .tz_convert(timezone.utc).to_pydatetime())
            held_bars = int((now_utc - open_utc).total_seconds() // inst["bar_seconds"])
            if held_bars >= inst["max_hold_bars"]:
                close_position(inst, pos, "time")
                continue
            if is_runner(inst):
                manage_runner(key, inst, pos, state)
                continue
            if inst.get("exit") == "trail":
                # chandelier: monotonic SL ratchet on every CLOSED bar of this feed.
                # basis "close" (DONCH_TR, validated): close -/+ trail_atr*ATR.
                # basis "hh22" (HAVW, mirrors gs_battery_lab._walk): 22-bar extreme
                # -/+ trail_atr*ATR. Longs raise the SL, shorts lower it — never loosened.
                bar = LIVE_TRAIL_BAR.get(feed_of(inst))
                if bar:
                    basis = inst["cfg"].get("trail_basis", "close")
                    ta = inst["cfg"]["trail_atr"] * bar["atr"]
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        ref = bar.get("hi22", bar["close"]) if basis == "hh22" else bar["close"]
                        cand = ref - ta
                        cur_sl = pos.sl or -10.0 ** 9
                        if cand > cur_sl + RUNNER_MIN_SL_STEP:
                            _modify_sl(key, broker_sym(inst["symbol"]), pos, cand, "trail")
                    else:
                        ref = bar.get("lo22", bar["close"]) if basis == "hh22" else bar["close"]
                        cand = ref + ta
                        cur_sl = pos.sl or 10.0 ** 9
                        if cand < cur_sl - RUNNER_MIN_SL_STEP:
                            _modify_sl(key, broker_sym(inst["symbol"]), pos, cand, "trail")
                continue
            be_r = inst.get("be_r") or 0
            if be_r > 0:
                risk = abs(pos.price_open - pos.sl) if pos.sl else 0
                if risk > 0:
                    bsym = broker_sym(inst["symbol"])
                    tick = mt5.symbol_info_tick(bsym)
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        prog = tick.bid - pos.price_open; be_needed = pos.sl < pos.price_open
                    else:
                        prog = pos.price_open - tick.ask; be_needed = pos.sl > pos.price_open
                    if be_needed and prog >= be_r * risk:
                        _modify_sl(key, bsym, pos, pos.price_open, "breakeven")
    rst = state.get("runner", {})
    for k in [k for k in rst if k not in open_keys]:
        rst.pop(k, None)
    save_state(state)


def trades_today(inst, ny_date):
    day_start_ny = datetime.strptime(ny_date, "%Y-%m-%d").replace(tzinfo=NY)
    frm = day_start_ny.astimezone(timezone.utc) - timedelta(hours=12)
    deals = mt5.history_deals_get(frm, datetime.now(timezone.utc) + timedelta(hours=12)) or []
    count = 0
    for d in deals:
        if d.magic == inst["magic"] and d.entry == mt5.DEAL_ENTRY_IN:
            t_ny = pd.Timestamp(d.time, unit="s").tz_localize(BTZ).tz_convert(NY)
            if t_ny.strftime("%Y-%m-%d") == ny_date:
                count += 1
    return count


# ============================== MONITORING CSVs ==============================
TB_COLS = ["open_time_ny", "close_time_ny", "symbol", "strategy", "direction", "lots",
           "entry_price", "sl_price", "tp_price", "exit_price", "exit_reason",
           "points", "profit_usd", "risk_points", "r_multiple",
           "swap_usd", "commission_usd"]
# profit_usd = NET account impact (price P/L + swap + commission + fees).
# swap_usd / commission_usd break out the costs for the 15-day review.


def _fresh_tradebook():
    with open(TRADEBOOK_CSV, "w", newline="") as f:
        csv.writer(f).writerow(TB_COLS)


def startup_summary():
    if not os.path.exists(TRADEBOOK_CSV):
        _fresh_tradebook()
        log("Tradebook created (no history yet).")
        return
    try:
        tb = pd.read_csv(TRADEBOOK_CSV)
        missing = [c for c in TB_COLS if c not in tb.columns]
        if missing and set(missing) <= {"swap_usd", "commission_usd"}:
            # in-place migration from the pre-July-2026 format — history is preserved
            for c in missing:
                tb[c] = ""
            tb = tb[TB_COLS]
            tb.to_csv(TRADEBOOK_CSV, index=False)
            log(f"Tradebook migrated: added columns {missing} (old rows keep blank costs).")
            missing = []
        if missing:
            raise ValueError(f"missing columns {missing}")
    except Exception as exc:  # noqa: BLE001
        bak = f"{TRADEBOOK_CSV}.bad_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.bak"
        os.replace(TRADEBOOK_CSV, bak)
        _fresh_tradebook()
        log(f"WARNING: tradebook not this bot's format ({exc}). Moved to {bak}, started fresh.")
        return
    if tb.empty:
        log("Tradebook empty — no live history yet.")
        return
    wins = (tb["profit_usd"] > 0).sum()
    log(f"LIVE HISTORY: {len(tb)} trades | win {wins/len(tb)*100:.1f}% | net ${tb['profit_usd'].sum():.2f}")
    for (s, st), g in tb.groupby(["symbol", "strategy"]):
        log(f"  {s} {st}: n={len(g)} net ${g['profit_usd'].sum():.2f}")


def poll_closed_trades(state):
    frm = (pd.Timestamp(state["last_deal_poll"]).to_pydatetime() if state.get("last_deal_poll")
           else datetime.now(timezone.utc) - timedelta(days=1))
    deals = mt5.history_deals_get(frm - timedelta(hours=12),
                                  datetime.now(timezone.utc) + timedelta(hours=12)) or []
    rows = []; latest = frm; opened = state.setdefault("open_trades", {})
    for d in deals:
        d_utc = pd.Timestamp(d.time, unit="s").tz_localize(BTZ).tz_convert(timezone.utc)
        if d_utc <= frm or d.magic not in MAGIC2KEY or d.entry != mt5.DEAL_ENTRY_OUT:
            latest = max(latest, d_utc.to_pydatetime())
            continue
        all_deals = mt5.history_deals_get(position=d.position_id) or []
        ins = [x for x in all_deals if x.entry == mt5.DEAL_ENTRY_IN]
        entry_px = ins[0].price if ins else float("nan")
        direction = "long" if (ins and ins[0].type == mt5.DEAL_TYPE_BUY) else "short"
        pts = (d.price - entry_px) if direction == "long" else (entry_px - d.price)
        key = MAGIC2KEY[d.magic]
        o = opened.pop(str(d.position_id), {})            # entry/SL/TP stored when it opened
        sl = o.get("sl"); tp = o.get("tp")
        # open time: state record, else the ENTRY deal's own timestamp (restart-proof)
        open_time = o.get("open_time_ny", "")
        if not open_time and ins:
            open_time = (pd.Timestamp(ins[0].time, unit="s").tz_localize(BTZ)
                         .tz_convert(NY).strftime("%Y-%m-%d %H:%M"))
        # risk: state record, else the ORIGINAL SL stored on the opening order (broker-side)
        riskp = abs(entry_px - sl) if (sl and not np.isnan(entry_px)) else float("nan")
        if np.isnan(riskp):
            try:
                for od in (mt5.history_orders_get(position=d.position_id) or []):
                    sl0 = float(getattr(od, "sl", 0.0) or 0.0)
                    if sl0 and not np.isnan(entry_px) and (
                            (direction == "long" and sl0 < entry_px)
                            or (direction == "short" and sl0 > entry_px)):
                        riskp = abs(entry_px - sl0)
                        sl = sl0
                        break
            except Exception:  # noqa: BLE001
                pass
        rmult = (pts / riskp) if (not np.isnan(riskp) and riskp > 0) else float("nan")
        # costs: swap+commission+fee across ALL of this position's deals (in and out legs)
        swap = sum(getattr(x, "swap", 0.0) or 0.0 for x in all_deals)
        comm = sum((getattr(x, "commission", 0.0) or 0.0) + (getattr(x, "fee", 0.0) or 0.0)
                   for x in all_deals)
        net_usd = d.profit + swap + comm                  # what the account actually moved
        rows.append([open_time, pd.Timestamp(d_utc).tz_convert(NY).strftime("%Y-%m-%d %H:%M"),
                     INSTANCES[key]["symbol"], key, direction, d.volume, round(entry_px, 5),
                     sl if sl else "", tp if tp else "", round(d.price, 5), d.comment,
                     round(pts, 5), round(net_usd, 2),
                     round(riskp, 5) if not np.isnan(riskp) else "",
                     round(rmult, 2) if not np.isnan(rmult) else "",
                     round(swap, 2), round(comm, 2)])
        latest = max(latest, d_utc.to_pydatetime())
    if rows:
        with open(TRADEBOOK_CSV, "a", newline="") as f:
            csv.writer(f).writerows(rows)
        for r in rows:
            log(f"TRADE CLOSED -> {r[3]} {r[4]} {r[5]} lots, ${r[12]} ({r[14]}R)")
            if NOTIFY_ON_CLOSE:
                res = "WIN" if r[12] > 0 else "LOSS"
                notify(f"CLOSE {r[3]} {r[4].upper()} {r[2]} @ {r[9]} | P/L ${r[12]} ({r[14]}R)  {res}")
        update_book_dd(state, [r[14] for r in rows])
    state["last_deal_poll"] = latest.isoformat()
    save_state(state)


def update_book_dd(state, new_r_values):
    """Track realized book R vs its high-water mark; drive the drawdown throttle and
    the phone alerts. Called with each batch of freshly closed trades' r_multiples."""
    br = float(state.get("book_r", 0.0)); pk = float(state.get("book_peak_r", 0.0))
    for r in new_r_values:
        try:
            br += float(r)
        except (TypeError, ValueError):
            continue
    pk = max(pk, br)
    dd = br - pk
    state["book_r"], state["book_peak_r"] = round(br, 2), round(pk, 2)
    alerted = set(state.get("dd_alerted", []))
    if dd >= -0.01:
        alerted.clear()
    for lvl in RISK_ALERT_LEVELS_R:
        if dd < lvl and lvl not in alerted:
            alerted.add(lvl)
            log(f"!! BOOK DRAWDOWN: portfolio is {dd:+.1f}R below its equity peak "
                f"(crossed the {lvl:+.0f}R monitoring level)")
            notify(f"Notice: Portfolio drawdown alert — the book is now {dd:+.1f}R below "
                   f"its equity peak (crossed the {lvl:+.0f}R monitoring level). "
                   f"Realized book: {br:+.1f}R, peak: {pk:+.1f}R.")
    state["dd_alerted"] = sorted(alerted)
    if RISK_THROTTLE_ENABLED:
        m = _RISK_MULT["m"]
        if m >= 1.0 and dd < RISK_THROTTLE_DD_R:
            _RISK_MULT["m"] = RISK_THROTTLE_MULT
            log(f"RISK THROTTLE ACTIVATED: portfolio drawdown {dd:+.1f}R crossed "
                f"{RISK_THROTTLE_DD_R:+.0f}R -> all new positions sized at "
                f"{RISK_THROTTLE_MULT:.0%} until recovery above {RISK_THROTTLE_RESTORE_R:+.0f}R")
            notify(f"Notice: We are automatically reducing the position size by "
                   f"{1 - RISK_THROTTLE_MULT:.0%} because the portfolio has reached a "
                   f"{RISK_THROTTLE_DD_R:+.0f}R drawdown level. Strict risk management "
                   f"controls are now active. (Current drawdown: {dd:+.1f}R.)")
        elif m < 1.0 and dd > RISK_THROTTLE_RESTORE_R:
            _RISK_MULT["m"] = 1.0
            log(f"RISK THROTTLE RELEASED: portfolio drawdown recovered to {dd:+.1f}R "
                f"(above {RISK_THROTTLE_RESTORE_R:+.0f}R) -> full position sizing restored")
            notify(f"Notice: Standard market position sizes have been fully restored "
                   f"automatically because the portfolio has successfully recovered to "
                   f"the {RISK_THROTTLE_RESTORE_R:+.0f}R level. "
                   f"(Current drawdown: {dd:+.1f}R.)")
    state["risk_mult"] = _RISK_MULT["m"]


def rebuild_book_equity(state):
    """Cold-start truth: rebuild book R, high-water mark and throttle state from the
    tradebook file itself (survives state loss; manual CSV edits are honored)."""
    try:
        tb = pd.read_csv(TRADEBOOK_CSV)
        r = pd.to_numeric(tb.get("r_multiple"), errors="coerce").dropna()
        eq = r.cumsum()
        br = float(eq.iloc[-1]) if len(eq) else 0.0
        pk = float(eq.cummax().iloc[-1]) if len(eq) else 0.0
    except Exception:  # noqa: BLE001
        br = pk = 0.0
    state["book_r"], state["book_peak_r"] = round(br, 2), round(pk, 2)
    dd = br - pk
    if RISK_THROTTLE_ENABLED and dd < RISK_THROTTLE_DD_R:
        _RISK_MULT["m"] = RISK_THROTTLE_MULT
    elif dd > RISK_THROTTLE_RESTORE_R:
        _RISK_MULT["m"] = 1.0
    else:                                   # inside the hysteresis band: stay conservative
        _RISK_MULT["m"] = float(state.get("risk_mult", RISK_THROTTLE_MULT))
    state["risk_mult"] = _RISK_MULT["m"]
    log(f"BOOK EQUITY: {br:+.1f}R (peak {pk:+.1f}R, DD {dd:+.1f}R) | "
        f"throttle {'ON x' + str(_RISK_MULT['m']) if _RISK_MULT['m'] < 1 else 'off'}")


def write_positions_snapshot():
    cols = ["ticket", "symbol", "strategy", "direction", "lots", "open_time_ny", "open_price",
            "sl", "tp", "unrealized_usd"]
    rows = []
    for key, inst in INSTANCES.items():
        for p in positions_for(inst):
            t_ny = pd.Timestamp(p.time, unit="s").tz_localize(BTZ).tz_convert(NY)
            rows.append([p.ticket, inst["symbol"], key,
                         "long" if p.type == mt5.POSITION_TYPE_BUY else "short", p.volume,
                         t_ny.strftime("%Y-%m-%d %H:%M"), p.price_open, p.sl, p.tp, round(p.profit, 2)])
    try:
        tmp = POSITIONS_CSV + ".tmp"
        pd.DataFrame(rows, columns=cols).to_csv(tmp, index=False)
        os.replace(tmp, POSITIONS_CSV)
    except OSError as exc:
        log(f"positions snapshot failed: {exc}")


def update_daily_pnl(ny_date):
    acc = mt5.account_info()
    if acc is None:
        return
    open_pnl = sum(p.profit for inst in INSTANCES.values() for p in positions_for(inst))
    realized = 0.0
    try:
        tb = pd.read_csv(TRADEBOOK_CSV)
        if not tb.empty and "close_time_ny" in tb.columns:
            mask = tb["close_time_ny"].astype(str).str.startswith(ny_date)
            realized = float(tb.loc[mask, "profit_usd"].sum())
    except Exception:  # noqa: BLE001
        pass
    row = {"date": ny_date, "balance": round(acc.balance, 2), "equity": round(acc.equity, 2),
           "realized_usd": round(realized, 2), "open_pnl_usd": round(open_pnl, 2)}
    try:
        df = (pd.read_csv(PNL_DAILY_CSV) if os.path.exists(PNL_DAILY_CSV)
              else pd.DataFrame(columns=list(row)))
        df = df[df["date"].astype(str) != ny_date]
        new_row = pd.DataFrame([row])
        df = new_row if df.empty else pd.concat([df, new_row], ignore_index=True)
        tmp = PNL_DAILY_CSV + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, PNL_DAILY_CSV)
    except Exception as exc:  # noqa: BLE001
        log(f"daily pnl update failed: {exc}")


# ============================== ENTRY DECISION ==============================
def try_enter(key, inst, frames, state):
    """Evaluate the signal for one instance on its latest closed bar; execute if valid."""
    if inst["engine"] == "gold":
        e5, e15 = frames["XAUUSD"]
        if inst["eval"] == "s5":
            sig, note = eval_s5(e5, e15, long_only=inst.get("long_only", True))
        elif inst["eval"] == "s6":
            sig, note = eval_s6(e5)
        elif inst["eval"] == "s3":
            sig, note = eval_s3(e5)
        else:
            sig, note = eval_s4(e5)
        ny_date = e5.iloc[-1]["ny_date"]
        sym_for_tick = "XAUUSD"
    else:
        frame = frames[feed_of(inst)]
        sig = LS.signal_at_last_bar(frame, inst["cfg"])
        note = f"SIGNAL {sig['direction']}" if sig else "no setup"
        ny_date = frame.iloc[-1]["ny_date"]
        sym_for_tick = inst["symbol"]
    if sig is None:
        return note
    if positions_for(inst):
        return "position open"
    if trades_today(inst, ny_date) >= inst["max_tpd"]:
        return "daily cap"
    # equity gate: big-ticket instances arm only once the account can afford their risk
    emin = inst.get("equity_min", 0)
    if emin:
        ai = mt5.account_info()
        if ai is None or ai.equity < emin:
            return f"equity gate (needs ${emin}, have ${ai.equity:.0f})" if ai else "equity gate (no account info)"
    if (inst["symbol"] == "XAUUSD" and sig.get("direction") == "long"
            and gold_long_stack_count() >= MAX_STACKED_GOLD_LONGS):
        return f"gold stack cap ({MAX_STACKED_GOLD_LONGS})"
    # book-wide concurrency governor (correlation / USD-shock protection)
    if MAX_CONCURRENT_TOTAL and open_position_count() >= MAX_CONCURRENT_TOTAL:
        return f"total concurrency cap ({MAX_CONCURRENT_TOTAL})"
    if MAX_CONCURRENT_PER_USD:
        my_usd = _usd_side(inst["symbol"], sig.get("direction", "long") == "long")
        # my_usd == 0 (USD-neutral index) skips the per-USD cap; TOTAL cap already applied
        if my_usd and usd_aligned_count(my_usd) >= MAX_CONCURRENT_PER_USD:
            return f"USD-aligned cap ({MAX_CONCURRENT_PER_USD}, side {my_usd:+d})"

    tick = mt5.symbol_info_tick(broker_sym(sym_for_tick))
    if tick is None:
        return "no tick"
    est_entry = tick.ask if sig["direction"] == "long" else tick.bid
    if inst["risk_mode"] == "boll":
        # BOLL fade: stop is ATR-offset from ENTRY; TP is the ABSOLUTE SMA target.
        atr = sig["atr"]
        if sig["direction"] == "long":
            stop = est_entry - sig["stop_atr"] * atr - inst["stop_pad"]
            if sig["target"] - est_entry <= 0.1 * atr:
                return "target too close"
        else:
            stop = est_entry + sig["stop_atr"] * atr + inst["stop_pad"]
            if est_entry - sig["target"] <= 0.1 * atr:
                return "target too close"
        risk = abs(est_entry - stop)
        if not (0.3 * atr <= risk <= 3.0 * atr):
            return f"risk {risk:.5f} out of ATR bounds"
        lot = fx_lot_for_min_risk(key, inst, sig["direction"], est_entry, stop)
        if lot is None:
            return "risk over cap — skipped"
        ok = send_market(key, inst, sig["direction"], lot, stop, None,
                         atr=atr, state=state, tp_abs=sig["target"])
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "rsi":
        # RSI fade (SHORT-only): stop is ATR-offset from ENTRY; TP = rr * risk below entry.
        atr = sig["atr"]
        stop = est_entry + sig["stop_atr"] * atr + inst["stop_pad"]
        risk = stop - est_entry
        if not (0.3 * atr <= risk <= 3.0 * atr):
            return f"risk {risk:.5f} out of ATR bounds"
        tp_abs = est_entry - sig["rr"] * risk
        lot = fx_lot_for_min_risk(key, inst, "short", est_entry, stop)
        if lot is None:
            return "risk over cap — skipped"
        ok = send_market(key, inst, "short", lot, stop, None,
                         atr=atr, state=state, tp_abs=tp_abs)
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "strad":
        # breakout: structural stop (far zone edge); TP = entry + M * zone_width (absolute).
        atr = sig["atr"]
        stop = sig["stop"] - inst["stop_pad"]
        risk = est_entry - stop
        if risk <= 0 or not (0.3 * atr <= risk <= 4.0 * atr):
            return f"risk {risk:.2f} out of ATR bounds"
        tp_abs = est_entry + sig["m"] * sig["width"]
        ok = send_market(key, inst, "long", throttled_base_lot(key, broker_sym(inst["symbol"])),
                         stop, None, atr=atr, state=state, tp_abs=tp_abs)
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "zone":
        # ZONE BREAKOUT (ZBPIV/ZBBOX): entry-relative stop_atr*ATR stop, TP = entry
        # +/- rr*risk — EXACTLY the zone_breakout_lab execution (stop pad plays the
        # lab's cost/2 role). Both directions. Rides broker-minimum lot; the gold
        # instance additionally passes the owner's XAUUSD_MIN/MAX_RISK_USD guard.
        atr = sig["atr"]
        if sig["direction"] == "long":
            stop = est_entry - sig["stop_atr"] * atr - inst["stop_pad"]
            risk = est_entry - stop
            tp_abs = est_entry + sig["rr"] * risk
        else:
            stop = est_entry + sig["stop_atr"] * atr + inst["stop_pad"]
            risk = stop - est_entry
            tp_abs = est_entry - sig["rr"] * risk
        if risk <= 0 or not (0.3 * atr <= risk <= 4.0 * atr):
            return f"risk {risk:.2f} out of ATR bounds"
        guard, gold_lot = _gold_usd_risk_guard(key, inst, risk)
        if guard:
            return guard
        ok = send_market(key, inst, sig["direction"],
                         gold_lot or throttled_base_lot(key, broker_sym(inst["symbol"])),
                         stop, None, atr=atr, state=state, tp_abs=tp_abs)
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "trend_trail":
        # Chandelier-trail family: structural stop at signal_close -/+ stop_atr*ATR like
        # "trend", but NO take-profit - the trail in manage_positions owns the exit.
        # DONCH_TR emits long-only; HAVW emits BOTH directions (stop padded AWAY per
        # side). Gold/index ride the broker-minimum lot (gold under the $ risk guard);
        # FX instances (HAVW H4) are dollar-sized via fx_lot_for_min_risk.
        atr = sig["atr"]
        if sig["direction"] == "short":
            stop = sig["stop"] + inst["stop_pad"]
            risk = stop - est_entry
        else:
            stop = sig["stop"] - inst["stop_pad"]
            risk = est_entry - stop
        if risk <= 0 or not (0.3 * atr <= risk <= 4.0 * atr):
            return f"risk {risk:.2f} out of ATR bounds"
        guard, gold_lot = _gold_usd_risk_guard(key, inst, risk)
        if guard:
            return guard
        if inst["symbol"] in MINLOT_SYMBOLS:
            lot = gold_lot or throttled_base_lot(key, broker_sym(inst["symbol"]))
        else:
            lot = fx_lot_for_min_risk(key, inst, sig["direction"], est_entry, stop)
            if lot is None:
                return "risk over cap — skipped"
        ok = send_market(key, inst, sig["direction"], lot,
                         stop, None, atr=atr, state=state)
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "trend":
        # trend/crash family: structural stop at signal_close -/+ stop_atr*ATR; TP = entry
        # -/+ rr * risk (absolute). Rides broker-minimum 0.01 lot (throttle can't shrink it).
        # DONCH/MACROSS emit direction="long"; CRASH emits "short" (mirror conventions,
        # identical to metal_short_hunt.sim_short: stop padded AWAY from price both sides).
        atr = sig["atr"]
        if sig["direction"] == "short":
            stop = sig["stop"] + inst["stop_pad"]
            risk = stop - est_entry
            tp_abs = est_entry - sig["rr"] * risk
        else:
            stop = sig["stop"] - inst["stop_pad"]
            risk = est_entry - stop
            tp_abs = est_entry + sig["rr"] * risk
        if risk <= 0 or not (0.3 * atr <= risk <= 4.0 * atr):
            return f"risk {risk:.2f} out of ATR bounds"
        guard, gold_lot = _gold_usd_risk_guard(key, inst, risk)
        if guard:
            return guard
        ok = send_market(key, inst, sig["direction"],
                         gold_lot or throttled_base_lot(key, broker_sym(inst["symbol"])),
                         stop, None, atr=atr, state=state, tp_abs=tp_abs)
        return f"{note}{' EXECUTED' if ok else ' FAILED'}"
    if inst["risk_mode"] == "p1":
        # LIMIT entry at the FVG-overlap zone edge; SL/TP ride on the pending order.
        atr = sig["atr"]; price = sig["limit"]
        if sig["direction"] == "short":
            stop = sig["stop_base"] + inst["stop_pad"]; risk = stop - price
            tp = price - inst["rr"] * risk
        else:
            stop = sig["stop_base"] - inst["stop_pad"]; risk = price - stop
            tp = price + inst["rr"] * risk
        if risk <= 0 or not (0.3 * atr <= risk <= 4.0 * atr):
            return f"risk {risk:.5f} out of ATR bounds"
        # a fresher zone supersedes any resting limit for this strategy
        for od in pending_for(inst):
            cancel_order(key, od.ticket)
        state.setdefault("pending", {}).pop(str(inst["magic"]), None)
        lot = fx_lot_for_min_risk(key, inst, sig["direction"], price, stop)
        if lot is None:
            return "risk over cap — skipped"
        ok = send_limit(key, inst, sig["direction"], lot, price, stop, tp,
                        LIMIT_EXPIRY_BARS * inst["bar_seconds"], state)
        return f"{note}{' LIMIT PLACED' if ok else ' FAILED'}"
    if sig["direction"] == "long":
        stop = sig["stop"] - inst["stop_pad"]; risk = est_entry - stop
    else:
        stop = sig["stop"] + inst["stop_pad"]; risk = stop - est_entry

    if inst["risk_mode"] == "points":
        if not (inst["min_risk"] <= risk <= inst["max_risk"]):
            return f"risk {risk:.2f} out of bounds"
    else:  # ATR-relative bounds (FX) — identical to the backtest's 0.55..8.0 x ATR50
        atr = sig.get("atr")
        if atr is None or not (LS.RISK_LO_ATR * atr <= risk <= LS.RISK_HI_ATR * atr):
            return f"risk {risk:.5f} out of ATR bounds"

    lot = fx_lot_for_min_risk(key, inst, sig["direction"], est_entry, stop)
    if lot is None:
        return "risk over cap — skipped"
    ok = send_market(key, inst, sig["direction"], lot, stop, inst["rr"],
                     atr=sig.get("atr"), state=state)
    return f"{note}{' EXECUTED' if ok else ' FAILED'}"


def broker_preflight():
    """Broker-migration safety: log each market's contract rules and WARN on anything that
    would silently break the strategies on a new broker (lot minimums, stop distances,
    wide spreads). Log-only — never blocks trading."""
    seen = set()
    for key, inst in INSTANCES.items():
        if not ENABLE.get(key):
            continue
        mkt = broker_sym(inst["symbol"])
        lot = LOTS[key]
        info = mt5.symbol_info(mkt)
        if info is None:
            log(f"PREFLIGHT {key}: no symbol_info for {mkt} !!")
            continue
        vmin = getattr(info, "volume_min", None); vstep = getattr(info, "volume_step", None)
        stops_pts = getattr(info, "trade_stops_level", 0) or 0
        point = getattr(info, "point", 0) or 0
        tick = mt5.symbol_info_tick(mkt)
        spr = (tick.ask - tick.bid) if tick else float("nan")
        if mkt not in seen:
            seen.add(mkt)
            log(f"PREFLIGHT {mkt}: spread={spr:.5f} | volume_min={vmin} step={vstep} | "
                f"min stop distance={stops_pts * point:.5f} ({stops_pts} pts)")
        if vmin is not None and lot < vmin:
            log(f"!! PREFLIGHT {key}: lot {lot} < broker volume_min {vmin} — orders WILL be "
                f"rejected. Raise LOTS['{key}'].")
        ref = LS.FX_SPREADS.get(inst["symbol"])
        if ref is not None and np.isfinite(spr) and spr > 3 * ref:
            # July 15 2026 fix: weekend/holiday quotes carry inflated spreads (EUR 3.0
            # pips on a Sunday vs 0.1 live) — flag market-closed so the warning is
            # advisory, not a false "consider disabling" panic.
            srv_now = server_epoch_now()
            closed = (tick is None or srv_now is None
                      or srv_now - float(tick.time) > 300)
            if closed:
                log(f"PREFLIGHT {key}: spread {spr:.5f} >3x assumption ({ref}) — but the "
                    f"market is CLOSED; weekend quotes are inflated. Re-check live hours.")
            else:
                log(f"!! PREFLIGHT {key}: live spread {spr:.5f} is >3x the backtest "
                    f"assumption ({ref}) — edge may not survive. Consider disabling.")
    log("Preflight done.")


def check_account_type():
    """Multi-strategy symbols (XAUUSD runs S5+S6+S4) need a HEDGING account so each strategy
    holds its OWN position. On a NETTING account the broker MERGES same-symbol orders into one
    position — breaking per-strategy magic/SL/TP/runner and making live != backtest. Warn loudly."""
    acc = mt5.account_info()
    if acc is None:
        return
    from collections import Counter
    cnt = Counter(i["symbol"] for k, i in INSTANCES.items() if ENABLE.get(k))
    multi = {s: c for s, c in cnt.items() if c > 1}
    mode = getattr(acc, "margin_mode", None)
    hedge = getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
    is_hedging = (mode == hedge)
    if multi and not is_hedging:
        log("!!! ACCOUNT IS NOT HEDGING (margin_mode=%s). These symbols run MULTIPLE strategies "
            "that each need their OWN position: %s. On a NETTING account the broker merges them "
            "into ONE position per symbol — per-strategy SL/TP/runner/magic WILL break and live "
            "will NOT match backtest. FIX: use a HEDGING account, or enable only one strategy per "
            "symbol." % (mode, multi))
    else:
        log("Account type: %s | multi-strategy symbols: %s"
            % ("HEDGING (OK)" if is_hedging else "mode " + str(mode), dict(multi) or "none"))


# ============================== MAIN LOOP ==============================
def _run_supervisor():
    """BROKER_PROFILE='both': spawn one worker per credential set and babysit them.
    Each worker is a full, independent copy of this file connected to its OWN
    terminal; a crashed worker is relaunched after 60s; Ctrl+C stops both."""
    import subprocess
    me = os.path.abspath(__file__)
    print(f"SUPERVISOR: launching standard + swapfree workers from {me}", flush=True)

    def spawn(role):
        env = os.environ.copy()
        env["MT5_BOT_ROLE"] = role
        return subprocess.Popen([sys.executable, me], env=env)

    procs = {}
    for role in ("standard", "swapfree"):
        procs[role] = spawn(role)
        print(f"SUPERVISOR: {role} worker pid={procs[role].pid}", flush=True)
        time.sleep(10)                      # stagger terminal logins
    try:
        while True:
            time.sleep(30)
            for role, pr in list(procs.items()):
                rc = pr.poll()
                if rc is not None:
                    print(f"SUPERVISOR: {role} worker EXITED rc={rc} - restart in 60s",
                          flush=True)
                    time.sleep(60)
                    procs[role] = spawn(role)
                    print(f"SUPERVISOR: {role} worker relaunched pid={procs[role].pid}",
                          flush=True)
    except KeyboardInterrupt:
        print("SUPERVISOR: Ctrl+C - terminating both workers", flush=True)
        for pr in procs.values():
            pr.terminate()


def main():
    if BROKER_PROFILE == "both":
        _run_supervisor()
        return
    log("=" * 70)
    log(f"LIVE MT5 BOT (multi-symbol) | DRY_RUN={DRY_RUN} | BROKER_PROFILE={BROKER_PROFILE}")
    log("Active: " + ", ".join(k for k in INSTANCES if ENABLE.get(k)))
    log("=" * 70)
    if not mt5_connect():
        sys.exit(1)
    state = load_state()
    acc = mt5.account_info()
    if acc is not None:
        log(f"ACCOUNT: balance ${acc.balance:.2f} | equity ${acc.equity:.2f} | currency {acc.currency}")
    _apply_capital_scaling(acc.equity if acc is not None else SIZING_BASE_CAPITAL)
    check_account_type()      # hedging vs netting — multi-strategy gold needs HEDGING
    broker_preflight()        # lot minimums / stop distances / live spreads vs assumptions
    startup_summary()
    rebuild_book_equity(state)   # drawdown throttle + alert state from the tradebook

    # --- detect broker timezone BEFORE warming caches (so bars localize correctly) ---
    refresh_broker_tz()

    # --- per-symbol caches ---
    caches = {}
    for sym in ACTIVE_SYMBOLS:
        sc = SYMBOLS[sym]
        c_main = BarCache(broker_sym(market_of(sym)), TF_MAP[sc["tf"]], sc["bars"], f"cache_{sym}_{sc['tf']}{_FILE_SUFFIX}.csv",
                          sc["baseline"], sc["bar_min"])
        c_bias = BarCache(broker_sym(market_of(sym)), TF_MAP[sc["bias_tf"]], sc["bias_bars"],
                          f"cache_{sym}_{sc['bias_tf']}{_FILE_SUFFIX}.csv", sc["baseline_bias"], sc["bias_min"])
        log(f"Warming {sym} ({sc['tf']}+{sc['bias_tf']})...")
        if not c_main.full_sync() or not c_bias.full_sync():
            log(f"FATAL: could not warm {sym} history.")
            mt5.shutdown(); sys.exit(1)
        caches[sym] = (c_main, c_bias)
        log(f"  {sym}: {len(c_main.df)} {sc['tf']} bars "
            f"({c_main.df['timestamp_ny'].iloc[0]:%Y-%m-%d} -> {c_main.df['timestamp_ny'].iloc[-1]:%Y-%m-%d %H:%M} NY)")

    # --- SURVIVAL LADDER banner: which tiers are armed at current equity ---
    ai0 = mt5.account_info()
    if ai0 is not None:
        eq0 = ai0.equity
        gated_insts = [(k2, i2["equity_min"]) for k2, i2 in INSTANCES.items()
                       if ENABLE.get(k2) and i2.get("equity_min")]
        armed_gated = [k2 for k2, g in gated_insts if eq0 >= g]
        waiting = sorted([(g, k2) for k2, g in gated_insts if eq0 < g])
        n_enabled = len([k2 for k2 in INSTANCES if ENABLE.get(k2)])
        log(f"SURVIVAL LADDER -> equity ${eq0:.0f}: {n_enabled - len(waiting)} of "
            f"{n_enabled} strategies armed"
            + (f" (gate-armed: {', '.join(armed_gated)})" if armed_gated else ""))
        for g, k2 in waiting:
            log(f"  waiting: {k2} arms at ${g} (needs ${g - eq0:.0f} more)")

    # --- TZ sanity banner ---
    r = mt5.copy_rates_from_pos(broker_sym(market_of(ACTIVE_SYMBOLS[0])), mt5.TIMEFRAME_M5, 0, 1)
    if r is not None and len(r):
        srv = pd.Timestamp(r[-1]["time"], unit="s")
        log(f"TZ CHECK -> broker {srv} | interpreted NY {srv.tz_localize(BTZ).tz_convert(NY)} | "
            f"UTC now {datetime.now(timezone.utc):%H:%M} | offset {BROKER_TZ} (auto={BROKER_TZ_AUTO})")
        log("           ^ 'interpreted NY' should match real New York wall-clock.")
    # METHOD 2 — independent cross-check on the warmed bars (broker-independent anchor)
    def weekend_crosscheck() -> bool:
        ok = True
        for sym2 in ACTIVE_SYMBOLS:
            mkt = market_of(sym2)
            # Index CFDs have their OWN session calendars (DAX closes Fri 16:00 NY, US
            # holidays close 12-13:00) — the Fri-16-17-NY fingerprint is an FX/gold anchor.
            # July 12 fix: GER40 15/25 tripped a FALSE "TIMEZONE CROSS-CHECK FAILED" while
            # every FX feed was 20/20. Indices rely on measured-offset METHOD 1 instead.
            if mkt in MINLOT_SYMBOLS and mkt != "XAUUSD":
                log(f"TZ VERIFY [{sym2}]: index CFD — own session calendar, weekend "
                    f"fingerprint n/a (covered by the measured-offset check)")
                continue
            # July 20 2026 fix: COARSE feeds (H4/D1) skip the weekend fingerprint.
            # Real broker H4 history has missing/truncated final Friday bars at ~half
            # the weekend boundaries (measured live: XAUUSD_H4 48/89, EURUSD_H4 53/89
            # while EVERY H1 feed on the SAME markets read 21/21 CONSISTENT OK and the
            # tick-measured offset was UTC+03:00). A coarse-bar fingerprint is
            # structurally unreliable on gappy history — same class of false positive
            # as the July 12 GER40 index incident and the July 16 H4 grid-phase bug,
            # and it froze the whole book's entries again on July 20. Coverage is NOT
            # lost: the same market's fine-grained feed still runs the fingerprint,
            # and the authoritative tick-offset METHOD-1 check runs for everything.
            if SYMBOLS[sym2].get("bar_min", 60) >= 240:
                log(f"TZ VERIFY [{sym2}]: coarse TF (>=H4) — weekend fingerprint n/a "
                    f"(covered by the same market's fine-TF fingerprint + measured offset)")
                continue
            if verify_tz_via_weekend(caches[sym2][0].df, sym2) is False:
                ok = False
        return ok

    tz_entries_ok = weekend_crosscheck()
    if not tz_entries_ok:
        log("!!! TIMEZONE CROSS-CHECK FAILED — the measured offset does not put Friday close at "
            "17:00 NY. Session filters would be WRONG. Investigate before trusting live signals.")
        log("!!! TZ ENTRY GATE ENGAGED — NEW ENTRIES DISABLED (July 15 2026 fix). Existing "
            "positions are still managed (trails/exits/closes). Re-measuring every 15 min; "
            "entries re-enable automatically once the cross-check passes.")

    last_bar = {sym: None for sym in ACTIVE_SYMBOLS}
    last_tz_day = datetime.now(timezone.utc).date()
    last_tz_retry = time.time()
    while True:
        try:
            if not ensure_connection():
                time.sleep(300); continue
            # daily broker-TZ re-check; on a DST shift, rebuild every cache cleanly
            today = datetime.now(timezone.utc).date()
            if today != last_tz_day:
                last_tz_day = today
                if refresh_broker_tz():
                    log("Broker TZ changed — full resync of all caches.")
                    for c_m, c_b in caches.values():
                        c_m.full_sync(); c_b.full_sync()
                    was_ok = tz_entries_ok
                    tz_entries_ok = weekend_crosscheck()
                    if was_ok and not tz_entries_ok:
                        log("!!! TZ ENTRY GATE ENGAGED after daily re-measure — new entries "
                            "disabled until the cross-check passes.")
            # TZ ENTRY GATE recovery: while blocked, re-measure + resync + re-verify
            # every 15 min so a transient bad measurement heals without a restart.
            if not tz_entries_ok and time.time() - last_tz_retry >= 900:
                last_tz_retry = time.time()
                log("TZ ENTRY GATE: re-measuring broker offset and re-verifying...")
                if refresh_broker_tz():
                    log("Broker TZ changed — full resync of all caches.")
                    for c_m, c_b in caches.values():
                        c_m.full_sync(); c_b.full_sync()
                tz_entries_ok = weekend_crosscheck()
                log("TZ ENTRY GATE: " + ("CLEARED — entries re-enabled" if tz_entries_ok
                                         else "still failing — entries remain disabled"))
            now_utc = datetime.now(timezone.utc)
            prop_blocked = _prop_guard(state)
            if prop_blocked and state.get("prop", {}).get("halted"):
                save_state(state)
                time.sleep(POLL_SECONDS)
                continue                       # halted: only the log line above, no trading
            manage_positions(now_utc, state)
            manage_pending(state)
            poll_closed_trades(state)

            for sym in ACTIVE_SYMBOLS:
                sc = SYMBOLS[sym]
                rr = mt5.copy_rates_from_pos(broker_sym(market_of(sym)), TF_MAP[sc["tf"]], 0, 2)
                if rr is None or len(rr) < 2:
                    continue
                closed_t = int(rr[-2]["time"])
                if closed_t == last_bar[sym]:
                    continue
                # STALE-SIGNAL GUARD (July 15 2026 fix): on (re)start the last closed bar
                # can be hours/days old (weekend, downtime). A signal from that bar was
                # valid at ITS next-bar open, not now — entering late diverges from the
                # backtest (and on closed markets burns retries: SPX 10018 on Sun Jul 12).
                # First sight of a feed: skip evaluation if the bar closed >1.5 bars ago.
                if last_bar[sym] is None:
                    bar_sec = sc["bar_min"] * 60
                    srv_now = server_epoch_now()
                    age = None if srv_now is None else srv_now - (closed_t + bar_sec)
                    if age is not None and age > 1.5 * bar_sec:
                        last_bar[sym] = closed_t
                        log(f"[{sym}] restart catch-up: last closed bar is {age/3600:.1f}h "
                            f"old — STALE, evaluation skipped (no late entries)")
                        continue
                last_bar[sym] = closed_t

                c_main, c_bias = caches[sym]
                df_main = c_main.update(); df_bias = c_bias.update()
                if df_main is None or df_bias is None:
                    log(f"{sym}: data refresh failed — skipping bar (fail-safe)")
                    continue
                if sc["engine"] == "gold":
                    e5, e15 = build_gold_frame(df_main, df_bias)
                    frames = {sym: (e5, e15)}
                    cur = e5.iloc[-1]
                else:
                    frame = LS.prep_h1_frame(df_main, df_bias, sc.get("pctile_win", 720))
                    frames = {sym: frame}
                    cur = frame.iloc[-1]
                    if np.isfinite(float(cur.get("atr50", float("nan")))):
                        LIVE_TRAIL_BAR[sym] = dict(close=float(cur["close"]),
                                                   atr=float(cur["atr50"]),
                                                   hi22=float(frame["high"].tail(22).max()),
                                                   lo22=float(frame["low"].tail(22).min()))

                write_positions_snapshot()
                update_daily_pnl(cur["ny_date"])

                status = []
                for key, inst in INSTANCES.items():
                    if feed_of(inst) != sym:
                        continue
                    if not ENABLE.get(key):
                        status.append(f"{key}:off"); continue
                    if not tz_entries_ok:
                        status.append(f"{key}: TZ-GATE (no new entries)"); continue
                    if prop_blocked:
                        status.append(f"{key}: PROP-GATE (no new entries)"); continue
                    status.append(f"{key}: {try_enter(key, inst, frames, state)}")
                log(f"[{sym} {cur['ny_time']} NY] " + " | ".join(status))
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log("Shutdown requested. Open positions remain (managed on restart).")
            break
        except Exception as exc:  # noqa: BLE001
            log(f"ERROR in main loop: {type(exc).__name__}: {exc} — continuing")
            time.sleep(POLL_SECONDS)
    mt5.shutdown()


if __name__ == "__main__":
    main()
