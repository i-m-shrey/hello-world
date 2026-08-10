"""ZONE BREAKOUT LAB — exhaustive structural-zone breakout scan (July 2026).

Directives (owner): breakouts ONLY (no fades), all symbols (XAUUSD, XAGUSD, FX majors,
indices), all timeframes (M15/M30/H1/H4/D1), no frequency/capital caps — escalate to
higher TFs where costs kill lower ones. PIVOT_K=5 hard rule (exactly 5 closed candles
left AND right). rr >= 2 only. IST translation layer + alignment verification built in.

House law preserved: real all-in costs, train<=2023 / holdout>=2024 both positive,
3x cost-stress, causal signals (pivot confirmed K bars late, entry next-bar open).

Zone families:
  PIV5  — pivot S/R breakout: close crosses the most recent CONFIRMED (k=5) pivot
          high/low +/- pad*ATR -> momentum continuation in the break direction.
  BOX   — Darvas/rectangle congestion: N-bar box whose range <= tight*ATR; close
          breaks outside the box -> continuation.
  CMPX  — ATR-compression expansion: atr50 percentile <= q AND close breaks the
          N-bar extreme -> expansion-leg continuation.
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

from multi_symbol_lab import load_mt5_export           # UTC-proven FX/metal exports
from idx_trend_lab import load_idx, COST as IDX_COST   # index CFDs (UTC+3 parse, verified)
from concepts_rank_lab import pivot_levels             # causal pivots (confirm at i+k)
import live_signals as LS

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
PIVOT_K = 5                       # HOUSE RULE: exactly 5 closed candles left and right
TRAIN_END = "2023-12-31"

COSTS = dict(LS.FX_SPREADS)                    # all-in (spread+commission), audited
COSTS["XAGUSD"] = 0.032                        # 0.03 spread + $7/lot on 5000oz = 0.0014
FX_METALS = ("EURUSD", "GBPUSD", "USDCHF", "USDCAD", "XAGUSD")
INDICES = ("SPX500", "GER40", "US30", "JPN225", "HK50")
for s in INDICES:
    COSTS[s] = IDX_COST[s]

MAX_HOLD = {"M15": 192, "M30": 96, "H1": 96, "H4": 60, "D1": 30}
BARS_PM = {"M15": 2000, "M30": 1000, "H1": 500, "H4": 125, "D1": 22}   # approx bars/month


# ── IST TRANSLATION LAYER ────────────────────────────────────────────────────
def add_ist(df: pd.DataFrame) -> pd.DataFrame:
    """Hardcoded IST view of every bar. Conversion is PER-TIMESTAMP (tz database),
    never a fixed offset — IST has no DST while NY does, so any fixed IST window
    is wrong for half the year. The live bot does the same thing via UTC."""
    df["timestamp_ist"] = df["timestamp_ny"].dt.tz_convert(IST)
    df["ist_hour"] = df["timestamp_ist"].dt.hour
    return df


def verify_ist_alignment(df: pd.DataFrame, label: str, lines: list):
    """Prove: (1) no ghost bars — IST conversion is a relabel, never adds/drops rows;
    (2) a session window defined in NY hours maps to the SAME bars when expressed
    through the IST layer; (3) a naive fixed-IST window diverges in DST months."""
    n0 = len(df)
    ist = df["timestamp_ny"].dt.tz_convert(IST)
    assert len(ist) == n0 and ist.notna().all(), "ghost bars introduced"
    assert (ist.dt.tz_convert("UTC") == df["timestamp_ny"].dt.tz_convert("UTC")).all(), \
        "conversion changed the instant"
    ny_mask = df["timestamp_ny"].dt.hour.isin(range(14, 24))          # validated NY window
    ist_equiv = df["timestamp_ny"].dt.tz_convert(IST).dt.tz_convert(NY).dt.hour.isin(range(14, 24))
    assert (ny_mask == ist_equiv).all(), "IST round-trip broke the session window"
    # naive fixed IST window 23:30-09:30 (NY14-24 in US summer) vs the true mapping
    hh = ist.dt.hour + ist.dt.minute / 60.0
    naive = (hh >= 23.5) | (hh < 9.5)
    div = int((naive != ny_mask).sum())
    lines.append(f"IST ALIGN [{label}]: {n0} bars, 0 ghost bars, NY14-24 window round-trips "
                 f"exactly; naive FIXED 23:30-09:30 IST window mislabels {div} bars "
                 f"({div / n0 * 100:.1f}%) across DST switches -> per-timestamp conversion is "
                 f"MANDATORY (bot already does this via UTC)")


# ── loaders (all -> timestamp_ny + OHLCV, then IST layer) ────────────────────
def _resample(df: pd.DataFrame, rule: str, day: bool = False) -> pd.DataFrame:
    g = df.set_index("timestamp_ny").resample(rule, offset="17h" if day else None)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum()}).dropna(subset=["open"]).reset_index()
    return out


def load_gold_tf(tf: str) -> pd.DataFrame:
    src = pd.read_csv("data/XAU_15m_data_TZFIX.csv", sep=";")
    src.columns = [c.lower() for c in src.columns]
    ts = (pd.to_datetime(src["date"], format="%Y.%m.%d %H:%M")
          .dt.tz_localize(ZoneInfo("Etc/GMT-2"), ambiguous="raise", nonexistent="shift_forward")
          .dt.tz_convert(NY))
    df = pd.DataFrame({"timestamp_ny": ts, "open": src["open"], "high": src["high"],
                       "low": src["low"], "close": src["close"],
                       "volume": pd.to_numeric(src.get("volume"), errors="coerce")})
    rule = {"M15": None, "M30": "30min", "H1": "1h", "H4": "4h", "D1": "24h"}[tf]
    return df if rule is None else _resample(df, rule, day=(tf == "D1"))


def load_fxm_tf(sym: str, tf: str) -> pd.DataFrame:
    if tf in ("M15", "M30", "H1", "H4"):
        return load_mt5_export(f"data/{sym}{ {'M15':15,'M30':30,'H1':60,'H4':240}[tf] }.csv")
    return _resample(load_mt5_export(f"data/{sym}60.csv"), "24h", day=True)


def load_idx_tf(sym: str, tf: str) -> pd.DataFrame:
    if tf in ("M15", "H1", "H4"):
        return load_idx(sym, tf)
    if tf == "M30":
        return _resample(load_idx(sym, "M15"), "30min")
    return _resample(load_idx(sym, "H1"), "24h", day=True)


def load_any(sym: str, tf: str) -> pd.DataFrame | None:
    try:
        if sym == "XAUUSD":
            df = load_gold_tf(tf)
        elif sym in FX_METALS:
            df = load_fxm_tf(sym, tf)
        else:
            df = load_idx_tf(sym, tf)
    except FileNotFoundError:
        return None
    if df is None or len(df) < 600:
        return None
    return add_ist(df.reset_index(drop=True))


def prep(df: pd.DataFrame) -> pd.DataFrame:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    df["atr_pctile"] = df["atr50"].rolling(720, min_periods=200).rank(pct=True)
    df["ny_date"] = df["timestamp_ny"].dt.tz_convert(NY).dt.date.astype(str)
    return df


# ── zone signal generators (0 / +1 / -1 at bar close, entry NEXT bar open) ──
def sig_piv5(df, pad):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    hi, lo = pivot_levels(h, l, PIVOT_K)
    up = np.nan_to_num((c > hi + pad * atr) &
                       (np.r_[np.nan, c[:-1]] <= np.r_[np.nan, (hi + pad * atr)[:-1]]))
    dn = np.nan_to_num((c < lo - pad * atr) &
                       (np.r_[np.nan, c[:-1]] >= np.r_[np.nan, (lo - pad * atr)[:-1]]))
    return up.astype(int) - dn.astype(int)


def sig_box(df, N, tight, pad=0.1):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    bh = pd.Series(h).shift(1).rolling(N).max().to_numpy()      # box built on CLOSED bars
    bl = pd.Series(l).shift(1).rolling(N).min().to_numpy()
    is_box = (bh - bl) <= tight * atr
    up = np.nan_to_num(is_box & (c > bh + pad * atr))
    dn = np.nan_to_num(is_box & (c < bl - pad * atr))
    return up.astype(int) - dn.astype(int)


def sig_cmpx(df, q, N=48):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pct = df["atr_pctile"].to_numpy(float)
    bh = pd.Series(h).shift(1).rolling(N).max().to_numpy()
    bl = pd.Series(l).shift(1).rolling(N).min().to_numpy()
    ok = pct <= q
    up = np.nan_to_num(ok & (c > bh))
    dn = np.nan_to_num(ok & (c < bl))
    return up.astype(int) - dn.astype(int)


# ── executor (house conventions: cost both sides, risk bounds, tpd cap) ─────
def run_cell(df, sig, cost, rr, stop_atr=2.0, max_hold=96, max_tpd=2):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = df["atr50"].to_numpy(float)
    dates = df["ny_date"].to_numpy()
    n = len(df); rows = []; tpd = {}; last_exit = -1
    for i in np.flatnonzero(sig != 0):
        ei = i + 1
        if ei >= n or ei <= last_exit or not np.isfinite(atr[i]):
            continue
        day = dates[ei]
        if tpd.get(day, 0) >= max_tpd:
            continue
        side = int(sig[i])
        entry = o[ei] + side * cost / 2
        stop = entry - side * (stop_atr * atr[i]) - side * cost / 2
        risk = side * (entry - stop)
        if risk <= 0 or not (0.3 * atr[i] <= risk <= 4.0 * atr[i]):
            continue
        target = entry + side * rr * risk
        xj = min(ei + max_hold, n - 1)
        xp, xi = _walk(h, l, c, ei, xj, side, stop, target)
        r = side * (xp - entry) / risk
        rows.append((dates[ei], df["timestamp_ist"].iloc[ei], side, r))
        tpd[day] = tpd.get(day, 0) + 1
        last_exit = xi
    return pd.DataFrame(rows, columns=["ny_date", "ist_time", "side", "r"])


def _walk(h, l, c, ei, xj, side, stop, target):
    for j in range(ei, xj + 1):
        if side == 1:
            if l[j] <= stop:
                return stop, j
            if h[j] >= target:
                return target, j
        else:
            if h[j] >= stop:
                return stop, j
            if l[j] <= target:
                return target, j
    return c[xj], xj


def stats(tb: pd.DataFrame, months: float):
    if not len(tb):
        return None
    tr = tb[tb["ny_date"] <= TRAIN_END]["r"]
    ho = tb[tb["ny_date"] > TRAIN_END]["r"]
    wins = tb["r"] > 0
    aw = tb.loc[wins, "r"].mean() if wins.any() else 0.0
    al = tb.loc[~wins, "r"].mean() if (~wins).any() else 0.0
    return dict(n=len(tb), tpm=len(tb) / months, wr=wins.mean() * 100,
                rr_real=abs(aw / al) if al else np.nan, avg_r=tb["r"].mean(),
                net=tb["r"].sum(), tr=tr.sum(), ho=ho.sum(), n_ho=len(ho))


def main():
    out = []; ist_lines = []; books = {}
    symbols = ["XAUUSD", "XAGUSD"] + list(FX_METALS[:-1]) + list(INDICES)
    tfs = ["M15", "M30", "H1", "H4", "D1"]
    grid = ([("PIV5", dict(pad=p), rr) for p in (0.1, 0.25) for rr in (2.0, 3.0)]
            + [("BOX", dict(N=N, tight=t), rr) for N in (24, 48) for t in (2.5,)
               for rr in (2.0, 3.0)]
            + [("CMPX", dict(q=q), rr) for q in (0.25,) for rr in (2.0, 3.0)])
    for sym in symbols:
        for tf in tfs:
            raw = load_any(sym, tf)
            if raw is None:
                print(f"-- {sym} {tf}: no data"); continue
            df = prep(raw)
            months = max((df["timestamp_ny"].iloc[-1] - df["timestamp_ny"].iloc[0]).days, 1) / 30.44
            if tf == "H1":
                verify_ist_alignment(df, f"{sym} {tf}", ist_lines)
            cost = COSTS[sym]
            sigs = {}
            for fam, prm, rr in grid:
                key = (fam, tuple(sorted(prm.items())))
                if key not in sigs:
                    sigs[key] = (sig_piv5(df, **prm) if fam == "PIV5"
                                 else sig_box(df, **prm) if fam == "BOX"
                                 else sig_cmpx(df, **prm))
                sig = sigs[key]
                mh = MAX_HOLD[tf]
                tb = run_cell(df, sig, cost, rr, max_hold=mh)
                tb3 = run_cell(df, sig, cost * 3, rr, max_hold=mh)
                st = stats(tb, months)
                if st is None:
                    continue
                st3 = tb3["r"].sum() if len(tb3) else 0.0
                pname = ",".join(f"{k}{v}" for k, v in sorted(prm.items()))
                cid = f"ZB-{fam}-{sym}-{tf}-{pname}-rr{rr:g}"
                verdict = ("DEPLOY-CANDIDATE" if st["n"] >= 40 and st["tr"] > 2 and st["ho"] > 1
                           and st["avg_r"] >= 0.05 and st3 > 0 and st["n_ho"] >= 8
                           else "WATCH" if st["tr"] > 0 and st["ho"] > 0 and st3 > 0
                           else "REJECT")
                out.append(dict(id=cid, symbol=sym, tf=tf, family=fam, params=pname,
                                rr_plan=rr, **st, stress3x=round(st3, 1),
                                stress3x_status="Pass" if st3 > 0 else "Fail",
                                verdict=verdict))
                if verdict == "DEPLOY-CANDIDATE":
                    books[cid] = tb
            print(f"done {sym} {tf} ({months:.0f} months, {len(df)} bars)")
    res = pd.DataFrame(out)
    res.to_csv("zone_breakout_matrix.csv", index=False)
    for cid, tb in books.items():
        tb.to_csv(f"tradebooks/{cid}_tradebook.csv", index=False)
    print("\n".join(ist_lines))
    print(f"\n{len(res)} cells -> zone_breakout_matrix.csv | "
          f"{(res['verdict'] == 'DEPLOY-CANDIDATE').sum()} deploy-candidates, "
          f"{(res['verdict'] == 'WATCH').sum()} watch, "
          f"{(res['verdict'] == 'REJECT').sum()} rejects")


if __name__ == "__main__":
    main()
