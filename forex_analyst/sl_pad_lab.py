"""SL-pad lab (Aug 2026): does widening every stop by a small pad improve the book?
Runs the exact live_signals conditions on 2y of proxy data (yahoo futures/cash),
simulates fixed-RR exits conservatively (SL-first on same-bar touch), and measures
avg R on the WIDENED risk (dollar-normalized, as the live sizers do). Two variants:
rr-scaled (TP recomputed from the wider risk = bot semantics) and tp-fixed (TP stays
at the baseline level = pure extra room). Trail cells, gold M5 SMC tier, 30m fades
and A/P1 families are out of scope (engine/data limits) - see SL_PAD_REPORT.md."""
import sys, types, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/workspace/hello-world/forex_analyst")
smc = types.ModuleType("smc_engine"); smc.build_smc_frame = lambda df: df
sys.modules["smc_engine"] = smc
import live_signals as LS
import numpy as np, pandas as pd, yfinance as yf

NY = "America/New_York"
def fetch(tkr, interval="1h", period="729d"):
    df = yf.download(tkr, interval=interval, period=period, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    df.index = df.index.tz_convert("UTC")
    e = df[["open","high","low","close","volume"]].copy()
    e["timestamp_ny"] = e.index.tz_convert(NY)
    return e.reset_index(drop=True)

def enrich(e, pw=720):
    prev = e["close"].shift(1)
    tr = pd.concat([e["high"]-e["low"],(e["high"]-prev).abs(),(e["low"]-prev).abs()],axis=1).max(axis=1)
    e["atr50"] = tr.rolling(50, min_periods=20).mean()
    e["atr_pctile"] = e["atr50"].rolling(pw, min_periods=min(200, pw//3)).rank(pct=True)
    return e

def bias(e):
    x = e.set_index(pd.DatetimeIndex(e["timestamp_ny"]))
    h4 = x["close"].resample("4h").last().dropna()
    b = ((h4.ewm(span=20,adjust=False).mean() > h4.ewm(span=50,adjust=False).mean()).astype(int)*2-1)
    e["htf_bias"] = b.reindex(pd.DatetimeIndex(e["timestamp_ny"]), method="ffill").fillna(0).astype(int).values
    return e

def resample(e, rule, day=False):
    x = e.set_index(pd.DatetimeIndex(e["timestamp_ny"]))
    out = x[["open","high","low","close","volume"]].resample("1D" if day else rule).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
    out["timestamp_ny"] = pd.DatetimeIndex(out.iloc[:,0]); return out[["timestamp_ny","open","high","low","close","volume"]]

print("downloading 2y...", flush=True)
GOLD = bias(enrich(fetch("GC=F")));  ES = enrich(fetch("ES=F")); YM = enrich(fetch("YM=F"))
NIY = enrich(fetch("NIY=F")); DAX = enrich(fetch("^GDAXI"))
EUR = bias(enrich(fetch("EURUSD=X"))); GBP = bias(enrich(fetch("GBPUSD=X")))
G4 = enrich(resample(GOLD, "4h"), pw=180); D1 = enrich(resample(ES, None, day=True), pw=180)
for n,d in [("GOLD",GOLD),("ES",ES),("YM",YM),("NIY",NIY),("DAX",DAX),("EUR",EUR),("GBP",GBP)]:
    print(n, len(d), str(d['timestamp_ny'].iloc[0])[:10], "->", str(d['timestamp_ny'].iloc[-1])[:10])

S = LS.FX_STRATS
def sig_wrap(fn, cfg, needs_arrays=False):
    if not needs_arrays:
        return lambda e,i: fn(e,i,cfg)
    def w(e,i):
        a = dict(h=e["high"].to_numpy(float), l=e["low"].to_numpy(float), o=e["open"].to_numpy(float),
                 c=e["close"].to_numpy(float), atr=e["atr50"].to_numpy(float),
                 atrp=e["atr_pctile"].to_numpy(float), htf=e["htf_bias"].to_numpy(int),
                 hrs=e["timestamp_ny"].dt.hour.to_numpy())
        return fn(a,i,cfg)
    return w

CELLS = [
 ("SPX500_DONCH", ES,  sig_wrap(LS.signal_DONCH, S["SPX500-DONCH"]), "rr"),
 ("US30_DONCH",   YM,  sig_wrap(LS.signal_DONCH, S["US30-DONCH"]),   "rr"),
 ("JPN225_DONCH", NIY, sig_wrap(LS.signal_DONCH, S["JPN225-DONCH"]), "rr"),
 ("GER40_DONCH",  DAX, sig_wrap(LS.signal_DONCH, S["GER40-DONCH"]),  "rr"),
 ("GER40_BOS",    DAX, sig_wrap(LS.signal_BOS, S["GER40-BOS"]),      "rr"),
 ("XAUUSD_BOS",   GOLD,sig_wrap(LS.signal_BOS, S["XAUUSD-BOS"]),     "rr"),
 ("XAUUSD_VCX_B", GOLD,sig_wrap(LS.signal_VCX, S["XAUUSD-VCX-B"]),   "rr"),
 ("XAUUSD_MACROSS~",GOLD,sig_wrap(LS.signal_MACROSS, S["XAUUSD-MACROSS"]), "rr"),
 ("XAUUSD_ZBPIV", G4,  sig_wrap(LS.signal_ZBPIV, S["XAUUSD-ZBPIV"]), "zb"),
 ("SPX500_ZBPIV", D1,  sig_wrap(LS.signal_ZBPIV, S["SPX500-ZBPIV"]), "zb"),
 ("XAUUSD_STRAD", GOLD,sig_wrap(LS.signal_STRAD, S["XAUUSD-STRAD"]), "strad"),
 ("EURUSD_E~",    EUR, sig_wrap(LS.signal_E, S["EURUSD-E"], True),   "e"),
 ("GBPUSD_E~",    GBP, sig_wrap(LS.signal_E, S["GBPUSD-E"], True),   "e"),
]

def simulate(e, i, kind, sig, cfg, pad_price, keep_tp_fixed):
    """Enter at bar i+1 open. Returns R measured on the WIDENED risk (dollar-normalized)."""
    if i + 2 >= len(e): return None
    o = e["open"].to_numpy(float); h = e["high"].to_numpy(float); l = e["low"].to_numpy(float)
    c = e["close"].to_numpy(float)
    entry = o[i+1]; atr = float(e["atr50"].iloc[i])
    if kind == "rr":
        d = sig.get("direction","long"); base_stop = sig["stop"]; rr = sig["rr"]
    elif kind == "zb":
        d = sig["direction"]
        base_stop = entry - sig["stop_atr"]*atr if d=="long" else entry + sig["stop_atr"]*atr
        rr = sig["rr"]
    elif kind == "strad":
        d = "long"; base_stop, width, _ = sig; rr = None; tp0 = entry + S["XAUUSD-STRAD"]["M"]*width
    elif kind == "e":
        side, stop_base, _ = sig; d = "long" if side==1 else "short"
        base_stop = stop_base; rr = 2.5
    base_risk = (entry-base_stop) if d=="long" else (base_stop-entry)
    if base_risk <= 0 or not (0.3*atr <= base_risk <= 8*atr): return None
    stop = base_stop - pad_price if d=="long" else base_stop + pad_price
    risk = (entry-stop) if d=="long" else (stop-entry)
    if kind == "strad": tp = tp0
    elif keep_tp_fixed: tp = entry + rr*base_risk if d=="long" else entry - rr*base_risk
    else:               tp = entry + rr*risk if d=="long" else entry - rr*risk
    be_at = S["EURUSD-E"]["be_r"] if kind=="e" else None
    max_hold = 96
    st = stop
    for j in range(i+1, min(i+1+max_hold, len(e))):
        if d=="long":
            if be_at and h[j] >= entry + be_at*base_risk: st = max(st, entry)
            if l[j] <= st: return (st-entry)/risk
            if h[j] >= tp: return (tp-entry)/risk
        else:
            if be_at and l[j] <= entry - be_at*base_risk: st = min(st, entry)
            if h[j] >= st: return (entry-st)/risk
            if l[j] <= tp: return (entry-tp)/risk
    return ((c[min(i+max_hold,len(e)-1)]-entry) if d=="long" else (entry-c[min(i+max_hold,len(e)-1)]))/risk

PADS = [("baseline", lambda price,atr: 0.0),
        ("+0.10xATR", lambda price,atr: 0.10*atr),
        ("+0.25xATR", lambda price,atr: 0.25*atr),
        ("+0.1%px",   lambda price,atr: 0.001*price),
        ("+0.2%px",   lambda price,atr: 0.002*price)]

print(f"\n{'cell':16s} {'variant':9s} " + "".join(f"{p[0]:>11s}" for p in PADS) + "   (n / avgR)")
summary = {}
for name, e, sigfn, kind in CELLS:
    sigs = []
    for i in range(len(e)-2):
        r = sigfn(e, i)
        if r is not None: sigs.append((i, r))
    for variant in ("rr-scaled", "tp-fixed"):
        cols = []
        for pname, pfn in PADS:
            rs = []
            for i, sg in sigs:
                price = float(e["close"].iloc[i]); atr = float(e["atr50"].iloc[i])
                rr_ = simulate(e, i, kind, sg, None, pfn(price, atr), variant == "tp-fixed")
                if rr_ is not None: rs.append(rr_)
            avg = np.mean(rs) if rs else float("nan")
            cols.append((len(rs), avg))
            summary.setdefault((variant, pname), []).append(avg*len(rs) if rs else 0)
        print(f"{name:16s} {variant:9s} " + "".join(f"{c[1]:+10.3f} " for c in cols) + f"  n={cols[0][0]}")
print("\nNote: R is measured on the widened stop (dollar risk normalized, as the live sizers do).")
