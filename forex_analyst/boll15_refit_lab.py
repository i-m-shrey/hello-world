"""BOLL15 REFIT LAB (July 2026) — diagnose the leak, then refine STRUCTURALLY.

Owner directive: salvage the high-frequency BOLL15 family without curve-fitting.

DIAGNOSIS AXES
  D1 cost wall     : legacy config re-run at validated cost (0.2p) vs audited live
                     all-in (0.8-1.0p) vs stressed (2p/3p). If the edge dies between
                     0.2p and live, the leak is cost, not logic.
  D2 regime autopsy: legacy trades bucketed by trend strength at entry
                     (|close-ema200|/ATR and ADX14). If losses concentrate in
                     strong-trend buckets, the fade needs a regime gate.

REFINEMENT GRID (white-box, structural — entry logic untouched)
  gates : none | ADX14<=25 | ADX14<=30 | slope gate |ema20-ema50|/ATR<=1.0 / 1.5
          | tighter calm filter atr_pctile<=0.50
  exits : max_hold 20 (legacy) | 12 | 8 | breakeven at +0.5R (hold 20)
  TFs   : M15 (deep, TZ-corrected NY+5 parse) | M30 (UTC-proven exports) —
          same logic one TF up halves cost/ATR.

HOUSE LAW: all costs are the AUDITED live all-in (LS.FX_SPREADS), not the 0.2p the
family was originally validated on. train<=2023 AND holdout>=2024 both positive,
3x cost-stress, parameter plateau. IST layer preserved on every loader (per-timestamp
tz conversion; verified no ghost bars).
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
import live_signals as LS

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
LIVE_COST = {s: LS.FX_SPREADS[s] for s in ("EURUSD", "GBPUSD", "USDCHF")}
VALID_COST = {"EURUSD": 0.00002, "GBPUSD": 0.00002, "USDCHF": 0.00006}  # original basis
SIDES = {"EURUSD": "long", "GBPUSD": "both", "USDCHF": "both"}


def load_deep_ny5(path):
    """TZ-CORRECTED deep parse (tz_audit verdict: naive stamps = NY wall clock + 5h)."""
    df = pd.read_csv(path, sep="\t", header=None)
    df.columns = ["date", "open", "high", "low", "close", "volume"][: df.shape[1]]
    dt = pd.to_datetime(df["date"], format="%Y-%m-%d %H:%M")
    df["timestamp_ny"] = (dt - pd.Timedelta(hours=5)).dt.tz_localize(
        NY, ambiguous="NaT", nonexistent="NaT")
    df = df.dropna(subset=["timestamp_ny"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def prep(df, tf_min):
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    win = max(60, round(30 * 1440 / tf_min))
    df["atr_pctile"] = df["atr50"].rolling(win, min_periods=max(60, win // 4)).rank(pct=True)
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    df["hour"] = df["timestamp_ny"].dt.hour
    # IST layer (house rule): per-timestamp tz conversion, never a fixed offset
    df["timestamp_ist"] = df["timestamp_ny"].dt.tz_convert(IST)
    assert df["timestamp_ist"].notna().all() and len(df["timestamp_ist"]) == len(df)
    for s in (20, 50, 200):
        df[f"ema{s}"] = df["close"].ewm(span=s, adjust=False).mean()
    # Wilder ADX(14)
    up = df["high"].diff(); dn = -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    df["adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    return df


def boll_signals(df, hours=set(range(14, 24))):
    sma = df["close"].rolling(20).mean(); sd = df["close"].rolling(20).std()
    ok = (df["atr_pctile"] <= 0.70) & df["atr50"].notna() & (df["hour"] != 17) \
         & df["hour"].isin(hours)
    sl = (ok & (df["close"] < sma - 2 * sd)).to_numpy()
    ss = (ok & (df["close"] > sma + 2 * sd)).to_numpy()
    return sl, ss


def exec_x(df, sl, ss, spread, stop_atr=1.2, max_hold=20, be_r=None, gate=None,
           max_tpd=3):
    """fx_lowtf_meanrev_lab._exec_fades VERBATIM + optional per-bar gate, custom
    max_hold, optional breakeven. Returns rows with entry index for the autopsy."""
    if gate is not None:
        sl = sl & gate; ss = ss & gate
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    atr = df["atr50"].to_numpy(float)
    sma = df["close"].rolling(20).mean().to_numpy(float)
    yrs = df["year"].to_numpy(int); dates = df["ny_date"].to_numpy()
    n = len(df); trades = []; tpd = {}; last_exit = -1
    for i in np.flatnonzero(sl | ss):
        ei = i + 1
        if ei >= n or ei <= last_exit:
            continue
        day = dates[ei]
        if tpd.get(day, 0) >= max_tpd:
            continue
        side = 1 if sl[i] else -1
        if side == 1:
            entry = o[ei] + spread / 2
            stop = entry - stop_atr * atr[i] - spread / 2
            target = sma[i]
            if target - entry <= 0.1 * atr[i]:
                continue
        else:
            entry = o[ei] - spread / 2
            stop = entry + stop_atr * atr[i] + spread / 2
            target = sma[i]
            if entry - target <= 0.1 * atr[i]:
                continue
        risk = abs(entry - stop)
        if not (0.3 * atr[i] <= risk <= 3.0 * atr[i]):
            continue
        be_lvl = entry + side * (be_r * risk) if be_r is not None else None
        xj = min(ei + max_hold, n - 1); xp = c[xj]; xi = xj
        for j in range(ei, xj + 1):
            if side == 1:
                if l[j] <= stop:
                    xp, xi = stop, j; break
                if h[j] >= target:
                    xp, xi = target, j; break
                if be_lvl is not None and stop < entry and h[j] >= be_lvl:
                    stop = entry
            else:
                if h[j] >= stop:
                    xp, xi = stop, j; break
                if l[j] <= target:
                    xp, xi = target, j; break
                if be_lvl is not None and stop > entry and l[j] <= be_lvl:
                    stop = entry
        pts = side * (xp - entry)
        trades.append((int(yrs[ei]), round(pts / risk, 4), i, side))
        tpd[day] = tpd.get(day, 0) + 1; last_exit = xi
    return pd.DataFrame(trades, columns=["year", "r", "i", "side"])


def sided(sl, ss, side):
    none = np.zeros(len(sl), bool)
    return (sl, none) if side == "long" else (none, ss) if side == "short" else (sl, ss)


def stats(t, months):
    if t is None or len(t) < 15:
        return None
    r = t["r"]; tr = t.loc[t.year <= 2023, "r"].sum(); ho = t.loc[t.year >= 2024, "r"].sum()
    aw = r[r > 0].mean() if (r > 0).any() else 0
    al = r[r <= 0].mean() if (r <= 0).any() else np.nan
    return dict(n=len(t), tpm=len(t) / months, wr=(r > 0).mean() * 100,
                rr=abs(aw / al) if al else np.nan, avg=r.mean(), net=r.sum(),
                tr=tr, ho=ho)


def main():
    out = []
    for sym in ("EURUSD", "GBPUSD", "USDCHF"):
        frames = {}
        d15 = prep(load_deep_ny5(f"data/{sym}15_deep.csv"), 15)
        d30 = prep(load_mt5_export(f"data/{sym}30.csv"), 30)
        frames["M15"] = d15; frames["M30"] = d30
        side = SIDES[sym]
        live = LIVE_COST[sym]
        print(f"\n{'='*100}\n{sym}  (deployed side: {side}; live all-in cost "
              f"{live*10000:.1f}p, validated at {VALID_COST[sym]*10000:.1f}p)\n{'='*100}")

        # ── D1: the cost wall on the legacy config (M15, corrected time) ──
        sl, ss = boll_signals(d15)
        months15 = max((d15["timestamp_ny"].iloc[-1] - d15["timestamp_ny"].iloc[0]).days, 1) / 30.44
        print("D1 COST WALL (legacy config, corrected time):")
        for tag, cost in (("validated 0.2-0.6p", VALID_COST[sym]), ("live all-in", live),
                          ("2.0 pip", 0.0002), ("3.0 pip (reopen)", 0.0003)):
            t = exec_x(d15, *sided(sl, ss, side), cost)
            st = stats(t, months15)
            if st:
                print(f"   {tag:20s} n={st['n']:5d} net={st['net']:+8.1f}R "
                      f"avg={st['avg']:+.4f} tr={st['tr']:+8.1f} ho={st['ho']:+6.1f}")

        # ── D2: regime autopsy at live cost ──
        t = exec_x(d15, *sided(sl, ss, side), live)
        tt = t.copy()
        tt["trend"] = (np.abs(d15["close"].to_numpy() - d15["ema200"].to_numpy())
                       / d15["atr50"].to_numpy())[tt["i"].to_numpy()]
        tt["adx"] = d15["adx14"].to_numpy()[tt["i"].to_numpy()]
        print("D2 REGIME AUTOPSY (live cost): avg R by regime bucket")
        for name, col, edges in (("dist(ema200)/ATR", "trend", (0, 2, 4, 6, 99)),
                                 ("ADX14", "adx", (0, 20, 25, 30, 99))):
            bl = pd.cut(tt[col], edges)
            g = tt.groupby(bl, observed=True)["r"]
            print(f"   {name:18s} " + " | ".join(
                f"{iv}: {v:+.3f} (n={g.size()[iv]})" for iv, v in g.mean().items()))

        # ── refinement grid ──
        for tf, dd in frames.items():
            months = max((dd["timestamp_ny"].iloc[-1] - dd["timestamp_ny"].iloc[0]).days, 1) / 30.44
            sl, ss = boll_signals(dd)
            gates = {
                "none": None,
                "adx25": (dd["adx14"] <= 25).to_numpy(),
                "adx30": (dd["adx14"] <= 30).to_numpy(),
                "slope1.0": ((dd["ema20"] - dd["ema50"]).abs() / dd["atr50"] <= 1.0).to_numpy(),
                "slope1.5": ((dd["ema20"] - dd["ema50"]).abs() / dd["atr50"] <= 1.5).to_numpy(),
                "atrp0.5": (dd["atr_pctile"] <= 0.50).to_numpy(),
            }
            exits = {"h20": dict(max_hold=20), "h12": dict(max_hold=12),
                     "h8": dict(max_hold=8), "be0.5": dict(max_hold=20, be_r=0.5)}
            for gname, g in gates.items():
                for ename, ex in exits.items():
                    t1 = exec_x(dd, *sided(sl, ss, side), live, gate=g, **ex)
                    st = stats(t1, months)
                    if st is None:
                        continue
                    t3 = exec_x(dd, *sided(sl, ss, side), live * 3, gate=g, **ex)
                    s3 = t3["r"].sum() if len(t3) else 0.0
                    verdict = ("PASS" if st["tr"] > 0 and st["ho"] > 1 and s3 > 0
                               else "FAIL")
                    out.append(dict(symbol=sym, tf=tf, gate=gname, exit=ename,
                                    side=side, **st, stress3x=round(s3, 1),
                                    verdict=verdict))
            print(f"   grid {tf}: done ({len(dd)} bars)")

    res = pd.DataFrame(out)
    res.to_csv("boll15_refit_matrix.csv", index=False)
    print(f"\n{len(res)} cells -> boll15_refit_matrix.csv | "
          f"{(res.verdict == 'PASS').sum()} PASS at live cost + 3x stress")
    p = res[res.verdict == "PASS"].sort_values("avg", ascending=False)
    cols = ["symbol", "tf", "gate", "exit", "n", "tpm", "wr", "rr", "avg", "tr", "ho", "stress3x"]
    print(p[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
