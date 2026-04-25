"""
Month simulation: 10K SIP client, market falls ~10 out of 20 trading days.
Shows day-by-day how daily budget adjusts and total monthly invested.

Scenario: realistic month with varying fall severity.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_MONTHLY = 8000.0
TRADING_DAYS = 20
MAX_SINGLE_ETF_PCT = 12.0
SEVERITY_BOOST_MAX = 1.15
SIP = 10000

# Tier allocation config
TIER_A_PCT = 60
TIER_B_PCT = 30
TIER_C_PCT = 10

# Simulated ETFs with real prices (from ETF_Data_2026-04-07.csv)
ETFS = [
    # (Symbol, LTP, Tier)
    ("TOP100CASE",  9.95,  "A"),
    ("TATAGOLD",   14.29,  "A"),
    ("MONIFTY500", 21.73,  "A"),
    ("TATSILV",    22.40,  "A"),
    ("PHARMABEES", 22.48,  "A"),
    ("AUTOIETF",   25.17,  "A"),
    ("PVTBANIETF", 25.57,  "A"),
    ("ITBEES",     34.60,  "A"),
    ("NEXT50IETF", 66.57,  "A"),
    ("CONSUMER",   10.18,  "B"),
    ("OILIETF",    10.94,  "B"),
    ("METALIETF",  11.82,  "B"),
    ("VAL30IETF",  14.90,  "B"),
    ("QUAL30IETF", 19.40,  "B"),
    ("MIDCAPETF",  20.52,  "B"),
    ("BFSI",       25.52,  "B"),
    ("HDFCPVTBAN", 25.64,  "B"),
    ("MOM30IETF",  28.80,  "B"),
    ("GROWWRAIL",  29.30,  "B"),
    ("SMALLCAP",   39.63,  "B"),
    ("INFRAIETF",  89.99,  "B"),
    ("PSUBNKBEES", 91.78,  "B"),
    ("GROWWPOWER", 10.36,  "C"),
    ("AONETOTAL",  10.79,  "C"),
    ("MULTICAP",   14.86,  "C"),
    ("LOWVOLIETF", 20.80,  "C"),
    ("LTGILTBEES", 28.92,  "C"),
    ("MNC",        29.61,  "C"),
    ("ALPHA",      44.69,  "C"),
    ("MOREALTY",   69.88,  "C"),
    ("TNIDETF",    80.90,  "C"),
    ("MODEFENCE",  85.42,  "C"),
    ("LIQUIDCASE",113.51,  "C"),
    ("MON100",    244.81,  "C"),
]

def simulate_day(etf_subset, daily_budget, severity_boost, sip_monthly):
    """Simulate a single day's investment with given qualifying ETFs."""
    adjusted_budget = daily_budget * severity_boost
    max_per_etf = (MAX_SINGLE_ETF_PCT / 100.0) * sip_monthly
    
    # Count per tier
    tier_counts = {}
    for sym, ltp, tier in etf_subset:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    
    active_tiers = {t for t in ['A','B','C'] if tier_counts.get(t,0) > 0}
    inactive_pct = sum({'A':TIER_A_PCT,'B':TIER_B_PCT,'C':TIER_C_PCT}[t] 
                       for t in ['A','B','C'] if t not in active_tiers)
    active_total = sum({'A':TIER_A_PCT,'B':TIER_B_PCT,'C':TIER_C_PCT}[t] for t in active_tiers) or 1
    
    # Calculate allocation per ETF
    results = []
    for sym, ltp, tier in etf_subset:
        base_pct = {'A':TIER_A_PCT,'B':TIER_B_PCT,'C':TIER_C_PCT}[tier]
        eff_pct = base_pct + inactive_pct * (base_pct / active_total)
        alloc = adjusted_budget * (eff_pct / 100.0) / tier_counts[tier]
        qty = int(alloc / ltp) if ltp > 0 else 0
        amount = qty * ltp
        if amount > max_per_etf:
            qty = int(max_per_etf / ltp)
            amount = qty * ltp
        results.append((sym, ltp, tier, alloc, qty, amount))
    
    # Reallocate from 0-qty ETFs within each tier
    for tier in active_tiers:
        tier_items = [r for r in results if r[2] == tier]
        zero_alloc = sum(r[3] for r in tier_items if r[4] == 0)
        nonzero = [r for r in tier_items if r[4] > 0]
        if zero_alloc > 0 and nonzero:
            extra = zero_alloc / len(nonzero)
            new_results = []
            for r in results:
                if r[2] == tier and r[4] > 0:
                    new_alloc = r[3] + extra
                    new_qty = int(new_alloc / r[1])
                    new_amount = new_qty * r[1]
                    new_results.append((r[0], r[1], r[2], new_alloc, new_qty, new_amount))
                else:
                    new_results.append(r)
            results = new_results
    
    total = sum(r[5] for r in results)
    bought = sum(1 for r in results if r[4] > 0)
    return total, bought, results


def main():
    # Define a realistic month: 20 trading days, ~10 with falls
    # Some days: few ETFs fall (mild), some: moderate, some: broad crash
    # Day pattern: (num_etf_qualifying, severity_description, avg_severity)
    month_pattern = [
        # Day 1-5 (week 1)
        (0,   "flat",          0.0),   # Day 1: market flat
        (3,   "mild dip",      0.5),   # Day 2: only 3 ETFs fall
        (0,   "flat",          0.0),   # Day 3: flat
        (8,   "moderate fall", 1.5),   # Day 4: 8 ETFs fall
        (0,   "flat",          0.0),   # Day 5: flat
        # Day 6-10 (week 2)
        (5,   "mild fall",     0.8),   # Day 6
        (0,   "flat",          0.0),   # Day 7
        (0,   "flat",          0.0),   # Day 8
        (15,  "broad fall",    2.0),   # Day 9: major fall
        (4,   "mild dip",      0.5),   # Day 10
        # Day 11-15 (week 3)
        (0,   "flat",          0.0),   # Day 11
        (6,   "moderate",      1.2),   # Day 12
        (0,   "flat",          0.0),   # Day 13
        (20,  "crash day",     3.0),   # Day 14: crash!
        (0,   "flat",          0.0),   # Day 15
        # Day 16-20 (week 4)
        (3,   "mild bounce",   0.3),   # Day 16
        (0,   "flat",          0.0),   # Day 17
        (7,   "moderate fall", 1.0),   # Day 18
        (0,   "flat",          0.0),   # Day 19
        (10,  "end-month dip", 1.5),   # Day 20: 10 ETFs
    ]
    
    print("="*100)
    print(f"FULL MONTH SIMULATION: Rs.{SIP:,} SIP | 20 trading days | 10 fall days")
    print(f"BASE_MONTHLY = Rs.{BASE_MONTHLY:,.0f} | Tier split: A={TIER_A_PCT}% B={TIER_B_PCT}% C={TIER_C_PCT}%")
    print("="*100)
    
    cumulative = 0.0
    print(f"\n{'Day':>4} {'Desc':<16} {'ETFs':>4} {'Remaining':>12} {'RemDays':>8} {'DlyBdgt':>10} "
          f"{'Boost':>6} {'Invested':>10} {'Cumul':>10} {'%SIP':>6}")
    print("-" * 100)
    
    day_details = []
    
    for day_num, (num_etfs, desc, avg_sev) in enumerate(month_pattern, 1):
        remaining_sip = max(0, SIP - cumulative)
        remaining_days = max(1, TRADING_DAYS - day_num + 1)
        
        if num_etfs == 0:
            # No qualifying ETFs, no investment
            print(f"  {day_num:>2}  {desc:<16} {0:>4} {remaining_sip:>12,.2f} {remaining_days:>8} "
                  f"{'--':>10} {'--':>6} {'0.00':>10} {cumulative:>10,.2f} {cumulative/SIP*100:>5.0f}%")
            day_details.append((day_num, desc, 0, 0, cumulative))
            continue
        
        # Pick top N ETFs from the list (Tier A first)
        sorted_etfs = sorted(ETFS, key=lambda x: {'A':0,'B':1,'C':2}[x[2]])
        selected = sorted_etfs[:num_etfs]
        
        # Severity boost
        severity_boost = min(SEVERITY_BOOST_MAX, 1.0 + avg_sev * 0.05)
        
        # Daily budget based on remaining
        daily_budget = remaining_sip / remaining_days
        
        # Simulate
        invested, bought, results = simulate_day(selected, daily_budget, severity_boost, SIP)
        cumulative += invested
        
        print(f"  {day_num:>2}  {desc:<16} {num_etfs:>4} {remaining_sip:>12,.2f} {remaining_days:>8} "
              f"{daily_budget:>10,.2f} {severity_boost:>5.2f}x {invested:>10,.2f} {cumulative:>10,.2f} {cumulative/SIP*100:>5.0f}%")
        
        day_details.append((day_num, desc, bought, invested, cumulative))
    
    print("-" * 100)
    print(f"\n  MONTHLY TOTAL INVESTED: Rs.{cumulative:,.2f}")
    print(f"  SIP TARGET:            Rs.{SIP:,}")
    print(f"  DEPLOYMENT:            {cumulative/SIP*100:.1f}% of SIP")
    fall_days = sum(1 for d in month_pattern if d[0] > 0)
    print(f"  FALL DAYS:             {fall_days} / {TRADING_DAYS}")
    print(f"  AVG PER FALL DAY:      Rs.{cumulative/fall_days:,.2f}")
    
    # Detailed breakdown of each fall day
    print(f"\n{'='*100}")
    print(f"DETAILED BREAKDOWN OF EACH FALL DAY")
    print(f"{'='*100}")
    
    cumulative2 = 0.0
    for day_num, (num_etfs, desc, avg_sev) in enumerate(month_pattern, 1):
        if num_etfs == 0:
            continue
        
        remaining_sip = max(0, SIP - cumulative2)
        remaining_days = max(1, TRADING_DAYS - day_num + 1)
        daily_budget = remaining_sip / remaining_days
        severity_boost = min(SEVERITY_BOOST_MAX, 1.0 + avg_sev * 0.05)
        
        sorted_etfs = sorted(ETFS, key=lambda x: {'A':0,'B':1,'C':2}[x[2]])
        selected = sorted_etfs[:num_etfs]
        
        invested, bought, results = simulate_day(selected, daily_budget, severity_boost, SIP)
        cumulative2 += invested
        
        print(f"\n  Day {day_num}: {desc} | {num_etfs} ETFs | Budget Rs.{daily_budget:.0f} x {severity_boost:.2f} = Rs.{daily_budget*severity_boost:.0f}")
        print(f"  {'Symbol':<14} {'Tier':>4} {'LTP':>8} {'Alloc':>8} {'Qty':>5} {'Amount':>8}")
        for sym, ltp, tier, alloc, qty, amount in sorted(results, key=lambda x: -x[5]):
            if qty > 0:
                print(f"  {sym:<14} {tier:>4} {ltp:>8.2f} {alloc:>8.2f} {qty:>5} {amount:>8.2f}")
        print(f"  >> Invested: Rs.{invested:,.2f} | Cumulative: Rs.{cumulative2:,.2f} ({cumulative2/SIP*100:.0f}%)")
    
    # Now do same for all SIP levels
    print(f"\n{'='*100}")
    print(f"SUMMARY: SAME MONTH PATTERN ACROSS ALL SIP LEVELS")
    print(f"{'='*100}")
    
    sip_levels = [10000, 25000, 50000, 100000, 200000]
    
    print(f"\n  {'SIP':>10} {'Total Inv.':>12} {'% SIP':>8} {'Fall Days':>10} {'Avg/Day':>10}")
    print(f"  {'-'*10} {'-'*12} {'-'*8} {'-'*10} {'-'*10}")
    
    for sip in sip_levels:
        cum = 0.0
        for day_num, (num_etfs, desc, avg_sev) in enumerate(month_pattern, 1):
            if num_etfs == 0:
                continue
            rem_sip = max(0, sip - cum)
            rem_days = max(1, TRADING_DAYS - day_num + 1)
            daily_b = rem_sip / rem_days
            sev_b = min(SEVERITY_BOOST_MAX, 1.0 + avg_sev * 0.05)
            sorted_e = sorted(ETFS, key=lambda x: {'A':0,'B':1,'C':2}[x[2]])
            sel = sorted_e[:num_etfs]
            inv, _, _ = simulate_day(sel, daily_b, sev_b, sip)
            cum += inv
        
        print(f"  Rs.{sip:>7,} {cum:>12,.2f} {cum/sip*100:>7.0f}% {fall_days:>10} {cum/fall_days:>10,.2f}")


if __name__ == "__main__":
    main()
