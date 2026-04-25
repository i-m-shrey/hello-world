"""
ETF Categorizer - Intelligent grouping of ETFs by underlying asset category
Uses keyword matching on both symbol name and underlying asset description
Automatically handles new ETFs based on keyword patterns
"""
import re


CATEGORY_KEYWORDS = {
    'GOLD': {
        'symbol_keywords': ['GOLD'],
        'asset_keywords': ['gold', 'commodity gold', 'domestic price of gold', 'domestic price of physical gold', 'physical gold'],
        'priority': 1
    },
    'SILVER': {
        'symbol_keywords': ['SILVER', 'SILV'],
        'asset_keywords': ['silver', 'commodity silver', 'commodity-silver', 'domestic price of silver', 'physical silver', 'physical price of silver'],
        'priority': 2
    },
    'NIFTY_50': {
        'symbol_keywords': ['NIFTY50', 'NIFTY 50', 'N50'],
        'asset_keywords': ['nifty 50', 'nifty50', 'nifty 50 index'],
        'priority': 3
    },
    'NIFTY_BANK': {
        'symbol_keywords': ['BANK', 'NIFTYBANK', 'BANKNIFTY'],
        'asset_keywords': ['nifty bank', 'bank index', 'banking'],
        'priority': 4
    },
    'NIFTY_PRIVATE_BANK': {
        'symbol_keywords': ['PVTBANK', 'PRIVATEBANK'],
        'asset_keywords': ['private bank', 'nifty private bank'],
        'priority': 5
    },
    'NIFTY_PSU_BANK': {
        'symbol_keywords': ['PSUBANK', 'PSUB'],
        'asset_keywords': ['psu bank', 'public sector bank', 'bse psu bank'],
        'priority': 6
    },
    'HEALTHCARE': {
        'symbol_keywords': ['HEALTH', 'PHARMA', 'HEALTHCARE'],
        'asset_keywords': ['healthcare', 'health', 'pharma', 'pharmaceutical', 's&p bse healthcare'],
        'priority': 7
    },
    'IT': {
        'symbol_keywords': ['IT', 'TECH', 'INFORMATION'],
        'asset_keywords': ['nifty it', 'information technology', 'it index', 'technology'],
        'priority': 8
    },
    'INFRASTRUCTURE': {
        'symbol_keywords': ['INFRA'],
        'asset_keywords': ['infrastructure', 'nifty infra', 'bse india infrastructure'],
        'priority': 9
    },
    'REALTY': {
        'symbol_keywords': ['REALTY', 'REAL'],
        'asset_keywords': ['realty', 'real estate', 'nifty realty'],
        'priority': 10
    },
    'ENERGY': {
        'symbol_keywords': ['ENERGY', 'OIL', 'GAS'],
        'asset_keywords': ['energy', 'oil', 'gas', 'nifty energy'],
        'priority': 11
    },
    'AUTO': {
        'symbol_keywords': ['AUTO', 'AUTOMOBILE'],
        'asset_keywords': ['auto', 'automobile', 'automotive', 'nifty auto'],
        'priority': 12
    },
    'FMCG': {
        'symbol_keywords': ['FMCG', 'CONSUMPTION'],
        'asset_keywords': ['fmcg', 'consumption', 'nifty consumption', 'nifty india consumption'],
        'priority': 13
    },
    'MANUFACTURING': {
        'symbol_keywords': ['MANUFACT', 'MFG'],
        'asset_keywords': ['manufacturing', 'nifty india manufacturing'],
        'priority': 14
    },
    'PSU': {
        'symbol_keywords': ['PSU'],
        'asset_keywords': ['psu', 'public sector', 'cpse', 'railways psu'],
        'priority': 15
    },
    'DEFENCE': {
        'symbol_keywords': ['DEFENCE', 'DEFENSE'],
        'asset_keywords': ['defence', 'defense', 'india defence'],
        'priority': 16
    },
    'SENSEX': {
        'symbol_keywords': ['SENSEX'],
        'asset_keywords': ['sensex', 'bse sensex'],
        'priority': 17
    },
    'NIFTY_NEXT_50': {
        'symbol_keywords': ['NEXT50', 'N50JR', 'JUNIORBEES'],
        'asset_keywords': ['nifty next 50', 'next 50'],
        'priority': 18
    },
    'NIFTY_100': {
        'symbol_keywords': ['NIFTY100'],
        'asset_keywords': ['nifty 100', 'nifty100'],
        'priority': 19
    },
    'NIFTY_MIDCAP': {
        'symbol_keywords': ['MIDCAP', 'MIDCAP150', 'MIDCAP100'],
        'asset_keywords': ['midcap', 'mid cap', 'nifty midcap'],
        'priority': 20
    },
    'FINANCIAL_SERVICES': {
        'symbol_keywords': ['FIN', 'FINANCIAL'],
        'asset_keywords': ['financial services', 'nifty financial'],
        'priority': 21
    },
    'GSEC': {
        'symbol_keywords': ['GSEC', 'GILT'],
        'asset_keywords': ['g-sec', 'gsec', 'gilt', 'government securities', 'benchmark g-sec'],
        'priority': 22
    },
    'LIQUID': {
        'symbol_keywords': ['LIQUID', 'RATE'],
        'asset_keywords': ['liquid', 'nifty 1d rate', 'overnight', 'money market'],
        'priority': 23
    },
    'MOMENTUM': {
        'symbol_keywords': ['MOMENTUM', 'MOMEN'],
        'asset_keywords': ['momentum', 'nifty 200 momentum'],
        'priority': 24
    },
    'SMALLCAP': {
        'symbol_keywords': ['SMALLCAP', 'SMALL'],
        'asset_keywords': ['smallcap', 'small cap', 'nifty smallcap'],
        'priority': 25
    },
    'QUALITY': {
        'symbol_keywords': ['QUALITY', 'QUAL'],
        'asset_keywords': ['quality', 'nifty quality'],
        'priority': 26
    },
    'VALUE': {
        'symbol_keywords': ['VALUE'],
        'asset_keywords': ['value', 'nifty50 value'],
        'priority': 27
    },
    'DIVIDEND': {
        'symbol_keywords': ['DIVIDEND', 'DIV'],
        'asset_keywords': ['dividend', 'div', 'nifty dividend'],
        'priority': 28
    },
    'NASDAQ': {
        'symbol_keywords': ['NASDAQ', 'MON100', 'MONQ'],
        'asset_keywords': ['nasdaq', 'nasdaq100', 'nasdaq q-50'],
        'priority': 29
    },
    'GLOBAL': {
        'symbol_keywords': ['GLOBAL', 'WORLD', 'INTERNATIONAL'],
        'asset_keywords': ['global', 'international', 'world'],
        'priority': 30
    },
    'NIFTY_500': {
        'symbol_keywords': ['NIFTY500', 'N500'],
        'asset_keywords': ['nifty 500', 'nifty500'],
        'priority': 31
    },
    'NIFTY_200': {
        'symbol_keywords': ['NIFTY200', 'N200'],
        'asset_keywords': ['nifty 200', 'nifty200'],
        'priority': 32
    },
    'ALPHA': {
        'symbol_keywords': ['ALPHA'],
        'asset_keywords': ['alpha', 'nifty alpha', 'nifty200 alpha'],
        'priority': 33
    },
    'LOW_VOLATILITY': {
        'symbol_keywords': ['LOWVOL', 'LOW VOL'],
        'asset_keywords': ['low volatility', 'lowvol', 'alphalowvol'],
        'priority': 34
    },
    'LARGEMID': {
        'symbol_keywords': ['LARGEMID', 'LARGE MID'],
        'asset_keywords': ['largemid', 'large mid', 'nifty largemid'],
        'priority': 35
    },
    'MICROCAP': {
        'symbol_keywords': ['MICROCAP', 'MICRO'],
        'asset_keywords': ['microcap', 'micro cap', 'nifty microcap'],
        'priority': 36
    },
    'MULTICAP': {
        'symbol_keywords': ['MULTICAP', 'MULTI CAP'],
        'asset_keywords': ['multicap', 'multi cap', 'nifty500 multicap'],
        'priority': 37
    },
    'TOTAL_MARKET': {
        'symbol_keywords': ['TOTAL MKT', 'TOTALMARKET'],
        'asset_keywords': ['total market', 'total mkt', 'nifty total mkt'],
        'priority': 38
    },
    'DIGITAL': {
        'symbol_keywords': ['DIGITAL', 'TECH'],
        'asset_keywords': ['digital', 'nifty digital', 'nifty ind digital', 'india digital'],
        'priority': 39
    },
    'MEDIA': {
        'symbol_keywords': ['MEDIA'],
        'asset_keywords': ['media', 'nifty media'],
        'priority': 40
    },
    'METAL': {
        'symbol_keywords': ['METAL'],
        'asset_keywords': ['metal', 'nifty metal'],
        'priority': 41
    },
    'COMMODITIES': {
        'symbol_keywords': ['COMMODITY', 'COMMODITIES'],
        'asset_keywords': ['commodities', 'commodity', 'nifty commodities'],
        'priority': 42
    },
    'MNC': {
        'symbol_keywords': ['MNC'],
        'asset_keywords': ['mnc', 'multinational', 'nifty mnc'],
        'priority': 43
    },
    'SERVICES': {
        'symbol_keywords': ['SERVICE', 'SERV'],
        'asset_keywords': ['service', 'services', 'nifty serv sector', 'service sector'],
        'priority': 44
    },
    'GROWTH': {
        'symbol_keywords': ['GROWTH', 'GROWSECT'],
        'asset_keywords': ['growth', 'growth sector', 'nifty growsect'],
        'priority': 45
    },
    'ESG': {
        'symbol_keywords': ['ESG'],
        'asset_keywords': ['esg', 'nifty esg', 'nifty100 esg'],
        'priority': 46
    },
    'TATA': {
        'symbol_keywords': ['TATA'],
        'asset_keywords': ['tata', 'nifty tata'],
        'priority': 47
    },
}


def normalize_text(text):
    """Normalize text for matching: lowercase, remove special chars"""
    if not text:
        return ""
    text = str(text).lower().strip()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_etf_category(symbol, underlying_asset):
    """
    Determine ETF category based on symbol name and underlying asset
    Returns category name or None
    """
    symbol_norm = normalize_text(symbol)
    asset_norm = normalize_text(underlying_asset)
    
    matched_categories = []
    
    for category, config in CATEGORY_KEYWORDS.items():
        score = 0
        
        # Check symbol keywords
        for keyword in config['symbol_keywords']:
            keyword_norm = normalize_text(keyword)
            if keyword_norm in symbol_norm:
                score += 10
                break
        
        # Check asset keywords
        for keyword in config['asset_keywords']:
            keyword_norm = normalize_text(keyword)
            if keyword_norm in asset_norm:
                score += 5
                break
        
        if score > 0:
            matched_categories.append({
                'category': category,
                'score': score,
                'priority': config['priority']
            })
    
    if not matched_categories:
        return None
    
    # Sort by score (descending) then priority (ascending)
    matched_categories.sort(key=lambda x: (-x['score'], x['priority']))
    
    return matched_categories[0]['category']


def group_etfs_by_category(etf_dataframe):
    """
    Group ETFs by category
    
    Args:
        etf_dataframe: DataFrame with SYMBOL and UNDERLYING_ASSET columns
    
    Returns:
        dict: {category: [list of symbols]}
    """
    groups = {}
    uncategorized = []
    
    for _, row in etf_dataframe.iterrows():
        symbol = row.get('SYMBOL', '')
        underlying = row.get('UNDERLYING_ASSET', '') or row.get('UNDERLYING ASSET', '')
        
        category = get_etf_category(symbol, underlying)
        
        if category:
            if category not in groups:
                groups[category] = []
            groups[category].append(symbol)
        else:
            uncategorized.append(symbol)
    
    if uncategorized:
        groups['UNCATEGORIZED'] = uncategorized
    
    return groups


def find_alternatives_smart(failed_symbol, full_etf_df, exclude_symbols=None):
    """
    Find alternative ETFs in the same category, sorted by:
    1. Volume (descending - most liquid first)
    2. Price (ascending - lower price preferred)
    
    Args:
        failed_symbol: Symbol that failed
        full_etf_df: Complete ETF dataframe
        exclude_symbols: List of symbols to exclude
    
    Returns:
        list: [{'symbol': 'ALT1', 'price': 100.0, 'volume': 50000, 'category': 'GOLD'}, ...]
    """
    if full_etf_df is None or full_etf_df.empty:
        return []
    
    if exclude_symbols is None:
        exclude_symbols = []
    
    try:
        # Find the failed symbol's row
        failed_row = full_etf_df[full_etf_df['SYMBOL'] == failed_symbol]
        if failed_row.empty:
            return []
        
        failed_underlying = failed_row.iloc[0].get('UNDERLYING_ASSET') or failed_row.iloc[0].get('UNDERLYING ASSET', '')
        failed_category = get_etf_category(failed_symbol, failed_underlying)
        
        if not failed_category:
            print(f"  ⚠️ No category found for {failed_symbol}")
            return []
        
        print(f"  📁 Category: {failed_category}")
        
        # Find all ETFs in the same category
        alternatives = []
        for _, row in full_etf_df.iterrows():
            symbol = row['SYMBOL']
            
            if symbol == failed_symbol or symbol in exclude_symbols:
                continue
            
            underlying = row.get('UNDERLYING_ASSET') or row.get('UNDERLYING ASSET', '')
            category = get_etf_category(symbol, underlying)
            
            if category == failed_category:
                try:
                    volume_str = str(row.get('VOLUME', 0)).replace(',', '')
                    volume = float(volume_str) if volume_str else 0.0
                    
                    ltp_str = str(row.get('LTP', 0)).replace(',', '')
                    price = float(ltp_str) if ltp_str else 0.0
                    
                    if volume > 0 and price > 0:
                        alternatives.append({
                            'symbol': symbol,
                            'price': price,
                            'volume': volume,
                            'category': category,
                            'underlying': underlying
                        })
                except (ValueError, TypeError) as e:
                    continue
        
        if not alternatives:
            return []
        
        # Sort by volume DESC (primary), then price ASC (secondary)
        alternatives.sort(key=lambda x: (-x['volume'], x['price']))
        
        print(f"  ✅ Found {len(alternatives)} alternatives in {failed_category}")
        
        return alternatives
    
    except Exception as e:
        print(f"  ❌ Error finding alternatives for {failed_symbol}: {e}")
        return []


if __name__ == "__main__":
    # Test categorization
    test_cases = [
        ("GOLDSHARE", "Gold"),
        ("MOGOLD", "Domestic Price of Physical Gold"),
        ("SILVERIETF", "Domestic Price of Silver"),
        ("SILVERCASE", "Commodity-Silver"),
        ("EBANKNIFTY", "Edelweiss Nifty Bank ETF"),
        ("UTIBANKETF", "Nifty Bank"),
        ("MOHEALTH", "Motilal Oswal S&P BSE Healthcare ETF"),
        ("HEALTHY", "Nifty Healthcare TRI"),
        ("GROWWRAIL", "Nifty India Railways PSU Index"),
        ("INFRABEES", "Nifty Infra"),
    ]
    
    print("Testing ETF Categorization:")
    print("=" * 70)
    for symbol, asset in test_cases:
        category = get_etf_category(symbol, asset)
        print(f"{symbol:15} | {asset[:35]:35} -> {category or 'UNCATEGORIZED'}")
