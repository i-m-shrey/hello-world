"""ANALYST BOT — LLM discretionary trader, DEMO ONLY (system 3, July 2026, v2).

The user's concept: think like a human analyst — live news (ACTUAL vs FORECAST),
technicals, and HISTORICAL PRECEDENT — combined into one judgment, executed like a
junior trader on a practice desk: demo account (hard-locked), mandatory stop-loss,
small size, daily loss cap, every decision (including "no trade") logged.

v2 (this file) — hardened after the replay/calibration work:
  * precedent is now SURPRISE-KEYED: the calendar row's (actual - forecast) is
    z-scaled with the archive's per-family scale (family_scales.csv) and matched
    against event-keyed case_library.csv rows (key_type="event"); slot-keyed rows
    (key_type="slot") remain for unscheduled displacement.
  * slot_for_time() is byte-identical to case_library_builder2.slot_of (parity
    enforced in --selftest).
  * risk_usd() validates tick economics per symbol (tick_size/tick_value_loss,
    volume bounds) and refuses to trade when the terminal reports zeros.
  * the daily-stop window is anchored to the BROKER's clock (offset measured from
    tick time vs UTC), not the machine clock.
  * JSON extraction tolerates fences/preamble; every rejection is logged with its
    reason; cited case_refs must match a real precedent row from the packet.

HOW IT RUNS (one process, on the desktop with the C:\\MT5_DEMO terminal + claude CLI):
  deterministic watcher loop (60s):
    - fetches the ForexFactory calendar (cached)
    - T-10min before a ●●● event  -> LLM exposure check (may CLOSE own positions only)
    - T+5min after a ●●● event    -> LLM decision (actual-vs-forecast now known)
    - unscheduled 1.5-5x ATR M5 displacement -> LLM interpretation
    - assembles the input packet (event + surprise, technical panel, matching
      case-library rows), calls `claude -p`, expects STRICT JSON back, validates
      EVERYTHING in code and only then places the demo order.

  python analyst_bot.py            normal run (starts in DRY_RUN)
  python analyst_bot.py --selftest offline plumbing + parity test (no MT5/claude)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

# ====================== CONFIG (all knobs here) =============================
TERMINAL_PATH   = r"C:\MT5_DEMO\terminal64.exe"   # DEMO terminal (same as grid bot)
DRY_RUN         = True        # start dry; flip to False after 2 days of clean logs
WHITELIST       = ("XAUUSD", "EURUSD", "GBPUSD", "USDCHF", "USDCAD", "SPX500", "GER40")
LOT_MIN, LOT_MAX = 0.01, 0.03
RISK_CAP_USD    = 25.0        # max $ from entry to SL per trade (demo $2k ~ 1.2%)
MAX_OPEN        = 2
MAX_TRADES_DAY  = 3
DAILY_STOP_USD  = -60.0       # realized+floating for magic; breach -> flatten + halt day
CONF_MIN        = 65          # LLM confidence gate
CASE_N_MIN      = 20          # cited precedent must have at least this many cases
CLAUDE_RUNS_MAX = 6           # per day
PRE_EVENT_MIN   = 10          # exposure check this many minutes before a red event
POST_EVENT_MIN  = 5           # decision this many minutes after
MAGIC           = 98001
POLL_SEC        = 60
CASE_LIB        = "case_library.csv"
FAMILY_SCALES   = "family_scales.csv"             # per-(ccy,family) surprise scale
CAL_URL         = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CAL_CACHE       = "ff_cal_cache_analyst.json"
BOT_FILE_FOR_TG = "live_mt5_bot.py"               # Telegram token source (regex, never printed)
CLAUDE_ARGS     = ["--model", "claude-sonnet-5"]  # keep runs cheap; [] = account default
STATE_FILE      = "analyst_state.json"
DECISIONS_LOG   = "decisions.jsonl"
TRADEBOOK       = "analyst_tradebook.csv"
# ============================================================================

mt5 = None                    # imported in main() so --selftest needs no MT5


def log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z | {msg}", flush=True)


def ny_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def tg_send(text):
    try:
        src = open(BOT_FILE_FOR_TG, encoding="utf-8").read()
        tok = re.search(r"TELEGRAM_TOKEN\s*=\s*[\"']([^\"']+)", src)
        cid = re.search(r"TELEGRAM_CHAT_ID\s*=\s*[\"']?([\w-]+)", src)
        if not (tok and cid):
            return
        data = json.dumps({"chat_id": cid.group(1), "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{tok.group(1)}/sendMessage", data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        log(f"telegram skipped: {e}")


# ====================== state ==============================================
def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"))


def day_state(st):
    d = str(ny_now().date())
    if st.get("day") != d:
        st.update(day=d, runs=0, trades=0, halted=False, done_triggers=[])
    return st


# ====================== calendar ===========================================
def load_calendar():
    try:
        raw = urllib.request.urlopen(CAL_URL, timeout=15).read()
        open(CAL_CACHE, "wb").write(raw)
    except Exception:
        if not os.path.exists(CAL_CACHE):
            return []
        raw = open(CAL_CACHE, "rb").read()
    try:
        return json.loads(raw)
    except Exception:
        return []


def red_events():
    """[(id, ny_datetime, dict)] for High-impact events of whitelist-relevant currencies."""
    from zoneinfo import ZoneInfo
    rel = {"USD", "EUR", "GBP", "CHF", "CAD"}
    out = []
    for e in load_calendar():
        if e.get("impact") != "High" or e.get("country") not in rel:
            continue
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(ZoneInfo("America/New_York"))
        except Exception:
            continue
        eid = f"{e.get('date')}|{e.get('title')}"
        out.append((eid, dt, e))
    return out


# ====================== event family + surprise ============================
# IDENTICAL rules to news_archive_builder.FAMILY_RULES — parity is enforced by
# --selftest when news_archive_builder.py is present; edit them TOGETHER or
# precedent keys stop matching.
FAMILY_RULES = [
    (r"^Non-Farm Employment Change$", "NFP"),
    (r"^ADP Non-Farm Employment Change$", "ADP"),
    (r"^Unemployment Claims$", "CLAIMS"),
    (r"^Unemployment Rate$", "UNRATE"),
    (r"^Average Hourly Earnings", "AHE"),
    (r"^(CPI|Core CPI) m/m$", "CPI_MM"),
    (r"^(CPI|Core CPI|CPI Median|Trimmed|Common CPI) y/y$", "CPI_YY"),
    (r"^(PPI|Core PPI) m/m$", "PPI_MM"),
    (r"^Core PCE Price Index m/m$", "PCE_MM"),
    (r"Flash.*CPI|CPI Flash", "CPI_FLASH"),
    (r"^(Core )?Retail Sales m/m$", "RETAIL"),
    (r"^(Advance|Prelim|Final) GDP q/q$", "GDP"),
    (r"^GDP m/m$", "GDP_MM"),
    (r"^ISM Manufacturing PMI$", "ISM_MFG"),
    (r"^ISM (Non-Manufacturing|Services) PMI$", "ISM_SVC"),
    (r"Flash (Manufacturing|Services) PMI", "PMI_FLASH"),
    (r"^Consumer Confidence$|^CB Consumer Confidence$", "CONF"),
    (r"^(Prelim|Revised) UoM Consumer Sentiment$", "UOM"),
    (r"^Durable Goods|^Core Durable Goods", "DURABLES"),
    (r"^Employment Change$", "EMP_CHANGE"),
    (r"^Claimant Count Change$", "CLAIMANT"),
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
    (r"^Trade Balance$", "TRADE"),
    (r"^Building Permits$|^Housing Starts$", "HOUSING"),
    (r"^Pending Home Sales|^Existing Home Sales|^New Home Sales", "HOMESALES"),
    (r"^Crude Oil Inventories$", "CRUDE"),
]
_FAMILY_COMPILED = [(re.compile(p, re.I), f) for p, f in FAMILY_RULES]


def family_of(title):
    t = (title or "").strip()
    for rx, fam in _FAMILY_COMPILED:
        if rx.search(t):
            return fam
    return "OTHER"


_NUM_RX = re.compile(r"^\s*(<|>)?\s*(-?\d+(?:\.\d+)?)\s*(%|K|M|B|T)?\s*$", re.I)
_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_val(v):
    """'206K' -> 206000.0, '0.3%' -> 0.3, '' -> None. Never guesses."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    m = _NUM_RX.match(s)
    if not m:
        return None
    return float(m.group(2)) * _MULT.get((m.group(3) or "").upper(), 1.0)


_SCALES = None


def family_scale(ccy, fam):
    """Historical std of (actual - forecast) for the family — from the archive
    (family_scales.csv, written by case_library_builder2). None = unknown."""
    global _SCALES
    if _SCALES is None:
        _SCALES = {}
        try:
            import csv
            with open(FAMILY_SCALES, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if float(row["n"]) >= 8 and float(row["scale"]) > 0:
                        _SCALES[(row["ccy"], row["family"])] = float(row["scale"])
        except Exception as e:
            log(f"family_scales.csv not loaded ({e}) — surprise keying disabled")
    return _SCALES.get((ccy, fam))


def surprise_bucket(z):
    if z is None:
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


def event_surprise(ev):
    """(family, z, bucket) from a live ffcal row; z/bucket are None when the
    archive has no scale or values are unparseable. NOTHING is guessed."""
    fam = family_of(ev.get("title"))
    a = parse_val(ev.get("actual"))
    f = parse_val(ev.get("forecast"))
    sc = family_scale(ev.get("country"), fam)
    if a is None or f is None or not sc:
        return fam, None, None
    z = (a - f) / sc
    return fam, round(z, 3), surprise_bucket(z)


# ====================== case library =======================================
def load_cases():
    import pandas as pd
    lib = pd.read_csv(CASE_LIB)
    if "key_type" not in lib.columns:
        raise SystemExit("case_library.csv is the v1 schema — rebuild with "
                         "case_library_builder2.py")
    return lib


def slot_for_time(dt_ny, tf="M5"):
    """IDENTICAL to case_library_builder2.slot_of — parity enforced in --selftest."""
    hour, minute = dt_ny.hour, dt_ny.minute
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


def query_cases(lib, asset, slot=None, family=None, surprise=None):
    """Precedent rows for the packet: event-keyed rows for (family, surprise) when
    the surprise is known, plus slot-keyed rows as fallback context. <= 8 rows."""
    rows = []
    if family and surprise and surprise != "inline":
        q = lib[(lib.key_type == "event") & (lib.asset == asset)
                & (lib.family == family) & (lib.surprise == surprise)]
        rows += q.sort_values("n", ascending=False).to_dict("records")
    if slot:
        q = lib[(lib.key_type == "slot") & (lib.asset == asset) & (lib.slot == slot)
                & (lib.intensity == "ALL") & (lib.pretrend == "ALL")]
        rows += q.sort_values("n", ascending=False).to_dict("records")
    uniq, seen = [], set()
    for r in rows:
        k = (r["key_type"], r["tf"], r["family"], r["surprise"], r["slot"],
             r["direction"], r["intensity"], r["pretrend"])
        if k not in seen:
            seen.add(k)
            uniq.append({kk: (round(v, 3) if isinstance(v, float) else v)
                         for kk, v in r.items()})
    return uniq[:8]


# ====================== market panel =======================================
def panel_for(sym):
    """Technical snapshot from the demo terminal (read-only)."""
    import pandas as pd
    out = {"symbol": sym}
    for tf_name, tf_const, bars in (("M5", mt5.TIMEFRAME_M5, 300),
                                    ("H1", mt5.TIMEFRAME_H1, 250)):
        r = mt5.copy_rates_from_pos(sym, tf_const, 0, bars)
        if r is None or len(r) < 60:
            return None
        df = pd.DataFrame(r)
        c = df["close"]; h = df["high"]; l = df["low"]
        prev = c.shift(1)
        tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
        atr = tr.rolling(50, min_periods=20).mean().iloc[-2]
        e20 = c.ewm(span=20, adjust=False).mean().iloc[-2]
        e50 = c.ewm(span=50, adjust=False).mean().iloc[-2]
        e200 = c.ewm(span=200, adjust=False).mean().iloc[-2]
        last = df.iloc[-4:-1][["open", "high", "low", "close"]].round(5).values.tolist()
        d = dict(close=float(c.iloc[-2]), atr50=float(atr),
                 ema20=float(e20), ema50=float(e50), ema200=float(e200),
                 trend="up" if e20 > e50 else "down",
                 pretrend="bull" if float(c.iloc[-2]) > float(e200) else "bear",
                 last3_bars=last)
        if tf_name == "H1":
            d["hi96"] = float(h.iloc[-98:-2].max()); d["lo96"] = float(l.iloc[-98:-2].min())
        out[tf_name] = d
    tick = mt5.symbol_info_tick(sym)
    out["bid"] = tick.bid if tick else None
    out["ask"] = tick.ask if tick else None
    return out


# ====================== LLM call ===========================================
CONTRACT = """You are the ANALYST: a disciplined discretionary trader on a DEMO account.
Combine the news SURPRISE (packet gives actual, forecast, surprise_z = how unusual
this beat/miss is in units of the event family's historical surprise spread, and
the surprise bucket), the technical panel, and the HISTORICAL PRECEDENT rows.
Precedent rows are REAL scored history: key_type "event" rows = past releases of
this family with the same surprise bucket (n = cases; direction = the release
bar's first reaction; cont_* = fraction that kept moving in that direction at each
horizon; fwd_*_med = median move in ATRs from the T+5min decision price, signed in
the reaction direction; adverse_worst = worst adverse excursion in ATRs);
key_type "slot" rows = all explosive moves in this time slot regardless of cause.
Decide like a professional: standing aside is the default and a good decision —
most precedent is a coin-flip. REPLAY FINDING (July 2026, 18k scored events,
walked forward): per-cell continuation rates showed NO out-of-sample predictive
power on their own, and every mechanical follow/fade policy lost to costs. Treat
cont_* differences as noise unless n is large AND the surprise + technicals +
cross-asset picture independently agree; your value is the context the keys
cannot see. Only trade when surprise + precedent + technicals genuinely align.

Reply with ONLY one JSON object, nothing else:
{"action":"open"|"close"|"none", "symbol":"...", "direction":"long"|"short",
 "lot":0.01-0.03, "sl":<price>, "tp":<price or null>, "horizon_hours":<int>,
 "confidence":0-100, "case_refs":[{"signature":"...","n":<int>,"cont":<float>}],
 "reasoning":"<=100 words, MUST cite the precedent numbers you used"}

case_refs must copy n and the cont_* you relied on from packet rows — invented
numbers void the decision in code. Rules you are graded on: confidence must be
calibrated (your 70s should win ~70%). "close" may only reference your own open
positions (listed in the packet). If the packet phase is "pre_event" you may only
choose "close" or "none"."""


def extract_json(raw):
    """Tolerant STRICT-JSON extraction: plain object, fenced block, or the first
    balanced {...} span that parses. Returns dict or None — never guesses fields."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    for start in [i for i, ch in enumerate(s) if ch == "{"]:
        depth = 0
        for j in range(start, len(s)):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:j + 1])
                        if isinstance(obj, dict) and "action" in obj:
                            return obj
                    except Exception:
                        pass
                    break
    return None


def call_claude(packet):
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if exe is None:
        log("claude CLI not found — decision skipped"); return None, "no-cli"
    prompt = CONTRACT + "\n\nPACKET:\n" + json.dumps(packet, default=str)
    try:
        r = subprocess.run([exe, "-p", *CLAUDE_ARGS], input=prompt.encode("utf-8"),
                           capture_output=True, timeout=180)
        raw = r.stdout.decode("utf-8", "replace")
    except Exception as e:
        log(f"claude call failed: {e}"); return None, "call-failed"
    dec = extract_json(raw)
    if dec is None:
        log("claude reply had no valid JSON — discarded")
    return dec, raw


# ====================== validation + execution =============================
def broker_utc_offset_min():
    """Broker-server clock minus UTC, in minutes (rounded to 30), measured from a
    liquid symbol's last tick time. None when no tick is available."""
    for sym in WHITELIST:
        tick = mt5.symbol_info_tick(sym)
        if tick and getattr(tick, "time", 0):
            delta = tick.time - datetime.now(timezone.utc).timestamp()
            return round(delta / 1800.0) * 30
    return None


def broker_day_window():
    """(start, end) naive datetimes IN BROKER TIME covering the broker's current
    day — the honest window for history_deals_get (deal times are broker-clock)."""
    off = broker_utc_offset_min() or 0
    now_srv = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=off)
    start = datetime(now_srv.year, now_srv.month, now_srv.day)
    return start, now_srv + timedelta(minutes=5)


def risk_usd(sym, entry, sl, lot):
    """$ risk from entry to SL. Uses tick_value_loss (the pessimistic side) and
    refuses (returns None) when the terminal reports broken tick economics."""
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    tick_size = getattr(info, "trade_tick_size", 0.0) or 0.0
    tick_val = (getattr(info, "trade_tick_value_loss", 0.0)
                or getattr(info, "trade_tick_value", 0.0) or 0.0)
    if tick_size <= 0 or tick_val <= 0:
        return None
    vol_min = getattr(info, "volume_min", 0.01) or 0.01
    vol_max = getattr(info, "volume_max", 100.0) or 100.0
    if not (vol_min <= lot <= vol_max):
        return None
    return abs(entry - sl) / tick_size * tick_val * lot


def my_positions():
    ps = mt5.positions_get()
    return [p for p in (ps or []) if p.magic == MAGIC]


def cited_case_ok(dec, packet):
    """At least one cited ref must MATCH a real precedent row from the packet
    (same n, n >= CASE_N_MIN). The LLM cannot invent precedent."""
    packet_ns = {int(r["n"]) for rows in (packet.get("precedent") or {}).values()
                 for r in rows if isinstance(r, dict) and r.get("n") is not None}
    for r in (dec.get("case_refs") or []):
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n >= CASE_N_MIN and n in packet_ns:
            return True
    return False


def validate(dec, packet, st):
    """Return (ok, reason). EVERY gate lives here in code, not in the prompt."""
    if not isinstance(dec, dict) or dec.get("action") not in ("open", "close", "none"):
        return False, "bad action"
    if dec["action"] == "none":
        return True, "none"
    if dec.get("symbol") not in WHITELIST:
        return False, "symbol not whitelisted"
    if dec["action"] == "close":
        if dec["symbol"] not in {p.symbol for p in my_positions()}:
            return False, "close references a symbol we do not hold"
        return True, "close-own"
    if packet.get("phase") == "pre_event":
        return False, "open forbidden pre-event"
    if st["trades"] >= MAX_TRADES_DAY:
        return False, "daily trade cap"
    if len(my_positions()) >= MAX_OPEN:
        return False, "max open positions"
    if not (isinstance(dec.get("confidence"), (int, float)) and dec["confidence"] >= CONF_MIN):
        return False, f"confidence < {CONF_MIN}"
    if not cited_case_ok(dec, packet):
        return False, f"no cited case matching a packet row with n >= {CASE_N_MIN}"
    lot = dec.get("lot")
    if not (isinstance(lot, (int, float)) and LOT_MIN <= lot <= LOT_MAX):
        return False, "lot out of bounds"
    sl = dec.get("sl"); d = dec.get("direction")
    tick = mt5.symbol_info_tick(dec["symbol"])
    if tick is None or not isinstance(sl, (int, float)) or d not in ("long", "short"):
        return False, "missing sl/direction"
    entry = tick.ask if d == "long" else tick.bid
    if (d == "long" and sl >= entry) or (d == "short" and sl <= entry):
        return False, "sl on wrong side"
    r = risk_usd(dec["symbol"], entry, sl, lot)
    if r is None:
        return False, "broken tick economics (tick_size/tick_value/volume bounds)"
    if r > RISK_CAP_USD:
        return False, f"risk ${r:.2f} > cap ${RISK_CAP_USD}"
    return True, f"ok risk ${r:.2f}"


def flatten_all(reason):
    """Close every own position once, logging each result."""
    for p in my_positions():
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            log(f"flatten {p.symbol}: no tick — skipped"); continue
        side = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        px = tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask
        r = mt5.order_send(dict(action=mt5.TRADE_ACTION_DEAL, symbol=p.symbol,
                                volume=p.volume, type=side, position=p.ticket,
                                price=px, magic=MAGIC, comment=f"ANALYST-{reason}",
                                type_filling=mt5.ORDER_FILLING_IOC))
        ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
        log(f"flatten {p.symbol} ({reason}): "
            + ("ok" if ok else f"FAILED retcode={getattr(r, 'retcode', None)}"))


def execute(dec, st):
    if dec["action"] == "none":
        return "none"
    if DRY_RUN:
        log(f"DRY_RUN — would {dec['action']} {dec.get('symbol')} {dec.get('direction')}")
        return "dry"
    if dec["action"] == "close":
        for p in my_positions():
            if p.symbol == dec["symbol"]:
                tick = mt5.symbol_info_tick(p.symbol)
                if tick is None:
                    continue
                side = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                px = tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask
                mt5.order_send(dict(action=mt5.TRADE_ACTION_DEAL, symbol=p.symbol,
                                    volume=p.volume, type=side, position=p.ticket,
                                    price=px, magic=MAGIC, comment="ANALYST-close",
                                    type_filling=mt5.ORDER_FILLING_IOC))
        return "closed"
    tick = mt5.symbol_info_tick(dec["symbol"])
    d = dec["direction"]
    req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=dec["symbol"], volume=dec["lot"],
               type=mt5.ORDER_TYPE_BUY if d == "long" else mt5.ORDER_TYPE_SELL,
               price=tick.ask if d == "long" else tick.bid,
               sl=float(dec["sl"]), magic=MAGIC, comment="ANALYST",
               type_filling=mt5.ORDER_FILLING_IOC)
    if dec.get("tp"):
        req["tp"] = float(dec["tp"])
    r = mt5.order_send(req)
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    if ok:
        st["trades"] += 1
        tg_send(f"🧠 ANALYST {d.upper()} {dec['symbol']} {dec['lot']} "
                f"conf {dec['confidence']} — {dec.get('reasoning','')[:150]}")
    else:
        log(f"order FAILED retcode={getattr(r, 'retcode', None)} "
            f"comment={getattr(r, 'comment', None)}")
    return "opened" if ok else f"order failed {getattr(r, 'retcode', None)}"


def record(kind, packet, dec, raw, verdict):
    raw_s = raw if isinstance(raw, str) else (json.dumps(raw, default=str) if raw else None)
    with open(DECISIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(ts=str(datetime.now(timezone.utc)), kind=kind,
                                packet=packet, decision=dec,
                                raw=raw_s[:2000] if raw_s else None,
                                verdict=verdict), default=str) + "\n")


# ====================== triggers ===========================================
def build_packet(phase, event, symbols, lib, extra=None):
    now = ny_now()
    pk = dict(phase=phase, ny_time=str(now), event=event,
              my_open_positions=[dict(symbol=p.symbol, dir="long" if p.type == 0 else "short",
                                      lots=p.volume, pl=p.profit) for p in my_positions()],
              panels={}, precedent={})
    fam = srp = None
    ev_dt = None
    if event:
        fam, srp_z, srp = event_surprise(event)
        pk["event"] = dict(event, family=fam, surprise_z=srp_z, surprise=srp)
        ev_dt = datetime.fromisoformat(event["date_ny"])
    for s in symbols:
        p = panel_for(s)
        if p:
            pk["panels"][s] = p
            tf = "M5" if s == "XAUUSD" else "M15"
            base = ev_dt if ev_dt is not None else now
            pk["precedent"][s] = query_cases(lib, s, slot=slot_for_time(base, tf),
                                             family=fam, surprise=srp)
    if extra:
        pk.update(extra)
    return pk


def event_symbols(ev):
    cur = ev.get("country")
    m = {"USD": list(WHITELIST), "EUR": ["EURUSD", "GER40"], "GBP": ["GBPUSD"],
         "CHF": ["USDCHF"], "CAD": ["USDCAD"]}
    return m.get(cur, ["XAUUSD"])


def watcher():
    import pandas as pd  # noqa: F401
    lib = load_cases()
    st = day_state(load_state())
    log(f"ANALYST started | DRY_RUN={DRY_RUN} | case library "
        f"{len(lib)} signatures | runs today {st['runs']}/{CLAUDE_RUNS_MAX}")
    tg_send(f"🧠 ANALYST bot started (DRY_RUN={DRY_RUN})")
    while True:
        try:
            st = day_state(st)
            now = ny_now()
            # daily stop — realized (broker-day window, broker clock) + floating
            if not st["halted"]:
                ps = my_positions()
                d0, d1 = broker_day_window()
                deals = mt5.history_deals_get(d0, d1) or []
                realized = sum(d.profit for d in deals if d.magic == MAGIC)
                floating = sum(p.profit for p in ps)
                if realized + floating <= DAILY_STOP_USD:
                    if not DRY_RUN:
                        flatten_all("daily-stop")
                    st["halted"] = True
                    log(f"daily stop hit: realized {realized:.2f} + floating "
                        f"{floating:.2f} <= {DAILY_STOP_USD}")
                    tg_send(f"🧠⚠️ ANALYST daily stop {DAILY_STOP_USD}$ hit — halted for the day")
            triggers = []
            for eid, dt, ev in red_events():
                mins = (dt - now).total_seconds() / 60
                ev2 = dict(title=ev.get("title"), country=ev.get("country"),
                           forecast=ev.get("forecast"), previous=ev.get("previous"),
                           actual=ev.get("actual"), date_ny=dt.isoformat())
                if -PRE_EVENT_MIN <= -mins <= 0 and f"pre|{eid}" not in st["done_triggers"] \
                        and my_positions():
                    triggers.append(("pre_event", f"pre|{eid}", ev2))
                if POST_EVENT_MIN <= -mins <= POST_EVENT_MIN + 6 \
                        and f"post|{eid}" not in st["done_triggers"]:
                    triggers.append(("post_event", f"post|{eid}", ev2))
            for phase, tid, ev in triggers:
                if st["halted"] or st["runs"] >= CLAUDE_RUNS_MAX:
                    break
                st["done_triggers"].append(tid); st["runs"] += 1
                lib2 = load_cases() if phase == "post_event" else lib
                pk = build_packet(phase, ev, event_symbols(ev), lib2)
                dec, raw = call_claude(pk)
                if dec is None:
                    record(phase, pk, None, raw, "no-json")
                    log(f"{phase} {ev['title']}: no valid JSON — discarded")
                    continue
                ok, why = validate(dec, pk, st)
                verdict = execute(dec, st) if ok else f"rejected: {why}"
                record(phase, pk, dec, raw, verdict)
                log(f"{phase} {ev['title']}: {dec.get('action')} -> {verdict}")
                save_state(st)
            save_state(st)
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            log("stopped"); break
        except Exception as e:
            log(f"loop error: {e}"); time.sleep(120)


# ====================== selftest ===========================================
def selftest():
    ok_all = True

    def check(name, cond):
        nonlocal ok_all
        ok_all &= bool(cond)
        print(f"selftest: {name}: {bool(cond)}")

    # slot parity vs the builder (source of the library keys)
    try:
        import types
        import case_library_builder2 as b2
        pairs = [(8, 30, "M5"), (8, 30, "H1"), (10, 5, "M5"), (14, 0, "M5"),
                 (14, 0, "H1"), (3, 0, "M5"), (3, 0, "H1"), (11, 30, "M5"),
                 (5, 0, "M15"), (8, 25, "M15"), (13, 55, "M5"), (14, 10, "H1"),
                 (16, 0, "M15"), (2, 0, "M15"), (10, 0, "H1")]
        parity = all(
            slot_for_time(types.SimpleNamespace(hour=h, minute=m), tf)
            == b2.slot_of(h, m, tf) for h, m, tf in pairs)
        check("slot parity with case_library_builder2", parity)
    except ImportError:
        print("selftest: (case_library_builder2 not present — slot parity skipped; "
              "rules are inlined identically)")
    # family parity vs the archive builder, when present
    try:
        import news_archive_builder as nab
        titles = ["Non-Farm Employment Change", "CPI m/m", "Core CPI y/y",
                  "Federal Funds Rate", "Unemployment Claims", "Official Bank Rate",
                  "ECB Press Conference", "Some Unknown Event"]
        check("family parity with news_archive_builder",
              all(family_of(t) == nab.family_of(t) for t in titles))
    except ImportError:
        print("selftest: (news_archive_builder not present — family parity skipped)")
    # value parsing
    check("parse 206K", parse_val("206K") == 206000.0)
    check("parse 0.3%", parse_val("0.3%") == 0.3)
    check("parse <0.25%", parse_val("<0.25%") == 0.25)
    check("parse garbage -> None", parse_val("1.2%-2.3%") is None)
    # surprise buckets
    check("bucket 1.5 -> big_up", surprise_bucket(1.5) == "big_up")
    check("bucket -0.3 -> down", surprise_bucket(-0.3) == "down")
    check("bucket 0.1 -> inline", surprise_bucket(0.1) == "inline")
    # JSON extraction
    check("extract plain", (extract_json('{"action":"none"}') or {}).get("action") == "none")
    check("extract fenced",
          (extract_json('bla\n```json\n{"action":"open","symbol":"XAUUSD"}\n```')
           or {}).get("symbol") == "XAUUSD")
    check("extract with preamble",
          (extract_json('I think {"x":1} then {"action":"none"} ok')
           or {}).get("action") == "none")
    check("extract garbage -> None", extract_json("no json here") is None)
    # citation gate
    pk = dict(precedent={"XAUUSD": [dict(n=43, cont_1h=0.51)]})
    check("cited real case passes",
          cited_case_ok(dict(case_refs=[dict(n=43, cont=0.51)]), pk))
    check("invented case fails",
          not cited_case_ok(dict(case_refs=[dict(n=999, cont=0.9)]), pk))
    check("small case fails", not cited_case_ok(dict(case_refs=[dict(n=6)]),
          dict(precedent={"XAUUSD": [dict(n=6)]})))
    # whitelist
    check("whitelist rejects BTCUSD", "BTCUSD" not in WHITELIST)
    # v2 library loads + queries, when present
    if os.path.exists(CASE_LIB):
        try:
            lib = load_cases()
            rows = query_cases(lib, "XAUUSD", slot="0830_data", family="CPI_MM",
                               surprise="big_up")
            check("v2 library query returns rows", len(rows) > 0)
        except SystemExit as e:
            print(f"selftest: library check FAILED: {e}"); ok_all = False
    print("selftest", "PASSED" if ok_all else "FAILED",
          "(plumbing only — full validation needs MT5+claude on the target machine)")
    sys.exit(0 if ok_all else 1)


def main():
    if "--selftest" in sys.argv:
        selftest(); return
    global mt5
    import MetaTrader5 as _mt5
    mt5 = _mt5
    if not mt5.initialize(path=TERMINAL_PATH):
        log(f"cannot attach demo terminal: {mt5.last_error()}"); sys.exit(1)
    ai = mt5.account_info()
    # ---------------- HARD DEMO LOCK — DO NOT REMOVE ----------------
    if ai is None or ai.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        log("!!! REFUSING TO RUN: not a DEMO account. The ANALYST is demo-only "
            "until it earns promotion through its reviewed tradebook.")
        mt5.shutdown(); sys.exit(1)
    # ----------------------------------------------------------------
    watcher()
    mt5.shutdown()


if __name__ == "__main__":
    main()
