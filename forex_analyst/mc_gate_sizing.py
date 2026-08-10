"""MC GATE SIZING (July 2026) — Monte Carlo drawdown distributions for the three
new gold instances at CURRENT (2026) volatility, before any ENABLE flip.

Method = the house mc_capital.py convention exactly: build each strategy's REAL
daily $-P/L series (actual backtest trades, 2019+ so the vol regime is modern),
then 5-day block-bootstrap 4,000 x 30/60-day paths. $ risk per trade at 0.01 lot
= stop_atr x ATR x $1; evaluated at H1 ATR = $18 (mid of today's $16-20) and
stressed at $20. The 96% signal overlap is handled by CONSTRUCTION: portfolio
daily series = sum of the strategies' daily R on the same calendar days, so
stacked days stack in the paths.

Gate rule requested: the p95 30-day max drawdown must stay <= 5% of equity
-> min gate = p95(maxDD$) / 0.05. Also shown: p50/p90/p99, max consecutive-loss
streaks, and the house P(dip < $X) table.
"""
import numpy as np
import pandas as pd

import discovery_engine as DE
from discover_trend import gold_h1, donch_sig
from verify_vcx import vcx_mask
import live_signals as LS

ATR_NOW = 18.0
ATR_STRESS = 20.0
PATHS, BLOCK, SEED = 4000, 5, 42


def trades_for(key):
    g = gold_h1()
    cost = DE.COST["XAUUSD"]
    c = g["close"].to_numpy(float); atr = g["atr50"].to_numpy(float)
    if key == "DONCH_TR":
        cfg = LS.FX_STRATS["XAUUSD-DONCH-TR"]
        return DE.run_trades(g, donch_sig(g, cfg["N"]), None, cost,
                             stop_abs=c - cfg["stop_atr"] * atr,
                             trail_atr=cfg["trail_atr"], max_hold=cfg["max_hold"],
                             max_tpd=cfg["max_tpd"]), cfg["stop_atr"]
    cfg = LS.FX_STRATS[f"XAUUSD-VCX-{key[-1]}"]
    return DE.run_trades(g, vcx_mask(g, cfg), None, cost,
                         stop_abs=c - cfg["stop_atr"] * atr, rr=cfg["rr"],
                         max_hold=cfg["max_hold"], max_tpd=cfg["max_tpd"]), cfg["stop_atr"]


def daily_dollars(t, stop_atr, atr_usd):
    t = t.copy()
    t["d"] = pd.to_datetime(t["entry_ts"]).dt.date
    t = t[pd.to_datetime(t["entry_ts"]) >= "2019-01-01"]
    risk = stop_atr * atr_usd            # $ per R at 0.01 lot
    return t.groupby("d")["r"].sum() * risk, t, risk


def max_loss_streak(t):
    s, best = 0, 0
    for r in t["r"]:
        s = s + 1 if r < 0 else 0
        best = max(best, s)
    return best


def simulate(daily, days):
    v = daily.to_numpy(float)
    rs = np.random.RandomState(SEED)
    nb = days // BLOCK
    maxdd = np.empty(PATHS); ends = np.empty(PATHS)
    for p in range(PATHS):
        idx = rs.randint(0, len(v) - BLOCK, nb)
        path = np.concatenate([v[j:j + BLOCK] for j in idx])
        eq = np.cumsum(path)
        maxdd[p] = (eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min()
        ends[p] = eq[-1]
    return -maxdd, ends                  # maxdd as positive $


def main():
    print("Building actual trade series (2019+ daily $, house mc_capital convention)...")
    parts = {}
    for key in ("DONCH_TR", "VCX_A", "VCX_B"):
        t, stop_atr = trades_for(key)
        d, t19, risk = daily_dollars(t, stop_atr, ATR_NOW)
        parts[key] = dict(daily=d, trades=t19, risk=risk, stop_atr=stop_atr)
        print(f"  {key}: {len(t19)} trades 2019+, risk/trade ${risk:.0f} @ATR{ATR_NOW:.0f}, "
              f"max consecutive losses = {max_loss_streak(t19)} "
              f"(= ${max_loss_streak(t19) * risk:.0f} straight)")

    configs = {
        "DONCH_TR only": ["DONCH_TR"],
        "VCX_A only": ["VCX_A"],
        "VCX_B only": ["VCX_B"],
        "DONCH_TR + VCX_A": ["DONCH_TR", "VCX_A"],
        "DONCH_TR + VCX_B": ["DONCH_TR", "VCX_B"],
        "ALL THREE": ["DONCH_TR", "VCX_A", "VCX_B"],
    }
    print(f"\nMC: {PATHS} paths, {BLOCK}-day blocks, ATR ${ATR_NOW:.0f} "
          f"(stress ${ATR_STRESS:.0f} scales all $ by x{ATR_STRESS / ATR_NOW:.2f})\n")
    print(f"{'config':<20} {'horizon':>7} {'E[30d]':>8} {'maxDD p50':>10} {'p90':>8} "
          f"{'p95':>8} {'p99':>8} | {'gate: p95DD/5%':>15} {'@ATR20':>8}")
    recs = {}
    for name, keys in configs.items():
        combo = None
        for k in keys:
            combo = parts[k]["daily"] if combo is None else combo.add(
                parts[k]["daily"], fill_value=0.0)
        for days in (30, 60):
            dd, ends = simulate(combo, days)
            if days == 30:
                gate = np.percentile(dd, 95) / 0.05
                recs[name] = dict(gate=gate, exp=np.mean(ends),
                                  p95=np.percentile(dd, 95))
            print(f"{name:<20} {days:>6}d {np.mean(ends):>+8.0f} "
                  f"{np.percentile(dd, 50):>10.0f} {np.percentile(dd, 90):>8.0f} "
                  f"{np.percentile(dd, 95):>8.0f} {np.percentile(dd, 99):>8.0f} | "
                  f"{'$' + format(np.percentile(dd, 95) / 0.05, ',.0f') if days == 30 else '':>15} "
                  f"{'$' + format(np.percentile(dd, 95) / 0.05 * ATR_STRESS / ATR_NOW, ',.0f') if days == 30 else '':>8}")

    print("\nHouse-style dip table (30d, starting equity = the recommended gate):")
    for name, keys in configs.items():
        combo = None
        for k in keys:
            combo = parts[k]["daily"] if combo is None else combo.add(
                parts[k]["daily"], fill_value=0.0)
        E = recs[name]["gate"]
        dd, ends = simulate(combo, 30)
        print(f"  {name:<20} gate=${E:,.0f}: P(DD>5%E)={np.mean(dd > 0.05 * E) * 100:4.1f}% "
              f"P(DD>10%E)={np.mean(dd > 0.10 * E) * 100:4.1f}% "
              f"E[P&L 30d]=${np.mean(ends):+.0f}")

    print("\nMarginal value of each addition (expected 30d $ vs p95 DD $):")
    base = recs["DONCH_TR only"]
    for name in ("DONCH_TR + VCX_A", "DONCH_TR + VCX_B", "ALL THREE"):
        r = recs[name]
        print(f"  {name:<20} adds E[P&L] {r['exp'] - base['exp']:+.0f}$/30d "
              f"for extra p95 DD {r['p95'] - base['p95']:+.0f}$ "
              f"(marginal ratio {(r['exp'] - base['exp']) / max(1e-9, r['p95'] - base['p95']):+.2f})")


if __name__ == "__main__":
    main()
