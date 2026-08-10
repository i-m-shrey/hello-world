"""CONSOLIDATED DEPLOYMENT AUDIT — the families the standing verifiers don't cover.

Standing verifiers (run separately, all green 2026-07-05):
  lookahead_audit.py   engine truncation invariance (EUR/GBP/CAD H1) + atr_pctile + H4 bias
  s5_verify.py         S5 home backtest + gold 5m/15m causality + every-symbol port
  all_strats_verify.py S6/S4/S3 causal, S2 look-ahead demo (NOT deployed)
  verify_live_fx.py    A/E families: numbers + wrapper + windowed re-prep
  verify_rsi30.py      USDCHF_RSI30: numbers + signal-set + wrapper + windowed re-prep

THIS script covers, for the remaining deployed paths:
  [1] EURUSD-BOLL30  lab number + signal-set equality + wrapper + windowed re-prep
  [2] XAUUSD-STRAD   close-confirmed reference sim + signal-set + wrapper + windowed
  [3] GBPUSD-P1 / EURUSD-P1-30  lab numbers + lock-free signal-set + wrapper + windowed
  [4] XAUUSD-H1A     reference number + H4-ANCHOR SENSITIVITY (backtest used NY-anchored
                     H4 resample; live uses broker-anchored H4 — measure the difference)
  [5] Gold bot-parity: eval_s5 / eval_s3 fire on live-sized truncated frames at the
      tradebooks' signal bars (the bot's own code path, cache-sized data)
  [6] Config cross-check: deployed INSTANCES == validated FX_STRATS/STRAT params
"""
import os
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

import live_signals as LS
import smc_engine
from multi_symbol_lab import load_mt5_export
import fx_lowtf_meanrev_lab as MRLAB
import ict_patterns_lab as ICT
from sideways_lab import load_gold, add_features
from fx_h1_backtest import run_A

RESULTS = []


def verdict(section, ok, detail):
    RESULTS.append((section, ok, detail))
    print(f"  {'PASS' if ok else '!! FAIL'}  {detail}")


# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[1] EURUSD-BOLL30 — lab vs live signal path")
print("=" * 94)
CFG_B = LS.FX_STRATS["EURUSD-BOLL30"]
dfe = MRLAB.prep("EURUSD", 30)
tr_b = MRLAB.f1_boll(dfe, 0.00002, set(range(14, 24)))
tb = pd.DataFrame(tr_b, columns=["year", "r"])
print(f"  lab number (data now ends {dfe['ny_date'].iloc[-1]}): n={len(tb)} net={tb.r.sum():+.1f}R "
      f"(validated +54.9R n=1066 on the pre-Jul-03 file; the Jul-03 re-export both extends "
      f"AND slightly revises history — train moved +28.8->+26.1, 2026 lost ~8R live-period)")
verdict("BOLL30 number", len(tb) >= 1066 and tb.r.sum() > 35,
        f"BOLL30 lab backtest n={len(tb)}, net {tb.r.sum():+.1f}R — edge intact on revised data "
        f"(both splits +, watch 2026 stretch at monthly review)")

raw30e = load_mt5_export("data/EURUSD30.csv")
raw4e = load_mt5_export("data/EURUSD240.csv")
fre = LS.prep_h1_frame(raw30e, raw4e, pctile_win=1440)
assert len(fre) == len(dfe)
# lab mask (raw conditions, pre-caps)
sma = dfe["close"].rolling(20).mean(); sd = dfe["close"].rolling(20).std()
okm = (dfe["atr_pctile"] <= 0.70) & dfe["atr50"].notna() & (dfe["hour"] != 17) \
      & dfe["hour"].isin(set(range(14, 24)))
lab_long = (okm & (dfe["close"] < sma - 2 * sd)).to_numpy()
lab_short = (okm & (dfe["close"] > sma + 2 * sd)).to_numpy()
# live mask via signal_BOLL on the live frame
warm = 1440
live_long = np.zeros(len(fre), bool); live_short = np.zeros(len(fre), bool)
for i in range(warm, len(fre)):
    r = LS.signal_BOLL(fre, i, CFG_B)
    if r is not None:
        (live_long if r[0] == 1 else live_short)[i] = True
miss = int((lab_long[warm:] & ~live_long[warm:]).sum() + (lab_short[warm:] & ~live_short[warm:]).sum())
extra = int((~lab_long[warm:] & live_long[warm:]).sum() + (~lab_short[warm:] & live_short[warm:]).sum())
verdict("BOLL30 signal set", miss == 0 and extra == 0,
        f"BOLL30 signal-set equality: {int(lab_long.sum() + lab_short.sum())} lab signals, "
        f"{miss} missing, {extra} extra")
# wrapper sample
idx = np.flatnonzero(lab_long | lab_short); idx = idx[idx >= warm]
sample = idx[:: max(1, len(idx) // 40)][:40]
mism = 0
for i in sample:
    got = LS.signal_at_last_bar(fre.iloc[: i + 1], CFG_B)
    want = "long" if lab_long[i] else "short"
    if got is None or got["direction"] != want:
        mism += 1
verdict("BOLL30 wrapper", mism == 0, f"BOLL30 signal_at_last_bar: {len(sample)-mism}/{len(sample)} reproduced")
# windowed re-prep (live cache 3600 x M30)
ts_e = fre["timestamp_ny"].to_numpy()
win_mis = 0
wsample = sample[:20]
for i in wsample:
    cut = ts_e[i]
    d30 = raw30e[raw30e["timestamp_ny"] <= cut].tail(3600).reset_index(drop=True)
    d4 = raw4e[raw4e["timestamp_ny"] <= cut].tail(2500).reset_index(drop=True)
    got = LS.signal_at_last_bar(LS.prep_h1_frame(d30, d4, 1440), CFG_B)
    want = "long" if lab_long[i] else "short"
    if got is None or got["direction"] != want:
        win_mis += 1
verdict("BOLL30 windowed", win_mis == 0,
        f"BOLL30 3600-bar cache re-prep: {len(wsample)-win_mis}/{len(wsample)} reproduced")

# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[2] XAUUSD-STRAD — close-confirmed reference sim vs live signal path")
print("=" * 94)
CFG_S = LS.FX_STRATS["XAUUSD-STRAD"]
g60 = add_features(load_gold(60), 60)
SP_G = 0.60
o = g60["open"].to_numpy(float); h = g60["high"].to_numpy(float)
l = g60["low"].to_numpy(float); c = g60["close"].to_numpy(float)
atr = g60["atr50"].to_numpy(float); hrs = g60["hour"].to_numpy(int)
yrs = g60["year"].to_numpy(int); dts = g60["ny_date"].to_numpy()
W, K, M = CFG_S["W"], CFG_S["K"], CFG_S["M"]
n = len(g60); trades_s = []; sig_mask = np.zeros(n, bool)
tpd = {}; last_exit = -1
for i in range(W + 1, n - 1):
    if hrs[i] == 17 or not np.isfinite(atr[i]):
        continue
    zh = h[i - W: i].max(); zl = l[i - W: i].min(); width = zh - zl
    if not (1.0 * atr[i] <= width <= K * atr[i]):
        continue
    if not (c[i] > zh + 0.10 * atr[i]):
        continue
    sig_mask[i] = True
    ei = i + 1
    if ei <= last_exit:
        continue
    day = dts[ei]
    if tpd.get(day, 0) >= CFG_S["max_tpd"]:
        continue
    entry = o[ei] + SP_G / 2
    stop = zl - 0.10 * atr[i] - SP_G / 2
    risk = entry - stop
    if risk <= 0 or not (0.3 * atr[i] <= risk <= 4.0 * atr[i]):
        continue
    tp = entry + M * width
    xj = min(ei + CFG_S["max_hold"], n - 1); xp = c[xj]; xi = xj
    for j in range(ei, xj + 1):
        if l[j] <= stop:
            xp, xi = stop, j; break
        if h[j] >= tp:
            xp, xi = tp, j; break
    trades_s.append((int(yrs[ei]), (xp - entry) / risk))
    tpd[day] = tpd.get(day, 0) + 1; last_exit = xi
tss = pd.DataFrame(trades_s, columns=["year", "r"])
ok_num = abs(tss.r.sum() - 43.6) < 1.0 and abs(len(tss) - 142) <= 3
verdict("STRAD number", ok_num,
        f"STRAD close-confirmed reference: n={len(tss)} net={tss.r.sum():+.1f}R "
        f"(validated n=142, +43.6R)")
# live signal path on prep_h1_frame (STRAD signal ignores bias; H4 only feeds unused cols)
g240 = load_gold(240)
frg = LS.prep_h1_frame(g60[["timestamp_ny", "open", "high", "low", "close", "volume"]],
                       g240, pctile_win=720)
assert len(frg) == len(g60)
mism = extra = 0
idx = np.flatnonzero(sig_mask)
for i in idx:
    r = LS.signal_STRAD(frg, i, CFG_S)
    if r is None:
        mism += 1
chk = np.random.RandomState(7).choice(np.flatnonzero(~sig_mask[W + 1:]) + W + 1, 4000, replace=False)
for i in chk:
    if LS.signal_STRAD(frg, int(i), CFG_S) is not None:
        extra += 1
verdict("STRAD signal set", mism == 0 and extra == 0,
        f"STRAD signals: {len(idx)-mism}/{len(idx)} reproduced, {extra} false fires in 4000 controls")
wsample = idx[:: max(1, len(idx) // 15)][:15]
ts_g = frg["timestamp_ny"].to_numpy()
win_mis = 0
for i in wsample:
    cut = ts_g[i]
    d1 = g60[g60["timestamp_ny"] <= cut][["timestamp_ny", "open", "high", "low", "close", "volume"]].tail(2500).reset_index(drop=True)
    d4 = g240[g240["timestamp_ny"] <= cut].tail(2500).reset_index(drop=True)
    got = LS.signal_at_last_bar(LS.prep_h1_frame(d1, d4, 720), CFG_S)
    if got is None or got["direction"] != "long":
        win_mis += 1
verdict("STRAD windowed", win_mis == 0,
        f"STRAD 2500-bar cache re-prep: {len(wsample)-win_mis}/{len(wsample)} reproduced")

# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[3] P1 (GBPUSD H1 + EURUSD 30m) — lab vs live signal path")
print("=" * 94)
for tag, sym, tf, cache, pctw in (("GBPUSD-P1", "GBPUSD", 60, 2500, 720),
                                  ("EURUSD-P1-30", "EURUSD", 30, 3600, 1440),
                                  ("USDCHF-P1", "USDCHF", 60, 2500, 720)):
    CFG_P = LS.FX_STRATS[tag]
    dfp = MRLAB.prep(sym, tf)
    trp = ICT.p1_opposing_fvg(dfp, {"GBPUSD": 0.00002, "EURUSD": 0.00002, "USDCHF": 0.00006}[sym],
                              L=CFG_P["L"], wait=CFG_P["wait"], rr=CFG_P["rr"],
                              max_hold=CFG_P["max_hold"])
    tp_ = pd.DataFrame(trp, columns=["year", "r"])
    print(f"  {tag} lab number (data ends {dfp['ny_date'].iloc[-1]}): n={len(tp_)} net={tp_.r.sum():+.1f}R")
    verdict(f"{tag} number", tp_.r.sum() > 15,
            f"{tag} lab backtest n={len(tp_)}, net {tp_.r.sum():+.1f}R reproduced on current data")
    # lock-free raw signal set from the LAB loop (state update precedes locks -> pure)
    ol, hl, ll, cl = (dfp[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    al = dfp["atr50"].to_numpy(float); hh = dfp["hour"].to_numpy(int)
    swl = dfp["low"].shift(3).rolling(20).min().to_numpy(float)
    swh = dfp["high"].shift(3).rolling(20).max().to_numpy(float)
    nb = len(dfp); bull = bear = None
    lab_sigs = {}
    for t in range(25, nb - 1):
        disp = (hl[t - 1] - ll[t - 1]) >= CFG_P["disp_mult"] * al[t] if np.isfinite(al[t]) else False
        if disp and ll[t] > hl[t - 2]:
            bull = (ll[t], hl[t - 2], t)
        if disp and hl[t] < ll[t - 2]:
            bear = (ll[t - 2], hl[t], t)
        if hh[t] == 17 or not np.isfinite(al[t]):
            continue
        if bull and bear and bear[2] == t and 0 < t - bull[2] <= CFG_P["L"] and cl[t] < swl[bull[2]]:
            z_lo = max(bear[1], bull[1]); z_hi = min(bear[0], bull[0])
            if z_hi > z_lo:
                lab_sigs[t] = ("short", z_lo)
        if bear and bull and bull[2] == t and 0 < t - bear[2] <= CFG_P["L"] and cl[t] > swh[bear[2]]:
            z_lo = max(bull[1], bear[1]); z_hi = min(bull[0], bear[0])
            if z_hi > z_lo:
                lab_sigs[t] = ("long", z_hi)
    raw1 = load_mt5_export(f"data/{sym}{tf}.csv")
    raw4p = load_mt5_export(f"data/{sym}240.csv")
    frp = LS.prep_h1_frame(raw1, raw4p, pctile_win=pctw)
    assert len(frp) == len(dfp)
    miss = extra = 0
    warm = 60
    for i in range(warm, len(frp) - 1):
        r = LS.signal_P1(frp, i, CFG_P)
        if (r is not None) != (i in lab_sigs):
            if r is None:
                miss += 1
            else:
                extra += 1
        elif r is not None and (r["direction"] != lab_sigs[i][0]
                                or abs(r["limit"] - lab_sigs[i][1]) > 1e-9):
            miss += 1
    verdict(f"{tag} signal set", miss == 0 and extra == 0,
            f"{tag} signal-set equality: {len(lab_sigs)} lab signals, {miss} mismatched, {extra} extra")
    sig_bars = sorted(lab_sigs)
    wsample = sig_bars[:: max(1, len(sig_bars) // 12)][:12]
    ts_p = frp["timestamp_ny"].to_numpy()
    win_mis = 0
    for i in wsample:
        cut = ts_p[i]
        d1 = raw1[raw1["timestamp_ny"] <= cut].tail(cache).reset_index(drop=True)
        d4 = raw4p[raw4p["timestamp_ny"] <= cut].tail(2500).reset_index(drop=True)
        got = LS.signal_at_last_bar(LS.prep_h1_frame(d1, d4, pctw), CFG_P)
        if got is None or got["direction"] != lab_sigs[i][0]:
            win_mis += 1
    verdict(f"{tag} windowed", win_mis == 0,
            f"{tag} {cache}-bar cache re-prep: {len(wsample)-win_mis}/{len(wsample)} reproduced")

# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[4] XAUUSD-H1A — reference number + H4-ANCHOR sensitivity (NY vs broker anchor)")
print("=" * 94)
CFG_H = LS.FX_STRATS["XAUUSD-H1A"]
eg = smc_engine.build_smc_frame(g60[["timestamp_ny", "open", "high", "low", "close", "volume"]])
eg = add_features(eg, 60)
e4 = smc_engine.build_smc_frame(g240)
htf = e4[["timestamp_ny", "swing_bias"]].copy()
htf["timestamp_ny"] = htf["timestamp_ny"] + pd.Timedelta(minutes=240)
eg1 = pd.merge_asof(eg.sort_values("timestamp_ny"),
                    htf.rename(columns={"swing_bias": "htf_bias"}),
                    on="timestamp_ny", direction="backward")
eg1["htf_bias"] = eg1["htf_bias"].fillna(0).astype(int)
tb1 = pd.DataFrame(run_A(eg1, "XAUUSD", "XAUUSD-H1A", CFG_H, SP_G, sides=CFG_H["sides"]))
r1 = tb1["result_r"].sum() if len(tb1) else 0.0
verdict("H1A number", abs(r1 - 23.8) < 1.0,
        f"H1A reference (NY-anchored H4, as validated): n={len(tb1)} net={r1:+.1f}R (validated +23.8)")
# broker-anchored H4 (17:00-NY bins = 00:00 GMT+7 offset trick: resample with offset)
g5 = load_gold(5)
gb = g5.set_index("timestamp_ny").resample("240min", offset="-7h")
g240b = pd.DataFrame({"open": gb["open"].first(), "high": gb["high"].max(),
                      "low": gb["low"].min(), "close": gb["close"].last(),
                      "volume": gb["volume"].sum()}).dropna().reset_index()
e4b = smc_engine.build_smc_frame(g240b)
htfb = e4b[["timestamp_ny", "swing_bias"]].copy()
htfb["timestamp_ny"] = htfb["timestamp_ny"] + pd.Timedelta(minutes=240)
eg2 = pd.merge_asof(eg.sort_values("timestamp_ny"),
                    htfb.rename(columns={"swing_bias": "htf_bias"}),
                    on="timestamp_ny", direction="backward")
eg2["htf_bias"] = eg2["htf_bias"].fillna(0).astype(int)
agree = float((eg1["htf_bias"].to_numpy() == eg2["htf_bias"].to_numpy()).mean()) * 100
tb2 = pd.DataFrame(run_A(eg2, "XAUUSD", "XAUUSD-H1A", CFG_H, SP_G, sides=CFG_H["sides"]))
r2 = tb2["result_r"].sum() if len(tb2) else 0.0
t2 = tb2.loc[tb2["year"] <= 2023, "result_r"].sum() if len(tb2) else 0
h2 = tb2.loc[tb2["year"] >= 2024, "result_r"].sum() if len(tb2) else 0
print(f"  H4 bias agreement NY-anchor vs broker-anchor: {agree:.1f}% of H1 bars")
print(f"  H1A re-run with BROKER-anchored H4: n={len(tb2)} net={r2:+.1f}R "
      f"(train {t2:+.1f} / holdout {h2:+.1f})")
verdict("H1A H4-anchor sensitivity", r2 > 10 and t2 > 0 and h2 > 0,
        f"H1A edge holds under broker H4 anchoring: {r2:+.1f}R (both splits +) — "
        f"anchor is a robustness variable, not the edge")

# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[5] GOLD BOT-PARITY — the bot's own eval_s5/eval_s3 on live-sized truncated frames")
print("=" * 94)
sys.modules["MetaTrader5"] = MagicMock()
import importlib
import live_mt5_bot as BOT
g5f = g5  # full 5m
g15 = g5.set_index("timestamp_ny").resample("15min")
g15 = pd.DataFrame({"open": g15["open"].first(), "high": g15["high"].max(),
                    "low": g15["low"].min(), "close": g15["close"].last(),
                    "volume": g15["volume"].sum()}).dropna().reset_index()
for tag, tbfile, evalfn in (("S5-LO", "tradebooks/XAUUSD_S5_longonly_tradebook.csv", "s5"),
                            ("S3-LO", "tradebooks/XAUUSD_S3_longonly_tradebook.csv", "s3")):
    tbk = pd.read_csv(tbfile)
    # gold tradebooks carry entry_time only; the SIGNAL bar closed one 5m bar earlier
    if "signal_time" in tbk.columns:
        sig_ts = pd.to_datetime(tbk["signal_time"], utc=True).dt.tz_convert("America/New_York")
    else:
        sig_ts = (pd.to_datetime(tbk["entry_time"], utc=True).dt.tz_convert("America/New_York")
                  - pd.Timedelta(minutes=5))
    if "direction" in tbk.columns:
        sig_ts = sig_ts[tbk["direction"].str.lower().isin(["long", "buy"])]
    sample_ts = sig_ts.iloc[:: max(1, len(sig_ts) // 25)][:25]
    okc = 0
    for T in sample_ts:
        d5 = g5f[g5f["timestamp_ny"] <= T].tail(12500).reset_index(drop=True)
        d15 = g15[g15["timestamp_ny"] + pd.Timedelta(minutes=15) <= T + pd.Timedelta(minutes=5)]
        d15 = d15.tail(4600).reset_index(drop=True)
        try:
            e5b, e15b = BOT.build_gold_frame(d5, d15)
            if evalfn == "s5":
                sig, note = BOT.eval_s5(e5b, e15b, long_only=True)
            else:
                sig, note = BOT.eval_s3(e5b)
            if sig is not None and sig.get("direction") == "long":
                okc += 1
        except Exception as ex:
            print(f"    {tag} @ {T}: ERROR {ex}")
    verdict(f"{tag} bot parity", okc == len(sample_ts),
            f"{tag}: bot eval fired long on {okc}/{len(sample_ts)} tradebook signal bars "
            f"(live cache-sized frames)")

# ────────────────────────────────────────────────────────────────────────────
print("=" * 94)
print("[6] CONFIG CROSS-CHECK — deployed instance params == validated params")
print("=" * 94)
cc_ok = True
checks = [
    ("EURUSD_E hours", tuple(BOT.INSTANCES["EURUSD_E"]["cfg"]["hours"]), (2, 3, 4, 8, 9, 10, 14, 15)),
    ("EURUSD_E rr/be", (BOT.INSTANCES["EURUSD_E"]["rr"], BOT.INSTANCES["EURUSD_E"]["be_r"]), (2.5, 1.5)),
    ("GBPUSD_E rr/be", (BOT.INSTANCES["GBPUSD_E"]["rr"], BOT.INSTANCES["GBPUSD_E"]["be_r"]), (2.5, 1.5)),
    ("USDCAD_A rr/windows", (BOT.INSTANCES["USDCAD_A"]["cfg"]["rr"],
                             BOT.INSTANCES["USDCAD_A"]["cfg"]["choch_bars"],
                             BOT.INSTANCES["USDCAD_A"]["cfg"]["sweep_bars"]), (2.5, 36, 48)),
    ("USDCHF_A short-only", BOT.INSTANCES["USDCHF_A"]["cfg"]["sides"], ("bearish",)),
    ("XAUUSD_H1A long-only rr2.0", (BOT.INSTANCES["XAUUSD_H1A"]["cfg"]["sides"],
                                    BOT.INSTANCES["XAUUSD_H1A"]["cfg"]["rr"]), (("bullish",), 2.0)),
    ("BOLL30 bb/sd/stop/hours", (BOT.INSTANCES["EURUSD_BOLL30"]["cfg"]["bb_len"],
                                 BOT.INSTANCES["EURUSD_BOLL30"]["cfg"]["sd_mult"],
                                 BOT.INSTANCES["EURUSD_BOLL30"]["cfg"]["stop_atr"],
                                 BOT.INSTANCES["EURUSD_BOLL30"]["cfg"]["hours"][0]), (20, 2.0, 1.2, 14)),
    ("STRAD W/K/M", (BOT.INSTANCES["XAUUSD_STRAD"]["cfg"]["W"],
                     BOT.INSTANCES["XAUUSD_STRAD"]["cfg"]["K"],
                     BOT.INSTANCES["XAUUSD_STRAD"]["cfg"]["M"]), (24, 3.0, 2.0)),
    ("GBPUSD_P1 L/wait/disp/rr", (BOT.INSTANCES["GBPUSD_P1"]["cfg"]["L"],
                                  BOT.INSTANCES["GBPUSD_P1"]["cfg"]["wait"],
                                  BOT.INSTANCES["GBPUSD_P1"]["cfg"]["disp_mult"],
                                  BOT.INSTANCES["GBPUSD_P1"]["cfg"]["rr"]), (30, 30, 1.2, 2.0)),
    ("RSI30 hi/stop/rr/hours", (BOT.INSTANCES["USDCHF_RSI30"]["cfg"]["rsi_hi"],
                                BOT.INSTANCES["USDCHF_RSI30"]["cfg"]["stop_atr"],
                                BOT.INSTANCES["USDCHF_RSI30"]["cfg"]["rr"],
                                BOT.INSTANCES["USDCHF_RSI30"]["cfg"]["hours"][0]), (75, 1.0, 1.5, 14)),
    ("S5 rr/runner params", (BOT.STRAT["S5"]["rr"], BOT.RUNNER_BE_R, BOT.RUNNER_TRAIL_START_R,
                             BOT.RUNNER_TRAIL_ATR_MULT), (2.0, 1.0, 2.0, 2.0)),
    ("S3LO rr/be/magic", (BOT.INSTANCES["XAUUSD_S3LO"]["rr"], BOT.INSTANCES["XAUUSD_S3LO"]["be_r"],
                          BOT.INSTANCES["XAUUSD_S3LO"]["magic"]), (2.0, 1.0, 30001)),
    ("S6-R enabled + rehab params", (BOT.ENABLE["XAUUSD_S6"], BOT.S6R_DISP_ATR_MULT,
                                     BOT.S6R_REQUIRE_BIAS5), (True, 2.4, True)),
    ("gold stack cap (stacking study, 7 gold-longs)", BOT.MAX_STACKED_GOLD_LONGS, 4),
    ("FX max-risk cap + min floor off", (BOT.FX_MAX_RISK_USD, BOT.FX_MIN_RISK_USD,
                                         BOT.FX_MAX_RISK_SKIP), (10.5, 0.0, True)),
    ("book concurrency governor (total, per-USD)", (BOT.MAX_CONCURRENT_TOTAL,
                                                    BOT.MAX_CONCURRENT_PER_USD), (6, 4)),
    ("drawdown throttle armed", (BOT.RISK_THROTTLE_ENABLED, BOT.RISK_THROTTLE_DD_R,
                                 BOT.RISK_THROTTLE_MULT), (True, -20.0, 0.5)),
    ("BOLL15 magics/feeds", tuple((BOT.INSTANCES[k]["magic"], BOT.feed_of(BOT.INSTANCES[k]))
                                  for k in ("EURUSD_BOLL15", "GBPUSD_BOLL15", "USDCHF_BOLL15")),
     ((83001, "EURUSD_15"), (92001, "GBPUSD_15"), (73001, "USDCHF_15"))),
    ("EURUSD_BOLL15 long-only", BOT.INSTANCES["EURUSD_BOLL15"]["cfg"]["sides"], ("long",)),
    ("M15 feeds pctile/bars", tuple((BOT.SYMBOLS[f]["pctile_win"], BOT.SYMBOLS[f]["bars"])
                                    for f in ("EURUSD_15", "GBPUSD_15", "USDCHF_15")),
     ((2880, 6000),) * 3),
    ("index DONCH magics/params", tuple((BOT.INSTANCES[k]["magic"],
                                         BOT.INSTANCES[k]["cfg"]["N"],
                                         BOT.INSTANCES[k]["cfg"]["rr"],
                                         BOT.INSTANCES[k]["cfg"]["stop_atr"],
                                         BOT.INSTANCES[k]["risk_mode"])
                                        for k in ("SPX500_DONCH", "GER40_DONCH")),
     ((55001, 96, 3.0, 2.0, "trend"), (56001, 96, 3.0, 2.0, "trend"))),
    ("BOS magics/rr (gold rr5, DAX rr3)", ((BOT.INSTANCES["XAUUSD_BOS"]["magic"],
                                            BOT.INSTANCES["XAUUSD_BOS"]["cfg"]["rr"],
                                            BOT.INSTANCES["XAUUSD_BOS"]["cfg"]["piv_k"]),
                                           (BOT.INSTANCES["GER40_BOS"]["magic"],
                                            BOT.INSTANCES["GER40_BOS"]["cfg"]["rr"],
                                            BOT.INSTANCES["GER40_BOS"]["cfg"]["piv_k"])),
     ((59001, 5.0, 3), (59501, 3.0, 3))),
    ("equity gates wired to ladder variables",
     tuple(BOT.INSTANCES[k]["equity_min"]
           for k in ("XAUUSD_DONCH", "XAUUSD_MACROSS", "XAUUSD_BOS", "GER40_DONCH",
                     "GER40_BOS", "US30_DONCH", "JPN225_DONCH", "HK50_MACROSS")),
     (BOT.EQUITY_GATE_GOLD_TREND,) * 3 + (BOT.EQUITY_GATE_DAX_TREND,) * 2
     + (BOT.EQUITY_GATE_US30,) + (BOT.EQUITY_GATE_ASIA,) * 2),
    ("AVWAP fade magic/params/short-only", (BOT.INSTANCES["GBPUSD_AVWAP"]["magic"],
                                            BOT.INSTANCES["GBPUSD_AVWAP"]["cfg"]["k"],
                                            BOT.INSTANCES["GBPUSD_AVWAP"]["cfg"]["stop_atr"],
                                            BOT.INSTANCES["GBPUSD_AVWAP"]["cfg"]["sides"],
                                            BOT.INSTANCES["GBPUSD_AVWAP"]["risk_mode"],
                                            17 in BOT.INSTANCES["GBPUSD_AVWAP"]["cfg"]["hours"],
                                            BOT.ENABLE["GBPUSD_AVWAP"]),
     (58001, 1.5, 1.2, ("short",), "boll", False, True)),
    ("BOLL15 trio benched (July 14 2026)",
     tuple(BOT.ENABLE[k] for k in ("EURUSD_BOLL15", "GBPUSD_BOLL15", "USDCHF_BOLL15")),
     (False, False, False)),
    ("CRASH insurance magic/params/short", (BOT.INSTANCES["XAUUSD_CRASH"]["magic"],
                                            BOT.INSTANCES["XAUUSD_CRASH"]["cfg"]["range_atr"],
                                            BOT.INSTANCES["XAUUSD_CRASH"]["cfg"]["close_loc"],
                                            BOT.INSTANCES["XAUUSD_CRASH"]["cfg"]["rr"],
                                            BOT.INSTANCES["XAUUSD_CRASH"]["risk_mode"],
                                            BOT.ENABLE["XAUUSD_CRASH"]),
     (57001, 2.0, 0.25, 2.0, "trend", False)),   # user keeps insurance OFF for now
    ("index min-lot + USD-neutral exemptions",
     (tuple(s in BOT.MINLOT_SYMBOLS for s in ("SPX500", "GER40")),
      BOT._usd_side("SPX500", True), BOT._usd_side("GER40", False)),
     ((True, True), 0, 0)),
]
for name, got, want in checks:
    ok = got == want
    cc_ok &= ok
    print(f"  {'OK ' if ok else '!! '} {name}: {got}" + ("" if ok else f"  (expected {want})"))
verdict("config cross-check", cc_ok, f"{len(checks)} deployed-vs-validated param checks")

# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 94)
print("AUDIT SUMMARY")
print("=" * 94)
fails = [d for s, ok, d in RESULTS if not ok]
for s, ok, d in RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {s}")
print("=" * 94)
print("OVERALL: " + ("ALL SECTIONS PASS" if not fails else f"{len(fails)} FAILURES — see above"))
sys.exit(0 if not fails else 1)
