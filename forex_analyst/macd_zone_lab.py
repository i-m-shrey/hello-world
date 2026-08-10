"""MACD ZONE BREAKOUT LAB (July 2026) — owner-specified multi-timeframe MACD strategy.

Spec (verbatim from the owner, purely mechanical, no discretionary inputs):
  Assets   : XAUUSD, XAGUSD.
  Exec TFs : M15 (anchor H1) and H1 (anchor H4).
  MACD     : standard 12/26/9 (EMA12-EMA26, signal EMA9 of MACD, hist = macd-signal).
  Local Zone: highest/lowest MACD-HISTOGRAM values over the last HIST_LOOKBACK=50
             CLOSED bars (shift-1 rolling, causal).
  LONG entry (variant "PCO2"):
    1. a SECONDARY positive crossover (macd crosses above signal) BELOW the zero line
       on the exec TF — the 2nd+ PCO since macd was last >= 0;
    2. the anchor TF is concurrently in a post-positive-crossover state
       (macd > signal on its most recent CLOSED bar);
    3. the MACD line at the crossover bar sits INSIDE the 50-bar histogram Local Zone
       [zone_lo, zone_hi].
  HOOK variant: above the zero line (macd > 0), after the histogram fades (declines)
    for >= 2 consecutive bars, enter on the FIRST positive-turning histogram bar.
    Anchor gate identical.
  Stop     : absolute lowest low of the 5 candles before the signal bar (PIVOT_K=5
             structural convention).
  Target   : fixed 1:2 and 1:3 R:R matrices.
  Costs    : house all-in (XAUUSD 0.23, XAGUSD 0.032), 3x stress mandatory.
  Splits   : train <= 2023, holdout >= 2024 (gold 2008+ = 18y, silver 2011+).
  Plateau  : HIST_LOOKBACK neighbors 40/60 must agree in sign (PCO2).
  IST layer: per-timestamp tz conversion (Asia/Kolkata) on every frame, verified.

Conventions not fixed by the spec (disclosed, house defaults): entry at NEXT bar open
+cost/2; stop padded -cost/2; risk sanity 0.05*ATR..6*ATR; max_hold 96 exec bars ->
exit at close; one position at a time; no day cap. LONG-only, exactly as specified.
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

from multi_symbol_lab import load_mt5_export

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
HIST_LOOKBACK = 50
PIVOT_K = 5
COSTS = {"XAUUSD": 0.23, "XAGUSD": 0.032}
MAX_HOLD = 96


def load_frames(sym):
    """exec/anchor frame pairs: {'M15': (M15, H1), 'H1': (H1, H4)}."""
    if sym == "XAUUSD":
        src = pd.read_csv("data/XAU_5m_data_TZFIX.csv", sep=";")
        src.columns = [c.lower() for c in src.columns]
        ts = (pd.to_datetime(src["date"], format="%Y.%m.%d %H:%M")
              .dt.tz_localize(ZoneInfo("Etc/GMT-2"), ambiguous="raise",
                              nonexistent="shift_forward").dt.tz_convert(NY))
        base = pd.DataFrame({"timestamp_ny": ts, "open": src["open"], "high": src["high"],
                             "low": src["low"], "close": src["close"]})
        base = base[base["timestamp_ny"] >= pd.Timestamp("2008-01-01", tz=NY)]

        def rs(rule):
            g = base.set_index("timestamp_ny").resample(rule)
            return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                                 "low": g["low"].min(), "close": g["close"].last()}
                                ).dropna().reset_index()
        return {"M15": (rs("15min"), rs("1h")), "H1": (rs("1h"), rs("4h"))}
    return {"M15": (load_mt5_export(f"data/{sym}15.csv"), load_mt5_export(f"data/{sym}60.csv")),
            "H1": (load_mt5_export(f"data/{sym}60.csv"), load_mt5_export(f"data/{sym}240.csv"))}


def add_macd(df):
    c = df["close"]
    df["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["hist"] = df["macd"] - df["sig"]
    prev = c.shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    # IST layer: per-timestamp conversion (house rule — never a fixed offset)
    df["timestamp_ist"] = df["timestamp_ny"].dt.tz_convert(IST)
    assert df["timestamp_ist"].notna().all() and len(df["timestamp_ist"]) == len(df)
    df["year"] = df["timestamp_ny"].dt.year
    return df


def anchor_state(exec_df, anchor_df, anchor_hours):
    """Per exec bar: anchor TF macd>signal on its most recent CLOSED bar (bar at time T
    covers [T, T+anchor_hours) and only becomes available at T+anchor_hours — causal)."""
    a = anchor_df[["timestamp_ny", "macd", "sig"]].copy()
    a["avail"] = a["timestamp_ny"] + pd.Timedelta(hours=anchor_hours)
    a["bull"] = (a["macd"] > a["sig"]).astype(int)
    m = pd.merge_asof(exec_df[["timestamp_ny"]].sort_values("timestamp_ny"),
                      a[["avail", "bull"]].rename(columns={"avail": "timestamp_ny"})
                      .sort_values("timestamp_ny"),
                      on="timestamp_ny", direction="backward")
    return m["bull"].fillna(0).astype(bool).to_numpy()


def sig_pco2(df, anchor_bull, lookback=HIST_LOOKBACK):
    macd = df["macd"].to_numpy(float); sig = df["sig"].to_numpy(float)
    hist = df["hist"].to_numpy(float)
    zone_hi = pd.Series(hist).shift(1).rolling(lookback).max().to_numpy()
    zone_lo = pd.Series(hist).shift(1).rolling(lookback).min().to_numpy()
    cross_up = (macd > sig) & (np.r_[np.nan, macd[:-1]] <= np.r_[np.nan, sig[:-1]])
    n = len(df); out = np.zeros(n, bool); pco_count = 0
    for i in range(1, n):
        if macd[i] >= 0:
            pco_count = 0                      # episode resets when macd returns >= 0
            continue
        if cross_up[i]:
            pco_count += 1
            if (pco_count >= 2 and anchor_bull[i]
                    and np.isfinite(zone_lo[i]) and np.isfinite(zone_hi[i])
                    and zone_lo[i] < macd[i] < zone_hi[i]):
                out[i] = True
    return out


def sig_hook(df, anchor_bull, fade_bars=2):
    macd = df["macd"].to_numpy(float); hist = df["hist"].to_numpy(float)
    n = len(df); out = np.zeros(n, bool)
    for i in range(fade_bars + 1, n):
        if macd[i] <= 0 or not (hist[i] > hist[i - 1]):
            continue
        if not all(hist[i - k] < hist[i - k - 1] for k in range(1, fade_bars + 1)):
            continue                            # needs a >=2-bar fade first
        if anchor_bull[i]:
            out[i] = True
    return out


def run(df, sig_mask, cost, rr):
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    atr = df["atr50"].to_numpy(float); yrs = df["year"].to_numpy(int)
    n = len(df); rows = []; last_exit = -1
    for i in np.flatnonzero(sig_mask):
        ei = i + 1
        if ei >= n or ei <= last_exit or i < PIVOT_K or not np.isfinite(atr[i]):
            continue
        stop = l[i - PIVOT_K:i].min() - cost / 2      # lowest low of the 5 candles before i
        entry = o[ei] + cost / 2
        risk = entry - stop
        if risk <= 0 or not (0.05 * atr[i] <= risk <= 6.0 * atr[i]):
            continue
        target = entry + rr * risk
        xj = min(ei + MAX_HOLD, n - 1); xp = c[xj]; xi = xj
        for j in range(ei, xj + 1):
            if l[j] <= stop:
                xp, xi = stop, j; break
            if h[j] >= target:
                xp, xi = target, j; break
        rows.append((int(yrs[ei]), (xp - entry) / risk))
        last_exit = xi
    return pd.DataFrame(rows, columns=["year", "r"])


def stats(t, months):
    if t is None or len(t) < 15:
        return None
    r = t["r"]
    aw = r[r > 0].mean() if (r > 0).any() else 0.0
    al = r[r <= 0].mean() if (r <= 0).any() else np.nan
    return dict(n=len(t), tpm=len(t) / months, wr=(r > 0).mean() * 100,
                rr_real=abs(aw / al) if al else np.nan, avg=r.mean(), net=r.sum(),
                tr=t.loc[t.year <= 2023, "r"].sum(), ho=t.loc[t.year >= 2024, "r"].sum())


def main():
    out = []
    for sym in ("XAUUSD", "XAGUSD"):
        frames = load_frames(sym)
        cost = COSTS[sym]
        for tf, (ex, an) in frames.items():
            ex = add_macd(ex); an = add_macd(an)
            ah = {"M15": 1, "H1": 4}[tf]
            months = max((ex["timestamp_ny"].iloc[-1] - ex["timestamp_ny"].iloc[0]).days, 1) / 30.44
            abull = anchor_state(ex, an, ah)
            for variant, mask_fn in (("PCO2", sig_pco2), ("HOOK", sig_hook)):
                base_mask = mask_fn(ex, abull)
                for rr in (2.0, 3.0):
                    t = run(ex, base_mask, cost, rr)
                    st = stats(t, months)
                    if st is None:
                        out.append(dict(id=f"MACDZ-{variant}-{sym}-{tf}-rr{rr:g}",
                                        symbol=sym, tf=tf, variant=variant, rr_plan=rr,
                                        n=0 if t is None else len(t), verdict="NO-TRADES"))
                        continue
                    t3 = run(ex, base_mask, cost * 3, rr)
                    s3 = t3["r"].sum() if len(t3) else 0.0
                    plateau = ""
                    if variant == "PCO2":
                        signs = []
                        for lb in (40, 60):
                            tn = run(ex, sig_pco2(ex, abull, lookback=lb), cost, rr)
                            signs.append(len(tn) >= 15 and tn["r"].sum() > 0)
                        plateau = f"{sum(signs)}/2"
                    verdict = ("PASS" if st["tr"] > 0 and st["ho"] > 1 and s3 > 0
                               and (plateau in ("", "2/2")) else "FAIL")
                    out.append(dict(id=f"MACDZ-{variant}-{sym}-{tf}-rr{rr:g}",
                                    symbol=sym, tf=tf, variant=variant, rr_plan=rr,
                                    **st, stress3x=round(s3, 1),
                                    stress3x_status="Pass" if s3 > 0 else "Fail",
                                    plateau=plateau, verdict=verdict))
            print(f"done {sym} {tf}")
    res = pd.DataFrame(out)
    res.to_csv("macd_zone_matrix.csv", index=False)
    cols = [c for c in ("id", "n", "tpm", "wr", "rr_real", "avg", "tr", "ho",
                        "stress3x", "plateau", "verdict") if c in res.columns]
    print(res[cols].round(3).to_string(index=False))
    print(f"\n{len(res)} cells -> macd_zone_matrix.csv | {(res.verdict == 'PASS').sum()} PASS")


if __name__ == "__main__":
    main()
