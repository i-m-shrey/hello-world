"""SWAP AUDIT (July 2026) — dumps the broker's REAL per-symbol swap rates so the
holding-cost gap can be closed with true numbers instead of a flat $7 assumption.
Read-only. Run on the owner's machine: python swap_audit.py"""
import re
import sys


def main():
    import MetaTrader5 as mt5
    src = open("live_mt5_bot.py", encoding="utf-8").read()

    def grab(pat):
        m = re.search(pat, src, re.M)
        if not m:
            sys.exit(f"cannot find {pat}")
        return m.group(1)
    ok = mt5.initialize(grab(r'^MT5_TERMINAL_PATH\s*=\s*"(.+)"').encode().decode("unicode_escape"),
                        login=int(grab(r"^MT5_ACCOUNT\s*=\s*(\d+)")),
                        password=grab(r'^MT5_PASSWORD\s*=\s*"([^"]+)"'),
                        server=grab(r'^MT5_SERVER\s*=\s*"([^"]+)"'))
    if not ok:
        sys.exit(f"init failed: {mt5.last_error()}")
    syms = ("XAUUSD", "XAGUSD", "EURUSD.i", "GBPUSD.i", "USDCAD.i", "USDCHF.i",
            "SPX500", "GER40", "US30", "JPN225", "HK50")
    mode = {0: "points", 1: "base ccy", 2: "margin ccy", 3: "deposit ccy",
            4: "percent (interest)", 5: "percent (open price)"}
    print(f"{'symbol':10s} {'swap_long':>10s} {'swap_short':>10s} {'mode':18s} 3-day")
    for s in syms:
        i = mt5.symbol_info(s)
        if i is None:
            print(f"{s:10s} NOT FOUND"); continue
        print(f"{s:10s} {i.swap_long:10.2f} {i.swap_short:10.2f} "
              f"{mode.get(i.swap_mode, i.swap_mode):18s} day{i.swap_rollover3days}")
    mt5.shutdown()


if __name__ == "__main__":
    main()
