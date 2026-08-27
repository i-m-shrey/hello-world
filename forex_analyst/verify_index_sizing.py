"""Unit harness for the rev11 index dollar-risk sizer (§2f, Aug 2026).

Stubs MetaTrader5, imports the bot module, re-anchors it to the live PROP
config ($6K -> $45/trade budget) and drives _index_usd_risk_lot /
_usd_risk_guard through the FundedNext-measured contract specs plus boundary
cases. The per-point dollar values below are the ones measured from the live
Phase-2 tradebook (tick-verified Aug 13 2026):
    GER30  10 EUR/pt  -> $11.539/pt/lot      SPX500 10 USD/pt -> $10.00/pt/lot
    JP225  10 JPY/pt  -> $0.0628/pt/lot      HK50   10 HKD/pt -> $1.286/pt/lot

Run from anywhere: python verify_index_sizing.py
(needs numpy+pandas; does NOT need MetaTrader5 or a terminal)
"""
import os
import sys
import types
import tempfile
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(tempfile.mkdtemp(prefix="index_sizing_verify_"))  # keep bot logs out of the repo

# ---- stub MetaTrader5 before import ----
class _SymInfo:
    volume_step = 0.01
    volume_min = 0.01
    volume_max = 100.0
    digits = 2
    filling_mode = 2
    trade_tick_value = 0.0
    trade_tick_size = 0.0

fake = types.ModuleType("MetaTrader5")
for c in ["TIMEFRAME_M5", "TIMEFRAME_M15", "TIMEFRAME_M30", "TIMEFRAME_H1",
          "TIMEFRAME_H4", "TIMEFRAME_D1", "ORDER_FILLING_FOK", "ORDER_FILLING_IOC",
          "ORDER_FILLING_RETURN", "TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING",
          "TRADE_ACTION_REMOVE", "TRADE_ACTION_SLTP", "TRADE_ACTION_MODIFY",
          "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "ORDER_TYPE_BUY_LIMIT",
          "ORDER_TYPE_SELL_LIMIT", "ORDER_TIME_GTC", "ORDER_TIME_SPECIFIED",
          "TRADE_RETCODE_DONE", "POSITION_TYPE_BUY", "POSITION_TYPE_SELL",
          "COPY_TICKS_ALL"]:
    setattr(fake, c, 0)

# FundedNext-measured $-per-point per 1.0 lot (drives the order_calc_profit stub)
PT_VALUE = {
    "GER30.s": 11.539, "SPX500.s": 10.0, "US30.s": 2.5,
    "JP225.s": 0.0628, "HK50.s": 1.286,
}
_CALC_ENABLED = {"on": True}

def _sym_info(s):
    return _SymInfo()

def _calc_profit(otype, sym, lots, entry, stop):
    if not _CALC_ENABLED["on"]:
        return None
    v = PT_VALUE.get(sym)
    if v is None:
        return None
    return -abs(entry - stop) * v * lots

fake.symbol_info = _sym_info
fake.order_calc_profit = _calc_profit
fake.account_info = lambda: None
fake.positions_get = lambda **k: []
fake.orders_get = lambda **k: []
sys.modules["MetaTrader5"] = fake

smc = types.ModuleType("smc_engine")
class _Any:
    def __getitem__(self, k):
        return _Any()
    def get(self, k, d=None):
        return _Any()
    def __float__(self):
        return 0.0
    def __int__(self):
        return 0
smc.STRAT = _Any()
def _smc_getattr(name):
    return lambda *a, **k: None
smc.__getattr__ = _smc_getattr
sys.modules["smc_engine"] = smc
sys.path.insert(0, _HERE)

spec = importlib.util.spec_from_file_location(
    "bot", os.path.join(_HERE, "live_mt5_bot_FINAL.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

# ---- broker name mapping like the live FundedNext config ----
_MAP = {"GER40": "GER30.s", "SPX500": "SPX500.s", "US30": "US30.s",
        "JPN225": "JP225.s", "HK50": "HK50.s"}
bot.broker_sym = lambda s: _MAP.get(s, s)
bot.RISK_THROTTLE_ENABLED = False

failures = []
def check(name, key, symbol, risk_pts, want_skip, want_lot, entry=None):
    entry = 100.0 * risk_pts if entry is None else entry   # arbitrary but consistent
    stop = entry - risk_pts
    skip, lot = bot._usd_risk_guard(key, {"symbol": symbol}, risk_pts,
                                    "long", entry, stop)
    skipped = skip is not None
    ok = (skipped == want_skip) and (lot == want_lot)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {key} risk_pts={risk_pts} -> skip={skip!r} lot={lot}")
    if not ok:
        failures.append(name)

# ---- feature OFF: legacy passthrough everywhere ----
bot.INDEX_RISK_TARGET_USD = 0.0
check("feature off -> legacy", "GER40_DONCH", "GER40", 123.52, False, None)

# ---- PROP wiring: _apply_prop_mode sets the target to the $45 budget ----
bot.PROP_MODE = True
bot._apply_prop_mode()
ok = bot.INDEX_RISK_TARGET_USD == 45.0
print(f"[{'PASS' if ok else 'FAIL'}] PROP_MODE wiring -> INDEX_RISK_TARGET_USD="
      f"{bot.INDEX_RISK_TARGET_USD}")
if not ok:
    failures.append("prop wiring")

# ---- the four live-audit scenarios (Aug 2026 tradebook) ----
# GER40 123.52-pt stop: legacy 0.04 risked $57.01 -> sized 0.03 risks $42.74
check("GER40 live stop ($57 -> $43)", "GER40_DONCH", "GER40", 123.52, False, 0.03)
# SPX500 21.43-pt stop: legacy 0.04 risked $8.57 -> sized 0.20 risks $42.86
check("SPX500 live stop ($8.6 -> $43)", "SPX500_DONCH", "SPX500", 21.43, False, 0.20)
# US30 promoted: 300-pt stop at $2.5/pt/lot -> 0.06 lot risks $45.00
check("US30 promoted ($45)", "US30_DONCH", "US30", 300.0, False, 0.06)
# JPN225 excluded by triage: passthrough to the legacy dust lot
check("JPN225 excluded -> legacy", "JPN225_DONCH", "JPN225", 736.0, False, None)
# HK50 excluded (and disabled): passthrough
check("HK50 excluded -> legacy", "HK50_MACROSS", "HK50", 165.55, False, None)
ok = bot.ENABLE.get("HK50_MACROSS") is False
print(f"[{'PASS' if ok else 'FAIL'}] HK50_MACROSS disabled -> ENABLE="
      f"{bot.ENABLE.get('HK50_MACROSS')}")
if not ok:
    failures.append("hk50 enable")

# ---- boundaries ----
# min-lot bust: a contract so big even 0.01 lot risks over the target
PT_VALUE["US30.s"] = 6000.0
check("min lot busts target -> skip", "US30_DONCH", "US30", 1.0, True, None)
PT_VALUE["US30.s"] = 2.5
# ceiling: tiny per-lot risk wants 9.0 lots -> capped at INDEX_RISK_MAX_LOTS
PT_VALUE["SPX500.s"] = 10.0
check("ceiling clamps to 5.0 lots", "SPX500_DONCH", "SPX500", 0.5, False, 5.0)
# exact fit: budget divides cleanly into whole volume steps
check("clean divide -> 0.45 lot", "SPX500_DONCH", "SPX500", 10.0, False, 0.45)

# ---- throttle scales the TARGET like FX sizing ----
bot.RISK_THROTTLE_ENABLED = True
bot._RISK_MULT["m"] = 0.5
check("throttle halves target", "GER40_DONCH", "GER40", 123.52, False, 0.01)
bot._RISK_MULT["m"] = 1.0
bot.RISK_THROTTLE_ENABLED = False

# ---- order_calc_profit unavailable -> tick_value/tick_size fallback ----
_CALC_ENABLED["on"] = False
class _TickInfo(_SymInfo):
    trade_tick_value = 11.539
    trade_tick_size = 1.0
fake.symbol_info = lambda s: _TickInfo()
check("tick-data fallback (GER40)", "GER40_DONCH", "GER40", 123.52, False, 0.03)
# no calc AND no tick data -> skip loudly, never a silent mis-size
fake.symbol_info = lambda s: _SymInfo()
check("no pricing data -> skip", "GER40_DONCH", "GER40", 123.52, True, None)
fake.symbol_info = _sym_info
_CALC_ENABLED["on"] = True

# ---- gold path untouched through the dispatcher (regression) ----
bot.XAUUSD_MAX_RISK_USD = 45.0
bot.LOTS["XAUUSD_BOS"] = 0.02
skip, lot = bot._usd_risk_guard("XAUUSD_BOS", {"symbol": "XAUUSD"}, 20.0)
ok = skip is None and lot == 0.02
print(f"[{'PASS' if ok else 'FAIL'}] gold dispatch unchanged -> skip={skip!r} lot={lot}")
if not ok:
    failures.append("gold dispatch")

# ---- non-MINLOT symbol: dispatcher returns passthrough ----
skip, lot = bot._usd_risk_guard("EURUSD_E", {"symbol": "EURUSD"}, 0.005, "long", 1.16, 1.155)
ok = skip is None and lot is None
print(f"[{'PASS' if ok else 'FAIL'}] FX passthrough -> skip={skip!r} lot={lot}")
if not ok:
    failures.append("fx passthrough")

print()
if failures:
    print(f"FAILURES: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
