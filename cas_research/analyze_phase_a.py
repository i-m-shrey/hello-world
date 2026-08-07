"""Phase-A forensics: what changed in the 14:45-15:40 window after CAS go-live (2026-08-03).

Per session, per index series, fixed strikes ATM+/-2 (ATM anchored at the 15:00 spot),
CE and PE, computes:
  premium sub-window stats  : 15:00-15:15 / 15:15-15:30 / 15:30-15:40 net move, range, speed
  auction-match jump        : max 1-min |move| inside 15:28-15:36 vs day's 14:45-15:00 typical
  IV path                   : IV at 14:45 / 15:00 / 15:15 / 15:30 / last bar, deltas
  volume/OI migration       : per-bucket volume share, OI delta in final 10 min
  synthetic forward         : F = CE - PE + K (ATM), drift 15:15 -> last bar vs spot path
Outputs:
  reports/phase_a_session_metrics.csv   (one row per session x strike x side)
  reports/phase_a_summary.md            (pre vs post CAS aggregate comparison)
  reports/plots/*.png
"""
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
REP_DIR = os.path.join(HERE, "reports")
PLOT_DIR = os.path.join(REP_DIR, "plots")
CAS_GO_LIVE = "2026-08-03"

WINDOWS = {
    "w1500_1515": ("15:00", "15:14"),
    "w1515_1530": ("15:15", "15:29"),
    "w1530_1540": ("15:30", "15:40"),
    "ref_1445_1500": ("14:45", "14:59"),
}

STEP = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}


def load_master(series: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{series}_master.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume", "oi", "iv", "spot"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _win(df, w):
    a, b = WINDOWS[w]
    return df[(df["time_ist"] >= a) & (df["time_ist"] <= b)]


def leg_metrics(leg: pd.DataFrame, series: str, d: str, strike: float, side: str,
                offset: int) -> dict | None:
    leg = leg.sort_values("time_ist")
    if leg.empty or len(leg[leg["time_ist"] >= "15:00"]) < 5:
        return None
    r = {"series": series, "date": d, "strike": strike, "side": side, "offset": offset,
         "n_bars_1445_1540": len(leg[leg["time_ist"] >= "14:45"]),
         "last_bar": leg["time_ist"].max(),
         "has_post_1530": int((leg["time_ist"] > "15:30").any())}
    ref = _win(leg, "ref_1445_1500")
    r["ref_speed"] = ref["close"].diff().abs().mean() if len(ref) > 3 else np.nan
    r["prem_1500"] = _at(leg, "15:00")
    for w in ("w1500_1515", "w1515_1530", "w1530_1540"):
        sub = _win(leg, w)
        if len(sub) >= 2:
            c0, c1 = sub["close"].iloc[0], sub["close"].iloc[-1]
            r[f"{w}_net_pct"] = 100 * (c1 - c0) / c0 if c0 else np.nan
            r[f"{w}_range_pct"] = 100 * (sub["high"].max() - sub["low"].min()) / c0 if c0 else np.nan
            r[f"{w}_speed"] = sub["close"].diff().abs().mean()
            r[f"{w}_volume"] = sub["volume"].sum()
            r[f"{w}_oi_delta"] = sub["oi"].iloc[-1] - sub["oi"].iloc[0]
            r[f"{w}_iv_delta"] = sub["iv"].iloc[-1] - sub["iv"].iloc[0]
        else:
            for k in ("net_pct", "range_pct", "speed", "volume", "oi_delta", "iv_delta"):
                r[f"{w}_{k}"] = np.nan
    # auction-match jump 15:28-15:36
    jm = leg[(leg["time_ist"] >= "15:28") & (leg["time_ist"] <= "15:36")]
    if len(jm) >= 2 and r["ref_speed"] and not np.isnan(r["ref_speed"]) and r["ref_speed"] > 0:
        r["jump_max_1min"] = jm["close"].diff().abs().max()
        r["jump_ratio_vs_ref"] = r["jump_max_1min"] / r["ref_speed"]
    else:
        r["jump_max_1min"] = np.nan
        r["jump_ratio_vs_ref"] = np.nan
    for t, k in (("14:45", "iv_1445"), ("15:00", "iv_1500"), ("15:15", "iv_1515"),
                 ("15:30", "iv_1530")):
        r[k] = _at(leg, t, col="iv")
    last = leg.iloc[-1]
    r["iv_last"] = last["iv"]
    r["prem_last"] = last["close"]
    r["vol_total_1445_1540"] = leg[leg["time_ist"] >= "14:45"]["volume"].sum()
    return r


def _at(leg, t, col="close"):
    m = leg[leg["time_ist"] == t]
    if len(m):
        return m[col].iloc[-1]
    m = leg[(leg["time_ist"] >= t)]
    return m[col].iloc[0] if len(m) else np.nan


def session_rows(df: pd.DataFrame, series: str) -> list[dict]:
    index = series.split("_")[0]
    step = STEP[index]
    rows = []
    for d, day in df.groupby("date_ist"):
        spot_1500 = _at(day[day["option_type"] == "CE"].drop_duplicates("time_ist"),
                        "15:00", col="spot")
        if np.isnan(spot_1500):
            continue
        atm = round(spot_1500 / step) * step
        for off in (-2, -1, 0, 1, 2):
            k = atm + off * step
            for side in ("CE", "PE"):
                leg = day[(day["strike"] == k) & (day["option_type"] == side) &
                          (day["time_ist"] >= "14:40")]
                m = leg_metrics(leg, series, d, k, side, off)
                if m:
                    m["spot_1500"] = spot_1500
                    rows.append(m)
        # synthetic forward at ATM
        ce = day[(day["strike"] == atm) & (day["option_type"] == "CE")].set_index("time_ist")["close"]
        pe = day[(day["strike"] == atm) & (day["option_type"] == "PE")].set_index("time_ist")["close"]
        sp = day[(day["strike"] == atm) & (day["option_type"] == "CE")].set_index("time_ist")["spot"]
        both = pd.DataFrame({"ce": ce, "pe": pe, "spot": sp}).dropna().sort_index()
        both = both[both.index >= "14:45"]
        if len(both) > 5:
            both["synth_f"] = both["ce"] - both["pe"] + atm
            both["basis"] = both["synth_f"] - both["spot"]
            f1515 = both[both.index >= "15:15"]
            rows.append({
                "series": series, "date": d, "strike": atm, "side": "SYNTH", "offset": 0,
                "spot_1500": spot_1500,
                "synth_basis_1515": f1515["basis"].iloc[0] if len(f1515) else np.nan,
                "synth_basis_last": both["basis"].iloc[-1],
                "synth_drift_1515_last": (f1515["synth_f"].iloc[-1] - f1515["synth_f"].iloc[0])
                if len(f1515) > 1 else np.nan,
                "spot_drift_1515_last": (f1515["spot"].iloc[-1] - f1515["spot"].iloc[0])
                if len(f1515) > 1 else np.nan,
                "last_bar": both.index.max(),
            })
    return rows


def main():
    os.makedirs(REP_DIR, exist_ok=True)
    all_rows = []
    for f in sorted(os.listdir(DATA_DIR)):
        if not f.endswith("_master.csv"):
            continue
        series = f.replace("_master.csv", "")
        df = load_master(series)
        if df.empty:
            continue
        all_rows += session_rows(df, series)
    met = pd.DataFrame(all_rows)
    met["post_cas"] = (met["date"] >= CAS_GO_LIVE).astype(int)
    met["weekday"] = pd.to_datetime(met["date"]).dt.day_name()
    out = os.path.join(REP_DIR, "phase_a_session_metrics.csv")
    met.to_csv(out, index=False)
    print(f"wrote {out}: {len(met)} rows, "
          f"{met[met.post_cas == 1]['date'].nunique()} post-CAS sessions, "
          f"{met[met.post_cas == 0]['date'].nunique()} pre-CAS sessions")


if __name__ == "__main__":
    main()
