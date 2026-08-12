"""Unit harness for the Aug 2026 gold dollar-risk sizing change.

Stubs MetaTrader5, imports the bot module, re-anchors it to the live PROP
config ($6K, $45 cap, gold lot 0.02) and drives _gold_usd_risk_guard through
the real logged scenarios plus boundary cases.

Run from anywhere: python verify_gold_sizing.py
(needs numpy+pandas; does NOT need MetaTrader5 or a terminal)
"""
import os
import sys
import types
import tempfile
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(tempfile.mkdtemp(prefix="gold_sizing_verify_"))  # keep bot log files out of the repo

# ---- stub MetaTrader5 before import ----
class _SymInfo:
    volume_step = 0.01
    volume_min = 0.01
    digits = 2
    filling_mode = 2

fake = types.ModuleType("MetaTrader5")
def _const(name):
    return 0
for c in ["TIMEFRAME_M5", "TIMEFRAME_M15", "TIMEFRAME_M30", "TIMEFRAME_H1",
          "TIMEFRAME_H4", "TIMEFRAME_D1", "ORDER_FILLING_FOK", "ORDER_FILLING_IOC",
          "ORDER_FILLING_RETURN", "TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING",
          "TRADE_ACTION_REMOVE", "TRADE_ACTION_SLTP", "TRADE_ACTION_MODIFY",
          "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "ORDER_TYPE_BUY_LIMIT",
          "ORDER_TYPE_SELL_LIMIT", "ORDER_TIME_GTC", "ORDER_TIME_SPECIFIED",
          "TRADE_RETCODE_DONE", "POSITION_TYPE_BUY", "POSITION_TYPE_SELL",
          "COPY_TICKS_ALL"]:
    setattr(fake, c, 0)
fake.symbol_info = lambda s: _SymInfo()
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

# ---- re-anchor to the live PROP numbers ----
bot.XAUUSD_MAX_RISK_USD = 45.0
bot.XAUUSD_MIN_RISK_USD = 1.0
bot.RISK_THROTTLE_ENABLED = False
KEY = "XAUUSD_BOS"
bot.LOTS[KEY] = 0.02
INST = {"symbol": "XAUUSD"}

failures = []
def check(name, risk_points, want_skip, want_lot, lots=0.02):
    bot.LOTS[KEY] = lots
    skip, lot = bot._gold_usd_risk_guard(KEY, INST, risk_points)
    skipped = skip is not None
    ok = (skipped == want_skip) and (lot == want_lot)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: risk_pts={risk_points} lots_cfg={lots} -> "
          f"skip={skip!r} lot={lot}")
    if not ok:
        failures.append(name)

# The three real skipped trades from the FundedNext log (per-0.01-lot risk =
# half the logged 0.02-lot figures: $78.92, $67.37, $68.79)
check("log Aug10 BOS  ($78.92 @0.02)", 39.46, False, 0.01)
check("log Aug11 DONCH($67.37 @0.02)", 33.685, False, 0.01)
check("log Aug12 BOS  ($68.79 @0.02)", 34.395, False, 0.01)

# unchanged behavior: fits at configured lot
check("fits at 0.02 ($40)", 20.0, False, 0.02)
check("exact cap boundary ($45 at 0.02)", 22.5, False, 0.02)
check("just over boundary -> 0.01", 22.51, False, 0.01)

# still skipped: even 0.01 lot busts the cap
check("even min lot busts cap ($46)", 46.0, True, None)
check("way over ($120)", 120.0, True, None)

# min floor preserved
check("under $1 floor at sized lot", 0.4, True, None)
check("just above floor", 0.6, False, 0.02)   # 0.6*2 = $1.20 >= $1

# non-gold untouched
skip, lot = bot._gold_usd_risk_guard("EURUSD_E", {"symbol": "EURUSD"}, 50.0)
ok = skip is None and lot is None
print(f"[{'PASS' if ok else 'FAIL'}] non-gold passthrough -> skip={skip!r} lot={lot}")
if not ok:
    failures.append("non-gold")

# throttle interaction: throttled base lot is the ceiling
bot.RISK_THROTTLE_ENABLED = True
bot._RISK_MULT["m"] = 0.5
check("drawdown throttle halves ceiling", 10.0, False, 0.01, lots=0.02)
bot._RISK_MULT["m"] = 1.0
bot.RISK_THROTTLE_ENABLED = False

# solo-book config (cap $20, lot 0.01) — regression vs old behavior
bot.XAUUSD_MAX_RISK_USD = 20.0
check("solo: $18 at 0.01 passes", 18.0, False, 0.01, lots=0.01)
check("solo: $32 ATR stop still skipped", 32.0, True, None, lots=0.01)

print()
if failures:
    print(f"FAILURES: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
