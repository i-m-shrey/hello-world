"""NEWS ANALYST TRADER — single-file, news-REASONING MT5 demo engine (July 2026).

Successor to observer.py / demo_trader.py. Instead of a frozen technical
rulebook, every trade decision comes from an LLM reading the actual state of
the world — economic calendar (with actual-vs-forecast SURPRISE, not just
"an event exists"), live headlines from several feeds, and a compact market
snapshot — and synthesizing them into directional judgments with explicit
conviction, invalidation and horizon. Static heuristics only VALIDATE and
EXECUTE what the model decides; they never generate signals.

HARD LESSONS carried forward as first-class gates (paid for on demo, do not
remove):
  * commission dominates:   $7.00/lot on FX entries (measured, not queryable),
                            $0 on gold/index. Any trade whose estimated
                            commission exceeds COMMISSION_MAX_FRACTION of its
                            intended $ risk is REFUSED before sizing ends.
  * anti-overtrading:       per symbol+direction cooldown AND per-narrative
                            dedup — a persisting story must not re-buy every
                            cycle, paying commission each time.
  * stale broker ticks:     market-hours come from the SYSTEM clock in NY tz
                            (Sun 17:00 -> Fri 17:00), never inferred from the
                            broker's last tick (a stale weekend tick once
                            produced a -360min offset vs the true +180).
  * live fills != closes:   stops live broker-side; realized P&L sums
                            profit+commission+swap across ALL deals of the
                            position, queried with position= ONLY (the API
                            ignores position= when a date range is passed).

DEMO-ONLY: after mt5.login the account number is asserted against
EXPECTED_DEMO_LOGIN from demo_account_config.py; any mismatch aborts. This
file must never import or touch live_mt5_bot.py / live_signals.py.

Config (demo_account_config.py — the ONE place secrets live):
    MT5_LOGIN=7945842  MT5_PASSWORD="..."  MT5_SERVER="Eightcap-Demo"
    MT5_TERMINAL_PATH=r"C:\\Program Files\\MetaTrader 5 - Copy\\terminal64.exe"
    LLM_API_KEY="..."                       # required for reasoning
    LLM_BASE_URL="https://api.openai.com/v1"   # any OpenAI-compatible endpoint
    LLM_MODEL="gpt-5.5"                        # a REASONING model, per brief

Run:  python news_analyst_trader.py            (live demo loop)
      python news_analyst_trader.py --selftest (no MT5/LLM needed: exercises
      feeds, surprise math, sizing, commission gate, contract parsing)
      python news_analyst_trader.py --dry-run  (full loop, no order_send)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ───────────────────────────── configuration ────────────────────────────────
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

INSTRUMENTS = ["XAUUSD", "EURUSD", "GBPUSD", "USDCAD", "USDCHF", "SPX500", "GER40"]
BROKER_SYM = {s: (s + ".i" if s in ("EURUSD", "GBPUSD", "USDCAD", "USDCHF") else s)
              for s in INSTRUMENTS}
# measured on this account: flat $7/lot on FX ENTRY deals (zero variance across
# 433 trades); gold + index CFDs commission-free. Configurable because any other
# account WILL differ — measure from fills, never assume.
COMMISSION_PER_LOT = {"EURUSD": 7.0, "GBPUSD": 7.0, "USDCAD": 7.0, "USDCHF": 7.0,
                      "XAUUSD": 0.0, "SPX500": 0.0, "GER40": 0.0}
COMMISSION_MAX_FRACTION = 0.20     # refuse trade if est. commission > 20% of risk
RISK_PCT_BASE = 0.0075             # 0.75% of equity at conviction 1.0
RISK_USD_CAP = 25.0                # absolute per-trade cap
MIN_CONVICTION = 0.65              # stay flat below this
MAX_POSITIONS = 6                  # validated caps — reused as-is
MAX_SAME_USD_DIRECTION = 4
MAX_GOLD_LONGS = 4
COOLDOWN_MIN = 90                  # same symbol+direction re-entry cooldown
NARRATIVE_COOLDOWN_MIN = 240       # same narrative_id re-entry cooldown
CYCLE_SECONDS = 15 * 60            # decision cycle
LLM_MAX_CALLS_PER_DAY = 40
LLM_REVIEW_EVERY_MIN = 240         # force a full review at least this often
STOP_ATR_MIN, STOP_ATR_MAX = 0.5, 4.0
HORIZON_MAX_HOURS = 48
STATE_FILE = "news_trader_state.json"
LEDGER_FILE = "news_trader_ledger.csv"
MAGIC = 77001

CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
RSS_FEEDS = [
    ("forexlive", "https://www.forexlive.com/feed/news"),
    ("fxstreet", "https://www.fxstreet.com/rss/news"),
    ("cnbc_markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                     "?partnerId=wrss01&id=15839069"),
    ("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
]
HEADLINE_MAX_AGE_MIN = 360
HEADLINE_KEEP = 40

mt5 = None  # imported in live mode only


def log(msg: str):
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z | {msg}", flush=True)


# ─────────────────────────── market-hours gate ──────────────────────────────
def market_is_open(now_utc: datetime | None = None) -> bool:
    """PURE SYSTEM-CLOCK check (lesson: never infer time facts from broker
    ticks — they freeze when the market closes). FX/gold week: Sun 17:00 NY ->
    Fri 17:00 NY. Index CFDs have their own breaks; the broker simply rejects
    those orders, which is acceptable — this gate exists to stop the whole
    engine from acting on a frozen weekend tape."""
    now = (now_utc or datetime.now(UTC)).astimezone(NY)
    wd, t = now.weekday(), now.time()
    if wd == 5:                                   # Saturday
        return False
    if wd == 4 and t >= datetime.min.replace(hour=17).time():   # Fri >= 17:00
        return False
    if wd == 6 and t < datetime.min.replace(hour=17).time():    # Sun < 17:00
        return False
    return True


# ───────────────────────────── world state: calendar ────────────────────────
def _num(x):
    """'3.4%'->3.4, '250M'->250e6-ish scale-free float, ''->None."""
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if not s:
        return None
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1]
    for suf, m in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if s.upper().endswith(suf):
            s, mult = s[:-1], m
            break
    try:
        return float(s) * mult
    except ValueError:
        return None


def fetch_calendar() -> list[dict]:
    """ForexFactory weekly JSON. Emits events with parsed times and, when an
    'actual' exists, a SURPRISE reading (actual vs forecast, sign-normalized
    direction is left to the model — deciding whether a hot CPI is
    currency-positive is judgment, not arithmetic)."""
    try:
        with urllib.request.urlopen(
                urllib.request.Request(CAL_URL, headers={"User-Agent": "Mozilla/5.0"}),
                timeout=20) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        log(f"calendar fetch failed: {exc}")
        return []
    out = []
    for ev in raw:
        try:
            when = datetime.fromisoformat(ev["date"])
        except Exception:  # noqa: BLE001
            continue
        a, f, p = _num(ev.get("actual")), _num(ev.get("forecast")), _num(ev.get("previous"))
        surprise = None
        if a is not None and f is not None:
            denom = max(abs(f), abs(p or f), 1e-9)
            surprise = round((a - f) / denom, 4)
        out.append(dict(title=ev.get("title", ""), ccy=ev.get("country", ""),
                        when=when, impact=ev.get("impact", ""),
                        actual=ev.get("actual"), forecast=ev.get("forecast"),
                        previous=ev.get("previous"), surprise=surprise))
    return out


def calendar_window(cal: list[dict], now: datetime) -> tuple[list, list]:
    """(recent prints last 2h with actuals, upcoming next 12h)."""
    recent = [e for e in cal if e["actual"] is not None
              and timedelta(0) <= now - e["when"].astimezone(UTC) <= timedelta(hours=2)]
    upcoming = [e for e in cal if e["when"].astimezone(UTC) >= now
                and e["when"].astimezone(UTC) - now <= timedelta(hours=12)
                and e["impact"] in ("High", "Medium")]
    return recent, upcoming


# ───────────────────────────── world state: headlines ───────────────────────
def _rss_items(xml_text: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        when = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                when = datetime.strptime(pub, fmt)
                break
            except ValueError:
                continue
        if when is None:
            when = datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if title:
            out.append(dict(source=source, title=title, when=when.astimezone(UTC)))
    return out


def fetch_headlines() -> list[dict]:
    items = []
    for source, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                items += _rss_items(r.read().decode("utf-8", "replace"), source)
        except Exception as exc:  # noqa: BLE001
            log(f"rss {source} failed: {exc}")
    now = datetime.now(UTC)
    fresh = [h for h in items
             if now - h["when"] <= timedelta(minutes=HEADLINE_MAX_AGE_MIN)]
    fresh.sort(key=lambda h: h["when"], reverse=True)
    seen, dedup = set(), []
    for h in fresh:
        k = re.sub(r"\W+", "", h["title"].lower())[:80]
        if k not in seen:
            seen.add(k)
            h["id"] = hashlib.sha1(k.encode()).hexdigest()[:12]
            dedup.append(h)
    return dedup[:HEADLINE_KEEP]


# ───────────────────────────── market snapshot ──────────────────────────────
def market_snapshot() -> dict:
    """Compact per-instrument context for the model: price, ATR-normalized
    recent moves, spread. Numbers only — the model does the interpreting."""
    snap = {}
    for sym in INSTRUMENTS:
        bsym = BROKER_SYM[sym]
        rates = mt5.copy_rates_from_pos(bsym, mt5.TIMEFRAME_H1, 0, 200)
        if rates is None or len(rates) < 60:
            continue
        import numpy as np
        h = np.array([r["high"] for r in rates], float)
        l = np.array([r["low"] for r in rates], float)
        c = np.array([r["close"] for r in rates], float)
        prev = np.roll(c, 1); prev[0] = c[0]
        tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
        atr = float(tr[-50:].mean())
        tick = mt5.symbol_info_tick(bsym)
        info = mt5.symbol_info(bsym)
        if tick is None or info is None or atr <= 0:
            continue
        mid = (tick.bid + tick.ask) / 2
        snap[sym] = dict(
            price=round(mid, info.digits),
            atr_h1=round(atr, info.digits),
            move_1h_atr=round((c[-1] - c[-2]) / atr, 2),
            move_4h_atr=round((c[-1] - c[-5]) / atr, 2),
            move_24h_atr=round((c[-1] - c[-25]) / atr, 2),
            spread=round(tick.ask - tick.bid, info.digits),
        )
    return snap


# ───────────────────────────── LLM reasoning step ───────────────────────────
SYSTEM_PROMPT = """You are the sole discretionary analyst for a small MT5 book.
Instruments: XAUUSD (gold), EURUSD, GBPUSD, USDCAD, USDCHF, SPX500, GER40.

You receive: (1) economic prints from the last 2 hours WITH actual vs forecast
and a normalized surprise value, (2) upcoming events in the next 12 hours,
(3) fresh cross-source headlines, (4) a numeric market snapshot (price, H1 ATR,
ATR-normalized 1h/4h/24h moves, spread), (5) currently open positions with
their theses.

Your job is genuine synthesis, the way a human macro analyst reads a tape:
connect related events into one story (e.g. hot US CPI + hawkish Fed speaker +
oil supply shock = one USD-strength / risk-off narrative with second-order
effects on gold and indices), judge surprise vs consensus, and decide whether
any instrument offers a trade RIGHT NOW with a clear catalyst.

Discipline rules you must respect:
- Most cycles the correct output is NO trades. Only propose a trade when a
  concrete, current catalyst gives a directional edge over the next hours.
  Never propose a trade just because a technical level exists.
- Do not fight an imminent (<45 min) high-impact release on the same currency;
  either wait for the print or stand aside.
- Each idea needs: direction, conviction 0..1 (only >=0.65 will be traded),
  a stop distance in H1-ATR multiples (0.5..4.0) placed where the THESIS is
  invalidated, a horizon in hours (<=48), and a short narrative_id slug that
  names the story (e.g. "us-cpi-hot-jul") so repeated cycles of the same story
  are deduplicated instead of re-bought.
- If an OPEN position's thesis is now wrong or played out, return action
  "close" for it.

Return STRICT JSON only, no prose:
{"read": "<=60 words on the current macro tape",
 "decisions": [{"symbol":"XAUUSD","action":"long|short|close|flat",
   "conviction":0.0,"stop_atr":1.5,"horizon_hours":12,
   "narrative_id":"slug","thesis":"<=25 words"}]}
Omit instruments with nothing to say. JSON must parse."""


def llm_call(cfg, payload: dict) -> dict | None:
    """OpenAI-compatible chat call via stdlib urllib (self-contained). Returns
    parsed JSON dict or None."""
    body = json.dumps({
        "model": cfg.LLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": json.dumps(payload, default=str)}],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        cfg.LLM_BASE_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {cfg.LLM_API_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
        txt = out["choices"][0]["message"]["content"]
        return parse_decisions(txt)
    except Exception as exc:  # noqa: BLE001
        log(f"LLM call failed: {exc}")
        return None


def parse_decisions(txt: str) -> dict | None:
    """Tolerant JSON extraction + hard schema validation. Anything malformed
    is dropped — a garbled decision must never reach order_send."""
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    clean = {"read": str(obj.get("read", ""))[:400], "decisions": []}
    for d in obj.get("decisions", []):
        try:
            sym = str(d["symbol"]).upper()
            act = str(d["action"]).lower()
            if sym not in INSTRUMENTS or act not in ("long", "short", "close", "flat"):
                continue
            conv = min(max(float(d.get("conviction", 0)), 0.0), 1.0)
            stop_atr = min(max(float(d.get("stop_atr", 1.5)), STOP_ATR_MIN), STOP_ATR_MAX)
            horizon = min(max(float(d.get("horizon_hours", 12)), 1.0), HORIZON_MAX_HOURS)
            nid = re.sub(r"[^a-z0-9\-]", "", str(d.get("narrative_id", "na")).lower())[:40] or "na"
            clean["decisions"].append(dict(
                symbol=sym, action=act, conviction=conv, stop_atr=stop_atr,
                horizon_hours=horizon, narrative_id=nid,
                thesis=str(d.get("thesis", ""))[:200]))
        except (KeyError, TypeError, ValueError):
            continue
    return clean


def should_call_llm(state: dict, recent_prints, headlines, now: datetime) -> str | None:
    """Cost control: call the model only when the world changed or a periodic
    review is due. Returns a reason string or None."""
    calls = [t for t in state.get("llm_calls", [])
             if now - datetime.fromisoformat(t) <= timedelta(days=1)]
    state["llm_calls"] = calls
    if len(calls) >= LLM_MAX_CALLS_PER_DAY:
        return None
    seen_prints = set(state.get("seen_prints", []))
    new_prints = [e for e in recent_prints
                  if f"{e['title']}|{e['when']}" not in seen_prints]
    if new_prints:
        return f"new economic print(s): {', '.join(e['title'] for e in new_prints[:3])}"
    seen_heads = set(state.get("seen_headlines", []))
    fresh = [h for h in headlines if h["id"] not in seen_heads]
    if len(fresh) >= 3:
        return f"{len(fresh)} fresh headlines"
    last = state.get("last_llm_at")
    if last is None or now - datetime.fromisoformat(last) >= timedelta(minutes=LLM_REVIEW_EVERY_MIN):
        return "periodic full review"
    return None


# ─────────────────────── sizing + the commission gate ───────────────────────
def value_per_price_unit(bsym) -> float | None:
    """USD P&L for a 1.0-lot position per 1.0 price-unit move, from the
    broker's own tick metadata (robust across FX/metal/index CFDs)."""
    info = mt5.symbol_info(bsym)
    if info is None or info.trade_tick_size <= 0:
        return None
    return info.trade_tick_value / info.trade_tick_size


def size_trade(sym: str, conviction: float, stop_dist: float, equity: float):
    """Return (lot, risk_usd, est_commission) or (None, reason, None).
    THE lesson of the 627-trade post-mortem lives here: commission is checked
    against the intended risk BEFORE any order exists, and the trade is
    refused outright when it fails."""
    bsym = BROKER_SYM[sym]
    vpu = value_per_price_unit(bsym)
    info = mt5.symbol_info(bsym)
    if vpu is None or info is None or stop_dist <= 0:
        return None, "no contract metadata", None
    risk_target = min(equity * RISK_PCT_BASE * conviction, RISK_USD_CAP)
    risk_per_lot = stop_dist * vpu
    if risk_per_lot <= 0:
        return None, "bad risk per lot", None
    step = info.volume_step or 0.01
    lot = max(info.volume_min, int(risk_target / risk_per_lot / step) * step)
    lot = min(lot, info.volume_max or lot)
    lot = round(lot, 2)
    risk_usd = lot * risk_per_lot
    commission = COMMISSION_PER_LOT.get(sym, 7.0) * lot
    if risk_usd <= 0:
        return None, "zero risk", None
    if commission > COMMISSION_MAX_FRACTION * risk_usd:
        return None, (f"commission ${commission:.2f} > "
                      f"{COMMISSION_MAX_FRACTION:.0%} of risk ${risk_usd:.2f} — refused"), None
    if risk_usd > 2.5 * risk_target:
        return None, f"min lot risks ${risk_usd:.2f} >> target ${risk_target:.2f}", None
    return lot, risk_usd, commission


# ───────────────────────── execution mechanics (reused) ─────────────────────
def filling_mode(bsym):
    info = mt5.symbol_info(bsym)
    fm = info.filling_mode if info else 0
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def round_price(bsym, x: float) -> float:
    return round(x, mt5.symbol_info(bsym).digits)


def send_market(bsym: str, direction: str, lot: float, sl: float,
                comment: str, dry_run: bool) -> bool:
    tick = mt5.symbol_info_tick(bsym)
    if tick is None:
        return False
    price = tick.ask if direction == "long" else tick.bid
    if dry_run:
        log(f"DRY-RUN order: {direction} {lot} {bsym} @ {price} SL {sl}")
        return True
    req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=bsym, volume=lot,
               type=mt5.ORDER_TYPE_BUY if direction == "long" else mt5.ORDER_TYPE_SELL,
               price=price, sl=round_price(bsym, sl), magic=MAGIC,
               comment=comment[:26], type_filling=filling_mode(bsym),
               type_time=mt5.ORDER_TIME_GTC, deviation=30)
    for attempt in range(3):
        res = mt5.order_send(req)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log(f"order_send retry {attempt + 1}: retcode="
            f"{getattr(res, 'retcode', None)} {getattr(res, 'comment', '')}")
        time.sleep(1.5)
    return False


def close_position(pos, dry_run: bool) -> bool:
    bsym = pos.symbol
    tick = mt5.symbol_info_tick(bsym)
    if tick is None:
        return False
    is_buy = pos.type == mt5.POSITION_TYPE_BUY
    if dry_run:
        log(f"DRY-RUN close: {bsym} pos {pos.ticket}")
        return True
    req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=bsym, volume=pos.volume,
               type=mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               position=pos.ticket, price=tick.bid if is_buy else tick.ask,
               magic=MAGIC, comment="news-close",
               type_filling=filling_mode(bsym), deviation=30)
    for _ in range(3):
        res = mt5.order_send(req)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        time.sleep(1.5)
    return False


def realized_pnl(position_ticket: int) -> float:
    """Sum profit+commission+swap over EVERY deal of the position. Call with
    position= ONLY — the API silently ignores it when a date range is passed."""
    deals = mt5.history_deals_get(position=position_ticket) or []
    return sum(d.profit + d.commission + d.swap for d in deals)


def my_positions():
    out = []
    for bsym in set(BROKER_SYM.values()):
        for p in (mt5.positions_get(symbol=bsym) or []):
            if p.magic == MAGIC:
                out.append(p)
    return out


def usd_direction(sym: str, direction: str) -> int:
    """+1 = long USD, -1 = short USD, 0 = neither (indices)."""
    long_usd_when_long = {"USDCAD": 1, "USDCHF": 1, "EURUSD": -1, "GBPUSD": -1,
                          "XAUUSD": -1}
    v = long_usd_when_long.get(sym, 0)
    return v if direction == "long" else -v


def caps_allow(sym: str, direction: str, positions) -> str | None:
    if len(positions) >= MAX_POSITIONS:
        return f"max {MAX_POSITIONS} positions"
    sym_of = {v: k for k, v in BROKER_SYM.items()}
    my_usd = usd_direction(sym, direction)
    if my_usd != 0:
        same = sum(1 for p in positions
                   if usd_direction(sym_of.get(p.symbol, p.symbol),
                                    "long" if p.type == mt5.POSITION_TYPE_BUY else "short")
                   == my_usd)
        if same >= MAX_SAME_USD_DIRECTION:
            return f"max {MAX_SAME_USD_DIRECTION} same-USD-direction"
    if sym == "XAUUSD" and direction == "long":
        golds = sum(1 for p in positions
                    if p.symbol == BROKER_SYM["XAUUSD"] and p.type == mt5.POSITION_TYPE_BUY)
        if golds >= MAX_GOLD_LONGS:
            return f"max {MAX_GOLD_LONGS} gold longs"
    return None


# ───────────────────────────── state + ledger ───────────────────────────────
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, default=str, indent=1)
    os.replace(tmp, STATE_FILE)


def ledger_write(row: dict):
    exists = os.path.exists(LEDGER_FILE)
    cols = ["time_utc", "symbol", "action", "conviction", "narrative_id", "thesis",
            "lot", "risk_usd", "commission_est", "stop", "horizon_hours",
            "executed", "skip_reason", "read"]
    with open(LEDGER_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


# ───────────────────────────── decision cycle ───────────────────────────────
def run_cycle(cfg, state: dict, dry_run: bool):
    now = datetime.now(UTC)
    if not market_is_open(now):
        log("market closed (system-clock NY check) — no data reads, no decisions")
        return
    cal = fetch_calendar()
    recent_prints, upcoming = calendar_window(cal, now)
    headlines = fetch_headlines()
    reason = should_call_llm(state, recent_prints, headlines, now)
    if reason is None:
        log("no material change — LLM not called, staying with current book")
        return
    log(f"LLM review triggered: {reason}")

    snap = market_snapshot()
    positions = my_positions()
    sym_of = {v: k for k, v in BROKER_SYM.items()}
    open_book = [dict(symbol=sym_of.get(p.symbol, p.symbol),
                      direction="long" if p.type == mt5.POSITION_TYPE_BUY else "short",
                      lots=p.volume, entry=p.price_open, sl=p.sl,
                      unrealized_usd=round(p.profit + p.swap, 2),
                      thesis=state.get("theses", {}).get(str(p.ticket), ""))
                 for p in positions]
    payload = dict(
        utc_now=str(now), ny_now=str(now.astimezone(NY)),
        recent_prints=[{k: str(v) for k, v in e.items()} for e in recent_prints],
        upcoming_events=[{k: str(v) for k, v in e.items()} for e in upcoming[:15]],
        headlines=[dict(t=h["title"], src=h["source"],
                        age_min=int((now - h["when"]).total_seconds() // 60))
                   for h in headlines],
        market=snap, open_positions=open_book,
        account=dict(equity=round(mt5.account_info().equity, 2)),
    )
    result = llm_call(cfg, payload)
    state.setdefault("llm_calls", []).append(str(now))
    state["last_llm_at"] = str(now)
    state["seen_prints"] = ([f"{e['title']}|{e['when']}" for e in recent_prints]
                            + state.get("seen_prints", []))[:200]
    state["seen_headlines"] = ([h["id"] for h in headlines]
                               + state.get("seen_headlines", []))[:400]
    if result is None:
        log("LLM returned nothing usable — staying flat this cycle")
        return
    log(f"ANALYST READ: {result['read']}")

    equity = mt5.account_info().equity
    for d in result["decisions"]:
        sym, act = d["symbol"], d["action"]
        base = dict(time_utc=str(now), symbol=sym, action=act,
                    conviction=d["conviction"], narrative_id=d["narrative_id"],
                    thesis=d["thesis"], horizon_hours=d["horizon_hours"],
                    read=result["read"], executed=0, skip_reason="")
        if act == "flat":
            ledger_write(base)
            continue
        if act == "close":
            for p in positions:
                if sym_of.get(p.symbol) == sym:
                    ok = close_position(p, dry_run)
                    if ok and not dry_run:
                        log(f"{sym}: closed pos {p.ticket} on analyst call — "
                            f"realized ${realized_pnl(p.ticket):.2f}")
                    base.update(executed=int(ok))
            ledger_write(base)
            continue
        # entries
        if d["conviction"] < MIN_CONVICTION:
            base["skip_reason"] = f"conviction {d['conviction']:.2f} < {MIN_CONVICTION}"
            ledger_write(base); log(f"{sym}: {base['skip_reason']}"); continue
        if sym not in snap:
            base["skip_reason"] = "no market snapshot"
            ledger_write(base); continue
        held = [p for p in positions if sym_of.get(p.symbol) == sym]
        if held:
            base["skip_reason"] = "already positioned"
            ledger_write(base); continue
        cool = state.get("cooldowns", {}).get(f"{sym}|{act}")
        if cool and now - datetime.fromisoformat(cool) < timedelta(minutes=COOLDOWN_MIN):
            base["skip_reason"] = f"cooldown ({COOLDOWN_MIN}m) active"
            ledger_write(base); log(f"{sym}: {base['skip_reason']}"); continue
        ncool = state.get("narratives", {}).get(d["narrative_id"])
        if ncool and now - datetime.fromisoformat(ncool) < timedelta(minutes=NARRATIVE_COOLDOWN_MIN):
            base["skip_reason"] = f"narrative '{d['narrative_id']}' already traded"
            ledger_write(base); log(f"{sym}: {base['skip_reason']}"); continue
        block = caps_allow(sym, act, positions)
        if block:
            base["skip_reason"] = block
            ledger_write(base); log(f"{sym}: cap — {block}"); continue
        atr = snap[sym]["atr_h1"]
        stop_dist = d["stop_atr"] * atr + snap[sym]["spread"] / 2
        lot, risk_or_reason, commission = size_trade(sym, d["conviction"], stop_dist, equity)
        if lot is None:
            base["skip_reason"] = risk_or_reason
            ledger_write(base); log(f"{sym}: {risk_or_reason}"); continue
        tick = mt5.symbol_info_tick(BROKER_SYM[sym])
        entry = tick.ask if act == "long" else tick.bid
        sl = entry - stop_dist if act == "long" else entry + stop_dist
        ok = send_market(BROKER_SYM[sym], act, lot, sl,
                         f"news:{d['narrative_id']}", dry_run)
        base.update(lot=lot, risk_usd=round(risk_or_reason, 2),
                    commission_est=round(commission, 2),
                    stop=round_price(BROKER_SYM[sym], sl), executed=int(ok))
        ledger_write(base)
        if ok:
            log(f"{sym}: {act.upper()} {lot} lots | risk ${risk_or_reason:.2f} | "
                f"commission ${commission:.2f} | SL {sl:.5f} | "
                f"narrative '{d['narrative_id']}' | {d['thesis']}")
            state.setdefault("cooldowns", {})[f"{sym}|{act}"] = str(now)
            state.setdefault("narratives", {})[d["narrative_id"]] = str(now)
            if not dry_run:
                time.sleep(1)
                for p in my_positions():
                    if sym_of.get(p.symbol) == sym and str(p.ticket) not in state.get("theses", {}):
                        state.setdefault("theses", {})[str(p.ticket)] = d["thesis"]
                        state.setdefault("horizons", {})[str(p.ticket)] = str(
                            now + timedelta(hours=d["horizon_hours"]))

    # horizon expiry: analyst gave each position a shelf life — enforce it
    for p in my_positions():
        hz = state.get("horizons", {}).get(str(p.ticket))
        if hz and now >= datetime.fromisoformat(hz):
            if close_position(p, dry_run):
                log(f"horizon expiry close: pos {p.ticket} "
                    f"realized ${realized_pnl(p.ticket):.2f}" if not dry_run
                    else f"horizon expiry (dry-run): pos {p.ticket}")
                state["horizons"].pop(str(p.ticket), None)
                state.get("theses", {}).pop(str(p.ticket), None)


# ───────────────────────────── startup / main ───────────────────────────────
def connect(cfg):
    global mt5
    import MetaTrader5 as _mt5
    mt5 = _mt5
    if not mt5.initialize(path=cfg.MT5_TERMINAL_PATH, login=cfg.MT5_LOGIN,
                          password=cfg.MT5_PASSWORD, server=cfg.MT5_SERVER):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    acc = mt5.account_info()
    if acc is None or acc.login != cfg.EXPECTED_DEMO_LOGIN:
        mt5.shutdown()
        raise SystemExit(f"REFUSING TO RUN: connected account "
                         f"{getattr(acc, 'login', None)} != expected demo "
                         f"{cfg.EXPECTED_DEMO_LOGIN}. This engine is demo-only.")
    if "demo" not in (acc.server or "").lower():
        mt5.shutdown()
        raise SystemExit(f"REFUSING TO RUN: server '{acc.server}' does not look "
                         f"like a demo server.")
    for bsym in set(BROKER_SYM.values()):
        mt5.symbol_select(bsym, True)
    log(f"connected: {acc.login} @ {acc.server} | equity ${acc.equity:.2f} (DEMO OK)")


def selftest():
    """No MT5, no LLM key needed: proves feeds, surprise math, contract
    parsing, sizing arithmetic and the commission gate."""
    print("== market-hours gate ==")
    assert not market_is_open(datetime(2026, 7, 18, 12, 0, tzinfo=UTC))      # Saturday
    assert not market_is_open(datetime(2026, 7, 17, 22, 0, tzinfo=UTC))      # Fri 18:00 NY
    assert market_is_open(datetime(2026, 7, 20, 12, 0, tzinfo=UTC))          # Monday
    assert not market_is_open(datetime(2026, 7, 19, 20, 0, tzinfo=UTC))      # Sun 16:00 NY
    assert market_is_open(datetime(2026, 7, 19, 21, 30, tzinfo=UTC))         # Sun 17:30 NY
    print("PASS  Fri17->Sun17 NY closed, else open (pure system clock)")

    print("== surprise math ==")
    assert _num("3.4%") == 3.4 and _num("250M") == 250e6 and _num("") is None
    cal = fetch_calendar()
    print(f"PASS  calendar fetch: {len(cal)} events "
          f"({sum(1 for e in cal if e['surprise'] is not None)} with computed surprise)")

    print("== headlines ==")
    hs = fetch_headlines()
    print(f"PASS  {len(hs)} fresh deduped headlines from "
          f"{len(set(h['source'] for h in hs))} sources"
          + (f" | newest: {hs[0]['title'][:70]}" if hs else ""))

    print("== LLM contract parsing ==")
    good = parse_decisions('noise {"read":"usd bid on hot cpi","decisions":'
                           '[{"symbol":"XAUUSD","action":"short","conviction":0.72,'
                           '"stop_atr":9,"horizon_hours":900,"narrative_id":"US CPI hot!!",'
                           '"thesis":"hot cpi -> real yields up"},'
                           '{"symbol":"BTCUSD","action":"long","conviction":0.9}]} tail')
    assert good and len(good["decisions"]) == 1, good
    d = good["decisions"][0]
    assert d["stop_atr"] == STOP_ATR_MAX and d["horizon_hours"] == HORIZON_MAX_HOURS
    assert d["narrative_id"] == "uscpihot"
    assert parse_decisions("total garbage") is None
    print("PASS  schema clamps stop/horizon, drops unknown symbols, survives noise")

    print("== sizing + commission gate (mocked broker metadata) ==")
    class _Info:  # noqa: D401
        digits = 5; volume_min = 0.01; volume_step = 0.01; volume_max = 100.0
        trade_tick_value = 1.0; trade_tick_size = 0.00001    # $10/pip/lot FX-style
    class _MT5:  # noqa: D401
        @staticmethod
        def symbol_info(_): return _Info()
    global mt5
    mt5 = _MT5()
    # tight stop -> commission fraction = $7/(stop*vpu) > 20% -> REFUSE.
    # (with flat $/lot commission the fraction is lot-independent: refusal line
    # for FX-style $10/pip/lot metadata sits at stop < 3.5 pips — exactly the
    # "tightest stops paid the largest silent tax" mechanism from the post-mortem)
    lot, reason, _ = size_trade("EURUSD", 1.0, 0.0002, 2000.0)   # 2-pip stop
    assert lot is None and "commission" in reason, (lot, reason)
    print(f"PASS  2-pip-stop FX trade refused: {reason}")
    lot, risk, comm = size_trade("EURUSD", 1.0, 0.0040, 2000.0)  # 40-pip stop
    assert lot is not None and comm <= COMMISSION_MAX_FRACTION * risk
    print(f"PASS  40-pip-stop FX trade sized: lot={lot} risk=${risk:.2f} comm=${comm:.2f}")
    lot, risk, comm = size_trade("XAUUSD", 1.0, 0.0040, 2000.0)
    assert lot is not None and comm == 0.0
    print(f"PASS  gold commission-free path: lot={lot} comm=${comm:.2f}")
    mt5 = None
    print("\nSELFTEST: ALL SECTIONS PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true", help="single cycle then exit")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    import demo_account_config as cfg
    if not getattr(cfg, "EXPECTED_DEMO_LOGIN", None):
        cfg.EXPECTED_DEMO_LOGIN = cfg.MT5_LOGIN
    assert getattr(cfg, "LLM_API_KEY", None), \
        "LLM_API_KEY missing from demo_account_config.py — the reasoning step needs it"
    cfg.LLM_BASE_URL = getattr(cfg, "LLM_BASE_URL", "https://api.openai.com/v1")
    cfg.LLM_MODEL = getattr(cfg, "LLM_MODEL", "gpt-5.5")
    connect(cfg)
    state = load_state()
    log(f"NEWS ANALYST TRADER | dry_run={args.dry_run} | cycle {CYCLE_SECONDS}s | "
        f"model {cfg.LLM_MODEL} | max {LLM_MAX_CALLS_PER_DAY} LLM calls/day")
    while True:
        try:
            run_cycle(cfg, state, args.dry_run)
            save_state(state)
        except KeyboardInterrupt:
            log("stopped by user")
            break
        except Exception as exc:  # noqa: BLE001
            log(f"cycle error (contained): {exc!r}")
        if args.once:
            break
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
