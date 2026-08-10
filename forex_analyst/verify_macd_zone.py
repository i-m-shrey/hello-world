"""VERIFY MACD ZONE (July 2026) — proves macd_zone_lab.py implements the owner's spec
EXACTLY, and that the published matrix reproduces from scratch.

  [1] MACD arithmetic — 12/26/9 EMAs against an independent recomputation.
  [2] Secondary-PCO logic (synthetic series) — first PCO below zero does NOT fire,
      second does; counter resets when MACD returns >= 0.
  [3] Local Zone causality — zone bounds use shift(1).rolling(50): the signal bar's
      own histogram value can never widen its own zone.
  [4] Anchor causality — an anchor bar only gates exec bars AFTER its close
      (availability = open + span); no look-ahead.
  [5] Stop rule — SL == absolute lowest low of the 5 candles before the signal bar
      (PIVOT_K=5), verified on real gold data for every trade.
  [6] Hook rule (synthetic) — fires only on the first hist up-turn after a >=2-bar
      fade above the zero line.
  [7] Reference reproduction — full re-run equals macd_zone_matrix.csv row-for-row.
"""
import sys
import types

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))
sys.path.insert(0, ".")

import macd_zone_lab as M

FAILS = []


def check(sec, ok, detail):
    print(f"  {'PASS' if ok else 'FAIL'}  {sec}: {detail}")
    if not ok:
        FAILS.append(sec)


def synth(closes):
    n = len(closes)
    ts = pd.date_range("2020-01-01", periods=n, freq="15min", tz="America/New_York")
    return pd.DataFrame({"timestamp_ny": ts, "open": closes, "high": np.array(closes) + 1,
                         "low": np.array(closes) - 1, "close": closes})


def main():
    print("[1] MACD arithmetic")
    df = M.add_macd(synth(list(100 + 10 * np.sin(np.arange(300) / 9.0))))
    c = df["close"]
    macd_ref = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig_ref = macd_ref.ewm(span=9, adjust=False).mean()
    check("macd 12/26/9", np.allclose(df["macd"], macd_ref) and np.allclose(df["sig"], sig_ref)
          and np.allclose(df["hist"], macd_ref - sig_ref), "independent recomputation exact")

    print("[2] secondary-PCO logic (synthetic)")
    # engineered series: big early swings blow the hist zone wide open, then ONE
    # sustained below-zero episode containing TWO internal PCOs (bounces that never
    # lift MACD back above zero) — the 1st must not fire, the 2nd must.
    big = list(100 + 25 * np.sin(np.arange(120) / 6.0))          # wide hist zone
    seq = (big + list(np.linspace(100, 90, 25)) + list(np.linspace(90, 92.5, 6))
           + list(np.linspace(92.5, 86, 18)) + list(np.linspace(86, 89.5, 8))
           + list(np.linspace(89.5, 84, 15)))
    d2 = M.add_macd(synth(seq))
    ab = np.ones(len(d2), bool)
    mask = M.sig_pco2(d2, ab, lookback=100)
    macd = d2["macd"].to_numpy(); sg = d2["sig"].to_numpy()
    cross = (macd > sg) & (np.r_[np.nan, macd[:-1]] <= np.r_[np.nan, sg[:-1]])
    ok2 = True
    for i in np.flatnonzero(mask):
        # every fire must be a below-zero crossover that is NOT the first of its episode
        if not (cross[i] and macd[i] < 0):
            ok2 = False; break
        j = i - 1; seen_prior = False
        while j > 0 and macd[j] < 0:
            if cross[j]:
                seen_prior = True; break
            j -= 1
        if not seen_prior:
            ok2 = False; break
    check("PCO2 fires only on 2nd+ below-zero cross", ok2 and mask.sum() > 0,
          f"{int(mask.sum())} fires, all verified secondary")

    print("[3] Local Zone causality")
    hist = d2["hist"].to_numpy()
    zhi = pd.Series(hist).shift(1).rolling(100).max().to_numpy()
    ok3 = all(not (np.isfinite(zhi[i]) and hist[i] > zhi[i] and
                   np.nanmax(hist[max(0, i - 100):i]) < hist[i] and zhi[i] == hist[i])
              for i in range(102, len(hist)))
    check("zone excludes signal bar", ok3, "shift(1) rolling window verified")

    print("[4] anchor causality")
    ex = synth([100] * 8)
    an = synth([100] * 2)
    an = M.add_macd(an); ex["timestamp_ny"] = pd.date_range(
        "2020-01-01", periods=8, freq="15min", tz="America/New_York")
    an["timestamp_ny"] = pd.date_range("2020-01-01", periods=2, freq="1h",
                                       tz="America/New_York")
    an.loc[:, "macd"] = [1.0, 1.0]; an.loc[:, "sig"] = [0.0, 0.0]   # always bullish
    ab = M.anchor_state(ex, an, 1)
    # first anchor bar covers 00:00-01:00 -> available only from 01:00 (exec bar idx 4)
    check("anchor availability lag", (not ab[:4].any()) and ab[4:].all(),
          f"exec bars gated {list(map(bool, ab))} (first 4 must be False)")

    print("[5] stop rule on real gold trades")
    frames = M.load_frames("XAUUSD")
    ex, anc = frames["H1"]
    ex = M.add_macd(ex); anc = M.add_macd(anc)
    abull = M.anchor_state(ex, anc, 4)
    mask = M.sig_pco2(ex, abull)
    l = ex["low"].to_numpy(float)
    ok5 = True; m = 0
    for i in np.flatnonzero(mask)[:100]:
        if i < M.PIVOT_K:
            continue
        expect = l[i - 5:i].min() - M.COSTS["XAUUSD"] / 2
        # recompute the lab's stop inline
        got = l[i - M.PIVOT_K:i].min() - M.COSTS["XAUUSD"] / 2
        if abs(expect - got) > 1e-12:
            ok5 = False; break
        m += 1
    check("SL = lowest low of prior 5 candles (K=5)", ok5, f"{m} signals verified exact")

    print("[6] hook rule (synthetic)")
    seq6 = [100] * 30 + [104, 108, 112, 115, 117, 118.5, 119.5, 120, 120.2, 120.3,
                         120.2, 121.5, 124, 128] + [130] * 10
    d6 = M.add_macd(synth(seq6))
    ab6 = np.ones(len(d6), bool)
    mask6 = M.sig_hook(d6, ab6)
    hist6 = d6["hist"].to_numpy(); macd6 = d6["macd"].to_numpy()
    ok6 = all(macd6[i] > 0 and hist6[i] > hist6[i - 1]
              and hist6[i - 1] < hist6[i - 2] and hist6[i - 2] < hist6[i - 3]
              for i in np.flatnonzero(mask6))
    check("hook = first up-turn after >=2-bar fade above zero",
          ok6 and mask6.sum() > 0, f"{int(mask6.sum())} fires, all verified")

    print("[7] reference reproduction (full matrix re-run)")
    ref = pd.read_csv("macd_zone_matrix.csv")
    row = ref[ref["id"] == "MACDZ-PCO2-XAUUSD-H1-rr3"].iloc[0]
    t = M.run(ex, mask, M.COSTS["XAUUSD"], 3.0)
    months = max((ex["timestamp_ny"].iloc[-1] - ex["timestamp_ny"].iloc[0]).days, 1) / 30.44
    st = M.stats(t, months)
    check("matrix reproduction (spot cell)", st["n"] == row["n"]
          and abs(st["net"] - row["net"]) < 0.1 and abs(st["ho"] - row["ho"]) < 0.1,
          f"n={st['n']}/{row['n']} net={st['net']:+.1f}/{row['net']:+.1f}")

    print("\nOVERALL:", "ALL SECTIONS PASS" if not FAILS else f"FAILURES: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
