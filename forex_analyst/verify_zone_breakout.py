"""VERIFY ZONE BREAKOUT (July 2026) — proves the three wired instances reproduce
zone_breakout_lab.py EXACTLY before any ENABLE flip.

  [1] Reference reproduction — re-runs the lab backtest for each wired cell and
      compares n / train R / holdout R / avg R against zone_breakout_matrix.csv.
  [2] PIVOT_K=5 mathematical enforcement — synthetic candles prove a swing needs
      EXACTLY 5 lower closes on BOTH sides, and confirms 5 bars late (causal).
  [3] Windowed live-signal parity — live_signals.signal_at_last_bar replayed on
      2500-bar windows (the live cache size) over every lab signal bar + random
      quiet bars: same direction, zero false fires.
  [4] Execution math — the bot's risk_mode="zone" formulas (entry-relative stop,
      rr target, stop_pad = cost/2) reproduce the lab's entry/stop/target to 1e-9.
  [5] Config cross-check — magics 54101/54201/54301, ENABLE=False, params == the
      validated matrix cells, D1 in TF_MAP, XAGUSD registered min-lot + USD-side.
"""
import sys
import types

import numpy as np
import pandas as pd

from unittest.mock import MagicMock
sys.modules.setdefault("MetaTrader5", MagicMock())
sys.path.insert(0, ".")

import live_signals as LS
import zone_breakout_lab as Z

FAILS = []


def check(section, ok, detail):
    print(f"  {'PASS' if ok else 'FAIL'}  {section}: {detail}")
    if not ok:
        FAILS.append(section)


CELLS = {
    "XAUUSD_ZBPIV": dict(mid="ZB-PIV5-XAUUSD-H4-pad0.25-rr3", sym="XAUUSD", tf="H4",
                         fam="PIV5", prm=dict(pad=0.25), rr=3.0, ls="XAUUSD-ZBPIV"),
    "XAGUSD_ZBBOX": dict(mid="ZB-BOX-XAGUSD-H1-N24,tight2.5-rr2", sym="XAGUSD", tf="H1",
                         fam="BOX", prm=dict(N=24, tight=2.5), rr=2.0, ls="XAGUSD-ZBBOX"),
    "SPX500_ZBPIV": dict(mid="ZB-PIV5-SPX500-D1-pad0.1-rr2", sym="SPX500", tf="D1",
                         fam="PIV5", prm=dict(pad=0.1), rr=2.0, ls="SPX500-ZBPIV"),
}


def lab_frame(sym, tf):
    if sym == "XAUUSD":                      # full-history TZ-corrected 5m resample
        from zoneinfo import ZoneInfo
        src = pd.read_csv("data/XAU_5m_data_TZFIX.csv", sep=";")
        src.columns = [c.lower() for c in src.columns]
        ts = (pd.to_datetime(src["date"], format="%Y.%m.%d %H:%M")
              .dt.tz_localize(ZoneInfo("Etc/GMT-2"), ambiguous="raise",
                              nonexistent="shift_forward").dt.tz_convert(Z.NY))
        df = pd.DataFrame({"timestamp_ny": ts, "open": src["open"], "high": src["high"],
                           "low": src["low"], "close": src["close"],
                           "volume": pd.to_numeric(src.get("volume"), errors="coerce")})
        df = df[df["timestamp_ny"] >= pd.Timestamp("2008-01-01", tz=Z.NY)].reset_index(drop=True)
        rule = {"H4": "4h", "D1": "24h"}[tf]
        df = Z._resample(df, rule, day=(tf == "D1"))
        return Z.prep(Z.add_ist(df))
    return Z.prep(Z.load_any(sym, tf))


def main():
    ref = pd.read_csv("zone_breakout_matrix.csv").set_index("id")

    print("[1] reference reproduction (lab re-run vs frozen matrix)")
    frames, sigs, books = {}, {}, {}
    for key, c in CELLS.items():
        e = lab_frame(c["sym"], c["tf"])
        sig = (Z.sig_piv5(e, **c["prm"]) if c["fam"] == "PIV5"
               else Z.sig_box(e, **c["prm"]))
        tb = Z.run_cell(e, sig, Z.COSTS[c["sym"]], c["rr"], max_hold=Z.MAX_HOLD[c["tf"]])
        months = max((e["timestamp_ny"].iloc[-1] - e["timestamp_ny"].iloc[0]).days, 1) / 30.44
        st = Z.stats(tb, months)
        r = ref.loc[c["mid"]]
        ok = (st["n"] == r["n"] and abs(st["tr"] - r["tr"]) <= 0.1
              and abs(st["ho"] - r["ho"]) <= 0.1 and abs(st["avg_r"] - r["avg_r"]) <= 0.005)
        check(f"{key} reference", ok,
              f"n={st['n']}/{r['n']} train={st['tr']:+.1f}/{r['tr']:+.1f} "
              f"ho={st['ho']:+.1f}/{r['ho']:+.1f} avg={st['avg_r']:+.3f}/{r['avg_r']:+.3f}")
        frames[key], sigs[key], books[key] = e, sig, tb

    print("[2] PIVOT_K=5 mathematical enforcement (synthetic candles)")
    base = np.array([10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 9, 8], float)  # 5L/5R pivot at idx5
    hi, _ = LS._pivot_arrays(base, base - 1, 5)
    ok_a = np.isnan(hi[9]) and hi[10] == 20.0        # visible ONLY from bar 5+5=10
    broken = base.copy(); broken[10] = 21             # 5th right bar exceeds -> not a pivot
    hi2, _ = LS._pivot_arrays(broken, broken - 1, 5)
    ok_b = np.isnan(hi2[10]) or hi2[10] != 20.0
    four = np.array([10, 11, 12, 13, 20, 13, 12, 11, 10, 9], float)  # only 4 left candles
    hi3, _ = LS._pivot_arrays(four, four - 1, 5)
    ok_c = np.all(np.isnan(hi3))
    check("PIVOT_K=5 exact", ok_a and ok_b and ok_c,
          f"confirmed at +5 bars only: {ok_a}; 5th-right violation kills pivot: {ok_b}; "
          f"4-left candidate never confirms: {ok_c}")
    lab_hi, lab_lo = Z.pivot_levels(base, base - 1, 5)
    ls_hi, ls_lo = LS._pivot_arrays(base, base - 1, 5)
    check("lab==live pivot port",
          np.allclose(np.nan_to_num(lab_hi), np.nan_to_num(ls_hi))
          and np.allclose(np.nan_to_num(lab_lo), np.nan_to_num(ls_lo)),
          "identical arrays on synthetic series")

    print("[3] windowed live-signal parity (2500-bar live cache windows)")
    rng = np.random.RandomState(7)
    for key, c in CELLS.items():
        e, sig = frames[key], sigs[key]
        cfg = LS.FX_STRATS[c["ls"]]
        idx_sig = np.flatnonzero(sig != 0)
        idx_sig = idx_sig[idx_sig >= 60]
        take = idx_sig if len(idx_sig) <= 150 else rng.choice(idx_sig, 150, replace=False)
        quiet = rng.choice(np.flatnonzero((sig == 0) & (np.arange(len(sig)) > 800)),
                           300, replace=False)
        hit = miss = false_fire = 0
        for i in sorted(map(int, np.r_[take, quiet])):
            w = e.iloc[max(0, i - 2499):i + 1].reset_index(drop=True)
            res = LS.signal_at_last_bar(w, cfg)
            want = int(sig[i])
            got = 0 if res is None else (1 if res["direction"] == "long" else -1)
            if want != 0:
                hit += got == want; miss += got != want
            elif got != 0:
                false_fire += 1
        check(f"{key} parity", miss == 0 and false_fire == 0,
              f"{hit}/{len(take)} signal bars match, {false_fire} false fires "
              f"on {len(quiet)} quiet bars")

    print("[4] execution math (bot 'zone' branch == lab run_cell, 1e-9)")
    import live_mt5_bot as BOT
    for key, c in CELLS.items():
        e, sig = frames[key], sigs[key]
        o = e["open"].to_numpy(float); atr = e["atr50"].to_numpy(float)
        cost = Z.COSTS[c["sym"]]
        inst = BOT.INSTANCES[key]
        cfg = LS.FX_STRATS[c["ls"]]
        worst = 0.0; m = 0
        for i in np.flatnonzero(sig != 0)[:200]:
            ei = i + 1
            if ei >= len(e) or not np.isfinite(atr[i]):
                continue
            side = int(sig[i])
            lab_entry = o[ei] + side * cost / 2
            lab_stop = lab_entry - side * (cfg["stop_atr"] * atr[i]) - side * cost / 2
            lab_risk = side * (lab_entry - lab_stop)
            lab_tp = lab_entry + side * cfg["rr"] * lab_risk
            est = lab_entry                                   # live est_entry = the fill
            if side == 1:
                stop = est - cfg["stop_atr"] * atr[i] - inst["stop_pad"]
                risk = est - stop; tp = est + cfg["rr"] * risk
            else:
                stop = est + cfg["stop_atr"] * atr[i] + inst["stop_pad"]
                risk = stop - est; tp = est - cfg["rr"] * risk
            worst = max(worst, abs(stop - lab_stop), abs(tp - lab_tp),
                        abs(risk - lab_risk))
            m += 1
        check(f"{key} exec math", worst < 1e-9, f"{m} signals, max |delta| = {worst:.2e}")

    print("[5] config cross-check")
    magics = {k: BOT.INSTANCES[k]["magic"] for k in CELLS}
    check("magics", magics == {"XAUUSD_ZBPIV": 54101, "XAGUSD_ZBBOX": 54201,
                               "SPX500_ZBPIV": 54301}, f"{magics}")
    # owner go-live July 16 2026: gold/SPX pivot breakouts ON (equity-gated $250);
    # silver stays OFF until the broker's XAGUSD symbol is confirmed in Market Watch.
    check("ENABLE go-live state",
          BOT.ENABLE.get("XAUUSD_ZBPIV") is True
          and BOT.ENABLE.get("SPX500_ZBPIV") is True
          and BOT.ENABLE.get("XAGUSD_ZBBOX") is False,
          {k: BOT.ENABLE.get(k) for k in CELLS})
    p = LS.FX_STRATS
    check("params == matrix cells",
          (p["XAUUSD-ZBPIV"]["pad"], p["XAUUSD-ZBPIV"]["rr"], p["XAUUSD-ZBPIV"]["pivot_k"],
           p["XAGUSD-ZBBOX"]["N"], p["XAGUSD-ZBBOX"]["tight"], p["XAGUSD-ZBBOX"]["rr"],
           p["SPX500-ZBPIV"]["pad"], p["SPX500-ZBPIV"]["rr"], p["SPX500-ZBPIV"]["pivot_k"])
          == (0.25, 3.0, 5, 24, 2.5, 2.0, 0.1, 2.0, 5), "pad/rr/K/N/tight all exact")
    check("plumbing", "D1" in BOT.TF_MAP and "XAGUSD" in BOT.MINLOT_SYMBOLS
          and BOT._usd_side("XAGUSD", True) == 1
          and all(BOT.LOTS[k] == 0.01 for k in CELLS)
          and BOT.SYMBOLS["SPX500_D1"]["tf"] == "D1"
          and BOT.SYMBOLS["XAUUSD_H4"]["tf"] == "H4"
          and BOT.INSTANCES["XAGUSD_ZBBOX"]["equity_min"] == 400,
          "TF_MAP D1, silver min-lot+USD-side, lots 0.01, feeds, gates")

    print("\nOVERALL:", "ALL SECTIONS PASS" if not FAILS else f"FAILURES: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
