"""NEWS ARCHIVE BUILDER (July 2026) — real historical economic calendar, normalized.

Source: ForexFactory weekly calendar pages scraped year-by-year (forexfactory-go,
UTC-visual scrape). RAW FACT about those files, verified against known releases
(2024-07-05 NFP 08:30 actual 206K forecast 191K prev 218K; ADP 2024-07-03 08:15;
Spanish PMI 03:15 NY): the timestamp's NAIVE component is the event's
America/New_York local time (the trailing 'Z' the tool writes is a labeling bug).
We therefore parse the naive component and localize it to America/New_York.

Output: news_archive.csv — one row per calendar event:
  ts_ny, ccy, impact, event_raw, family, actual, forecast, previous,
  surprise, surprise_z, surprise_dir

HONESTY RULES (non-negotiable):
- actual/forecast/previous are used exactly as scraped; no imputation, ever.
- rows whose values cannot be parsed keep NaN and are excluded from surprise
  keying (they remain in the archive, keyed on slot only).
- surprise_z is POINT-IN-TIME: the z-scale for an event released at time T uses
  only surprises of the same family released BEFORE T (expanding window,
  min 8 prior observations). No lookahead.
"""
import glob
import os
import re

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.environ.get("FF_RAW_DIR", "/home/newsarchive")
OUT = os.path.join(ROOT, "news_archive.csv")

CCYS = {"USD", "EUR", "GBP", "CHF", "CAD"}

# ── event-family normalization ────────────────────────────────────────────────
# (regex on the raw FF title, per currency; first match wins). Families group
# releases whose surprises are comparable so the z-scale means something.
FAMILY_RULES = [
    # US employment
    (r"^Non-Farm Employment Change$", "NFP"),
    (r"^ADP Non-Farm Employment Change$", "ADP"),
    (r"^Unemployment Claims$", "CLAIMS"),
    (r"^Unemployment Rate$", "UNRATE"),
    (r"^Average Hourly Earnings", "AHE"),
    # inflation
    (r"^(CPI|Core CPI) m/m$", "CPI_MM"),
    (r"^(CPI|Core CPI|CPI Median|Trimmed|Common CPI) y/y$", "CPI_YY"),
    (r"^(PPI|Core PPI) m/m$", "PPI_MM"),
    (r"^Core PCE Price Index m/m$", "PCE_MM"),
    (r"Flash.*CPI|CPI Flash", "CPI_FLASH"),
    # activity
    (r"^(Core )?Retail Sales m/m$", "RETAIL"),
    (r"^(Advance|Prelim|Final) GDP q/q$", "GDP"),
    (r"^GDP m/m$", "GDP_MM"),
    (r"^ISM Manufacturing PMI$", "ISM_MFG"),
    (r"^ISM (Non-Manufacturing|Services) PMI$", "ISM_SVC"),
    (r"Flash (Manufacturing|Services) PMI", "PMI_FLASH"),
    (r"^Consumer Confidence$|^CB Consumer Confidence$", "CONF"),
    (r"^(Prelim|Revised) UoM Consumer Sentiment$", "UOM"),
    (r"^Durable Goods|^Core Durable Goods", "DURABLES"),
    (r"^Employment Change$", "EMP_CHANGE"),          # CAD monthly jobs
    (r"^Claimant Count Change$", "CLAIMANT"),        # GBP jobs
    # central banks — rate decisions & statements/pressers
    (r"^Federal Funds Rate$", "FOMC_RATE"),
    (r"^FOMC (Statement|Press Conference)$|^FOMC Meeting Minutes$", "FOMC_COMM"),
    (r"^Main Refinancing Rate$", "ECB_RATE"),
    (r"^ECB Press Conference$|^Monetary Policy Statement$", "ECB_COMM"),
    (r"^Official Bank Rate$", "BOE_RATE"),
    (r"^(MPC|BOE).*|^Monetary Policy Summary$", "BOE_COMM"),
    (r"^(SNB )?(Libor Rate|Policy Rate)$", "SNB_RATE"),
    (r"^SNB (Monetary Policy Assessment|Press Conference)$", "SNB_COMM"),
    (r"^Overnight Rate$", "BOC_RATE"),
    (r"^BOC (Rate Statement|Press Conference|Monetary Policy Report)$", "BOC_COMM"),
    (r"Fed Chair|Chair.*(Testifies|Speaks)|Powell|Yellen|Bernanke", "FED_SPEAK"),
    (r"President.*Speaks|Draghi|Lagarde|Trichet", "ECB_SPEAK"),
    (r"Governor.*Speaks|Bailey|Carney|King ", "BOE_SPEAK"),
    # misc high-impact
    (r"^Trade Balance$", "TRADE"),
    (r"^Building Permits$|^Housing Starts$", "HOUSING"),
    (r"^Pending Home Sales|^Existing Home Sales|^New Home Sales", "HOMESALES"),
    (r"^Crude Oil Inventories$", "CRUDE"),
]
_FAMILY_COMPILED = [(re.compile(p, re.I), f) for p, f in FAMILY_RULES]


def family_of(title: str) -> str:
    t = (title or "").strip()
    for rx, fam in _FAMILY_COMPILED:
        if rx.search(t):
            return fam
    return "OTHER"


_NUM_RX = re.compile(r"^\s*(<|>)?\s*(-?\d+(?:\.\d+)?)\s*(%|K|M|B|T)?\s*$", re.I)
_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "%": 1.0, None: 1.0, "": 1.0}


def parse_val(v):
    """'206K' -> 206000.0, '0.3%' -> 0.3, '<0.25%' -> 0.25, '' -> NaN.
    Never guesses: anything unparseable returns NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return np.nan
    m = _NUM_RX.match(s)
    if not m:
        return np.nan
    return float(m.group(2)) * _MULT[(m.group(3) or "").upper() or None]


def load_raw():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "ff_*.csv")))
    if not files:
        raise SystemExit(f"no ff_*.csv found in {RAW_DIR}")
    parts = []
    for f in files:
        df = pd.read_csv(f, dtype=str)
        parts.append(df)
    raw = pd.concat(parts, ignore_index=True)
    # naive component == NY local time (verified; see module docstring)
    naive = pd.to_datetime(raw["date"].str.replace(r"Z$|[+-]\d{2}:\d{2}$", "", regex=True),
                           format="%Y-%m-%dT%H:%M:%S", errors="coerce")
    raw["ts_ny"] = naive.dt.tz_localize("America/New_York", ambiguous="NaT",
                                        nonexistent="NaT")
    raw = raw.dropna(subset=["ts_ny"])
    raw = raw[raw["currency"].isin(CCYS)]
    raw = raw[~(raw["all_day"].astype(str).str.lower() == "true")]
    raw = raw.drop_duplicates(subset=["ts_ny", "currency", "title"])
    return raw


def main():
    raw = load_raw().reset_index(drop=True)
    df = pd.DataFrame({
        "ts_ny": raw["ts_ny"],          # keep the tz-aware Series (never .values —
                                        # numpy strips the tz and rebases to UTC)
        "ccy": raw["currency"],
        "impact": raw["impact"].fillna("None"),
        "event_raw": raw["title"],
    })
    df["family"] = [family_of(t) for t in df["event_raw"]]
    for col_src, col in (("actual", "actual"), ("forecast", "forecast"),
                         ("previous", "previous")):
        df[col] = [parse_val(v) for v in raw[col_src]]
    df = df.sort_values("ts_ny").reset_index(drop=True)
    df["surprise"] = df["actual"] - df["forecast"]

    # point-in-time z: expanding std of PRIOR surprises within (ccy, family)
    df["surprise_z"] = np.nan
    for (ccy, fam), g in df.groupby(["ccy", "family"]):
        s = g["surprise"]
        prior_std = s.expanding().std().shift(1)
        prior_n = s.notna().expanding().sum().shift(1)
        z = s / prior_std
        z[(prior_n < 8) | ~np.isfinite(z)] = np.nan
        df.loc[g.index, "surprise_z"] = z
    df["surprise_dir"] = np.select(
        [df["surprise_z"] > 0.25, df["surprise_z"] < -0.25,
         df["surprise_z"].notna()],
        ["up", "down", "inline"], default="unknown")

    df.to_csv(OUT, index=False)
    hi = df[df["impact"].str.contains("High", na=False)]
    print(f"news_archive.csv: {len(df)} events "
          f"({df.ts_ny.min()} -> {df.ts_ny.max()}), high-impact {len(hi)}")
    print(f"with forecast+actual: {df['surprise'].notna().sum()} "
          f"| with point-in-time z: {df['surprise_z'].notna().sum()}")
    print("\nhigh-impact family counts (top 25):")
    print(hi["family"].value_counts().head(25).to_string())
    print("\nrelease-minute sanity (high-impact USD, NY time):")
    print(hi[hi.ccy == "USD"]["ts_ny"].dt.strftime("%H:%M")
          .value_counts().head(8).to_string())


if __name__ == "__main__":
    main()
