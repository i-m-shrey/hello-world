"""Unit harness for the rev12 gold $ budget sizer (§2g) + FX floor re-anchor.

Live motivation (Aug 27 audit): +2.83R over 25 trades netted -$177 because
winners deployed $58/R vs losers' $83/R. rev12 sizes gold UP toward the budget
(gap ceiling 3x legacy lot) and floors FX at the budget.
Run from anywhere: python verify_gold_sizeup.py (numpy+pandas only).
"""
import os, sys, types, tempfile, importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(tempfile.mkdtemp(prefix="gold_sizeup_verify_"))

class _S: volume_step = 0.01; volume_min = 0.01; digits = 2; filling_mode = 2
fake = types.ModuleType("MetaTrader5")
for c in ["TIMEFRAME_M5","TIMEFRAME_M15","TIMEFRAME_M30","TIMEFRAME_H1","TIMEFRAME_H4",
          "TIMEFRAME_D1","ORDER_FILLING_FOK","ORDER_FILLING_IOC","ORDER_FILLING_RETURN",
          "TRADE_ACTION_DEAL","TRADE_ACTION_PENDING","TRADE_ACTION_REMOVE","TRADE_ACTION_SLTP",
          "TRADE_ACTION_MODIFY","ORDER_TYPE_BUY","ORDER_TYPE_SELL","ORDER_TYPE_BUY_LIMIT",
          "ORDER_TYPE_SELL_LIMIT","ORDER_TIME_GTC","ORDER_TIME_SPECIFIED","TRADE_RETCODE_DONE",
          "POSITION_TYPE_BUY","POSITION_TYPE_SELL","COPY_TICKS_ALL"]:
    setattr(fake, c, 0)
fake.symbol_info = lambda s: _S(); fake.account_info = lambda: None
fake.positions_get = lambda **k: []; fake.orders_get = lambda **k: []
sys.modules["MetaTrader5"] = fake
smc = types.ModuleType("smc_engine")
class _A:
    def __getitem__(s, k): return _A()
    def get(s, k, d=None): return _A()
smc.STRAT = _A(); smc.__getattr__ = lambda n: (lambda *a, **k: None)
sys.modules["smc_engine"] = smc
sys.path.insert(0, _HERE)

spec = importlib.util.spec_from_file_location("bot", os.path.join(_HERE, "live_mt5_bot_FINAL.py"))
bot = importlib.util.module_from_spec(spec); spec.loader.exec_module(bot)

failures = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: failures.append(name)

# PROP wiring at 15K: budget + FX floor set
bot.PROP_MODE = True; bot.PROP_ACCOUNT_SIZE = 15000.0
bot._apply_prop_mode()
check("PROP sets GOLD_RISK_TARGET_USD=112.5", bot.GOLD_RISK_TARGET_USD == 112.5)
check("PROP sets FX_MIN_RISK_USD=112.5 (floor==cap)", bot.FX_MIN_RISK_USD == 112.5)

bot.RISK_THROTTLE_ENABLED = False
KEY, INST = "XAUUSD_S6", {"symbol": "XAUUSD"}
bot.LOTS[KEY] = 0.05   # 15K legacy gold lot

def guard(risk):
    return bot._gold_usd_risk_guard(KEY, INST, risk)

# live-audit scenarios (risk_points = $ per 0.01 lot)
s, l = guard(16.51);  check(f"S6 $16.51 stop: 0.05->0.06 ($99.1) [{l}]", s is None and l == 0.06)
s, l = guard(9.90);   check(f"S6 $9.90 stop: 0.05->0.11 ($108.9) [{l}]", s is None and l == 0.11)
s, l = guard(27.47);  check(f"S5 $27.47 stop: 0.05->0.04 down ($109.9) [{l}]", s is None and l == 0.04)
s, l = guard(3.0);    check(f"micro $3 stop: gap ceiling 0.15 ($45) [{l}]", s is None and l == 0.15)
s, l = guard(120.0);  check(f"$120 stop busts $112.5 even at 0.01 -> skip [{s is not None}]", s is not None and l is None)
# legacy behavior preserved when the feature is off
bot.GOLD_RISK_TARGET_USD = 0.0
s, l = guard(16.51);  check(f"target=0 legacy: fixed 0.05 [{l}]", s is None and l == 0.05)
bot.GOLD_RISK_TARGET_USD = 112.5
# throttle halves the ceiling via base lot
bot.RISK_THROTTLE_ENABLED = True; bot._RISK_MULT["m"] = 0.5
s, l = guard(9.90);   check(f"throttled: ceiling 3x0.02=0.06... fit min [{l}]", s is None and l == 0.06)
bot.RISK_THROTTLE_ENABLED = False; bot._RISK_MULT["m"] = 1.0

print()
if failures:
    print("FAILURES:", failures); sys.exit(1)
print("ALL CHECKS PASSED")
