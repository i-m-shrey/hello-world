"""ANALYST REVIEW (July 2026) — the weekly scoreboard for system 3 (deliverable D).

Run it on the observer desktop (same folder as analyst_bot.py):

    python analyst_review.py                # full report to stdout + ANALYST_WEEKLY.md
    python analyst_review.py --days 7      # restrict to the last N days

It ingests, using whatever is present:
  decisions.jsonl          every LLM run (packet, decision, verdict) — from the bot
  analyst_tradebook.csv    closed trades (written/refreshed here from MT5 history
                           when MetaTrader5 is importable: deals with magic 98001)
  ledger.csv               (optional) the observer's prediction ledger, for context
  live tradebook           NOT touched — system 1 is reviewed by its own tooling.

It answers the spec's two promotion questions, honestly:
  1. CALIBRATION: do the ANALYST's confidence-70 calls win ~70%?
     (confidence bucket vs realized win rate of EXECUTED trades; DRY_RUN decisions
     are scored as hypothetical when price data allows is NOT attempted here —
     dry decisions are counted, not scored.)
  2. P&L vs the "always NONE" baseline (which is $0.00 by definition).

Nothing here trades or modifies state. Read-only everywhere.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DECISIONS = os.path.join(ROOT, "decisions.jsonl")
TRADEBOOK = os.path.join(ROOT, "analyst_tradebook.csv")
OUT = os.path.join(ROOT, "ANALYST_WEEKLY.md")
MAGIC = 98001
CONF_BINS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101))


def load_decisions(days=None):
    rows = []
    if not os.path.exists(DECISIONS):
        return pd.DataFrame()
    with open(DECISIONS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            dec = d.get("decision") or {}
            ev = (d.get("packet") or {}).get("event") or {}
            rows.append(dict(
                ts=pd.to_datetime(d.get("ts"), utc=True, errors="coerce"),
                kind=d.get("kind"), verdict=d.get("verdict"),
                action=dec.get("action"), symbol=dec.get("symbol"),
                direction=dec.get("direction"), confidence=dec.get("confidence"),
                event=ev.get("title"), family=ev.get("family"),
                surprise=ev.get("surprise"), surprise_z=ev.get("surprise_z")))
    df = pd.DataFrame(rows)
    if days and len(df):
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        df = df[df["ts"] >= cutoff]
    return df


def refresh_tradebook_from_mt5():
    """When run on the bot machine: rebuild analyst_tradebook.csv from closed
    deals with our magic. Read-only MT5 use (history_deals_get only)."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    try:
        deals = mt5.history_deals_get(datetime(2026, 1, 1), datetime.now() +
                                      timedelta(days=2)) or []
        rows = [dict(ticket=d.ticket, position=d.position_id, symbol=d.symbol,
                     time=datetime.fromtimestamp(d.time, tz=timezone.utc),
                     type=d.type, entry=d.entry, volume=d.volume, price=d.price,
                     profit=d.profit, comment=d.comment)
                for d in deals if d.magic == MAGIC]
    finally:
        mt5.shutdown()
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # one row per closed position: sum profits of its deals, keep last exit time
    g = (df.groupby("position")
         .agg(symbol=("symbol", "first"), profit=("profit", "sum"),
              closed=("time", "max"), volume=("volume", "max")).reset_index())
    g.to_csv(TRADEBOOK, index=False)
    return g


def load_tradebook():
    fresh = refresh_tradebook_from_mt5()
    if fresh is not None:
        return fresh
    if os.path.exists(TRADEBOOK):
        df = pd.read_csv(TRADEBOOK)
        if "closed" in df.columns:
            df["closed"] = pd.to_datetime(df["closed"], utc=True, errors="coerce")
        return df
    return pd.DataFrame()


def match_confidence(trades, decisions):
    """Attach the decision confidence to each closed trade by (symbol, nearest
    preceding opened-decision time)."""
    if not len(trades) or not len(decisions):
        trades["confidence"] = None
        return trades
    opened = decisions[(decisions["action"] == "open")
                       & (decisions["verdict"].astype(str)
                          .str.startswith(("opened", "dry")))].dropna(subset=["ts"])
    conf = []
    for r in trades.itertuples():
        cand = opened[opened["symbol"] == r.symbol]
        if "closed" in trades.columns and pd.notna(getattr(r, "closed", None)):
            cand = cand[cand["ts"] <= r.closed]
        conf.append(cand["confidence"].iloc[-1] if len(cand) else None)
    trades = trades.copy()
    trades["confidence"] = conf
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    args = ap.parse_args()

    dec = load_decisions(args.days)
    tb = load_tradebook()
    L = [f"# ANALYST WEEKLY REVIEW — {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z"
         + (f" (last {args.days} days)" if args.days else " (all history)"), ""]

    # ── decision funnel ──────────────────────────────────────────────────
    L.append("## Decision funnel")
    if not len(dec):
        L.append("- no decisions.jsonl yet (bot not started, or empty window).")
    else:
        L.append(f"- LLM runs: **{len(dec)}** "
                 f"({dec['kind'].value_counts().to_dict()})")
        L.append(f"- actions: {Counter(dec['action'].fillna('no-json')).most_common()}")
        rej = dec[dec["verdict"].astype(str).str.startswith("rejected")]
        if len(rej):
            L.append("- rejection reasons:")
            for reason, cnt in Counter(rej["verdict"]).most_common():
                L.append(f"    - {cnt} x {reason}")
        none_rate = (dec["action"] == "none").mean()
        L.append(f"- stand-aside rate: **{none_rate:.0%}** "
                 "(high is healthy — see ANALYST_REPLAY_REPORT.md)")
    L.append("")

    # ── P&L vs always-NONE ───────────────────────────────────────────────
    L.append("## P&L vs the always-NONE baseline ($0.00)")
    if not len(tb):
        L.append("- no closed trades yet.")
    else:
        tot = tb["profit"].sum()
        wins = (tb["profit"] > 0)
        L.append(f"- closed trades: **{len(tb)}** | total P&L: **${tot:+.2f}** | "
                 f"win rate {wins.mean():.0%} | avg ${tb['profit'].mean():+.2f} | "
                 f"worst ${tb['profit'].min():+.2f}")
        L.append(f"- verdict vs doing nothing: "
                 f"{'AHEAD' if tot > 0 else 'BEHIND'} by ${abs(tot):.2f}")
        by_sym = tb.groupby("symbol")["profit"].agg(["count", "sum"])
        for sym, r in by_sym.iterrows():
            L.append(f"    - {sym}: {int(r['count'])} trades, ${r['sum']:+.2f}")
    L.append("")

    # ── calibration ──────────────────────────────────────────────────────
    L.append("## Calibration (confidence bucket vs realized win rate)")
    tbc = match_confidence(tb, dec) if len(tb) else tb
    if not len(tbc) or tbc["confidence"].isna().all():
        L.append("- not enough matched trades yet. (Needs closed trades whose "
                 "opening decision is in decisions.jsonl.)")
    else:
        L.append("| conf bucket | trades | realized win rate | avg $ |")
        L.append("|---|---|---|---|")
        for lo, hi in CONF_BINS:
            sub = tbc[(tbc["confidence"] >= lo) & (tbc["confidence"] < hi)]
            if not len(sub):
                continue
            L.append(f"| {lo}-{hi} | {len(sub)} | "
                     f"{(sub['profit'] > 0).mean():.0%} | "
                     f"{sub['profit'].mean():+.2f} |")
        L.append("")
        L.append("Promotion bar (spec): 4+ weeks BOTH ahead of always-NONE AND "
                 "calibrated (70s win ~70%). Neither alone is enough.")
    L.append("")

    report = "\n".join(L)
    open(OUT, "w", encoding="utf-8").write(report + "\n")
    print(report)
    print(f"\n(written to {OUT})")


if __name__ == "__main__":
    main()
