"""
Symbol Configuration - Exclusions, Mappings, and Fallbacks
Now uses intelligent category-based grouping via etf_categorizer
"""
from etf_categorizer import find_alternatives_smart, get_etf_category

EXCLUDED_SYMBOLS = [
    'GOLDSHARE',
]

GLOBAL_SYMBOL_MAPPING = {
    'GOLDSHARE': 'GOLDBEES',
}

BROKER_SPECIFIC_MAPPING = {
    'ZERODHA': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'DHAN': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'FINVASIA': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'ANGEL': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'ANGELONE': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'ANGLE': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'GROWW': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'UPSTOX': {
        'GOLDSHARE': 'GOLDBEES',
    },
}


def get_mapped_symbol(original_symbol, broker_name=None):
    """Get mapped symbol for broker or global mapping"""
    original_symbol = original_symbol.strip().upper()
    
    if broker_name:
        broker_name = broker_name.strip().upper()
        if broker_name in BROKER_SPECIFIC_MAPPING:
            if original_symbol in BROKER_SPECIFIC_MAPPING[broker_name]:
                return BROKER_SPECIFIC_MAPPING[broker_name][original_symbol]
    
    if original_symbol in GLOBAL_SYMBOL_MAPPING:
        return GLOBAL_SYMBOL_MAPPING[original_symbol]
    
    return None


def calculate_alternative_qty(original_qty, original_price, alternative_price):
    """Calculate quantity for alternative symbol based on amount preservation"""
    if alternative_price <= 0:
        return 0
    
    original_amount = original_qty * original_price
    new_qty = int(original_amount / alternative_price)
    
    return max(1, new_qty)


def find_alternative_by_underlying_asset(failed_symbol, full_etf_df, exclude_symbols=None):
    """
    Find alternative ETF using intelligent category-based matching
    Now uses etf_categorizer for robust grouping by actual asset category
    Sorts by: Volume DESC (most important), Price ASC (secondary)
    
    Args:
        failed_symbol: Original symbol that failed
        full_etf_df: Complete ETF dataframe with SYMBOL, UNDERLYING_ASSET, VOLUME, LTP
        exclude_symbols: List of symbols already tried (to skip)
    
    Returns:
        list: [{'symbol': 'ALT1', 'price': 100.0, 'volume': 50000, ...}, ...]
    """
    return find_alternatives_smart(failed_symbol, full_etf_df, exclude_symbols)
