"""Single source of truth for the FX H1 signal conditions (A and E families).

Both the backtest (fx_h1_backtest.run_A / run_E) AND the live bot call THESE functions,
so live == backtest by construction. Faithfulness is proven by verify_fx_signals.py:
re-running the backtests through these functions reproduces the exact validated R numbers
(USDCAD-A +21.7, EURUSD-E +48.8, GBPUSD-E +41.5, USDCHF-A short-only +24.8).

A-family (USDCAD-A, USDCHF-A): SMC sweep -> CHoCH -> FVG retest, H4-bias aligned.
E-family (EURUSD-E, GBPUSD-E): session-open displacement + H4 bias.

Risk bounds are ATR-relative (0.55 .. 8.0 x ATR50) — DIFFERENT from gold's fixed points.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import smc_engine

# Shared constants (identical to fx_h1_backtest)
RISK_LO_ATR, RISK_HI_ATR = 0.55, 8.0
MAX_TPD = 2

# ── Validated per-strategy configs (locked) ───────────────────────────────────
FX_STRATS = {
    "EURUSD-E": dict(symbol="EURUSD", family="E", rr=2.5, be_r=1.5,
                     consol_max_atr=1.5, disp_min_atr=1.2, close_loc=0.65,
                     consol_bars=6, max_hold=72, sides=("bullish", "bearish"),
                     hours=(2, 3, 4, 8, 9, 10, 14, 15)),   # WIDER session set — walk-forward
                     # validated (11/16 yrs +, 2024-26 all +), ~29 trades/yr vs 19 base, +101R.
    "GBPUSD-E": dict(symbol="GBPUSD", family="E", rr=2.5, be_r=1.5,
                     consol_max_atr=1.5, disp_min_atr=1.0, close_loc=0.65,
                     consol_bars=6, max_hold=72, sides=("bullish", "bearish")),
    "USDCAD-A": dict(symbol="USDCAD", family="A", rr=2.5, be_r=None,
                     atr_pct=0.25, choch_bars=36, sweep_bars=48, max_hold=96,
                     sides=("bullish", "bearish")),
    "USDCHF-A": dict(symbol="USDCHF", family="A", rr=2.5, be_r=None,
                     atr_pct=0.25, choch_bars=24, sweep_bars=36, max_hold=96,
                     sides=("bearish",)),   # SHORT-ONLY (longs drag; shorts +24.8R both splits)
    "XAUUSD-H1A": dict(symbol="XAUUSD", family="A", rr=2.0, be_r=1.5,
                       atr_pct=0.25, choch_bars=24, sweep_bars=36, max_hold=96,
                       sides=("bullish",)),  # GOLD H1, LONG-ONLY — +23.8R, PF 1.212,
                       # maxDD -9.6R, positive 12/18 years (sideways_lab.py, 2008-2025)
    "EURUSD-BOLL30": dict(symbol="EURUSD", family="BOLL", be_r=None,
                          bb_len=20, sd_mult=2.0, stop_atr=1.2, atrp_max=0.70,
                          hours=tuple(range(14, 24)), max_hold=20, max_tpd=3),
                          # 30m quiet-hours Bollinger fade -> SMA20 target. +54.9R, PF 1.10,
                          # 8/9 years positive, ~118 trades/yr (fx_lowtf_meanrev_lab.py).
                          # STRICTLY a low-cost edge: dies at spread >= ~1.2 pip — disable
                          # this strategy if the broker widens EURUSD spreads.
    "XAUUSD-STRAD": dict(symbol="XAUUSD", family="STRAD", be_r=None,
                         W=24, K=3.0, M=2.0, max_hold=48, max_tpd=2),
                         # GOLD H1 consolidation-breakout, LONG-only, CLOSE-CONFIRMED:
                         # bar closes above zone_hi+0.1*ATR -> enter next bar; stop = far zone
                         # edge; TP = entry + 2*zone_width. +43.6R, PF 1.78, maxDD -5.7R,
                         # 13/18 years positive; survives 3x cost (straddle labs, 2008-2025).
    "GBPUSD-P1": dict(symbol="GBPUSD", family="P1", rr=2.0, be_r=None,
                      L=30, wait=30, disp_mult=1.2, max_hold=60, max_tpd=2),
                      # Opposing-FVG reversal, LIMIT entry in the FVG-overlap zone.
                      # GBPUSD H1: +42R, PF 1.91, WR 49%, 12/17 yrs; COST-IMMUNE (3x: +43R);
                      # all parameter neighbors positive (ict_patterns_lab.py).
    "EURUSD-P1-30": dict(symbol="EURUSD", family="P1", rr=2.0, be_r=None,
                         L=30, wait=30, disp_mult=1.2, max_hold=60, max_tpd=2),
                         # Same pattern, EURUSD 30m: +21R, PF 1.36, holdout +10R, 7/9 yrs.
                         # Cost-sensitive (3x spread -> +7R): needs the cheap EURUSD spread.
    "USDCHF-P1": dict(symbol="USDCHF", family="P1", rr=2.0, be_r=None,
                      L=30, wait=30, disp_mult=1.2, max_hold=60, max_tpd=2),
                      # Opposing-FVG reversal on USDCHF H1 (fx_port_lab July 2026): +16R,
                      # avg +0.125R, train +10/holdout +6 both splits +, survives 2x cost,
                      # 8/17 yrs. Corr to existing USDCHF book -0.007 -> independent.
    # ── BOLL30R refined variant (boll15_refit_lab.py July 2026). The BOLL15 refit
    # proved the M15 family unsalvageable at the AUDITED live all-in cost (holdout
    # >=2024 negative for all three symbols at 0.8-1.0p; no regime gate or exit fixes
    # it — the leak is pure cost drag, not logic). The one live-cost survivor is the
    # M30 migration on EURUSD, LONG-only, with the calm filter tightened 0.70->0.50:
    # n=400/16y, WR 49.5%, avg +0.102, train +13.5 / holdout +27.4, 3x-stress +6.5.
    # COST-FRAGILE by nature (plateau positive 17/18 neighbors but 3x-robust only at
    # the center cells) — treat like BOLL30: disable if EURUSD all-in spread > ~1p.
    "EURUSD-BOLL30R": dict(symbol="EURUSD", family="BOLL", be_r=None,
                           bb_len=20, sd_mult=2.0, stop_atr=1.2, atrp_max=0.50,
                           hours=tuple(range(14, 24)), max_hold=20, max_tpd=3,
                           sides=("long",)),
    # ── BOLL15 family (July 2026, m15_deep_validation.py on 18.5y HistData M15) ──
    # Same quiet-hours Bollinger fade as BOLL30, one timeframe down. Validated on
    # 2008-2026 (train <=2023 spans euro crisis/2014 USD/Brexit/COVID/2022 hikes).
    # Sibling daily-R corr vs deployed strategies all < +0.22 -> additive edges.
    # LOW-COST edges (GBP survives 3x spread; EUR/CHF need <=2x — preflight guards).
    "EURUSD-BOLL15": dict(symbol="EURUSD", family="BOLL", be_r=None,
                          bb_len=20, sd_mult=2.0, stop_atr=1.2, atrp_max=0.70,
                          hours=tuple(range(14, 24)), max_hold=20, max_tpd=3,
                          sides=("long",)),
                          # LONG-ONLY: +206R, PF 1.15, tr +172/ho +34, 16/19 years
                          # (short side drags -46R). corr vs BOLL30 +0.216.
    "GBPUSD-BOLL15": dict(symbol="GBPUSD", family="BOLL", be_r=None,
                          bb_len=20, sd_mult=2.0, stop_atr=1.2, atrp_max=0.70,
                          hours=tuple(range(14, 24)), max_hold=20, max_tpd=3,
                          sides=("long", "short")),
                          # +409R, PF 1.15, tr +362/ho +47, 17/19 years, COST-IMMUNE
                          # (3x: +294R) — strongest FX mean-reversion result on record.
    "USDCHF-BOLL15": dict(symbol="USDCHF", family="BOLL", be_r=None,
                          bb_len=20, sd_mult=2.0, stop_atr=1.2, atrp_max=0.70,
                          hours=tuple(range(14, 24)), max_hold=20, max_tpd=3,
                          sides=("long", "short")),
                          # +363R, PF 1.16, tr +308/ho +56, 19/19 YEARS positive.
                          # FEED-SENSITIVE: broker feed showed +35R vs deep +101R on the
                          # common window — expect live closer to the broker level.
    # ── GOLD TREND family (July 2026, gold_discovery_lab.py — gold TRENDS, FX doesn't) ──
    # LONG-only (gold structurally bullish; short sides bleed in bull runs). Both positive
    # across ALL regimes 2008-2026, 3x-cost-immune, corr to existing gold book < +0.16.
    "XAUUSD-DONCH": dict(symbol="XAUUSD", family="DONCH", N=96, rr=3.0, stop_atr=2.0,
                         max_hold=96, max_tpd=2),
                         # close breaks the 96-bar high +0.1ATR -> ride; +95.4R avg +0.116.
    "XAUUSD-DONCH-TR": dict(symbol="XAUUSD", family="DONCH", N=96, rr=None, stop_atr=2.0,
                            trail_atr=5.0, max_hold=192, max_tpd=2),
                            # EXIT-UPGRADE VARIANT (July 2026, discover_overlap.py):
                            # SAME entries as XAUUSD-DONCH (signal_DONCH N=96, structural
                            # 2xATR stop) but NO take-profit — a chandelier trail raises
                            # the SL to close - 5.0xATR(bar) on every CLOSED H1 bar,
                            # time exit 192 bars. OWNER-SELECTED cell (July 2026):
                            # trail 5.0. Validated on TZ-correct 2008-2026 with the LIVE
                            # stop convention (signal_close - 2xATR): n=609 +205.8R
                            # avg +0.338, WR 32.8%, realized R:R 3.14, train +157.4 /
                            # holdout +48.5, 2x +0.298 / 3x +0.273, maxDD -34.3R.
                            # Whole trail grid 2.5..5.0 passes; 5.0 = highest avg,
                            # NOTE: weaker holdout than trail 4.0 (+48.5 vs +66.0).
                            # MUTUALLY EXCLUSIVE with XAUUSD-DONCH: identical entries —
                            # enable exactly ONE of the two (owner's call).
    # ── INDEX TREND family (July 2026, idx_trend_lab.py — indices trend like gold) ──
    # Donchian-long replicated on 5/6 broker indices; CROSS-FEED VERIFIED on independent
    # HistData (WR matches to the point; Nikkei +61.4 vs +62.2, S&P +39.8 vs +41.8).
    # 18/18 neighbor cells pass, 2x-cost immune. LONG-only (secular-long assets).
    "SPX500-DONCH": dict(symbol="SPX500", family="DONCH", N=96, rr=3.0, stop_atr=2.0,
                         max_hold=96, max_tpd=2),
                         # +41.8R, WR 33%, avg +0.121; ~$2 risk/trade at 0.01 lot.
    "GER40-DONCH": dict(symbol="GER40", family="DONCH", N=96, rr=3.0, stop_atr=2.0,
                        max_hold=96, max_tpd=2),
                        # +62.9R, WR 32%, avg +0.192; ~$9 risk/trade at 0.01 lot.
    # ── VCX family (July 2026, discover_trend/discover_overlap.py): volatility-
    # contraction -> expansion breakout. The prior-96-bar box is at its tightest
    # (range percentile <= q over 720 bars) AND the close breaks the box high
    # + pad*ATR -> LONG, structural stop = close - stop_atr*ATR, TP = rr*risk.
    # 27/27 neighbor cells passed the iron gate on TZ-correct 2008-2026.
    # OVERLAP WARNING (measured): ~96% open-time overlap with XAUUSD-DONCH and
    # with each other — these stack the same gold-long trades. The two cells
    # below are OWNER-SELECTED; enable with the stacking cap in mind.
    # No swing/pivot logic is used anywhere in this family. House rule for any
    # future pivot logic: EXACTLY 5 closed candles left AND right (PIVOT_K=5).
    "XAUUSD-VCX-A": dict(symbol="XAUUSD", family="VCX", W=96, q=0.20, pad=0.2,
                         stop_atr=2.5, rr=3.0, max_hold=96, max_tpd=2),
                         # n=273 +97.0R avg +0.356, WR 38.1%, R:R 2.56, train +79.8 /
                         # holdout +17.3, 2x/3x +0.30/+0.25, maxDD -17.3R (live conv).
    "XAUUSD-VCX-B": dict(symbol="XAUUSD", family="VCX", W=96, q=0.25, pad=0.1,
                         stop_atr=2.0, rr=3.0, max_hold=96, max_tpd=2),
                         # n=339 +110.0R avg +0.325, WR 34.5%, R:R 2.83, train +81.2 /
                         # holdout +28.9, 2x/3x +0.27/+0.27, maxDD -16.6R (live conv).
    "XAUUSD-MACROSS": dict(symbol="XAUUSD", family="MACROSS", fast=20, slow=50, rr=3.0,
                           stop_atr=2.0, max_hold=96, max_tpd=2),
                           # EMA20x50 cross up, H4-bias aligned -> continuation; +49.8R avg +0.110.
    "XAUUSD-CRASH": dict(symbol="XAUUSD", family="CRASH", rr=2.0, stop_atr=2.0,
                         range_atr=2.0, close_loc=0.25, max_hold=96, max_tpd=2),
                         # CRASH-INSURANCE SHORT (metal_short_hunt.py, 2008-2025): bar range
                         # >=2xATR closing red in bottom 25% + H4 bias bearish -> short next
                         # open, stop close+2xATR, rr 2. +63.1R, WR 37%, avg +0.106, maxDD
                         # -22R. Pays in EVERY bear window (2011-15 +42, 2013 +23, 2022 +10);
                         # bleeds ~-10R in strong bull years (2024) — that's the premium.
                         # 2x/3x cost immune. INSURANCE for the 7-strategy gold-long stack.
    "XAUUSD-BOS": dict(symbol="XAUUSD", family="BOS", piv_k=3, pad=0.1, rr=5.0,
                       stop_atr=2.0, max_hold=96, max_tpd=2),
                       # STRUCTURE-BREAK CONTINUATION LONG (concepts_wave2_lab, 2008-2025):
                       # close crosses above the last CONFIRMED pivot high (k=3) +0.1*ATR ->
                       # momentum long, stop close-2ATR, TARGET 5R (exit grid: rr axis
                       # monotone 3->4->5 = +214/+221/+267R; gold trends run far).
                       # +267.4R, avg +0.170, WR 26%, maxDD -39.9, 14/18 yrs, THREE-x cost
                       # immune (+182R at 3x), 9/10 neighbors pass, family replicates on
                       # 4/5 indices. Overlap vs DONCH 30%/corr .29, MACROSS 19%/.24.
                       # WR 26% => 8-10 loss streaks are NORMAL - do not panic-disable.
    "GER40-BOS": dict(symbol="GER40", family="BOS", piv_k=3, pad=0.1, rr=3.0,
                      stop_atr=2.0, max_hold=96, max_tpd=2),
                      # DAX structure-break long: +51.6R/7y, avg +0.070, both splits + at
                      # 2x cost. rr3 NOT 5 - DAX rr axis is monotone DOWN (0.070/0.055/
                      # 0.053): its moves don't extend like gold's. Overlap vs GER40-DONCH
                      # 32%/corr .19. ~$10 risk/trade at 0.01 lot (rides min lot).
    # ── EQUITY-GATED index watchlist (validated idx_trend_lab July 2026; risk/trade
    # $15-21 at 0.01 lot => armed by the bot's equity gate, not by hand) ──
    "US30-DONCH": dict(symbol="US30", family="DONCH", N=96, rr=3.0, stop_atr=2.0,
                       max_hold=96, max_tpd=2),
                       # +26.1R avg +0.079, 4/8y; 18/18 family neighbors passed.
    "JPN225-DONCH": dict(symbol="JPN225", family="DONCH", N=96, rr=3.0, stop_atr=2.0,
                         max_hold=96, max_tpd=2),
                         # +62.2R avg +0.189, 6/8y; HistData cross-check +61.4.
    "HK50-MACROSS": dict(symbol="HK50", family="MACROSS", fast=20, slow=50, rr=3.0,
                         stop_atr=2.0, max_hold=96, max_tpd=2),
                         # +31.6R avg +0.231, 7/10y (best avg of the HK cells).
    "GBPUSD-AVWAP": dict(symbol="GBPUSD", family="AVWAP", k=1.5, stop_atr=1.2,
                         max_hold=20, max_tpd=3, sides=("short",),
                         hours=tuple(h for h in range(14, 24) if h != 17)),
                         # DAILY-AVWAP STRETCH FADE, SHORT-ONLY (avwap_liq_lab.py, 16y H1):
                         # close >= 1.5*ATR above the NY-day anchored VWAP in quiet hours ->
                         # fade back to the AVWAP. +123.0R, avg +0.084, WR 39.6% with ~1.7:1
                         # realized RR (winners ride to a far target), maxDD -22.5,
                         # 13/17 yrs +; 2x cost +89.3 (13/17), 3x +57; 9/9 neighbors pass
                         # (k 1.25-2.25, stop 1.0-1.4, hold 12-28); replicates on the broker
                         # feed (+59.7R 2020-26, holdout +27.2). LONG side drags — never add
                         # it without a fresh side-split validation. Overlap vs E/P1: 2.6%/
                         # 0.1% time, corr 0.00. Quiet-hours ESSENTIAL (all-hours -13.7R).
    # ── ZONE BREAKOUT family (zone_breakout_lab.py, July 2026). Structural-zone
    # momentum continuation, BOTH directions, entry-relative 2*ATR stop, fixed rr
    # target. House rule enforced: every pivot uses EXACTLY 5 closed candles left
    # AND right (pivot_k=5) — confirmed k bars AFTER the pivot bar (causal).
    "XAUUSD-ZBPIV": dict(symbol="XAUUSD", family="ZBPIV", pivot_k=5, pad=0.25,
                         stop_atr=2.0, rr=3.0, max_hold=60, max_tpd=2),
                         # H4 pivot-S/R breakout: n=708/18y, WR 32.3%, realized R:R
                         # 2.59, avg +0.16, train +87.9 / ho +23.7, 3x-stress +98.8,
                         # 10/10 param plateau; corr to deployed book <=0.20.
    "XAGUSD-ZBBOX": dict(symbol="XAGUSD", family="ZBBOX", N=24, tight=2.5, pad=0.1,
                         stop_atr=2.0, rr=2.0, max_hold=96, max_tpd=2),
                         # H1 Darvas box (24-bar box <= 2.5*ATR) breakout: n=125/15y,
                         # WR 41.6%, realized R:R 1.91, avg +0.21, train +17.3 /
                         # ho +9.0, 3x-stress +9.5, 10/10 plateau. FIRST validated
                         # silver edge (costs killed every lower-TF attempt).
    "SPX500-ZBPIV": dict(symbol="SPX500", family="ZBPIV", pivot_k=5, pad=0.1,
                         stop_atr=2.0, rr=2.0, max_hold=30, max_tpd=2),
                         # D1 pivot-S/R breakout: n=66/7y, WR 47.0% (highest-WR
                         # survivor), realized R:R 1.63, avg +0.23, train +12.2 /
                         # ho +2.7, 3x-stress +14.7, 10/10 plateau. D1 bars roll at
                         # broker midnight = 17:00 NY (EET-DST broker), matching the
                         # backtest day boundary exactly.
    "USDCHF-RSI30": dict(symbol="USDCHF", family="RSI", rr=1.5, be_r=None,
                         rsi_n=14, rsi_hi=75, stop_atr=1.0, atrp_max=0.70,
                         hours=tuple(range(14, 24)), max_hold=24, max_tpd=3),
                         # 30m quiet-hours Wilder-RSI(14) overbought fade, SHORT-ONLY
                         # (side-split validated July 2026: longs drag ho -5.2; shorts
                         # +23.5R, PF 1.62, WR 52%, maxDD -4.5R, positive 9/9 years,
                         # survives 3x cost; all threshold/stop/rr/hour neighbors positive).
                         # Overlap vs USDCHF-A: 1% time, daily-R corr -0.03 -> independent.
    # ── HAVW family (gs_battery_lab.py July 2026): Heikin-Ashi color flip + RSI
    # pullback + volume-weighted MACD cross, BOTH directions, 3-ATR chandelier
    # trail from the 22-bar extreme (trail_basis=hh22). Validated verify_gs_battery
    # 7/7 + 16-generator truncation audit; 36/36 parameter neighbors positive;
    # daily-R corr to entire gold book <= +0.05.
    "XAUUSD-HAVW": dict(symbol="XAUUSD", family="HAVW", rsi_n=14, rsi_lo=40,
                        rsi_hi=60, rsi_look=10, stop_atr=3.0, trail_atr=3.0,
                        trail_basis="hh22", max_hold=120, max_tpd=2),
                        # H1: n=369/5.7y, WR 52.6%, avg +0.166, train +43.4/ho +17.9,
                        # 3x +53.5, +every year 2020-25, maxDD -5.5R.
    "EURUSD-HAVW": dict(symbol="EURUSD", family="HAVW", rsi_n=14, rsi_lo=40,
                        rsi_hi=60, rsi_look=10, stop_atr=3.0, trail_atr=3.0,
                        trail_basis="hh22", max_hold=120, max_tpd=2),
                        # H4: n=320/18y, WR 63.1%, avg +0.277, train +71.3/ho +17.4,
                        # 3x +84.3, maxDD -2.5R.
    "GBPUSD-HAVW": dict(symbol="GBPUSD", family="HAVW", rsi_n=14, rsi_lo=40,
                        rsi_hi=60, rsi_look=10, stop_atr=3.0, trail_atr=3.0,
                        trail_basis="hh22", max_hold=120, max_tpd=2),
                        # H4: n=335/18y, WR 56.7%, avg +0.221, train +66.0/ho +8.1,
                        # 3x +69.9, maxDD -3.2R.
}

# Per-symbol ALL-IN round-trip cost (price units): raw spread + the $7/lot commission
# converted at pip value (measured from the user's own trade history 2026-07-06).
# Used for stop pads and the preflight 3x-cost warning — keep these HONEST.
FX_SPREADS = {"EURUSD": 0.00008, "GBPUSD": 0.00010, "USDCAD": 0.00014, "USDCHF": 0.00010,
              "XAGUSD": 0.032,  # silver: 0.03 spread + $7/lot on 5000oz = 0.0014 commission
              "XAUUSD": 0.23,   # gold: 0.16 spread + $7/lot(100oz) = 0.07 pts commission
              "SPX500": 1.7, "GER40": 4.7,   # indices: live spread + $7/lot(contract 10)
              "US30": 3.4, "JPN225": 13.5, "HK50": 8.3}


# ── Frame prep (mirrors htf_discovery_lab.prep EXACTLY, but takes DataFrames) ──
def prep_h1_frame(df_h1: pd.DataFrame, df_h4: pd.DataFrame, pctile_win: int = 720) -> pd.DataFrame:
    """df_h1 / df_h4: columns timestamp_ny (tz-aware), open, high, low, close, volume.
    Returns the engine frame + atr50 / atr_pctile(pctile_win) / vol_ma50 / htf_bias (from H4).
    pctile_win = ~30 days of bars on the trade TF (720 at H1, 1440 at 30m)."""
    e1 = smc_engine.build_smc_frame(df_h1)
    prev_c = e1["close"].shift(1)
    tr = pd.concat([e1["high"] - e1["low"], (e1["high"] - prev_c).abs(),
                    (e1["low"] - prev_c).abs()], axis=1).max(axis=1)
    e1["atr50"] = tr.rolling(50, min_periods=20).mean()
    e1["atr_pctile"] = e1["atr50"].rolling(pctile_win, min_periods=200).rank(pct=True)
    e1["vol_ma50"] = e1["volume"].rolling(50, min_periods=20).mean()
    # daily anchored VWAP (NY-day anchor, typical price, tick-volume weighted) — used by
    # the AVWAP fade family; a harmless extra column for every other strategy.
    day = e1["timestamp_ny"].dt.date.astype(str).values
    tpv = (e1["high"] + e1["low"] + e1["close"]) / 3.0 * e1["volume"]
    e1["avwap_d"] = tpv.groupby(day).cumsum() / e1["volume"].groupby(day).cumsum()

    e4 = smc_engine.build_smc_frame(df_h4)
    htf = e4[["timestamp_ny", "swing_bias"]].copy()
    htf["timestamp_ny"] = htf["timestamp_ny"] + pd.Timedelta(hours=4)  # available after H4 close
    e1 = pd.merge_asof(e1.sort_values("timestamp_ny"),
                       htf.rename(columns={"swing_bias": "htf_bias"}),
                       on="timestamp_ny", direction="backward")
    e1["htf_bias"] = e1["htf_bias"].fillna(0).astype(int)
    return e1


def build_arrays(e: pd.DataFrame) -> dict:
    """Numpy arrays used by the signal functions (identical set to fx_h1_backtest._arrays)."""
    return dict(
        h=e["high"].to_numpy(float), l=e["low"].to_numpy(float),
        o=e["open"].to_numpy(float), c=e["close"].to_numpy(float),
        atr=e["atr50"].to_numpy(float), atrp=e["atr_pctile"].to_numpy(float),
        htf=e["htf_bias"].to_numpy(int), ltf=e["swing_bias"].to_numpy(int),
        iev=e["internal_event"].to_numpy(object), swp=e["sweep_direction"].to_numpy(object),
        hrs=e["timestamp_ny"].dt.hour.to_numpy(),
        bt=e["bull_fvg_top"].to_numpy(float), bb=e["bull_fvg_bottom"].to_numpy(float),
        ba=e["bull_fvg_age"].to_numpy(float), brt=e["bear_fvg_top"].to_numpy(float),
        brb=e["bear_fvg_bottom"].to_numpy(float), bra=e["bear_fvg_age"].to_numpy(float),
        lsl=e["last_swing_low"].to_numpy(float), lsh=e["last_swing_high"].to_numpy(float),
    )


def update_choch_sweep_state(a: dict, i: int, lc: dict, ls: dict) -> None:
    """Advance the running 'most-recent CHoCH / sweep' state to include bar i (in place)."""
    v = a["iev"][i]
    if v == "bullish_choch":   lc["bullish"] = i
    elif v == "bearish_choch": lc["bearish"] = i
    s = a["swp"][i]
    if s == "bullish":   ls["bullish"] = i
    elif s == "bearish": ls["bearish"] = i


# ── A-family per-bar signal (sweep -> CHoCH -> FVG retest, H4 bias) ────────────
def signal_A(a: dict, i: int, lc: dict, ls: dict, cfg: dict, sides=None):
    """Return (side, stop_base, atr) for a signal at bar i, else None. Pure condition —
    the caller handles entry@i+1, daily cap, overlap lock, risk bounds, exits."""
    if sides is None:
        sides = cfg.get("sides", ("bullish", "bearish"))
    # NaN-safe: an unwarmed (NaN) ATR-percentile must SKIP, never vacuously pass the gate.
    # (Matches the gold path's `not (atr_pctile > min)` form; the live cache is always warmed.)
    if not (a["atrp"][i] > cfg["atr_pct"]) or a["hrs"][i] == 17:
        return None
    for direction in sides:
        side = 1 if direction == "bullish" else -1
        ci, si = lc[direction], ls[direction]
        if ci is None or i - ci > cfg["choch_bars"]:            continue
        if si is None or si > ci or i - si > cfg["sweep_bars"]: continue
        if a["htf"][i] != side:                                 continue
        if side == -1 and a["ltf"][i] != -1:                    continue
        ftop = a["bt"][i] if side == 1 else a["brt"][i]
        fbot = a["bb"][i] if side == 1 else a["brb"][i]
        fage = a["ba"][i] if side == 1 else a["bra"][i]
        if np.isnan(ftop) or np.isnan(fbot) or not (fage > 0): continue
        if not (a["l"][i] <= ftop and a["h"][i] >= fbot):       continue
        if side == 1:
            base = min(a["lsl"][i] if not np.isnan(a["lsl"][i]) else fbot, fbot)
        else:
            base = max(a["lsh"][i] if not np.isnan(a["lsh"][i]) else ftop, ftop)
        return side, float(base), float(a["atr"][i])
    return None


# ── E-family per-bar signal (session-open displacement + H4 bias) ─────────────
def signal_E(a: dict, i: int, cfg: dict):
    """Return (side, stop_base, atr) for a signal at bar i, else None."""
    cb = cfg["consol_bars"]
    if i < cb:
        return None
    if a["hrs"][i] not in cfg.get("hours", (3, 4, 9, 10)):   # default base set if unspecified
        return None
    if not (a["atrp"][i] > 0.25):           # NaN-safe (unwarmed regime skips, never vacuous-passes)
        return None
    if np.isnan(a["atr"][i]):
        return None
    pre_h = a["h"][i - cb:i].max(); pre_l = a["l"][i - cb:i].min()
    if pre_h - pre_l > cfg["consol_max_atr"] * a["atr"][i]:
        return None
    rng = a["h"][i] - a["l"][i]
    if rng < cfg["disp_min_atr"] * a["atr"][i]:
        return None
    if a["c"][i] > a["o"][i] and (a["c"][i] - a["l"][i]) / max(rng, 1e-9) >= cfg["close_loc"] and a["htf"][i] == 1:
        return 1, float(a["l"][i]), float(a["atr"][i])
    if a["c"][i] < a["o"][i] and (a["h"][i] - a["c"][i]) / max(rng, 1e-9) >= cfg["close_loc"] and a["htf"][i] == -1:
        return -1, float(a["h"][i]), float(a["atr"][i])
    return None


def signal_BOLL(e: pd.DataFrame, i: int, cfg: dict):
    """Quiet-hours Bollinger fade (mirrors fx_lowtf_meanrev_lab.f1_boll EXACTLY).
    Close beyond the sd_mult band + calm regime -> fade toward the 20-SMA.
    Returns (side, sma_target, atr) or None. Stop is ATR-offset from ENTRY (handled
    by the caller): stop = entry -/+ stop_atr*ATR -/+ half-spread."""
    n = cfg["bb_len"]
    if i < n:
        return None
    row_hour = int(e["timestamp_ny"].iloc[i].hour)
    if row_hour == 17 or row_hour not in cfg["hours"]:
        return None
    atrp = float(e["atr_pctile"].iloc[i]); atr = float(e["atr50"].iloc[i])
    if not (atrp <= cfg["atrp_max"]) or not np.isfinite(atr):
        return None
    win = e["close"].iloc[i - n + 1: i + 1]
    sma = float(win.mean()); sd = float(win.std(ddof=1))
    close = float(e["close"].iloc[i])
    if close < sma - cfg["sd_mult"] * sd:
        return 1, sma, atr
    if close > sma + cfg["sd_mult"] * sd:
        return -1, sma, atr
    return None


def signal_STRAD(e: pd.DataFrame, i: int, cfg: dict):
    """Gold H1 consolidation-breakout, LONG-only, close-confirmed (mirrors the validated
    close-confirmed straddle backtest EXACTLY). Zone = W-bar band over bars [i-W..i-1]
    (shift-1 rolling). CONSOL if 1*ATR <= width <= K*ATR. Signal: bar i CLOSES above
    zone_hi + 0.1*ATR. Returns (stop_base, width, atr) or None."""
    W = cfg["W"]
    if i < W + 1:
        return None
    if int(e["timestamp_ny"].iloc[i].hour) == 17:
        return None
    atr = float(e["atr50"].iloc[i])
    if not np.isfinite(atr):
        return None
    zone_hi = float(e["high"].iloc[i - W: i].max())
    zone_lo = float(e["low"].iloc[i - W: i].min())
    width = zone_hi - zone_lo
    if not (1.0 * atr <= width <= cfg["K"] * atr):
        return None
    buy_lvl = zone_hi + 0.10 * atr
    if float(e["close"].iloc[i]) > buy_lvl:
        return zone_lo - 0.10 * atr, width, atr       # stop base, zone width, atr
    return None


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI via EWM(alpha=1/n) — byte-identical to fx_lowtf_meanrev_lab.wilder_rsi.
    Forward-recursive only (value at bar i depends solely on bars <= i)."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def signal_RSI(e: pd.DataFrame, i: int, cfg: dict):
    """Quiet-hours RSI overbought fade, SHORT-ONLY (mirrors fx_lowtf_meanrev_lab.f2_rsi's
    short leg EXACTLY). RSI(14) > rsi_hi in a calm regime during NY quiet hours -> fade.
    Returns atr or None. Stop is ATR-offset from ENTRY and TP = rr * risk — both are
    entry-relative, so the caller computes them (same split as the BOLL family)."""
    row_hour = int(e["timestamp_ny"].iloc[i].hour)
    if row_hour == 17 or row_hour not in cfg["hours"]:
        return None
    atrp = float(e["atr_pctile"].iloc[i]); atr = float(e["atr50"].iloc[i])
    # NaN-safe: an unwarmed percentile/ATR must SKIP, never vacuously pass.
    if not (atrp <= cfg["atrp_max"]) or not np.isfinite(atr):
        return None
    rsi = float(wilder_rsi(e["close"].iloc[: i + 1], cfg["rsi_n"]).iloc[-1])
    if rsi > cfg["rsi_hi"]:
        return atr
    return None


def signal_P1(e: pd.DataFrame, i: int, cfg: dict):
    """Opposing-FVG reversal (mirrors ict_patterns_lab.p1_opposing_fvg EXACTLY).
    A displacement FVG in one direction followed within L bars by an opposing
    displacement FVG that closes beyond the prior swing -> the OVERLAP of the two FVGs
    is a LIMIT-entry zone. Returns dict(direction, limit, stop_base, atr) or None.
    Only the last-L-bars window matters, so the scan is O(L) and causal."""
    L = cfg["L"]
    if i < 25 + L:
        return None
    if int(e["timestamp_ny"].iloc[i].hour) == 17:
        return None
    atr_i = float(e["atr50"].iloc[i])
    if not np.isfinite(atr_i):
        return None
    h = e["high"].to_numpy(float); l = e["low"].to_numpy(float)
    c = e["close"].to_numpy(float); a = e["atr50"].to_numpy(float)
    bull = bear = None                              # (top, bottom, bar)
    for t in range(i - L, i + 1):
        if not np.isfinite(a[t]):
            continue
        disp = (h[t - 1] - l[t - 1]) >= cfg["disp_mult"] * a[t]
        if disp and l[t] > h[t - 2]:
            bull = (l[t], h[t - 2], t)
        if disp and h[t] < l[t - 2]:
            bear = (l[t - 2], h[t], t)
    # SELL: bear FVG formed AT bar i, bull FVG before it within L, close below prior swing low
    if bear and bear[2] == i and bull and 0 < i - bull[2] <= L:
        b = bull[2]
        swing_lo = float(np.min(l[b - 22: b - 2]))          # shift(3).rolling(20) at bar b
        if c[i] < swing_lo:
            z_lo = max(bear[1], bull[1]); z_hi = min(bear[0], bull[0])
            if z_hi > z_lo:
                return dict(direction="short", limit=float(z_lo),
                            stop_base=float(z_hi + 0.1 * atr_i), atr=atr_i)
    # BUY mirror: bull FVG formed AT bar i after a bear FVG, close above prior swing high
    if bull and bull[2] == i and bear and 0 < i - bear[2] <= L:
        b = bear[2]
        swing_hi = float(np.max(h[b - 22: b - 2]))
        if c[i] > swing_hi:
            z_lo = max(bull[1], bear[1]); z_hi = min(bull[0], bear[0])
            if z_hi > z_lo:
                return dict(direction="long", limit=float(z_hi),
                            stop_base=float(z_lo - 0.1 * atr_i), atr=atr_i)
    return None


def signal_DONCH(e: pd.DataFrame, i: int, cfg: dict):
    """Gold Donchian breakout, LONG-only (mirrors gold_discovery_lab EXACTLY): the close
    breaks above the prior-N-bar high + 0.1*ATR -> enter next open, structural stop at
    signal-close - stop_atr*ATR, target rr*risk. Channel excludes the current bar
    (shift-1 rolling), so the signal is fully causal."""
    N = cfg["N"]
    if i < N:
        return None
    atr = float(e["atr50"].iloc[i])
    if not np.isfinite(atr):
        return None
    hi = float(e["high"].iloc[i - N:i].max())            # bars [i-N, i-1]
    close = float(e["close"].iloc[i])
    if close > hi + 0.1 * atr:
        return dict(direction="long", stop=close - cfg["stop_atr"] * atr,
                    atr=atr, rr=cfg["rr"])
    return None


def signal_VCX(e: pd.DataFrame, i: int, cfg: dict):
    """Volatility-contraction -> expansion breakout, LONG-only (mirrors
    discover_trend.vcx_sig EXACTLY): the prior-W-bar box range sits in its
    tightest q-percentile of the past 720 bars AND the close breaks the box
    high + pad*ATR. Stop = close - stop_atr*ATR, target = rr*risk. Fully
    causal: box and percentile use bars [i-W, i-1] via shift(1) windows.
    NO pivot/swing logic (house rule: future pivots use exactly 5L/5R)."""
    W = cfg["W"]
    if i < W + 250:
        return None
    atr = float(e["atr50"].iloc[i])
    if not np.isfinite(atr):
        return None
    h = e["high"]; l = e["low"]
    rng = h.shift(1).rolling(W).max() - l.shift(1).rolling(W).min()
    tight = rng.rolling(720, min_periods=200).rank(pct=True)
    tp = float(tight.iloc[i])
    if not (np.isfinite(tp) and tp <= cfg["q"]):
        return None
    boxhi = float(h.iloc[i - W:i].max())
    close = float(e["close"].iloc[i])
    if close > boxhi + cfg["pad"] * atr:
        return dict(direction="long", stop=close - cfg["stop_atr"] * atr,
                    atr=atr, rr=cfg["rr"])
    return None


def signal_MACROSS(e: pd.DataFrame, i: int, cfg: dict):
    """Gold EMA-cross momentum, LONG-only (mirrors gold_discovery_lab EXACTLY): fast EMA
    crosses ABOVE slow EMA on bar i AND the H4 bias is bullish -> continuation long,
    structural stop at close - stop_atr*ATR, target rr*risk. EMAs are recursive (causal);
    on the bot's ~2500-bar cache they are byte-identical to full history beyond warmup."""
    if i < cfg["slow"] + 2:
        return None
    atr = float(e["atr50"].iloc[i])
    if not np.isfinite(atr):
        return None
    close = e["close"]
    ef = close.ewm(span=cfg["fast"], adjust=False).mean()
    es = close.ewm(span=cfg["slow"], adjust=False).mean()
    cross_up = ef.iloc[i] > es.iloc[i] and ef.iloc[i - 1] <= es.iloc[i - 1]
    if not cross_up:
        return None
    if int(e["htf_bias"].iloc[i]) != 1:
        return None
    return dict(direction="long", stop=float(close.iloc[i]) - cfg["stop_atr"] * atr,
                atr=atr, rr=cfg["rr"])


def signal_CRASH(e: pd.DataFrame, i: int, cfg: dict):
    """Gold crash-continuation, SHORT-only (mirrors metal_short_hunt EXACTLY): bar i has
    range >= range_atr*ATR, closes red in the bottom close_loc of its range, AND the H4
    bias is bearish -> short next open, stop at close + stop_atr*ATR, target rr*risk.
    Uses only bar i's own OHLC + ATR + merged H4 bias — fully causal."""
    atr = float(e["atr50"].iloc[i])
    if not np.isfinite(atr):
        return None
    o = float(e["open"].iloc[i]); h = float(e["high"].iloc[i])
    l = float(e["low"].iloc[i]); c = float(e["close"].iloc[i])
    rng = h - l
    if rng <= 0 or rng < cfg["range_atr"] * atr:
        return None
    if not (c < o and (c - l) <= cfg["close_loc"] * rng):
        return None
    if int(e["htf_bias"].iloc[i]) != -1:
        return None
    return dict(direction="short", stop=c + cfg["stop_atr"] * atr,
                atr=atr, rr=cfg["rr"])


def _last_pivot_high(h: np.ndarray, j: int, k: int):
    """Most recent CONFIRMED pivot high as of bar j (pivot at p needs bars p-k..p+k, so
    it is confirmed when j >= p+k). Mirrors concepts_rank_lab.pivot_levels exactly."""
    for p in range(j - k, k - 1, -1):
        if h[p] == h[p - k:p + k + 1].max():
            return float(h[p])
    return np.nan


def signal_BOS(e: pd.DataFrame, i: int, cfg: dict):
    """Structure-break continuation, LONG-only (mirrors concepts_wave2_lab.q8_bos
    EXACTLY): the close CROSSES above the last confirmed pivot-high level + pad*ATR
    (previous close was at-or-below its own bar's threshold). Stop close - stop_atr*ATR,
    target rr*risk. Fully causal: pivots need k bars of right-hand confirmation."""
    k = cfg["piv_k"]
    if i < 2 * k + 2:
        return None
    atr_i = float(e["atr50"].iloc[i])
    atr_p = float(e["atr50"].iloc[i - 1])
    if not (np.isfinite(atr_i) and np.isfinite(atr_p)):
        return None
    h = e["high"].to_numpy(float)
    lvl_i = _last_pivot_high(h, i, k)
    lvl_p = _last_pivot_high(h, i - 1, k)
    if not (np.isfinite(lvl_i) and np.isfinite(lvl_p)):
        return None
    c_i = float(e["close"].iloc[i]); c_p = float(e["close"].iloc[i - 1])
    if c_i > lvl_i + cfg["pad"] * atr_i and c_p <= lvl_p + cfg["pad"] * atr_p:
        return dict(direction="long", stop=c_i - cfg["stop_atr"] * atr_i,
                    atr=atr_i, rr=cfg["rr"])
    return None


def signal_AVWAP(e: pd.DataFrame, i: int, cfg: dict):
    """Daily-AVWAP stretch fade, SHORT-only (mirrors avwap_liq_lab.exec_fade EXACTLY):
    in the quiet-hours window the close sits >= k*ATR ABOVE the NY-day anchored VWAP ->
    fade back toward it. Stop is entry-relative (stop_atr*ATR, the BOLL convention);
    target is the ABSOLUTE avwap_d value at the signal bar. Fully causal: avwap_d at
    bar i uses bars of the same NY day up to and including the closed bar i."""
    atr = float(e["atr50"].iloc[i])
    vw = float(e["avwap_d"].iloc[i])
    if not (np.isfinite(atr) and np.isfinite(vw)):
        return None
    if e["timestamp_ny"].iloc[i].hour not in cfg["hours"]:
        return None
    c = float(e["close"].iloc[i])
    if "short" in cfg["sides"] and c - vw >= cfg["k"] * atr:
        return dict(direction="short", target=vw, atr=atr, stop_atr=cfg["stop_atr"])
    if "long" in cfg["sides"] and vw - c >= cfg["k"] * atr:
        return dict(direction="long", target=vw, atr=atr, stop_atr=cfg["stop_atr"])
    return None


def _pivot_arrays(h, l, k):
    """Verbatim port of concepts_rank_lab.pivot_levels: causal pivot levels.
    A pivot at bar i needs h[i] == max(h[i-k..i+k]) (EXACTLY k closed candles each
    side, house PIVOT_K=5) and is only VISIBLE from bar i+k (confirmation bar).
    Returns lvl_hi[t], lvl_lo[t] = most recent confirmed pivot high/low as of t."""
    n = len(h)
    lvl_hi = np.full(n, np.nan); lvl_lo = np.full(n, np.nan)
    cur_hi = cur_lo = np.nan
    for i in range(k, n - k):
        cur_hi_new = h[i] if h[i] == h[i - k:i + k + 1].max() else None
        cur_lo_new = l[i] if l[i] == l[i - k:i + k + 1].min() else None
        t = i + k
        if cur_hi_new is not None:
            cur_hi = cur_hi_new
        if cur_lo_new is not None:
            cur_lo = cur_lo_new
        if t < n:
            lvl_hi[t] = cur_hi; lvl_lo[t] = cur_lo
    lvl_hi = pd.Series(lvl_hi).ffill().to_numpy()
    lvl_lo = pd.Series(lvl_lo).ffill().to_numpy()
    return lvl_hi, lvl_lo


def signal_ZBPIV(e: pd.DataFrame, i: int, cfg: dict):
    """Pivot-S/R zone breakout (mirrors zone_breakout_lab.sig_piv5 EXACTLY):
    close crosses the most recent CONFIRMED pivot high + pad*ATR -> long; below
    pivot low - pad*ATR -> short. Cross = previous close was on/inside the level."""
    if i < 2 * cfg["pivot_k"] + 2:
        return None
    h = e["high"].to_numpy(float); l = e["low"].to_numpy(float)
    c = e["close"].to_numpy(float); atr = e["atr50"].to_numpy(float)
    if not (np.isfinite(atr[i]) and np.isfinite(atr[i - 1])):
        return None
    hi, lo = _pivot_arrays(h[:i + 1], l[:i + 1], cfg["pivot_k"])
    pad = cfg["pad"]
    if np.isfinite(hi[i]) and np.isfinite(hi[i - 1])             and c[i] > hi[i] + pad * atr[i] and c[i - 1] <= hi[i - 1] + pad * atr[i - 1]:
        return dict(direction="long", atr=float(atr[i]),
                    stop_atr=cfg["stop_atr"], rr=cfg["rr"])
    if np.isfinite(lo[i]) and np.isfinite(lo[i - 1])             and c[i] < lo[i] - pad * atr[i] and c[i - 1] >= lo[i - 1] - pad * atr[i - 1]:
        return dict(direction="short", atr=float(atr[i]),
                    stop_atr=cfg["stop_atr"], rr=cfg["rr"])
    return None


def signal_ZBBOX(e: pd.DataFrame, i: int, cfg: dict):
    """Darvas/rectangle congestion breakout (mirrors zone_breakout_lab.sig_box
    EXACTLY): the N CLOSED bars before i form a box (range <= tight*ATR); a close
    beyond the box edge +/- pad*ATR is the expansion trigger. Both directions."""
    N = cfg["N"]
    if i < N + 1:
        return None
    h = e["high"].to_numpy(float); l = e["low"].to_numpy(float)
    c = e["close"].to_numpy(float); atr = e["atr50"].to_numpy(float)
    if not np.isfinite(atr[i]):
        return None
    bh = h[i - N:i].max(); bl = l[i - N:i].min()
    if (bh - bl) > cfg["tight"] * atr[i]:
        return None
    if c[i] > bh + cfg["pad"] * atr[i]:
        return dict(direction="long", atr=float(atr[i]),
                    stop_atr=cfg["stop_atr"], rr=cfg["rr"])
    if c[i] < bl - cfg["pad"] * atr[i]:
        return dict(direction="short", atr=float(atr[i]),
                    stop_atr=cfg["stop_atr"], rr=cfg["rr"])
    return None


def signal_HAVW(e: pd.DataFrame, i: int, cfg: dict):
    """Heikin-Ashi flip + RSI pullback + VW-MACD cross (mirrors gs_battery_lab
    ev_havw EXACTLY). Long: HA flips red->green at bar i, RSI(14) dipped below
    rsi_lo within the last rsi_look bars, VW-MACD crosses above its signal at i.
    Short is the mirror. Stop = close -/+ stop_atr*ATR (entry-relative structural);
    the chandelier trail (trail_atr from the 22-bar extreme) owns the exit."""
    if i < 60:
        return None
    o = e["open"].to_numpy(float); h = e["high"].to_numpy(float)
    l = e["low"].to_numpy(float); c = e["close"].to_numpy(float)
    atr = e["atr50"].to_numpy(float)
    if not np.isfinite(atr[i]):
        return None
    v = e["volume"].fillna(1.0).to_numpy(float) if "volume" in e else np.ones(len(c))
    if not np.isfinite(v).all() or v.sum() <= 0:
        v = np.ones(len(c))
    ha_c = (o + h + l + c) / 4
    ha_o = np.empty(i + 1); ha_o[0] = o[0]
    for k in range(1, i + 1):
        ha_o[k] = (ha_o[k - 1] + ha_c[k - 1]) / 2
    green_i = ha_c[i] > ha_o[i]; green_p = ha_c[i - 1] > ha_o[i - 1]
    if green_i == green_p:
        return None
    d = np.diff(c[:i + 1], prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / cfg["rsi_n"], adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / cfg["rsi_n"], adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
    pv = pd.Series(c[:i + 1] * v[:i + 1])
    vs_ = pd.Series(v[:i + 1])
    vw_fast = pv.ewm(span=12, adjust=False).mean() / vs_.ewm(span=12, adjust=False).mean()
    vw_slow = pv.ewm(span=26, adjust=False).mean() / vs_.ewm(span=26, adjust=False).mean()
    macd = (vw_fast - vw_slow).to_numpy()
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().to_numpy()
    look = cfg["rsi_look"]
    if (green_i and rsi[i - look:i].min() < cfg["rsi_lo"]
            and macd[i] > sig[i] and macd[i - 1] <= sig[i - 1]):
        return dict(direction="long", atr=float(atr[i]),
                    stop=float(c[i] - cfg["stop_atr"] * atr[i]))
    if (not green_i and rsi[i - look:i].max() > cfg["rsi_hi"]
            and macd[i] < sig[i] and macd[i - 1] >= sig[i - 1]):
        return dict(direction="short", atr=float(atr[i]),
                    stop=float(c[i] + cfg["stop_atr"] * atr[i]))
    return None


def signal_at_last_bar(e: pd.DataFrame, cfg: dict):
    """Live entry point: evaluate the LAST (most recently closed) bar of frame `e`.
    Returns dict(direction, stop, atr) or None — for family BOLL the dict instead
    carries (direction, target, atr, stop_atr) since the stop is entry-relative.
    Builds the running CHoCH/sweep state in a single pass — identical values to the
    backtest's accumulated state."""
    i = len(e) - 1
    if cfg["family"] == "BOLL":
        res = signal_BOLL(e, i, cfg)
        if res is None:
            return None
        side, sma, atr = res
        direction = "long" if side == 1 else "short"
        # optional side restriction (EURUSD-BOLL15 is long-only); absent key = both sides
        if direction not in cfg.get("sides", ("long", "short")):
            return None
        return dict(direction=direction,
                    target=sma, atr=atr, stop_atr=cfg["stop_atr"])
    if cfg["family"] == "STRAD":
        res = signal_STRAD(e, i, cfg)
        if res is None:
            return None
        stop_base, width, atr = res
        return dict(direction="long", stop=stop_base, atr=atr,
                    width=width, m=cfg["M"])
    if cfg["family"] == "P1":
        return signal_P1(e, i, cfg)      # dict(direction, limit, stop_base, atr) or None
    if cfg["family"] == "RSI":
        atr = signal_RSI(e, i, cfg)
        if atr is None:
            return None
        return dict(direction="short", atr=atr,
                    stop_atr=cfg["stop_atr"], rr=cfg["rr"])
    if cfg["family"] == "DONCH":
        return signal_DONCH(e, i, cfg)      # dict(direction=long, stop, atr, rr) or None
    if cfg["family"] == "MACROSS":
        return signal_MACROSS(e, i, cfg)    # dict(direction=long, stop, atr, rr) or None
    if cfg["family"] == "VCX":
        return signal_VCX(e, i, cfg)        # dict(direction=long, stop, atr, rr) or None
    if cfg["family"] == "CRASH":
        return signal_CRASH(e, i, cfg)      # dict(direction=short, stop, atr, rr) or None
    if cfg["family"] == "AVWAP":
        return signal_AVWAP(e, i, cfg)      # BOLL-shaped dict(direction, target, atr, stop_atr)
    if cfg["family"] == "ZBPIV":
        return signal_ZBPIV(e, i, cfg)      # dict(direction, atr, stop_atr, rr) both sides
    if cfg["family"] == "HAVW":
        return signal_HAVW(e, i, cfg)       # dict(direction, stop, atr) both sides
    if cfg["family"] == "ZBBOX":
        return signal_ZBBOX(e, i, cfg)      # dict(direction, atr, stop_atr, rr) both sides
    if cfg["family"] == "BOS":
        return signal_BOS(e, i, cfg)        # dict(direction=long, stop, atr, rr) or None
    a = build_arrays(e)
    if cfg["family"] == "A":
        lc = {"bullish": None, "bearish": None}
        ls = {"bullish": None, "bearish": None}
        for k in range(i + 1):
            update_choch_sweep_state(a, k, lc, ls)
        res = signal_A(a, i, lc, ls, cfg)
    else:
        res = signal_E(a, i, cfg)
    if res is None:
        return None
    side, base, atr = res
    return dict(direction="long" if side == 1 else "short", stop=base, atr=atr)
