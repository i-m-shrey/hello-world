"""CASE LIBRARY BUILDER v2 (July 2026) — the ANALYST's historical memory, now keyed
on the NEWS SURPRISE, not just the time slot.

v1 (case_library_builder.py) keyed explosive bars on (asset, tf, NY slot, direction,
intensity, pretrend) because no historical news feed existed. We now have a REAL
archive (news_archive.csv: ForexFactory 2007->2026, actual/forecast/previous,
validated 100% against an independent scrape on NFP+CPI). v2 therefore builds TWO
kinds of signatures into one library:

  key_type="event": one row per (asset, family, surprise bucket, first-reaction
      direction [, pretrend]). The surprise bucket comes from the POINT-IN-TIME
      z-score of (actual - forecast) within the event family — the information the
      user actually wanted the ANALYST to key on. Outcomes are measured from the
      T+5min DECISION price (first bar open at/after release+5min — the same moment
      the live bot decides), in ATR units, at +15m/+1h/+4h/+24h, plus MFE/MAE.
      cont_* = fraction of cases whose forward move continued in the direction of
      the RELEASE-BAR reaction (known at decision time).

  key_type="slot": the v1-style price-signature rows (explosive bar -> slot,
      direction, intensity, pretrend) — still needed for UNSCHEDULED shocks, and
      rebuilt here on TZ-VERIFIED loaders (event_price_lib): the v1 library was
      built with load_gold's fixed GMT+2 parse, which shifted every summer bar +1h
      and mis-slotted half the year's events.

HONESTY RULES: events without a parseable forecast get NO surprise key (they are
covered by slot rows only); n >= MIN_N or the row is dropped; nothing is imputed.

Reproducible: python case_library_builder2.py  ->  case_library.csv (+ a cached
per-event outcomes table analyst_events.parquet that analyst_replay.py reuses for
point-in-time aggregation).
"""
import os

import numpy as np
import pandas as pd

import event_price_lib as epl

ROOT = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(ROOT, "news_archive.csv")
OUT_LIB = os.path.join(ROOT, "case_library.csv")
OUT_EVENTS = os.path.join(ROOT, "analyst_events.parquet")

MIN_N = 5
HORIZONS_MIN = (15, 60, 240, 1440)
DECISION_DELAY_MIN = 5          # T+5 — mirrors analyst_bot POST_EVENT_MIN
OUT_SCALES = os.path.join(ROOT, "family_scales.csv")

EVENT_SYMBOLS = {"USD": ["XAUUSD", "EURUSD", "GBPUSD", "USDCHF", "USDCAD",
                         "SPX500", "GER40"],
                 "EUR": ["EURUSD", "GER40"], "GBP": ["GBPUSD"],
                 "CHF": ["USDCHF"], "CAD": ["USDCAD"]}


def surprise_bucket(z):
    if not np.isfinite(z):
        return None
    if z >= 1.0:
        return "big_up"
    if z >= 0.25:
        return "up"
    if z <= -1.0:
        return "big_down"
    if z <= -0.25:
        return "down"
    return "inline"


def slot_of(hour, minute, tf):
    """IDENTICAL to case_library_builder.slot_of — the bot must match this exactly."""
    if tf == "H1":
        if hour == 8:
            return "0830_data"
        if hour == 10:
            return "1000_data"
        if hour == 14:
            return "1400_fomc"
        if 2 <= hour <= 5:
            return "eu_session"
        return "other"
    t = hour * 60 + minute
    if 505 <= t <= 520:
        return "0830_data"
    if 595 <= t <= 610:
        return "1000_data"
    if 835 <= t <= 850:
        return "1400_fomc"
    if 120 <= t <= 300:
        return "eu_session"
    return "other"


def intensity_bucket(mult):
    if mult >= 10:
        return "10x+"
    if mult >= 5:
        return "5-10x"
    return "3-5x"


# ── per-event outcome rows (the raw material; cached for the replay) ─────────
def build_event_rows():
    ev = pd.read_csv(ARCHIVE)
    # mixed -04:00/-05:00 offsets -> parse via UTC then back to NY
    ev["ts_ny"] = (pd.to_datetime(ev["ts_ny"], utc=True)
                   .dt.tz_convert("America/New_York"))
    ev = ev[ev["impact"].str.contains("High", na=False)].copy()
    rows = []
    for asset_ccy, assets in EVENT_SYMBOLS.items():
        sub = ev[ev["ccy"] == asset_ccy]
        for asset in assets:
            for r in sub.itertuples():
                ts = r.ts_ny
                rx = epl.reaction_after_release(asset, ts)
                if rx is None:
                    continue
                out = epl.outcome_after(asset, ts + pd.Timedelta(minutes=DECISION_DELAY_MIN),
                                        HORIZONS_MIN)
                if out is None:
                    continue
                pan = epl.panel_at(asset, ts + pd.Timedelta(minutes=DECISION_DELAY_MIN))
                d = 1 if rx["dir"] == "up" else -1
                atr = out["atr"]
                row = dict(ts_ny=ts, asset=asset, ccy=asset_ccy, family=r.family,
                           event_raw=r.event_raw,
                           tf=epl.SOURCES[asset][0],
                           slot=slot_of(ts.hour, ts.minute, epl.SOURCES[asset][0]),
                           surprise_z=r.surprise_z,
                           surprise=surprise_bucket(r.surprise_z),
                           direction=rx["dir"],
                           react_atr=rx["move_atr"], range_mult=rx["range_mult"],
                           intensity=intensity_bucket(rx["range_mult"]),
                           pretrend=pan["pretrend"] if pan else None,
                           entry=out["entry"], atr=atr)
                for hm in HORIZONS_MIN:
                    v = out.get(f"fwd_{hm}m")
                    row[f"fwd_{_hname(hm)}"] = d * v / atr if v == v else np.nan
                row["worst_adverse_atr"] = (d * out["mae"] if d == 1 else d * out["mfe"]) / atr
                rows.append(row)
    df = pd.DataFrame(rows)
    df.to_parquet(OUT_EVENTS, index=False)
    return df


def _hname(hm):
    return {15: "15m", 60: "1h", 240: "4h", 1440: "24h"}[hm]


FWD_COLS = [f"fwd_{_hname(h)}" for h in HORIZONS_MIN]


def _agg(g):
    def cont(x):
        x = x.dropna()
        return float((x > 0).mean()) if len(x) else np.nan
    out = dict(n=len(g))
    for c in FWD_COLS:
        out[f"{c}_med"] = g[c].median()
        out[f"cont_{c[4:]}"] = cont(g[c])
    out["adverse_med"] = g["worst_adverse_atr"].median()
    out["adverse_worst"] = g["worst_adverse_atr"].min()
    return out


def aggregate_event_rows(df, cutoff=None):
    """(asset, family, surprise, direction [, pretrend]) rows. cutoff (Timestamp)
    makes it POINT-IN-TIME: only events strictly before cutoff are used."""
    if cutoff is not None:
        df = df[df["ts_ny"] < cutoff]
    df = df[df["surprise"].notna() & (df["surprise"] != "inline")]
    recs = []
    for keys, extra in ((["asset", "tf", "family", "surprise", "direction"], False),
                        (["asset", "tf", "family", "surprise", "direction",
                          "pretrend"], True)):
        for k, g in df.groupby(keys, dropna=True):
            if len(g) < MIN_N:
                continue
            r = dict(zip(keys, k)); r.update(_agg(g))
            r["key_type"] = "event"
            r["slot"] = g["slot"].mode().iat[0]
            r["intensity"] = "ALL"
            if not extra:
                r["pretrend"] = "ALL"
            recs.append(r)
    return pd.DataFrame(recs)


# ── v1-style slot rows on the verified frames ────────────────────────────────
def build_slot_rows():
    recs = []
    thresholds = {"M5": 3.0, "M15": 2.5, "H1": 2.5}
    fwd_bars = {"M5": {15: 3, 60: 12, 240: 48, 1440: 288},
                "M15": {15: 1, 60: 4, 240: 16, 1440: 96},
                "H1": {60: 1, 240: 4, 1440: 24}}
    for asset in epl.SOURCES:
        df = epl.load_frame(asset)
        tf = epl.SOURCES[asset][0]
        h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
        o = df["open"].to_numpy(float); c = df["close"].to_numpy(float)
        atr = df["atr50"].to_numpy(float)
        ts = df["timestamp_ny"]
        hrs = ts.dt.hour.to_numpy(); mins = ts.dt.minute.to_numpy()
        ema48 = pd.Series(c).ewm(span=48, adjust=False).mean().to_numpy()
        rng = h - l
        n = len(df)
        fb = fwd_bars[tf]
        maxk = max(fb.values())
        mask = np.isfinite(atr) & (atr > 0) & (rng >= thresholds[tf] * atr)
        for i in np.flatnonzero(mask):
            if i + maxk >= n:
                continue
            up = c[i] > o[i]
            d = 1 if up else -1
            row = dict(ts_ny=ts.iloc[i], asset=asset, tf=tf,
                       slot=slot_of(int(hrs[i]), int(mins[i]), tf),
                       direction="up" if up else "dn",
                       intensity=intensity_bucket(rng[i] / atr[i]),
                       pretrend="bull" if c[i] > ema48[i] else "bear")
            for hm, k in fb.items():
                row[f"fwd_{_hname(hm)}"] = d * (c[i + k] - c[i]) / atr[i]
            for hm in HORIZONS_MIN:
                row.setdefault(f"fwd_{_hname(hm)}", np.nan)
            lastk = fb[max(fb)]
            adverse = (min(l[i + 1:i + lastk + 1].min(), c[i]) - c[i]) if up else \
                      -(max(h[i + 1:i + lastk + 1].max(), c[i]) - c[i])
            row["worst_adverse_atr"] = adverse / atr[i]
            recs.append(row)
    return pd.DataFrame(recs)


def aggregate_slot_rows(df, cutoff=None):
    if cutoff is not None:
        df = df[df["ts_ny"] < cutoff]
    recs = []
    for keys, fine in ((["asset", "tf", "slot", "direction"], False),
                       (["asset", "tf", "slot", "direction", "intensity",
                         "pretrend"], True)):
        for k, g in df.groupby(keys, dropna=True):
            if len(g) < MIN_N:
                continue
            r = dict(zip(keys, k)); r.update(_agg(g))
            r["key_type"] = "slot"
            r["family"] = "ANY"; r["surprise"] = "ALL"
            if not fine:
                r["intensity"] = "ALL"; r["pretrend"] = "ALL"
            recs.append(r)
    return pd.DataFrame(recs)


COL_ORDER = ["key_type", "asset", "tf", "family", "surprise", "slot", "direction",
             "intensity", "pretrend", "n",
             *[f"{c}_med" for c in FWD_COLS], *[f"cont_{c[4:]}" for c in FWD_COLS],
             "adverse_med", "adverse_worst"]


def build_library(event_rows=None, slot_rows=None, cutoff=None):
    if event_rows is None:
        event_rows = (pd.read_parquet(OUT_EVENTS) if os.path.exists(OUT_EVENTS)
                      else build_event_rows())
    if slot_rows is None:
        slot_rows = build_slot_rows()
    lib = pd.concat([aggregate_event_rows(event_rows, cutoff),
                     aggregate_slot_rows(slot_rows, cutoff)], ignore_index=True)
    lib = lib[COL_ORDER].round(4).sort_values(
        ["key_type", "asset", "family", "n"], ascending=[True, True, True, False])
    return lib.reset_index(drop=True)


def main():
    ev = build_event_rows()
    print(f"event rows: {len(ev)} scored (from the archive x affected assets)")
    write_family_scales()
    sl = build_slot_rows()
    print(f"slot rows: {len(sl)} explosive bars")
    sl.to_parquet(os.path.join(ROOT, "analyst_slot_events.parquet"), index=False)
    lib = build_library(ev, sl)
    lib.to_csv(OUT_LIB, index=False)
    ne = (lib.key_type == "event").sum()
    print(f"case_library.csv: {len(lib)} signatures ({ne} event-keyed, "
          f"{len(lib) - ne} slot-keyed)")
    print("\nSAMPLE — gold, CPI m/m, big upside surprise:")
    q = lib[(lib.asset == "XAUUSD") & (lib.family == "CPI_MM")]
    cols = ["surprise", "direction", "pretrend", "n", "cont_15m", "cont_1h",
            "cont_4h", "fwd_1h_med", "adverse_worst"]
    print(q[cols].head(12).to_string(index=False))
    print("\nSAMPLE — gold slot rows (0830, up):")
    q2 = lib[(lib.key_type == "slot") & (lib.asset == "XAUUSD")
             & (lib.slot == "0830_data") & (lib.direction == "up")]
    print(q2[["intensity", "pretrend", "n", "cont_15m", "cont_1h", "cont_4h"]]
          .head(8).to_string(index=False))


def write_family_scales():
    """Per-(ccy, family) std of (actual - forecast) over the full archive — the
    live bot's z-scale for fresh surprises (forward use only: no lookahead)."""
    arch = pd.read_csv(ARCHIVE)
    g = (arch.dropna(subset=["surprise"])
         .groupby(["ccy", "family"])["surprise"]
         .agg(scale="std", n="size").reset_index())
    g = g[(g["n"] >= 8) & (g["scale"] > 0)]
    g.round(6).to_csv(OUT_SCALES, index=False)
    print(f"family_scales.csv: {len(g)} (ccy, family) scales")


if __name__ == "__main__":
    main()
