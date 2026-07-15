"""EVENT PRICE LIB (July 2026) — price frames + panels + outcomes for the ANALYST
news-surprise work (case_library_builder2.py + analyst_replay.py).

One place for:
  load_frame()       asset -> event-resolution OHLC frame (timestamp_ny, OHLC, atr50)
                     XAUUSD  M5   2004-2025 (XAU_5m_data) stitched + broker M5 2025-04->2026-07
                     EURUSD  M15  2008-2026 (deep) / GBPUSD M15 / USDCHF M15
                     USDCAD  H1   2010-2026 (only hourly depth exists — kept honest)
                     SPX500  M15  2022-2026 (broker; short history, small n expected)
                     GER40   M15  2022-2026

TIMEZONE RULES — EMPIRICALLY VERIFIED July 2026 (news-spike fingerprint: the
max-range bar on 68 summer + 46 winter first-Friday NFP days must sit at
08:30 NY; see the tz audit section of the replay report):
  XAU_5m_data.csv      naive = BROKER SERVER time (NY+7: GMT+2 winter/GMT+3 summer)
                       -> ny = naive - 7h.  (sideways_lab.load_gold's fixed
                       Etc/GMT-2 parse shifts every SUMMER timestamp +1h — repo bug,
                       reported, NOT reused here.)
  XAUUSD_M5_live.csv   naive = SERVER time (NY+7), NOT UTC as load_mt5_export
                       assumes. 42/68 summer NFPs spike at 08:30 under NY+7.
  *15_deep.csv         naive = NY wall clock + 5h FLAT (UTC only in winter)
                       -> ny = naive - 5h.  ~49 of 54 summer NFPs at 08:30 under
                       NY+5, 09:30 under the repo's UTC parse.
  *60.csv (H1)         true UTC (verified: NFP spike inside the 08:00 NY H1 bar).
  IDX_*_M15.csv        SERVER time (NY+7).
  panel_at(df, ts)   the offline twin of analyst_bot.panel_for: technical snapshot
                     using ONLY bars closed at/before ts (causal).
  outcome_after(...) forward move / MFE / MAE measured from a decision price at
                     t_decision, in ATR units and price units.

The gold stitch is VERIFIED at import-use time by verify_stitch(): the two feeds
must agree on the overlap (median |close diff| < 0.1% of price) or we refuse.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))

_FRAMES = {}


def _add_atr(df):
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    c = df["close"]
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["hi96"] = df["high"].rolling(96, min_periods=20).max()
    df["lo96"] = df["low"].rolling(96, min_periods=20).min()
    return df


def _load_mt5_export(path):
    df = pd.read_csv(path, sep="\t", header=None)
    df.columns = ["date", "open", "high", "low", "close", "volume"][: df.shape[1]]
    dt = pd.to_datetime(df["date"], format="%Y-%m-%d %H:%M")
    df["timestamp_ny"] = dt.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["timestamp_ny", "open", "high", "low", "close"]].dropna().reset_index(drop=True)


def _load_tab(path, rule):
    """rule: 'utc' | 'ny+5' | 'ny+7' (see module docstring — all verified)."""
    df = pd.read_csv(path, sep="\t", header=None)
    df.columns = ["date", "open", "high", "low", "close", "volume"][: df.shape[1]]
    naive = pd.to_datetime(df["date"], format="%Y-%m-%d %H:%M")
    if rule == "utc":
        ts = naive.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    else:
        h = {"ny+5": 5, "ny+7": 7}[rule]
        ts = (naive - pd.Timedelta(hours=h)).dt.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT")
    df["timestamp_ny"] = ts
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (df[["timestamp_ny", "open", "high", "low", "close"]]
            .dropna().sort_values("timestamp_ny").reset_index(drop=True))


def _load_gold_m5():
    """XAU_5m_data.csv (2004->2025-04, SERVER time NY+7) stitched with the broker
    export XAUUSD_M5_live.csv (also SERVER time NY+7, 2024-05->2026-07). Overlap
    agreement ~0.002% median under these rules (same feed) — enforced below."""
    df = pd.read_csv(os.path.join(ROOT, "data/XAU_5m_data.csv"), sep=";")
    df.columns = [c.lower() for c in df.columns]
    ts = (pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M") - pd.Timedelta(hours=7)
          ).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    old = pd.DataFrame({"timestamp_ny": ts,
                        "open": pd.to_numeric(df["open"]),
                        "high": pd.to_numeric(df["high"]),
                        "low": pd.to_numeric(df["low"]),
                        "close": pd.to_numeric(df["close"])}).dropna()
    new = _load_tab(os.path.join(ROOT, "data/XAUUSD_M5_live.csv"), "ny+7")
    cut = new["timestamp_ny"].min()
    verify_stitch(old, new)
    out = pd.concat([old[old["timestamp_ny"] < cut], new], ignore_index=True)
    return out.sort_values("timestamp_ny").reset_index(drop=True)


def verify_stitch(old, new):
    """Overlap agreement check between the two gold feeds — refuse silently wrong data."""
    a = old.set_index("timestamp_ny")["close"]
    b = new.set_index("timestamp_ny")["close"]
    common = a.index.intersection(b.index)
    if len(common) < 1000:
        raise SystemExit(f"gold stitch: only {len(common)} overlapping bars — refusing")
    diff = (a.loc[common] - b.loc[common]).abs() / b.loc[common]
    med = float(diff.median())
    if med > 0.0005:
        raise SystemExit(f"gold stitch: median overlap disagreement {med:.4%} — refusing")
    return med


SOURCES = {
    "XAUUSD": ("M5", _load_gold_m5),
    "EURUSD": ("M15", lambda: _load_tab(os.path.join(ROOT, "data/EURUSD15_deep.csv"), "ny+5")),
    "GBPUSD": ("M15", lambda: _load_tab(os.path.join(ROOT, "data/GBPUSD15_deep.csv"), "ny+5")),
    "USDCHF": ("M15", lambda: _load_tab(os.path.join(ROOT, "data/USDCHF15_deep.csv"), "ny+5")),
    "USDCAD": ("H1", lambda: _load_tab(os.path.join(ROOT, "data/USDCAD60.csv"), "utc")),
    "SPX500": ("M15", lambda: _load_tab(os.path.join(ROOT, "data/IDX_SPX500_M15.csv"), "ny+7")),
    "GER40": ("M15", lambda: _load_tab(os.path.join(ROOT, "data/IDX_GER40_M15.csv"), "ny+7")),
}

# per-symbol ALL-IN round-trip cost in price units — same numbers as
# live_signals.FX_SPREADS (measured from the user's own fills). Keep HONEST.
ALL_IN_COST = {"EURUSD": 0.00008, "GBPUSD": 0.00010, "USDCAD": 0.00014,
               "USDCHF": 0.00010, "XAUUSD": 0.23, "SPX500": 1.7, "GER40": 4.7}


def load_frame(asset):
    if asset not in _FRAMES:
        tf, loader = SOURCES[asset]
        df = _add_atr(loader())
        df["tf"] = tf
        _FRAMES[asset] = df.reset_index(drop=True)
    return _FRAMES[asset]


def bar_minutes(asset):
    return {"M5": 5, "M15": 15, "H1": 60}[SOURCES[asset][0]]


def idx_at(df, ts):
    """Index of the LAST bar whose open time is <= ts. Bars are labeled by open time."""
    i = df["timestamp_ny"].searchsorted(ts, side="right") - 1
    return int(i) if i >= 0 else None


def idx_closed_at(df, ts, tf_min):
    """Index of the last bar fully CLOSED at time ts (causal for panels)."""
    i = df["timestamp_ny"].searchsorted(ts - pd.Timedelta(minutes=tf_min), side="right") - 1
    return int(i) if i >= 0 else None


def panel_at(asset, ts):
    """Offline twin of analyst_bot.panel_for: uses only bars closed at/before ts."""
    df = load_frame(asset)
    tfm = bar_minutes(asset)
    i = idx_closed_at(df, ts, tfm)
    if i is None or i < 210:
        return None
    row = df.iloc[i]
    e20, e50, e200 = float(row["ema20"]), float(row["ema50"]), float(row["ema200"])
    atr = float(row["atr50"])
    hi96, lo96 = float(row["hi96"]), float(row["lo96"])
    last3 = df.iloc[i - 2: i + 1][["open", "high", "low", "close"]].round(5).values.tolist()
    close = float(row["close"])
    return dict(symbol=asset, tf=SOURCES[asset][0], close=close, atr50=atr,
                ema20=e20, ema50=e50, ema200=e200,
                trend="up" if e20 > e50 else "down",
                hi96=hi96, lo96=lo96, last3_bars=last3,
                pretrend="bull" if close > e200 else "bear")


def reaction_after_release(asset, ts_release, k_bars=1):
    """Direction & size of the initial reaction: the release bar (bar containing
    ts_release) measured close-vs-open, in ATR units. Returns None off-hours."""
    df = load_frame(asset)
    i = idx_at(df, ts_release)
    if i is None or i + k_bars >= len(df):
        return None
    bar = df.iloc[i]
    gap_min = (ts_release - bar["timestamp_ny"]).total_seconds() / 60
    if gap_min >= bar_minutes(asset) * 3:      # market closed / data hole at release
        return None
    atr = df["atr50"].iloc[max(0, i - 1)]
    if not np.isfinite(atr) or atr <= 0:
        return None
    move = float(bar["close"] - bar["open"])
    rng = float(bar["high"] - bar["low"])
    return dict(i=i, dir="up" if move > 0 else "dn", move_atr=move / atr,
                range_mult=rng / atr, atr=float(atr),
                bar_ts=bar["timestamp_ny"])


def outcome_after(asset, ts_decision, horizons_min):
    """Forward outcomes from the first bar OPEN at/after ts_decision (the honest
    fill for a decision made at ts_decision). Returns dict with entry price and,
    per horizon, the signed move (up = positive) in price and ATR units, plus
    MFE/MAE over the longest horizon."""
    df = load_frame(asset)
    n = len(df)
    j = df["timestamp_ny"].searchsorted(ts_decision, side="left")
    if j >= n:
        return None
    entry_bar = df.iloc[j]
    if (entry_bar["timestamp_ny"] - ts_decision) > pd.Timedelta(hours=12):
        return None                                 # weekend/holiday gap
    entry = float(entry_bar["open"])
    atr = df["atr50"].iloc[max(0, j - 1)]
    if not np.isfinite(atr) or atr <= 0:
        return None
    out = dict(entry=entry, entry_ts=entry_bar["timestamp_ny"], atr=float(atr), j=int(j))
    tfm = bar_minutes(asset)
    maxk = 0
    for hm in horizons_min:
        k = max(1, round(hm / tfm))
        maxk = max(maxk, k)
        if j + k - 1 >= n:
            out[f"fwd_{hm}m"] = np.nan
        else:
            out[f"fwd_{hm}m"] = float(df["close"].iloc[j + k - 1] - entry)
    seg = df.iloc[j: j + maxk]
    out["mfe"] = float(seg["high"].max() - entry)
    out["mae"] = float(seg["low"].min() - entry)
    return out
