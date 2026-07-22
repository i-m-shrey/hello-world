"""LIQUIDITY GRAB — reproducible XAUUSD M1 data fetch (Dukascopy, July 2026).

Downloads XAUUSD 1-minute candles from Dukascopy via dukascopy-node in YEARLY
chunks with retries:

  npx -y dukascopy-node -i xauusd -from YYYY-MM-DD -to YYYY-MM-DD -t m1 -f csv -v true

Facts verified on this VM (2026-07-22):
  * CSV columns: timestamp,open,high,low,close,volume ; timestamp = epoch
    MILLISECONDS UTC, bar labelled by OPEN time.
  * -from inclusive, -to EXCLUSIVE (2008-01-01..2009-01-01 -> last bar
    2008-12-31 23:56 UTC).
  * WITHOUT `-v true`, dukascopy-node PADS closed/tickless minutes with flat
    o=h=l=c candles carried at the last close (2024: 441,810 rows padded vs
    355,892 real, zero volume==0 rows in the -v file; the whole closed
    Sat-17:00->Sun-17:00 NY day arrives as 100% flat filler). `-v true` emits
    only real bars -> it is MANDATORY here; the lab refuses padded input.
  * BID series is the default; ASK series via `-p ask` (used to measure the
    real M1 spread distribution over the recent years).
  * 2008 is dense (~440k real M1 bars) -> earliest year probe starts at 2008
    and walks FORWARD only if a year comes back empty/sparse.

Output (NOT committed — see .gitignore):
  data/download/xauusd-m1-bid-<from>-<to>.csv    2008..2026-07-22 (exclusive)
  data/download/xauusd-m1-ask-<from>-<to>.csv    2024..2026-07-22 (spread audit)

Usage:  python3 download_data.py            (idempotent; skips complete files)
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")            # gitignored
DL = os.path.join(DATA, "download")
FIRST_YEAR = 2008                            # probe start (walk forward if sparse)
END = "2026-07-22"                           # exclusive -> includes 2026-07-21
ASK_FIRST_YEAR = 2024                        # >=2 recent years of ASK for spread
MIN_ROWS_FULL_YEAR = 50_000                  # a real year has ~370k+ M1 bars
RETRIES = 3


def fetch(frm: str, to: str, price: str) -> str | None:
    """One dukascopy-node chunk with retries. Returns csv path or None."""
    name = f"xauusd-m1-{price}-{frm}-{to}.csv"
    path = os.path.join(DL, name)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        print(f"  keep   {name} ({os.path.getsize(path)/1e6:.1f} MB)")
        return path
    cmd = ["npx", "-y", "dukascopy-node", "-i", "xauusd", "-from", frm, "-to", to,
           "-t", "m1", "-f", "csv", "-v", "true"]
    if price != "bid":
        cmd += ["-p", price]
    for attempt in range(1, RETRIES + 1):
        try:
            r = subprocess.run(cmd, cwd=DATA, capture_output=True, text=True,
                               timeout=900)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                rows = sum(1 for _ in open(path)) - 1
                print(f"  fetch  {name}: {rows} rows (attempt {attempt})")
                return path
            print(f"  empty  {name} attempt {attempt}: rc={r.returncode} "
                  f"{(r.stderr or r.stdout)[-200:].strip()}")
        except subprocess.TimeoutExpired:
            print(f"  timeout {name} attempt {attempt}")
        time.sleep(5 * attempt)
    return None


def rows_in(path: str) -> int:
    return sum(1 for _ in open(path)) - 1


def main() -> int:
    os.makedirs(DL, exist_ok=True)
    # ── probe earliest year (walk forward while empty/sparse) ────────────────
    start_year = None
    for y in range(FIRST_YEAR, 2015):
        p = fetch(f"{y}-01-01", f"{y + 1}-01-01", "bid")
        if p and rows_in(p) >= MIN_ROWS_FULL_YEAR:
            start_year = y
            print(f"earliest clean year: {y} ({rows_in(p)} rows)")
            break
        print(f"  {y}: empty/sparse -> walking forward")
    if start_year is None:
        print("FATAL: no dense year found in probe range", file=sys.stderr)
        return 1
    # ── bid, yearly chunks ───────────────────────────────────────────────────
    failed = []
    for y in range(start_year + 1, 2026):
        if fetch(f"{y}-01-01", f"{y + 1}-01-01", "bid") is None:
            failed.append(("bid", y))
    if fetch("2026-01-01", END, "bid") is None:
        failed.append(("bid", 2026))
    # ── ask, recent years (spread measurement) ───────────────────────────────
    for y in range(ASK_FIRST_YEAR, 2026):
        if fetch(f"{y}-01-01", f"{y + 1}-01-01", "ask") is None:
            failed.append(("ask", y))
    if fetch("2026-01-01", END, "ask") is None:
        failed.append(("ask", 2026))
    if failed:
        print(f"FAILED chunks after {RETRIES} retries: {failed}", file=sys.stderr)
        return 1
    print("all chunks complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
