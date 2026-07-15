"""TIMEZONE AUDIT (July 2026, Mandate 0) — validation-integrity re-run of every
deployed strategy whose VALIDATION sat on a mis-parsed data file.

THE BUG (empirically proven by news-spike fingerprinting — the max-range bar on
first-Friday NFP days must sit at 08:30 NY; 42/68 summer + winter anchors):
  XAU_5m_data.csv / XAU_15m_data.csv   naive = broker SERVER time (GMT+2 winter /
      GMT+3 summer, i.e. "NY+7"). The labs' fixed Etc/GMT-2 parse is correct in
      winter and +1h WRONG for every summer bar.
  *15_deep.csv                          naive = NY wall clock + 5h FLAT ("NY+5").
      The UTC parse is correct in winter, +1h wrong in summer.
  {sym}5/15/30/60.csv broker exports    TRUE UTC — correct all year (verified).
  IDX_*_M15.csv / XAUUSD_M5_live.csv    server time (structural strategies only).

WHO IS EXPOSED: a validation is distorted only when BOTH (a) it read a buggy file
and (b) the strategy conditions on clock time — hour windows/blocked hours,
session boxes, NY-day anchors, or H4 bins resampled from the shifted labels
(a +1h shift is NOT a multiple of 4h, so summer H4 bars aggregate the wrong
hours). Pure structure (Donchian channels, pivot breaks, zone breaks) on H1 bars
is immune: a whole-hour label shift leaves the bar CONTENT identical.

WHAT THIS SCRIPT DOES — for each exposed strategy, run the ORIGINAL lab code
twice: once with the original (buggy) parse — which must reproduce the official
number, proving harness fidelity — and once with the corrected parse. Report
n / net R / train / holdout side by side. Live execution is unaffected (the bot
reads the broker feed and measures its own TZ at startup); this is about whether
the VALIDATED EDGE still stands on correctly-timed history.

    python tz_audit.py            (writes TZ_AUDIT_REPORT.md)
"""
import importlib.util
import json
import os
import sys
import types
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
NY = "America/New_York"
REPORT = os.path.join(ROOT, "TZ_AUDIT_REPORT.md")
L = []                       # report lines


def say(s=""):
    print(s)
    L.append(s)


# ── corrected loaders ────────────────────────────────────────────────────────
def load_gold_fixed(tf_min):
    """sideways_lab.load_gold executed UNCHANGED, but pointed at the TZFIX copy of
    the 5m file (whose naive stamps make the original Etc/GMT-2 parse yield the
    true NY times). Zero harness drift by construction."""
    import shutil
    import sideways_lab
    tzdir = os.path.join(ROOT, "tmp_tzfix")
    os.makedirs(os.path.join(tzdir, "data"), exist_ok=True)
    dst = os.path.join(tzdir, "data", "XAU_5m_data.csv")
    if not os.path.exists(dst):
        shutil.copy(write_shifted_gold_csv(), dst)
    old_root = sideways_lab.ROOT
    try:
        sideways_lab.ROOT = tzdir
        return sideways_lab.load_gold(tf_min)
    finally:
        sideways_lab.ROOT = old_root


def load_raw_fixed(path):
    """rebaseline_engine.load_raw with the NY+7 parse (same window filters)."""
    df = pd.read_csv(path, sep=";")
    df.columns = [c.lower() for c in df.columns]
    df["timestamp_ny"] = (pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M")
                          - pd.Timedelta(hours=7)).dt.tz_localize(
        NY, ambiguous="NaT", nonexistent="NaT")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "timestamp_ny"])
    d = df["timestamp_ny"].dt.date.astype(str)
    return df.loc[(d >= "2020-06-01") & (d <= "2025-04-25"),
                  ["timestamp_ny", "open", "high", "low", "close"]].reset_index(drop=True)


def load_mt5_export_ny5(path):
    """multi_symbol_lab.load_mt5_export with the verified NY+5 rule for deep files."""
    df = pd.read_csv(path, sep="\t", header=None)
    df.columns = ["date", "open", "high", "low", "close", "volume"][: df.shape[1]]
    dt = pd.to_datetime(df["date"], format="%Y-%m-%d %H:%M")
    df["timestamp_ny"] = (dt - pd.Timedelta(hours=5)).dt.tz_localize(
        NY, ambiguous="NaT", nonexistent="NaT")
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = np.nan
    return df[["timestamp_ny", "open", "high", "low", "close", "volume"]].dropna(
        subset=["timestamp_ny", "open", "high", "low", "close"]).reset_index(drop=True)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def write_shifted_gold_csv(src="data/XAU_5m_data.csv"):
    """data/XAU_5m_data_TZFIX.csv — naive timestamps chosen so that the ORIGINAL
    labs' fixed Etc/GMT-2 parse yields the TRUE NY times (naive-7h). Running the
    unmodified lab code on this file isolates the TZ effect with ZERO harness
    drift. (Winter rows are unchanged; summer rows shift -1h; the ~2 bars/year
    that land in DST transitions are dropped.)"""
    out = os.path.join(ROOT, src.replace(".csv", "_TZFIX.csv"))
    if os.path.exists(out):
        return out
    from zoneinfo import ZoneInfo
    df = pd.read_csv(os.path.join(ROOT, src), sep=";")
    cols = list(df.columns)
    naive = pd.to_datetime(df[cols[0]], format="%Y.%m.%d %H:%M")
    true_ny = (naive - pd.Timedelta(hours=7)).dt.tz_localize(
        NY, ambiguous="NaT", nonexistent="NaT")
    shifted = true_ny.dt.tz_convert(ZoneInfo("Etc/GMT-2")).dt.strftime("%Y.%m.%d %H:%M")
    df[cols[0]] = shifted
    df = df.dropna(subset=[cols[0]])
    df = df[df[cols[0]] != "NaT"]
    df.to_csv(out, sep=";", index=False)
    return out


def tb_stats(tb, rcol="result_r", ycol="year"):
    if tb is None or not len(tb):
        return dict(n=0, net=0.0, tr=0.0, ho=0.0)
    if ycol not in tb.columns:
        for tcol in ("entry_time", "entry_ts", "signal_time"):
            if tcol in tb.columns:
                tb = tb.copy()
                tb[ycol] = pd.to_datetime(tb[tcol], utc=True).dt.year
                break
    r = tb[rcol]
    return dict(n=len(tb), net=float(r.sum()),
                tr=float(tb.loc[tb[ycol] <= 2023, rcol].sum()),
                ho=float(tb.loc[tb[ycol] >= 2024, rcol].sum()))


def row(label, old, new, official=None):
    off = f" (official {official})" if official else ""
    say(f"| {label} | {old['n']} | {old['net']:+.1f} | {old['tr']:+.1f} | "
        f"{old['ho']:+.1f} | {new['n']} | {new['net']:+.1f} | {new['tr']:+.1f} | "
        f"{new['ho']:+.1f} |{off}")


def main():
    say("# TIMEZONE AUDIT — deployed-strategy exposure & TZ-correct re-runs")
    say(f"\nGenerated {pd.Timestamp.utcnow():%Y-%m-%d %H:%M}Z. Live execution is "
        "unaffected (the bot trades the broker feed and self-verifies its TZ at "
        "startup); this audit is about whether each VALIDATION still stands on "
        "correctly-timed history. `verify_*.py` cannot catch this class of bug — "
        "they prove live==backtest on the SAME (mis-parsed) frame.\n")

    # ── exposure matrix ──────────────────────────────────────────────────
    say("## Exposure matrix (all 23 live instances)\n")
    say("| instance | validation data | file TZ-buggy? | clock-conditioned? | exposed? |")
    say("|---|---|---|---|---|")
    M = [
        ("XAUUSD_S5",      "XAU_5m (GMT+2 parse)", "YES (+1h summer)", "blocked_hours (7,8,20-23)", "**YES**"),
        ("XAUUSD_S6",      "XAU_5m (GMT+2 parse)", "YES (+1h summer)", "blocked_hours (3-7,9)", "**YES**"),
        ("XAUUSD_S4",      "XAU_5m (GMT+2 parse)", "YES (+1h summer)", "session boxes 06-12", "**YES**"),
        ("XAUUSD_S3LO",    "XAU_5m (GMT+2 parse)", "YES (+1h summer)", "NY-AM session 09:00-11:55", "**YES**"),
        ("EURUSD_BOLL15",  "EURUSD15_deep (UTC parse)", "YES (+1h summer)", "hours 14-24", "**YES** (benched)"),
        ("GBPUSD_BOLL15",  "GBPUSD15_deep (UTC parse)", "YES (+1h summer)", "hours 14-24", "**YES** (benched)"),
        ("USDCHF_BOLL15",  "USDCHF15_deep (UTC parse)", "YES (+1h summer)", "hours 14-24", "**YES** (benched)"),
        ("XAUUSD_H1A",     "XAU_5m->H1/H4 (GMT+2)", "YES (+1h summer)", "H4-bias bins (1h!=4h multiple)", "partial — H4 bins"),
        ("XAUUSD_MACROSS", "XAU_5m->H1/H4 (GMT+2)", "YES (+1h summer)", "H4-bias gate", "partial — H4 bins"),
        ("XAUUSD_CRASH",   "XAU_5m->H1/H4 (GMT+2)", "YES (+1h summer)", "H4-bias gate", "partial — H4 bins"),
        ("XAUUSD_STRAD",   "XAU_5m->H1 (GMT+2)", "YES (+1h summer)", "no (structure; day cap only)", "no — re-run anyway"),
        ("XAUUSD_DONCH",   "XAU_5m->H1 (GMT+2)", "YES (+1h summer)", "no (structure; day cap only)", "no — re-run anyway"),
        ("XAUUSD_BOS",     "XAU_5m->H1 (GMT+2)", "YES (+1h summer)", "no (structure; day cap only)", "no (class-covered)"),
        ("EURUSD_E",       "EURUSD60 (UTC)", "no — true UTC", "session hours", "no"),
        ("GBPUSD_E",       "GBPUSD60 (UTC)", "no — true UTC", "session hours", "no"),
        ("USDCAD_A",       "USDCAD60 (UTC)", "no — true UTC", "no", "no"),
        ("USDCHF_A",       "USDCHF60 (UTC)", "no — true UTC", "no", "no"),
        ("GBPUSD_P1",      "GBPUSD60 (UTC)", "no — true UTC", "no", "no"),
        ("EURUSD_P1_30",   "EURUSD30 (UTC)", "no — true UTC", "no", "no"),
        ("EURUSD_BOLL30",  "EURUSD30 (UTC)", "no — true UTC", "hours 14-24", "no (data correct)"),
        ("USDCHF_RSI30",   "USDCHF30 (UTC)", "no — true UTC", "hours 14-24", "no (data correct)"),
        ("GBPUSD_AVWAP",   "GBPUSD60 (UTC)", "no — true UTC", "hours + NY-day anchor", "no (data correct)"),
        ("SPX500/GER40/US30/JPN225/HK50 trend", "IDX M15->H1 (UTC parse)", "YES (server time)", "no (structure; whole-hour shift)", "no — labels only"),
    ]
    for m in M:
        say("| " + " | ".join(m) + " |")
    say("")

    say("## Re-runs — original lab code, original (buggy) parse vs corrected parse\n")
    say("Columns: n / net R / train R (<=2023) / holdout R (>=2024). The 'old' run "
        "must reproduce the official number (harness fidelity), then the ONLY "
        "change is the timestamp parse.\n")

    # ---- gold M5 strategies (S4, S6 read raw file directly) --------------
    say("### Gold M5 session strategies\n")
    say("| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |")
    say("|---|---|---|---|---|---|---|---|---|")

    tzfix_csv = write_shifted_gold_csv()
    def s4_run(mod):
        return mod.simulate(mod.localize_time(mod.read_xau(mod.CFG.data_path),
                                              mod.CFG.raw_timezone))

    def s6_run(mod):
        df = mod.load_data()
        return mod.simulate(df, mod.build_signals(df))

    for tag, folder, runner in (
            ("S4 (NY manipulation)", "strategy_4_ny_manipulation", s4_run),
            ("S6 (HF displacement)", "strategy_6_hf_displacement", s6_run)):
        os.chdir(folder)
        try:
            official = json.load(open("results_summary.json")) if os.path.exists(
                "results_summary.json") else None
            mod_o = load_module(f"tz_{folder}_o", "backtest.py")
            tb_old = runner(mod_o)
            mod_n = load_module(f"tz_{folder}_n", "backtest.py")
            mod_n.CFG = replace(mod_n.CFG, data_path=Path(tzfix_csv))
            tb_new = runner(mod_n)
            off = None
            if official:
                off = str({k: round(v, 1) if isinstance(v, float) else v
                           for k, v in official.items()
                           if k in ("trades", "net_r", "net_R", "train_r",
                                    "holdout_r")})
            row(tag, tb_stats(tb_old), tb_stats(tb_new), off)
        finally:
            os.chdir(ROOT)

    # ---- S5 / S3 via engine event candles --------------------------------
    import smc_engine
    from rebaseline_engine import load_raw as load_raw_old
    tzfix_15m = write_shifted_gold_csv("data/XAU_15m_data.csv")
    for src5, src15, label in (("data/XAU_5m_data.csv", "data/XAU_15m_data.csv", "old"),
                               (tzfix_csv, tzfix_15m, "fixed")):
        e5 = smc_engine.build_smc_frame(load_raw_old(src5))
        e5 = e5[e5["ny_date"] >= "2020-08-24"].reset_index(drop=True)
        e5.to_csv(f"data/tz_audit_candles_5m_{label}.csv", index=False)
        e15 = smc_engine.build_smc_frame(load_raw_old(src15))
        e15 = e15[e15["ny_date"] >= "2020-08-24"].reset_index(drop=True)
        e15[["timestamp_ny", "swing_bias"]].to_csv(
            f"data/tz_audit_candles_15m_{label}.csv", index=False)

    res = {}
    for label in ("old", "fixed"):
        os.chdir(os.path.join(ROOT, "strategy_5_lux_htf_sweep"))
        s5 = load_module(f"tz_s5_{label}", "backtest.py")
        s5.CFG = replace(s5.CFG, data_5m=Path(f"../data/tz_audit_candles_5m_{label}.csv"),
                         data_15m=Path(f"../data/tz_audit_candles_15m_{label}.csv"))
        res[("S5", label)] = tb_stats(s5.simulate(s5.load_data()))
        os.chdir(os.path.join(ROOT, "strategy_3_ny_am_fvg"))
        s3 = load_module(f"tz_s3_{label}", "backtest.py")
        s3.CFG = replace(s3.CFG, data_path=Path(f"../data/tz_audit_candles_5m_{label}.csv"))
        res[("S3", label)] = tb_stats(s3.simulate(s3.load_data()))
        os.chdir(ROOT)
    row("S5 (engine labels)", res[("S5", "old")], res[("S5", "fixed")])
    row("S3 (engine labels)", res[("S3", "old")], res[("S3", "fixed")])
    say("")

    # ---- gold H1 family ---------------------------------------------------
    say("### Gold H1 family (H4-bias bins / day-cap exposure)\n")
    say("| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |")
    say("|---|---|---|---|---|---|---|---|---|")
    import sideways_lab
    import live_signals as LS
    import fx_h1_backtest

    def gold_frames(loader):
        g = sideways_lab.add_features(loader(60), 60)
        g4 = loader(240)
        e4 = smc_engine.build_smc_frame(g4)
        htf = e4[["timestamp_ny", "swing_bias"]].copy()
        htf["timestamp_ny"] = htf["timestamp_ny"] + pd.Timedelta(minutes=240)
        g = pd.merge_asof(g.sort_values("timestamp_ny"),
                          htf.rename(columns={"swing_bias": "htf_bias"}),
                          on="timestamp_ny", direction="backward")
        g["htf_bias"] = g["htf_bias"].fillna(0).astype(int)
        return g

    def gold_engine_frames(loader):
        eg = smc_engine.build_smc_frame(
            loader(60)[["timestamp_ny", "open", "high", "low", "close", "volume"]])
        eg = sideways_lab.add_features(eg, 60)
        e4 = smc_engine.build_smc_frame(loader(240))
        htf = e4[["timestamp_ny", "swing_bias"]].copy()
        htf["timestamp_ny"] = htf["timestamp_ny"] + pd.Timedelta(minutes=240)
        eg = pd.merge_asof(eg.sort_values("timestamp_ny"),
                           htf.rename(columns={"swing_bias": "htf_bias"}),
                           on="timestamp_ny", direction="backward")
        eg["htf_bias"] = eg["htf_bias"].fillna(0).astype(int)
        return eg

    SP_G = LS.FX_SPREADS["XAUUSD"]
    g_old = gold_frames(sideways_lab.load_gold)
    g_new = gold_frames(load_gold_fixed)
    # H4-bias agreement, summer months only
    both = pd.merge(g_old[["timestamp_ny", "htf_bias"]],
                    g_new[["timestamp_ny", "htf_bias"]], on="timestamp_ny",
                    suffixes=("_o", "_n"))
    summer = both[both["timestamp_ny"].dt.month.isin((4, 5, 6, 7, 8, 9, 10))]
    say(f"| H4-bias agreement old-vs-fixed (DST months) | | "
        f"{100 * (summer['htf_bias_o'] == summer['htf_bias_n']).mean():.1f}% "
        f"of H1 bars agree | | | | | | |")

    # H1A (A family, H4-bias-aligned) — engine frames as in deployed_audit [4]
    eg_old = gold_engine_frames(sideways_lab.load_gold)
    eg_new = gold_engine_frames(load_gold_fixed)
    cfg_h = LS.FX_STRATS["XAUUSD-H1A"]
    t_old = pd.DataFrame(fx_h1_backtest.run_A(eg_old, "XAUUSD", "XAUUSD-H1A", cfg_h,
                                              SP_G, sides=cfg_h["sides"]))
    t_new = pd.DataFrame(fx_h1_backtest.run_A(eg_new, "XAUUSD", "XAUUSD-H1A", cfg_h,
                                              SP_G, sides=cfg_h["sides"]))
    row("H1A (official +23.8R)", tb_stats(t_old), tb_stats(t_new))

    import gold_trend_battery as GTB
    for tag, fn in (("MACROSS H4-gated long (official +49.8R)",
                     lambda g: GTB.macross(g, 3.0, SP_G, gate=True, sides=("long",))),
                    ("DONCH N96 long (official +95.4R)",
                     lambda g: GTB.donchian(g, 96, 3.0, SP_G, sides=("long",)))):
        t_o, t_n = fn(g_old), fn(g_new)
        for t in (t_o, t_n):
            if t is not None and len(t) and "year" not in t:
                t["year"] = pd.to_datetime(t["entry_ts"]).dt.year
        row(tag, tb_stats(t_o, "r"), tb_stats(t_n, "r"))

    # CRASH — the deployed signal condition (live_signals.signal_CRASH) run
    # through the battery executor (sim_ts wants a +/-1 signal array).
    def crash_trades(g):
        cfg = LS.FX_STRATS["XAUUSD-CRASH"]
        atr = g["atr50"].to_numpy(float)
        o = g["open"].to_numpy(float); h = g["high"].to_numpy(float)
        l = g["low"].to_numpy(float); c = g["close"].to_numpy(float)
        bias = g["htf_bias"].to_numpy(int)
        rng = h - l
        cond = (np.isfinite(atr) & (rng > 0) & (rng >= cfg["range_atr"] * atr)
                & (c < o) & ((c - l) <= cfg["close_loc"] * rng) & (bias == -1))
        sig = np.where(cond, -1, 0)
        stop = c + cfg["stop_atr"] * atr
        return GTB.sim_ts(g, sig, SP_G, stop, cfg["rr"],
                          max_hold=cfg["max_hold"], max_tpd=cfg["max_tpd"],
                          sides=("short",))
    t_o, t_n = crash_trades(g_old), crash_trades(g_new)
    for t in (t_o, t_n):
        if t is not None and len(t) and "year" not in t:
            t["year"] = pd.to_datetime(t["entry_ts"]).dt.year
    row("CRASH short (official +63.1R)", tb_stats(t_o, "r"), tb_stats(t_n, "r"))

    # STRAD (day-cap exposure only)
    import straddle_lab
    for label, loader in (("old", sideways_lab.load_gold), ("fixed", load_gold_fixed)):
        g = sideways_lab.add_features(loader(60), 60)
        tr_list = straddle_lab.straddle(g, 24, "edge", 2)
        t = (pd.DataFrame(tr_list, columns=["year", "r", "dur"])
             if tr_list else None)
        res[("STRAD", label)] = tb_stats(t, "r")
    row("STRAD W24 edge M2 (official +43.6R)", res[("STRAD", "old")], res[("STRAD", "fixed")])
    say("")

    # ---- S6R (the DEPLOYED rehab cell: bias5 gate + 2.4x displacement) ------
    say("### S6R — the deployed rehab cell (s6_rehab_lab pipeline, disp 2.4x, bias5)\n")
    say("| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |")
    say("|---|---|---|---|---|---|---|---|---|")
    import s6_rehab_lab as S6L

    def run6r(df, mult):
        """s6_rehab_lab.run VERBATIM with the displacement multiplier as a
        parameter (deployed S6R_DISP_ATR_MULT=2.4; the lab hardcodes 2.2)."""
        rng = (df["high"] - df["low"]).replace(0, np.nan)
        disp = ((rng >= mult * df["atr50"]) & (df["volume"] > df["vol_ma50"])
                & (df["atr_pctile"] > 0.25) & ~df["hour"].isin((3, 4, 5, 6, 7, 9)))
        sigm = disp & (df["close"] > df["open"]) & ((df["close"] - df["low"]) / rng >= 0.75)
        sigm &= df["bias5"] == 1
        o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
        l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
        dates = df["ny_date"].to_numpy(); years = df["year"].to_numpy(int)
        n = len(df); trades = []; tpd = {}; last_exit = -1
        for i in np.flatnonzero(sigm.to_numpy()):
            ei = i + 1
            if ei >= n or ei <= last_exit:
                continue
            day = dates[ei]
            if tpd.get(day, 0) >= 2:
                continue
            entry = o[ei] + S6L.SP / 2
            stop = l[i] - S6L.SP / 2
            risk = entry - stop
            if not (1.0 <= risk <= 25.0):
                continue
            target = entry + 1.5 * risk
            xj = min(ei + 96, n - 1); xp = c[xj]; xi = xj
            for j in range(ei, xj + 1):
                if l[j] <= stop:
                    xp, xi = stop, j; break
                if h[j] >= target:
                    xp, xi = target, j; break
            trades.append((int(years[ei]), (xp - entry) / risk))
            tpd[day] = tpd.get(day, 0) + 1; last_exit = xi
        return trades

    s6res = {}
    orig_lg = S6L.load_gold
    for label, loader in (("old", orig_lg), ("fixed", load_gold_fixed)):
        S6L.load_gold = loader
        try:
            df6 = S6L.prep()
        finally:
            S6L.load_gold = orig_lg
        t = pd.DataFrame(run6r(df6, 2.4), columns=["year", "r"])
        s6res[label] = tb_stats(t, "r")
    row("S6R deployed (bias5 + 2.4x disp)", s6res["old"], s6res["fixed"])
    say("")

    # ---- BOLL15 (benched) --------------------------------------------------
    say("### BOLL15 trio (deep-file NY+5 bug; BENCHED July 14 — audit anyway)\n")
    say("| strategy | old n | old net | old tr | old ho | new n | new net | new tr | new ho |")
    say("|---|---|---|---|---|---|---|---|---|")
    import m15_deep_validation as MDV
    sides_dep = {"EURUSD": "long", "GBPUSD": "both", "USDCHF": "both"}
    orig_loader = MDV.load_mt5_export
    for sym in ("EURUSD", "GBPUSD", "USDCHF"):
        sp = MDV.SPREADS[sym]
        MDV.load_mt5_export = orig_loader
        deep_old = MDV.prep_from(f"data/{sym}15_deep.csv")
        MDV.load_mt5_export = load_mt5_export_ny5
        deep_new = MDV.prep_from(f"data/{sym}15_deep.csv")
        MDV.load_mt5_export = orig_loader
        t_o = MDV.stat(MDV.boll_sided(deep_old, sp, set(range(14, 24)), sides_dep[sym]))
        t_n = MDV.stat(MDV.boll_sided(deep_new, sp, set(range(14, 24)), sides_dep[sym]))
        def st(t):
            if t is None or not len(t):
                return dict(n=0, net=0.0, tr=0.0, ho=0.0)
            return dict(n=len(t), net=float(t["r"].sum()),
                        tr=float(t.loc[t["year"] <= 2023, "r"].sum()),
                        ho=float(t.loc[t["year"] >= 2024, "r"].sum()))
        row(f"{sym}-BOLL15 {sides_dep[sym]}", st(t_o), st(t_n))
    say("")

    open(REPORT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
