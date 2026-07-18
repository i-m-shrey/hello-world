"""GS BATTERY LAB — owner's 20-strategy document, tested under house law (July 2026).

Document strategies mapped to already-VALIDATED live book (not re-tested here):
  GS-05 VCX            == XAUUSD_VCX_A/B (deployed, verify_vcx.py)
  Strategy 8 Chandelier == XAUUSD_DONCH_TR exit-twin (deployed)
  Strategy 10 Kelly/sizing == house risk caps + mc_capital.py / mc_gate_sizing.py
  Strategy 4 News (NFP/CPI) == SKIPPED: needs tick-stamped economic calendar; the
      house news_archive.csv is headline-level, not release-second-level. Honest skip.

Everything else is implemented below EXACTLY as specified (tweaks noted per family),
under house law: real all-in costs both sides, causal signals (pivot confirmed K bars
late, entry NEXT bar open / limit fills touch-checked pessimistically), train<=2023 /
holdout>=2024 both positive, 3x cost-stress, PIVOT_K=5 everywhere a pivot is used.

Families:
  GS01  OB+FVG confluence limit    GS02  PIV5 sweep-fail reversal
  GS03  NY open-range breakout     GS04  20-day channel + 4ATR trail
  GS06  CHoCH 61.8 fib limit       GS07  H4 BOS gate + M30 Donchian
  GS08  trendline flush reclaim    GS09  Asia box London breakout (+filtered)
  GS10  S/R flip retest limit      SMC1  PDH/PDL sweep + FVG 50% reclaim
  BRKR  breaker-block retest       HAVW  Heikin-Ashi + RSI + VW-MACD trend
  PIVR2 daily-pivot R2/S2 + round-number fade
  GSR   gold/silver-ratio 80/50 gate (overlay study on GS04 gold longs)
"""
import os
import sys
import types
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from concepts_rank_lab import pivot_levels
from zone_breakout_lab import load_any, prep, COSTS, MAX_HOLD, TRAIN_END, add_ist  # noqa

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
PIVOT_K = 5
PIP = {"XAUUSD": 0.1, "XAGUSD": 0.01, "EURUSD": 0.0001, "GBPUSD": 0.0001,
       "USDCHF": 0.0001, "USDCAD": 0.0001, "SPX500": 1.0}


# ═══════════════════════════ shared execution engine ════════════════════════
def _walk(h, l, c, ei, xj, side, stop, target, trail_mult=None, atr=None,
          hh=None, ma=None, o=None):
    """Bar walk with optional chandelier trail (closed-bar) or MA exit.
    Pessimistic: stop checked before target inside each bar."""
    ts = stop
    for j in range(ei, xj + 1):
        if side == 1:
            if l[j] <= ts:
                return ts, j
            if target is not None and h[j] >= target:
                return target, j
        else:
            if h[j] >= ts:
                return ts, j
            if target is not None and l[j] <= target:
                return target, j
        if trail_mult is not None and atr is not None:      # closed-bar chandelier
            new = (hh[j] - trail_mult * atr[j]) if side == 1 else (hh[j] + trail_mult * atr[j])
            ts = max(ts, new) if side == 1 else min(ts, new)
        if ma is not None and j > ei:                        # closed-bar MA exit
            if (side == 1 and c[j] < ma[j]) or (side == -1 and c[j] > ma[j]):
                if j + 1 <= xj and o is not None:
                    return o[j + 1], j + 1
                return c[j], j
    return c[xj], xj


def run_events(df, events, cost, max_tpd=2):
    """events: list of dicts(i, side, entry='market'|'limit', limit, expiry,
    stop, target, time_exit, trail_mult, ma_n). Prices are RAW (cost applied here)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    dates = df["ny_date"].to_numpy()
    hh_hi = pd.Series(h).rolling(22, min_periods=5).max().to_numpy()
    hh_lo = pd.Series(l).rolling(22, min_periods=5).min().to_numpy()
    n = len(df); rows = []; tpd = {}; last_exit = -1
    ma_cache = {}
    for ev in sorted(events, key=lambda e: e["i"]):
        i = ev["i"]; side = ev["side"]
        if i + 1 >= n or i + 1 <= last_exit or not np.isfinite(atr[i]):
            continue
        ma = None
        if ev.get("ma_n"):
            if ev["ma_n"] not in ma_cache:
                ma_cache[ev["ma_n"]] = pd.Series(c).rolling(ev["ma_n"]).mean().to_numpy()
            ma = ma_cache[ev["ma_n"]]
        if ev.get("entry") == "limit":
            L = ev["limit"]; fill = None
            for j in range(i + 1, min(i + 1 + ev.get("expiry", 24), n)):
                if (side == 1 and l[j] <= L) or (side == -1 and h[j] >= L):
                    fill = j; break
            if fill is None:
                continue
            ei = fill
            entry = L + side * cost / 2
        else:
            ei = i + 1
            entry = o[ei] + side * cost / 2
        day = dates[ei]
        if tpd.get(day, 0) >= max_tpd:
            continue
        stop = ev["stop"] - side * cost / 2
        risk = side * (entry - stop)
        if risk <= 0 or not (0.2 * atr[i] <= risk <= 6.0 * atr[i]):
            continue
        target = ev.get("target")
        if ev.get("rr") is not None:
            target = entry + side * ev["rr"] * risk
        if target is not None and side * (target - entry) / risk < 0.7:
            continue
        xj = min(ei + ev.get("time_exit", ev.get("max_hold", 96)), n - 1)
        hh = hh_hi if side == 1 else hh_lo
        xp, xi = _walk(h, l, c, ei, xj, side, stop, target,
                       trail_mult=ev.get("trail_mult"), atr=atr, hh=hh,
                       ma=ma, o=o)
        # pessimistic same-bar rule for limit fills: stop touched on fill bar = loss
        if ev.get("entry") == "limit" and xi == ei and xp == target and (
                (side == 1 and l[ei] <= stop) or (side == -1 and h[ei] >= stop)):
            xp = stop
        r = side * (xp - entry) / risk
        rows.append((dates[ei], side, r))
        tpd[day] = tpd.get(day, 0) + 1
        last_exit = xi
    return pd.DataFrame(rows, columns=["ny_date", "side", "r"])


def stats(tb, months):
    if not len(tb):
        return None
    tr = tb[tb["ny_date"] <= TRAIN_END]["r"]; ho = tb[tb["ny_date"] > TRAIN_END]["r"]
    wins = tb["r"] > 0
    aw = tb.loc[wins, "r"].mean() if wins.any() else 0.0
    al = tb.loc[~wins, "r"].mean() if (~wins).any() else 0.0
    return dict(n=len(tb), tpm=round(len(tb) / months, 2), wr=round(wins.mean() * 100, 1),
                rr_real=round(abs(aw / al), 2) if al else np.nan,
                avg_r=round(tb["r"].mean(), 4), net=round(tb["r"].sum(), 1),
                tr=round(tr.sum(), 1), ho=round(ho.sum(), 1), n_ho=len(ho))


# ═════════════════════════ event generators (all causal) ════════════════════
def _fvg(h, l):
    """bull_fvg[i]: low[i] > high[i-2] (gap). bear_fvg[i]: high[i] < low[i-2]."""
    bull = np.zeros(len(h), bool); bear = np.zeros(len(h), bool)
    bull[2:] = l[2:] > h[:-2]
    bear[2:] = h[2:] < l[:-2]
    return bull, bear


def ev_gs01(df, sym, rr=3.0, zone_frac=0.25):
    """OB+FVG confluence: BOS (close crosses confirmed PIV5 level) with a 3-candle
    FVG whose zone sits in the origin 25% of the impulse leg. Limit at FVG proximal
    edge, SL 2 pips beyond the leg origin."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi, lo = pivot_levels(h, l, PIVOT_K)
    bull, bear = _fvg(h, l)
    pip = PIP[sym]; evs = []
    for i in np.flatnonzero(bull | bear):
        if not np.isfinite(atr[i]) or not np.isfinite(hi[i]) or not np.isfinite(lo[i]):
            continue
        if bull[i] and c[i] > hi[i]:                       # bullish BOS + bull FVG
            leg_lo, leg_hi = lo[i], h[i]
            if leg_hi <= leg_lo:
                continue
            zone_top = l[i]                                 # FVG proximal edge
            if (zone_top - leg_lo) / (leg_hi - leg_lo) > zone_frac:
                continue                                    # FVG must hug the OB origin
            evs.append(dict(i=i, side=1, entry="limit", limit=zone_top, expiry=24,
                            stop=leg_lo - 2 * pip, rr=rr, max_hold=96))
        if bear[i] and c[i] < lo[i]:
            leg_hi_, leg_lo_ = hi[i], l[i]
            if leg_hi_ <= leg_lo_:
                continue
            zone_bot = h[i]
            if (leg_hi_ - zone_bot) / (leg_hi_ - leg_lo_) > zone_frac:
                continue
            evs.append(dict(i=i, side=-1, entry="limit", limit=zone_bot, expiry=24,
                            stop=leg_hi_ + 2 * pip, rr=rr, max_hold=96))
    return evs


def ev_gs02(df, sym, stop_pad_atr=2.5, min_rr=2.0, target_mode="mid"):
    """PIV5 sweep-fail: wick beyond the confirmed pivot level, close back inside.
    Spec-strict: SL 2.5*ATR beyond the sweep wick, TP structural midpoint, min 2R.
    Tweaked variant (stop_pad_atr=0.5, min_rr=1.0, target='opp'): practical stop
    just past the wick, TP at the OPPOSITE pivot level."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi, lo = pivot_levels(h, l, PIVOT_K)
    evs = []
    for i in range(len(c)):
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i]) and np.isfinite(atr[i])):
            continue
        mid = (hi[i] + lo[i]) / 2
        tgt_s = mid if target_mode == "mid" else lo[i]
        tgt_l = mid if target_mode == "mid" else hi[i]
        if h[i] > hi[i] and c[i] < hi[i]:                   # swept the high, failed
            stop = h[i] + stop_pad_atr * atr[i]
            risk = stop - c[i]
            if risk > 0 and (c[i] - tgt_s) / risk >= min_rr:
                evs.append(dict(i=i, side=-1, stop=stop, target=tgt_s, max_hold=96))
        if l[i] < lo[i] and c[i] > lo[i]:
            stop = l[i] - stop_pad_atr * atr[i]
            risk = c[i] - stop
            if risk > 0 and (tgt_l - c[i]) / risk >= min_rr:
                evs.append(dict(i=i, side=1, stop=stop, target=tgt_l, max_hold=96))
    return evs


def ev_gs03(df, sym):
    """NY ORB: box = first 4 M15 candles from 09:30 NY. Close outside -> next-bar
    entry, SL box midpoint, TP 2R, hard time exit 16 bars."""
    ny_h = df["timestamp_ny"].dt.tz_convert(NY)
    hm = ny_h.dt.hour * 60 + ny_h.dt.minute
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    dates = df["ny_date"].to_numpy(); evs = []
    start = 9 * 60 + 30
    idx_by_day = {}
    for i, (d, m) in enumerate(zip(dates, hm)):
        if start <= m < start + 60:
            idx_by_day.setdefault(d, []).append(i)
    for d, ids in idx_by_day.items():
        if len(ids) < 4:
            continue
        box = ids[:4]
        bh = max(h[j] for j in box); bl = min(l[j] for j in box)
        mid = (bh + bl) / 2
        j0 = box[-1] + 1
        for i in range(j0, min(j0 + 20, len(c))):
            if dates[i] != d:
                break
            if c[i] > bh:
                evs.append(dict(i=i, side=1, stop=mid, rr=2.0, time_exit=16)); break
            if c[i] < bl:
                evs.append(dict(i=i, side=-1, stop=mid, rr=2.0, time_exit=16)); break
    return evs


def ev_gs04(df, sym, trail=True):
    """20-day channel breakout, 4*ATR stop, 4-ATR chandelier trail (no TP)."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi20 = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    lo20 = pd.Series(l).shift(1).rolling(20).min().to_numpy()
    evs = []
    for i in range(len(c)):
        if not (np.isfinite(hi20[i]) and np.isfinite(atr[i])):
            continue
        if c[i] > hi20[i]:
            evs.append(dict(i=i, side=1, stop=c[i] - 4 * atr[i],
                            trail_mult=4.0 if trail else None, max_hold=200))
        elif c[i] < lo20[i]:
            evs.append(dict(i=i, side=-1, stop=c[i] + 4 * atr[i],
                            trail_mult=4.0 if trail else None, max_hold=200))
    return evs


def ev_gs06(df, sym):
    """CHoCH + 61.8 fib limit. Downtrend (close < confirmed pivot low happened more
    recently than close > pivot high) then close breaks pivot high = CHoCH up.
    Leg = last pivot low origin -> break bar high. Limit at 61.8 retrace,
    SL 2 pips under origin, TP = leg high."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi, lo = pivot_levels(h, l, PIVOT_K)
    pip = PIP[sym]; evs = []
    trend = 0                                   # -1 down, +1 up (structural)
    for i in range(1, len(c)):
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i]) and np.isfinite(atr[i])):
            continue
        if c[i] < lo[i] and c[i - 1] >= lo[i - 1]:
            trend = -1
        if c[i] > hi[i] and c[i - 1] <= hi[i - 1]:
            if trend == -1:                      # CHoCH up after downtrend
                origin = lo[i]
                leg_hi = h[i]
                if leg_hi > origin:
                    lim = leg_hi - 0.618 * (leg_hi - origin)
                    evs.append(dict(i=i, side=1, entry="limit", limit=lim, expiry=36,
                                    stop=origin - 2 * pip, target=leg_hi, max_hold=96))
            trend = 1
        if c[i] < lo[i] and c[i - 1] >= lo[i - 1] and trend == 1:  # CHoCH down
            origin = hi[i]; leg_lo = l[i]
            if origin > leg_lo:
                lim = leg_lo + 0.618 * (origin - leg_lo)
                evs.append(dict(i=i, side=-1, entry="limit", limit=lim, expiry=36,
                                stop=origin + 2 * pip, target=leg_lo, max_hold=96))
            trend = -1
    return evs


def ev_gs07(df30, df4h, sym):
    """H4 BOS gate (close above last confirmed PIV5 high; off when close below
    pivot low) -> M30 Donchian-48 breakout long. SL = M30 48-bar low.
    Exit when M30 closes below SMA20 (next open). Long-only per spec, plus mirror."""
    h4, l4, c4 = (df4h[k].to_numpy(float) for k in ("high", "low", "close"))
    hi4, lo4 = pivot_levels(h4, l4, PIVOT_K)
    gate = np.zeros(len(c4), int); g = 0
    for i in range(len(c4)):
        if np.isfinite(hi4[i]) and c4[i] > hi4[i]:
            g = 1
        elif np.isfinite(lo4[i]) and c4[i] < lo4[i]:
            g = -1
        gate[i] = g
    g4 = pd.DataFrame({"timestamp_ny": df4h["timestamp_ny"], "gate": gate})
    m = pd.merge_asof(df30[["timestamp_ny"]], g4, on="timestamp_ny",
                      direction="backward", allow_exact_matches=False)
    gate30 = m["gate"].fillna(0).to_numpy()
    h, l, c = (df30[k].to_numpy(float) for k in ("high", "low", "close"))
    hi48 = pd.Series(h).shift(1).rolling(48).max().to_numpy()
    lo48 = pd.Series(l).shift(1).rolling(48).min().to_numpy()
    evs = []
    for i in range(len(c)):
        if not np.isfinite(hi48[i]):
            continue
        if gate30[i] == 1 and c[i] > hi48[i]:
            evs.append(dict(i=i, side=1, stop=lo48[i], ma_n=20, max_hold=192))
        elif gate30[i] == -1 and c[i] < lo48[i]:
            evs.append(dict(i=i, side=-1, stop=hi48[i], ma_n=20, max_hold=192))
    return evs


def ev_gs08(df, sym):
    """Trendline flush: 3 rising confirmed pivot lows -> line; flush through line,
    close back above -> long. SL 1 pip under flush wick, TP 3.5R."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    n = len(c); pip = PIP[sym]
    piv_i, piv_v = [], []
    conf = np.full(n, -1)
    for i in range(PIVOT_K, n - PIVOT_K):
        if l[i] == l[i - PIVOT_K:i + PIVOT_K + 1].min():
            conf[i + PIVOT_K] = i
    evs = []
    for t in range(n):
        if conf[t] >= 0:
            piv_i.append(conf[t]); piv_v.append(l[conf[t]])
            if len(piv_i) >= 3:
                i1, i2, i3 = piv_i[-3:]; v1, v2, v3 = piv_v[-3:]
                if v1 < v2 < v3:                     # rising line through 1 and 3
                    slope = (v3 - v1) / (i3 - i1)
                    # middle pivot near the line
                    if abs(v2 - (v1 + slope * (i2 - i1))) <= 0.5 * atr[t]:
                        # watch next 60 bars for a flush
                        for j in range(t + 1, min(t + 60, n)):
                            line = v1 + slope * (j - i1)
                            if slope <= 0 or not np.isfinite(atr[j]):
                                break
                            if l[j] < line - 0.1 * atr[j] and c[j] > line:
                                evs.append(dict(i=j, side=1, stop=l[j] - pip,
                                                rr=3.5, max_hold=96))
                                break
                            if c[j] < line - 0.5 * atr[j]:
                                break                # structural break, line dead
    return evs


def ev_gs09(df, sym, filtered=False):
    """Asia box (UTC 0-5) -> London (UTC 7-11) breakout. SL box midpoint, TP 2R.
    filtered: 200EMA direction + body>=60% + 61.8 fib limit retest, TP 1.8R."""
    ts_utc = df["timestamp_ny"].dt.tz_convert(UTC)
    uh = ts_utc.dt.hour.to_numpy()
    udate = ts_utc.dt.date.astype(str).to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
    evs = []; n = len(c)
    days = {}
    for i in range(n):
        if 0 <= uh[i] < 5:
            days.setdefault(udate[i], []).append(i)
    for d, ids in days.items():
        bh = max(h[j] for j in ids); bl = min(l[j] for j in ids)
        mid = (bh + bl) / 2
        j0 = ids[-1] + 1
        for i in range(j0, min(j0 + 40, n)):
            if udate[i] != d or uh[i] >= 12:
                break
            if uh[i] < 7:
                continue
            up = c[i] > bh; dn = c[i] < bl
            if not (up or dn):
                continue
            side = 1 if up else -1
            if filtered:
                if (side == 1 and c[i] < ema200[i]) or (side == -1 and c[i] > ema200[i]):
                    break
                rng = h[i] - l[i]
                if rng <= 0 or abs(c[i] - o[i]) / rng < 0.6:
                    break
                edge = bh if up else bl
                leg = c[i] - edge if up else edge - c[i]
                lim = c[i] - side * 0.618 * leg
                evs.append(dict(i=i, side=side, entry="limit", limit=lim, expiry=8,
                                stop=mid, rr=1.8, time_exit=32))
            else:
                evs.append(dict(i=i, side=side, stop=mid, rr=2.0, time_exit=32))
            break
    return evs


def ev_gs10(df, sym):
    """S/R flip: >=3 confirmed pivot highs clustered within 0.3*ATR band in the last
    300 bars; close breaks 0.25*ATR above -> buy limit AT the level, SL 2*ATR below,
    TP 3R. Mirror for support flips."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    n = len(c)
    ph = np.full(n, np.nan); pl = np.full(n, np.nan)
    for i in range(PIVOT_K, n - PIVOT_K):
        if h[i] == h[i - PIVOT_K:i + PIVOT_K + 1].max():
            ph[i + PIVOT_K] = h[i]
        if l[i] == l[i - PIVOT_K:i + PIVOT_K + 1].min():
            pl[i + PIVOT_K] = l[i]
    evs = []
    cool = -1
    for i in range(300, n):
        if i <= cool or not np.isfinite(atr[i]):
            continue
        win_h = ph[i - 300:i]; win_h = win_h[np.isfinite(win_h)]
        if len(win_h) >= 3:
            lvl = np.median(win_h[-6:])
            near = np.abs(win_h - lvl) <= 0.3 * atr[i]
            if near.sum() >= 3 and c[i] > lvl + 0.25 * atr[i] and c[i - 1] <= lvl + 0.25 * atr[i - 1]:
                evs.append(dict(i=i, side=1, entry="limit", limit=lvl, expiry=48,
                                stop=lvl - 2 * atr[i], rr=3.0, max_hold=96))
                cool = i + 12
        win_l = pl[i - 300:i]; win_l = win_l[np.isfinite(win_l)]
        if len(win_l) >= 3:
            lvl = np.median(win_l[-6:])
            near = np.abs(win_l - lvl) <= 0.3 * atr[i]
            if near.sum() >= 3 and c[i] < lvl - 0.25 * atr[i] and c[i - 1] >= lvl - 0.25 * atr[i - 1]:
                evs.append(dict(i=i, side=-1, entry="limit", limit=lvl, expiry=48,
                                stop=lvl + 2 * atr[i], rr=3.0, max_hold=96))
                cool = i + 12
    return evs


def ev_smc1(df, sym):
    """PDH/PDL sweep + displacement FVG + 50% (consequent-encroachment) limit.
    Sweep bar: wick beyond previous NY-day extreme, close back inside. Within 5 bars
    an opposing FVG forms -> limit at FVG midpoint, SL beyond sweep wick, TP 3R."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    dates = df["ny_date"].to_numpy()
    day_hi, day_lo = {}, {}
    for d in np.unique(dates):
        m = dates == d
        day_hi[d] = h[m].max(); day_lo[d] = l[m].min()
    udays = list(np.unique(dates)); prev = {}
    for k in range(1, len(udays)):
        prev[udays[k]] = udays[k - 1]
    bull, bear = _fvg(h, l)
    pip = PIP[sym]; evs = []; n = len(c)
    for i in range(n):
        d = dates[i]
        if d not in prev or not np.isfinite(atr[i]):
            continue
        pdh, pdl = day_hi[prev[d]], day_lo[prev[d]]
        if h[i] > pdh and c[i] < pdh:                       # swept PDH
            for j in range(i + 1, min(i + 6, n)):
                if bear[j]:                                  # bearish FVG: [h[j], l[j-2]]
                    ce = (h[j] + l[j - 2]) / 2
                    evs.append(dict(i=j, side=-1, entry="limit", limit=ce, expiry=24,
                                    stop=h[i] + 2 * pip, rr=3.0, max_hold=96))
                    break
        if l[i] < pdl and c[i] > pdl:
            for j in range(i + 1, min(i + 6, n)):
                if bull[j]:
                    ce = (l[j] + h[j - 2]) / 2
                    evs.append(dict(i=j, side=1, entry="limit", limit=ce, expiry=24,
                                    stop=l[i] - 2 * pip, rr=3.0, max_hold=96))
                    break
    return evs


def ev_brkr(df, sym):
    """Breaker block: bullish OB (last down candle before close breaks PIV5 high)
    -> later BODY close below OB low flips it bearish -> retest short at OB low,
    SL above the flip swing (max high since flip)+pad, TP 2R. Mirror long.
    Macro filter: EMA200 direction on the exec TF."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi, lo = pivot_levels(h, l, PIVOT_K)
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
    n = len(c); evs = []
    obs = []                                                 # (lo, hi, kind) kind=+1 bull OB
    for i in range(1, n):
        if not (np.isfinite(hi[i]) and np.isfinite(atr[i])):
            continue
        if c[i] > hi[i] and c[i - 1] <= hi[i - 1]:           # bullish BOS -> find last down candle
            for j in range(i - 1, max(i - 12, 0), -1):
                if c[j] < o[j]:
                    obs.append([l[j], h[j], 1, None]); break
        if c[i] < lo[i] and c[i - 1] >= lo[i - 1]:
            for j in range(i - 1, max(i - 12, 0), -1):
                if c[j] > o[j]:
                    obs.append([l[j], h[j], -1, None]); break
        keep = []
        for ob in obs[-8:]:
            zl, zh, kind, flip = ob
            if kind == 1 and flip is None and min(o[i], c[i]) < zl:   # body close below
                ob[3] = i                                              # flipped bearish
            elif kind == -1 and flip is None and max(o[i], c[i]) > zh:
                ob[3] = i
            elif flip is not None:
                if kind == 1 and i - flip <= 60 and h[i] >= zl and c[i] < ema200[i]:
                    swing = h[flip:i + 1].max()
                    evs.append(dict(i=i, side=-1, stop=swing + 0.2 * atr[i],
                                    rr=2.0, max_hold=96))
                    continue                                           # consume
                if kind == -1 and i - flip <= 60 and l[i] <= zh and c[i] > ema200[i]:
                    swing = l[flip:i + 1].min()
                    evs.append(dict(i=i, side=1, stop=swing - 0.2 * atr[i],
                                    rr=2.0, max_hold=96))
                    continue
            keep.append(ob)
        obs = obs[:-8] + keep if len(obs) > 8 else keep
    return evs


def ev_havw(df, sym):
    """Heikin-Ashi flip + RSI pullback + VW-MACD cross. Long: RSI(14) < 40 within
    last 10 bars, HA flips red->green, VW-MACD crosses above signal. 3-ATR
    chandelier trail (spec: swing hold). Mirror short."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].fillna(1.0).to_numpy(float) if "volume" in df else np.ones(len(c))
    atr = df["atr50"].to_numpy(float)
    n = len(c)
    ha_c = (o + h + l + c) / 4
    ha_o = np.empty(n); ha_o[0] = o[0]
    for i in range(1, n):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    green = ha_c > ha_o
    delta = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(delta > 0, delta, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    dn = pd.Series(np.where(delta < 0, -delta, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
    pv = pd.Series(c * v)
    vw_fast = (pv.ewm(span=12, adjust=False).mean()
               / pd.Series(v).ewm(span=12, adjust=False).mean())
    vw_slow = (pv.ewm(span=26, adjust=False).mean()
               / pd.Series(v).ewm(span=26, adjust=False).mean())
    macd = (vw_fast - vw_slow).to_numpy()
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().to_numpy()
    evs = []
    for i in range(10, n):
        if not np.isfinite(atr[i]):
            continue
        if (green[i] and not green[i - 1] and rsi[i - 10:i].min() < 40
                and macd[i] > sig[i] and macd[i - 1] <= sig[i - 1]):
            evs.append(dict(i=i, side=1, stop=c[i] - 3 * atr[i], trail_mult=3.0,
                            max_hold=120))
        if (not green[i] and green[i - 1] and rsi[i - 10:i].max() > 60
                and macd[i] < sig[i] and macd[i - 1] >= sig[i - 1]):
            evs.append(dict(i=i, side=-1, stop=c[i] + 3 * atr[i], trail_mult=3.0,
                            max_hold=120))
    return evs


def ev_pivr2(df, sym):
    """Daily floor-pivot R2/S2 + round-number confluence fade (gold: $100 grid).
    Touch R2 (round number within 0.5*ATR), close back below -> short to central P."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    dates = df["ny_date"].to_numpy()
    day_rows = {}
    for i, d in enumerate(dates):
        day_rows.setdefault(d, []).append(i)
    udays = sorted(day_rows)
    piv = {}
    for k in range(1, len(udays)):
        ids = day_rows[udays[k - 1]]
        H = max(h[j] for j in ids); L = min(l[j] for j in ids); C = c[ids[-1]]
        P = (H + L + C) / 3
        piv[udays[k]] = (P, P + (H - L), P - (H - L))        # P, R2, S2
    grid = 100.0 if sym == "XAUUSD" else (1.0 if sym == "XAGUSD" else 0.01)
    evs = []
    for i in range(len(c)):
        d = dates[i]
        if d not in piv or not np.isfinite(atr[i]):
            continue
        P, R2, S2 = piv[d]
        if abs(R2 - round(R2 / grid) * grid) <= 0.5 * atr[i]:
            if h[i] >= R2 and c[i] < R2:
                evs.append(dict(i=i, side=-1, stop=R2 + 1.5 * atr[i], target=P,
                                time_exit=32))
        if abs(S2 - round(S2 / grid) * grid) <= 0.5 * atr[i]:
            if l[i] <= S2 and c[i] > S2:
                evs.append(dict(i=i, side=1, stop=S2 - 1.5 * atr[i], target=P,
                                time_exit=32))
    return evs


# ═════════════════════════════ matrix driver ════════════════════════════════
CELLS = [
    # family, generator, [(sym, tf)], kwargs
    ("GS01", ev_gs01, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("XAUUSD", "H4"),
                       ("XAGUSD", "H1"), ("EURUSD", "H1"), ("GBPUSD", "H1")], {}),
    ("GS01L", ev_gs01, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("XAUUSD", "H4"),
                        ("EURUSD", "H1"), ("GBPUSD", "H1")], dict(zone_frac=0.5)),
    ("GS02", ev_gs02, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("XAUUSD", "H4"),
                       ("XAGUSD", "H1"), ("EURUSD", "H1"), ("GBPUSD", "H1")], {}),
    ("GS02T", ev_gs02, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("XAUUSD", "H4"),
                        ("XAGUSD", "H1"), ("EURUSD", "H1"), ("GBPUSD", "H1")],
     dict(stop_pad_atr=0.5, min_rr=1.0, target_mode="opp")),
    ("GS03", ev_gs03, [("XAUUSD", "M15"), ("EURUSD", "M15"), ("GBPUSD", "M15")], {}),
    ("GS04", ev_gs04, [("XAUUSD", "D1"), ("XAGUSD", "D1"), ("EURUSD", "D1"),
                       ("GBPUSD", "D1"), ("SPX500", "D1")], {}),
    ("GS06", ev_gs06, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("XAUUSD", "H4"),
                       ("EURUSD", "H1"), ("GBPUSD", "H1")], {}),
    ("GS08", ev_gs08, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("EURUSD", "H1"),
                       ("GBPUSD", "H1")], {}),
    ("GS09", ev_gs09, [("XAUUSD", "M15"), ("EURUSD", "M15"), ("GBPUSD", "M15")], {}),
    ("GS09F", ev_gs09, [("XAUUSD", "M15"), ("EURUSD", "M15"), ("GBPUSD", "M15")],
     dict(filtered=True)),
    ("GS10", ev_gs10, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("EURUSD", "H1"),
                       ("GBPUSD", "H1")], {}),
    ("SMC1", ev_smc1, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("EURUSD", "M15"),
                       ("GBPUSD", "M15")], {}),
    ("BRKR", ev_brkr, [("XAUUSD", "M15"), ("XAUUSD", "H1"), ("EURUSD", "H1"),
                       ("GBPUSD", "H1")], {}),
    ("HAVW", ev_havw, [("XAUUSD", "H1"), ("XAUUSD", "H4"), ("XAUUSD", "D1"),
                       ("EURUSD", "H4"), ("GBPUSD", "H4")], {}),
    ("PIVR2", ev_pivr2, [("XAUUSD", "M15"), ("XAUUSD", "H1")], {}),
]


def gsr_overlay(out_lines):
    """Strategy 7: GSR 80/50 gate as an overlay on GS04 gold D1 longs."""
    au = prep(load_any("XAUUSD", "D1")); ag = load_any("XAGUSD", "D1")
    if ag is None:
        out_lines.append("GSR: no silver D1 data"); return
    agd = ag.set_index(ag["timestamp_ny"].dt.tz_convert(NY).dt.date)["close"]
    aud = au["timestamp_ny"].dt.tz_convert(NY).dt.date
    gsr = (au["close"].to_numpy()
           / agd.reindex(aud).ffill().to_numpy())
    evs = ev_gs04(au, "XAUUSD")
    cost = COSTS["XAUUSD"]
    tb = run_events(au, evs, cost)
    if not len(tb):
        out_lines.append("GSR: no GS04 gold trades"); return
    ev_i = [e["i"] for e in sorted(evs, key=lambda e: e["i"])]
    # re-run and tag each trade with GSR at signal (match by date order — approximate,
    # acceptable for an overlay STUDY, not a deployable cell)
    sig_dates = [au["ny_date"].iloc[min(i + 1, len(au) - 1)] for i in ev_i]
    gsr_by_date = dict(zip(au["ny_date"], gsr))
    tb = tb.copy()
    tb["gsr"] = [gsr_by_date.get(d, np.nan) for d in tb["ny_date"]]
    longs = tb[tb["side"] == 1]
    hi = longs[longs["gsr"] > 80]; lo80 = longs[longs["gsr"] <= 80]
    lo50 = longs[longs["gsr"] < 50]
    out_lines.append(
        f"GSR OVERLAY on GS04 gold D1 longs: n={len(longs)} | GSR>80: n={len(hi)} "
        f"avg {hi['r'].mean():+.3f}R | GSR<=80: n={len(lo80)} avg {lo80['r'].mean():+.3f}R"
        f" | GSR<50: n={len(lo50)} avg {(lo50['r'].mean() if len(lo50) else float('nan')):+.3f}R")


def main():
    rows = []; lines = []
    cache = {}
    for fam, gen, cells, kw in CELLS:
        for sym, tf in cells:
            key = (sym, tf)
            if key not in cache:
                raw = load_any(sym, tf)
                cache[key] = prep(raw) if raw is not None else None
            df = cache[key]
            if df is None:
                print(f"-- {fam} {sym} {tf}: no data"); continue
            months = max((df["timestamp_ny"].iloc[-1] - df["timestamp_ny"].iloc[0]).days,
                         1) / 30.44
            cost = COSTS[sym]
            if fam == "GS07":
                continue
            evs = gen(df, sym, **kw)
            tb = run_events(df, evs, cost)
            tb3 = run_events(df, evs, cost * 3)
            st = stats(tb, months)
            if st is None:
                print(f"-- {fam} {sym} {tf}: 0 trades"); continue
            st3 = round(tb3["r"].sum(), 1) if len(tb3) else 0.0
            verdict = ("DEPLOY-CANDIDATE" if st["n"] >= 40 and st["tr"] > 2 and st["ho"] > 1
                       and st["avg_r"] >= 0.05 and st3 > 0 and st["n_ho"] >= 8
                       else "WATCH" if st["tr"] > 0 and st["ho"] > 0 and st3 > 0
                       else "REJECT")
            rows.append(dict(id=f"{fam}-{sym}-{tf}", family=fam, symbol=sym, tf=tf,
                             **st, stress3x=st3, verdict=verdict))
            print(f"{fam}-{sym}-{tf}: n={st['n']} wr={st['wr']} avg={st['avg_r']:+.3f} "
                  f"tr={st['tr']} ho={st['ho']} 3x={st3} -> {verdict}")
    # GS07 (needs two frames)
    for sym in ("XAUUSD", "EURUSD", "GBPUSD"):
        d30 = cache.get((sym, "M30"))
        if d30 is None:
            raw = load_any(sym, "M30")
            d30 = prep(raw) if raw is not None else None
        d4h = cache.get((sym, "H4"))
        if d4h is None:
            raw = load_any(sym, "H4")
            d4h = prep(raw) if raw is not None else None
        if d30 is None or d4h is None:
            print(f"-- GS07 {sym}: missing frame"); continue
        months = max((d30["timestamp_ny"].iloc[-1] - d30["timestamp_ny"].iloc[0]).days,
                     1) / 30.44
        evs = ev_gs07(d30, d4h, sym)
        cost = COSTS[sym]
        tb = run_events(d30, evs, cost); tb3 = run_events(d30, evs, cost * 3)
        st = stats(tb, months)
        if st is None:
            print(f"-- GS07 {sym}: 0 trades"); continue
        st3 = round(tb3["r"].sum(), 1) if len(tb3) else 0.0
        verdict = ("DEPLOY-CANDIDATE" if st["n"] >= 40 and st["tr"] > 2 and st["ho"] > 1
                   and st["avg_r"] >= 0.05 and st3 > 0 and st["n_ho"] >= 8
                   else "WATCH" if st["tr"] > 0 and st["ho"] > 0 and st3 > 0
                   else "REJECT")
        rows.append(dict(id=f"GS07-{sym}-M30", family="GS07", symbol=sym, tf="M30",
                         **st, stress3x=st3, verdict=verdict))
        print(f"GS07-{sym}-M30: n={st['n']} wr={st['wr']} avg={st['avg_r']:+.3f} "
              f"tr={st['tr']} ho={st['ho']} 3x={st3} -> {verdict}")
    lines = []
    gsr_overlay(lines)
    for ln in lines:
        print(ln)
    pd.DataFrame(rows).to_csv("gs_battery_matrix.csv", index=False)
    print(f"\nsaved gs_battery_matrix.csv ({len(rows)} cells)")


if __name__ == "__main__":
    main()
