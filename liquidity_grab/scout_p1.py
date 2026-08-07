"""scout_p1.py — GBPUSD H1 opposing-FVG reversal (P1) reimplementation, plus gold
H4 DONCH-TR exploration cells. Produces the numbers quoted in SCOUT.md §3.

P1 rules transcribed from live_signals.signal_P1 (capy/tz-audit-discovery):
displacement FVG one way, opposing displacement FVG within L bars whose close
breaks the prior 20-bar swing -> LIMIT entry at the near edge of the FVG-overlap
zone (wait bars for the retrace fill), stop beyond the far edge +0.1*ATR,
TP = rr*risk, max_hold from fill, max 2/day. The limit-fill executor here is a
faithful reimplementation (gap-through fills at the open; same-bar stop counts
against the trade); the official ict_patterns_lab validation remains primary.
"""
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg
from multi_asset import load_pair
from strategy_scout import frame, run_trades, stats


def p1_trades(d, cost, L=30, wait=30, disp=1.2, rr=2.0, max_hold=60, max_tpd=2):
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    o = d["open"].to_numpy(float); c = d["close"].to_numpy(float)
    a = d["atr50"].to_numpy(float); n = len(d)
    hrs = d["timestamp_ny"].dt.hour.to_numpy()
    ts = d["timestamp_ny"].to_numpy()
    yrs = d["year"].to_numpy(int); dates = d["ny_date"].to_numpy()
    bullF = np.zeros(n, bool); bearF = np.zeros(n, bool)
    for t in range(2, n):
        if not np.isfinite(a[t]):
            continue
        if (h[t - 1] - l[t - 1]) >= disp * a[t]:
            if l[t] > h[t - 2]:
                bullF[t] = True
            if h[t] < l[t - 2]:
                bearF[t] = True
    last_bull = -10**9; last_bear = -10**9
    trades = []; tpd = {}; busy = -1
    for i in range(25 + L, n):
        sig = None
        if hrs[i] != 17 and np.isfinite(a[i]):
            # SELL: bear FVG at i (top=l[i-2], bottom=h[i]) after bull FVG at b
            # (top=l[b], bottom=h[b-2]) within L; close below prior swing low.
            if bearF[i] and 0 < i - last_bull <= L:
                b = last_bull
                if c[i] < np.min(l[b - 22: b - 2]):
                    z_lo = max(h[i], h[b - 2]); z_hi = min(l[i - 2], l[b])
                    if z_hi > z_lo:
                        sig = ("short", z_lo, z_hi + 0.1 * a[i])
            # BUY mirror: bull FVG at i after bear FVG at b; close above swing hi.
            if sig is None and bullF[i] and 0 < i - last_bear <= L:
                b = last_bear
                if c[i] > np.max(h[b - 22: b - 2]):
                    z_lo = max(h[i - 2], h[b]); z_hi = min(l[i], l[b - 2])
                    if z_hi > z_lo:
                        sig = ("long", z_hi, z_lo - 0.1 * a[i])
        if bullF[i]:
            last_bull = i
        if bearF[i]:
            last_bear = i
        if sig is None:
            continue
        side = -1 if sig[0] == "short" else 1
        limit, stop_base = sig[1], sig[2]
        fill = None
        for j in range(i + 1, min(i + 1 + wait, n)):
            if j <= busy:
                continue
            if (side == -1 and h[j] >= limit) or (side == 1 and l[j] <= limit):
                fill = j
                break
        if fill is None:
            continue
        day = dates[fill]
        if tpd.get(day, 0) >= max_tpd or fill <= busy:
            continue
        entry = limit + side * cost / 2
        if side == -1 and o[fill] > limit:
            entry = o[fill] + cost / 2
        if side == 1 and o[fill] < limit:
            entry = o[fill] - cost / 2
        stop = stop_base - side * cost / 2
        risk = side * (entry - stop)
        if risk <= 0 or not np.isfinite(risk):
            continue
        target = entry + side * rr * risk
        xpx = None; xj = None
        for j in range(fill, min(fill + max_hold, n)):
            if side == 1:
                if l[j] <= stop:
                    xpx, xj = stop, j; break
                if h[j] >= target:
                    xpx, xj = target, j; break
            else:
                if h[j] >= stop:
                    xpx, xj = stop, j; break
                if l[j] <= target:
                    xpx, xj = target, j; break
        if xj is None:
            xj = min(fill + max_hold, n) - 1
            xpx = c[xj]
        pnl = side * (xpx - entry) - cost / 2
        trades.append((ts[fill], ts[xj], side, pnl / risk, yrs[fill]))
        tpd[day] = tpd.get(day, 0) + 1
        busy = xj
    return pd.DataFrame(trades,
                        columns=["entry_ts", "exit_ts", "side", "r", "year"])


def main():
    gbp = frame(load_pair("GBPUSD"), 60)
    print("GBPUSD H1 P1 (official 18.5y: +42R PF1.91 WR49 cost-immune) — "
          "2016+ Dukascopy:")
    for m in (1.0, 2.0, 3.0):
        t = p1_trades(gbp, 0.00010 * m)
        s = stats(t)
        print(f"  [{m:.0f}x] n={s.get('n', 0)} net={s.get('net', 0):+.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} "
              f"wr={s.get('wr', float('nan')):.2f} tr={s.get('tr', 0):+.1f} "
              f"ho={s.get('ho', 0):+.1f} yrs+={s.get('yrs_pos', '-')}")
        if m == 1.0:
            t.to_csv("scout_gbp_p1_trades.csv", index=False)

    g = frame(lg.load_m1(), 240)
    print("\nXAUUSD DONCH-TR twins on H4 (exploration cells, not official):")
    for N, mh in ((24, 48), (96, 192)):
        hiN = g["high"].shift(1).rolling(N).max().to_numpy(float)
        atr = g["atr50"].to_numpy(float)
        sig = g["close"].to_numpy(float) > hiN + 0.1 * atr
        sa = g["close"].to_numpy(float) - 2.0 * atr
        t = run_trades(g, sig, None, 0.23, stop_abs=sa, trail_atr=5.0,
                       max_hold=mh, max_tpd=2)
        s = stats(t)
        print(f"  H4 N={N}: n={s.get('n', 0)} net={s.get('net', 0):+.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} tr={s.get('tr', 0):+.1f} "
              f"ho={s.get('ho', 0):+.1f} yrs+={s.get('yrs_pos', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
