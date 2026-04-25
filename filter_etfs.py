import pandas as pd
import os
import logging

# Constants
DAILY_SIP_MIN = 200

# Parameters for filtering (modifiable)
MIN_VOLUME = 80000  # Minimum volume threshold for filtering
GENERIC_AVERAGE_FALL = -1.2  # Default average fall percentage

DEBT_KEYWORDS = [
    "Debt", "Bond", "Gilt", "Treasury", "Fixed Income",
    "Corporate", "Govt Sec", "Securities", 'Media', 'Commodity'
]


def match_index_name(underlying_asset, avg_fall_df):
    """
    Match UNDERLYING_ASSET to INDEX_NAME using substring checks.

    Args:
    - underlying_asset (str): The name of the underlying asset (e.g., "Gold ETF").
    - avg_fall_df (DataFrame): DataFrame containing INDEX_NAME and AVERAGE_FALL_(%) columns.

    Returns:
    - str: The matched INDEX_NAME if found, or None otherwise.
    """
    for index_name in avg_fall_df['INDEX_NAME']:
        # Check if INDEX_NAME is a substring of UNDERLYING_ASSET
        if index_name.lower() in underlying_asset.lower():
            return index_name  # Return the matched INDEX_NAME
    return None  # Return None if no match is found


def calculate_quantities(filtered_etfs):
    """
    Filter ETFs based on criteria and allocate investment amounts with progressive severity-based formula.

    NEW APPROACH:
    - Each sector decides its allocation independently based on its own severity
    - No averaging across sectors
    - No artificial caps or budget constraints
    - Progressive formula rewards higher severity more aggressively
    - PHASE 1: Stores daily ETF data for future dynamic average fall calculation
    """
    if filtered_etfs.empty:
        print("No ETFs to allocate.")
        return filtered_etfs

    original_etf_data = filtered_etfs.copy()

    # Clean column names: remove whitespace and standardize
    filtered_etfs.columns = (
        filtered_etfs.columns.str.strip()
        .str.replace(" ", "_")
        .str.upper()
    )

    # Ensure numeric and clean data
    filtered_etfs['%CHNG'] = pd.to_numeric(filtered_etfs['%CHNG'], errors='coerce').fillna(0)
    filtered_etfs['LTP'] = pd.to_numeric(filtered_etfs['LTP'], errors='coerce').fillna(0)
    filtered_etfs['VOLUME'] = pd.to_numeric(filtered_etfs['VOLUME'].str.replace(',', ''), errors='coerce').fillna(0)

    # Filter out ETFs with LTP <= 0 or low volume
    filtered_etfs = filtered_etfs[(filtered_etfs['LTP'] > 0) & (filtered_etfs['VOLUME'] >= MIN_VOLUME)]

    # Remove assets containing any DEBT_KEYWORDS
    pattern = "|".join(DEBT_KEYWORDS)
    filtered_etfs = filtered_etfs[~filtered_etfs['UNDERLYING_ASSET'].str.contains(pattern, case=False, na=False)]

    # Load average fall data (supports dynamic calculation with hardcoded CSV fallback)
    def _resolve_avg_fall_csv():
        env_path = os.getenv('AVG_FALL_CSV')
        if env_path and os.path.isfile(env_path):
            return env_path
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, 'average_percentage_fall_indices.csv'),
            os.path.join(os.path.dirname(here), 'strategy_runner', 'average_percentage_fall_indices.csv'),
            os.path.join(os.getcwd(), 'average_percentage_fall_indices.csv'),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    csv_path = _resolve_avg_fall_csv()
    if not csv_path:
        raise FileNotFoundError(
            'average_percentage_fall_indices.csv not found in expected locations. Set AVG_FALL_CSV env to override.')

    logging.info(f"Hardcoded average fall CSV: {csv_path}")

    # Load CSV into DataFrame (needed for match_index_name regardless of dynamic/static mode)
    avg_fall_df = pd.read_csv(csv_path)
    avg_fall_df.columns = avg_fall_df.columns.str.strip().str.replace(" ", "_").str.upper()

    print("Average fall data columns:", avg_fall_df.columns.tolist())

    if 'INDEX_NAME' in avg_fall_df.columns:
        index_name_col = 'INDEX_NAME'
    else:
        index_name_col = [col for col in avg_fall_df.columns if 'INDEX' in col or 'NAME' in col][0]
        print(f"Using '{index_name_col}' as index name column")

    if 'AVERAGE_FALL_(%)' in avg_fall_df.columns:
        avg_fall_col = 'AVERAGE_FALL_(%)'
    else:
        avg_fall_col = [col for col in avg_fall_df.columns if 'FALL' in col or 'AVERAGE' in col][0]
        print(f"Using '{avg_fall_col}' as average fall column")

    try:
        from dynamic_fall_calculator import get_average_fall_dict, ENABLE_DYNAMIC_FALL

        if ENABLE_DYNAMIC_FALL:
            logging.info("🔄 Dynamic fall calculation ENABLED - attempting to use historical data")
            avg_fall_dict = get_average_fall_dict(hardcoded_csv_path=csv_path)

            if not avg_fall_dict:
                logging.warning("⚠️ Dynamic calculation returned empty - falling back to hardcoded CSV")
                raise ValueError("Empty dynamic fall dictionary")

            logging.info(f"✅ Using DYNAMIC average fall data ({len(avg_fall_dict)} entries)")
        else:
            logging.info("Using hardcoded CSV (dynamic calculation disabled)")
            raise ImportError("Dynamic fall disabled by config")

    except Exception as e:
        logging.info(f"📋 Using hardcoded CSV fallback (reason: {e})")
        avg_fall_dict = dict(zip(avg_fall_df[index_name_col], avg_fall_df[avg_fall_col]))
        logging.info(f"Loaded {len(avg_fall_dict)} entries from hardcoded CSV")

    # Match UNDERLYING_ASSET to INDEX_NAME
    filtered_etfs['MATCHED_INDEX'] = filtered_etfs['UNDERLYING_ASSET'].apply(
        lambda x: match_index_name(x, avg_fall_df)
    )
    
    # Category-to-primary-index mapping (use most conservative avg fall per category)
    CATEGORY_PRIMARY_INDEX = {
        'NIFTY_MIDCAP': 'NIFTY MIDCAP 50',
        'NIFTY_SMALLCAP': 'NIFTY SMLCAP 50',
        'MOMENTUM': 'NIFTY200MOMENTM30'
    }
    
    # Add CATEGORY column for category-based grouping
    try:
        from etf_categorizer import get_etf_category
        filtered_etfs['CATEGORY'] = filtered_etfs.apply(
            lambda row: get_etf_category(row['SYMBOL'], row.get('UNDERLYING_ASSET', '')),
            axis=1
        )
    except:
        filtered_etfs['CATEGORY'] = None
    
    # Map categories to primary index, then get avg fall
    def get_avg_fall_for_row(row):
        category = row.get('CATEGORY')
        matched_index = row.get('MATCHED_INDEX')
        
        # If category has a primary index mapping, use that
        if category and category in CATEGORY_PRIMARY_INDEX:
            primary_index = CATEGORY_PRIMARY_INDEX[category]
            return avg_fall_dict.get(primary_index, avg_fall_dict.get(matched_index, GENERIC_AVERAGE_FALL))
        
        # Otherwise use matched index
        return avg_fall_dict.get(matched_index, GENERIC_AVERAGE_FALL)
    
    # Add AVG_FALL column with category-based mapping
    filtered_etfs['AVG_FALL'] = filtered_etfs.apply(get_avg_fall_for_row, axis=1)

    # DEBUG: Check if AVG_FALL column exists and has valid values
    print("Sample of filtered ETFs with AVG_FALL:")
    print(filtered_etfs[['SYMBOL', 'UNDERLYING_ASSET', 'MATCHED_INDEX', 'AVG_FALL']].head())

    # Filter based on avg fall (only ETFs that fell MORE than their average)
    filtered_etfs = filtered_etfs[filtered_etfs['%CHNG'] < filtered_etfs['AVG_FALL']]

    # If no ETFs meet criteria, return empty DataFrame
    if filtered_etfs.empty:
        print("No ETFs meet the criteria (falling more than their average).")
        return filtered_etfs

    # Deduplication: pick 1 ETF per CATEGORY (highest volume, then lowest price)
    # Example: MIDCAP50, MIDCAP100, MIDCAP150 → only 1 MIDCAP order (best liquidity + best price)
    filtered_etfs['CATEGORY_SAFE'] = filtered_etfs['CATEGORY'].fillna('NO_MATCH')
    filtered_etfs = filtered_etfs.sort_values(['VOLUME', 'LTP'], ascending=[False, True])
    filtered_etfs = filtered_etfs.groupby('CATEGORY_SAFE', as_index=False).first()

    # Calculate severity for each sector independently
    def calculate_severity(row):
        return (row['AVG_FALL'] - row['%CHNG']) / abs(row['AVG_FALL'])

    filtered_etfs['SEVERITY'] = filtered_etfs.apply(calculate_severity, axis=1)

    # Print severity values for selected ETFs
    print("\nSelected ETFs with severity scores:")
    print(filtered_etfs[['SYMBOL', '%CHNG', 'AVG_FALL', 'SEVERITY']].to_string())

    # Calculate fall ratio for reference
    filtered_etfs['FALL_RATIO'] = filtered_etfs['%CHNG'] / filtered_etfs['AVG_FALL']

    # NEW PROGRESSIVE ALLOCATION FORMULA
    # Each sector decides independently - no averaging, no caps
    def allocate_based_on_severity(row):
        """
        Progressive allocation formula - rewards higher severity more aggressively

        Formula tiers:
        - severity < 1.0:  50 + (severity × 80)           → ₹50-130  (mild dips)
        - severity 1.0-2.0: 130 + ((severity-1.0) × 100)  → ₹130-230 (moderate dips)
        - severity 2.0+:    230 + ((severity-2.0) × 120)  → ₹230+    (severe crashes)

        This ensures:
        - Low severity (0.5): Gets ₹90 (conservative)
        - Medium severity (1.5): Gets ₹180 (moderate)
        - High severity (3.0): Gets ₹350 (aggressive)
        - Very high severity (4.0): Gets ₹470 (very aggressive)
        """
        severity = row['SEVERITY']

        if severity < 1.0:
            # Mild dip - conservative allocation
            return 50 + severity * 80
        elif severity < 2.0:
            # Moderate dip - medium allocation
            return 130 + (severity - 1.0) * 100
        else:
            # Severe crash - aggressive allocation
            return 230 + (severity - 2.0) * 120

    # Apply the progressive allocation to each ETF
    filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs.apply(allocate_based_on_severity, axis=1)

    # Print allocations
    print("\nAllocations based on progressive severity formula:")
    print(filtered_etfs[['SYMBOL', 'SEVERITY', 'ALLOCATED_AMOUNT']].to_string())

    # Calculate quantities safely (base level, before multiplier)
    filtered_etfs['QTY'] = filtered_etfs.apply(
        lambda row: int(row['ALLOCATED_AMOUNT'] / row['LTP']) if row['LTP'] > 0 else 0,
        axis=1
    )
    
    # Handle 0-qty ETFs: try to find lower-priced alternatives in same category
    # Keep ETF even if no alternative (high-multiplier clients will get qty > 0)
    zero_qty_etfs = filtered_etfs[filtered_etfs['QTY'] == 0].copy()
    if not zero_qty_etfs.empty:
        print(f"\n⚠️  Found {len(zero_qty_etfs)} ETFs with 0 qty at base - searching for lower-priced alternatives...")
        
        # Need original data for alternatives
        original_with_category = original_etf_data.copy()
        original_with_category.columns = original_with_category.columns.str.strip().str.replace(" ", "_").str.upper()
        original_with_category['%CHNG'] = pd.to_numeric(original_with_category['%CHNG'], errors='coerce').fillna(0)
        original_with_category['LTP'] = pd.to_numeric(original_with_category['LTP'], errors='coerce').fillna(0)
        original_with_category['VOLUME'] = pd.to_numeric(original_with_category['VOLUME'].str.replace(',', ''), errors='coerce').fillna(0)
        
        # Add category to original data
        try:
            from etf_categorizer import get_etf_category
            original_with_category['CATEGORY'] = original_with_category.apply(
                lambda row: get_etf_category(row['SYMBOL'], row.get('UNDERLYING_ASSET', '')),
                axis=1
            )
        except:
            original_with_category['CATEGORY'] = None
        
        for idx, row in zero_qty_etfs.iterrows():
            category = row.get('CATEGORY')
            allocated = row['ALLOCATED_AMOUNT']
            current_price = row['LTP']
            
            if not category:
                print(f"  ⚠️  {row['SYMBOL']} (₹{current_price:.2f}) - no category, keeping as-is for high-multiplier clients")
                continue
            
            # Find all ETFs in same category from original data (exclude current symbol)
            category_etfs = original_with_category[
                (original_with_category['CATEGORY'] == category) & 
                (original_with_category['SYMBOL'] != row['SYMBOL']) &
                (original_with_category['LTP'] > 0) &
                (original_with_category['VOLUME'] >= MIN_VOLUME)
            ].copy()
            
            if category_etfs.empty:
                print(f"  ⚠️  {row['SYMBOL']} (₹{current_price:.2f}) - no alternatives, keeping for high-multiplier clients")
                continue
            
            # Sort by price ascending, volume descending
            category_etfs = category_etfs.sort_values(['LTP', 'VOLUME'], ascending=[True, False])
            
            # Try to find ETF with price <= allocated amount
            affordable = category_etfs[category_etfs['LTP'] <= allocated]
            
            if not affordable.empty:
                # Found affordable alternative - replace
                alt = affordable.iloc[0]
                qty = int(allocated / alt['LTP'])
                print(f"  ✅ {row['SYMBOL']} (₹{current_price:.2f}) → {alt['SYMBOL']} (₹{alt['LTP']:.2f}) | Qty: {qty}")
                filtered_etfs.loc[idx, 'SYMBOL'] = alt['SYMBOL']
                filtered_etfs.loc[idx, 'LTP'] = alt['LTP']
                filtered_etfs.loc[idx, 'VOLUME'] = alt['VOLUME']
                filtered_etfs.loc[idx, 'QTY'] = qty
                filtered_etfs.loc[idx, 'FINAL_AMOUNT'] = qty * alt['LTP']
            else:
                # Check if lowest price is within 20% of allocated
                lowest = category_etfs.iloc[0]
                if lowest['LTP'] <= allocated * 1.20:
                    # Replace with lowest price alternative (1 qty)
                    print(f"  📈 {row['SYMBOL']} (₹{current_price:.2f}) → {lowest['SYMBOL']} (₹{lowest['LTP']:.2f}) | Qty: 1 (within 20%)")
                    filtered_etfs.loc[idx, 'SYMBOL'] = lowest['SYMBOL']
                    filtered_etfs.loc[idx, 'LTP'] = lowest['LTP']
                    filtered_etfs.loc[idx, 'VOLUME'] = lowest['VOLUME']
                    filtered_etfs.loc[idx, 'QTY'] = 1
                    filtered_etfs.loc[idx, 'FINAL_AMOUNT'] = lowest['LTP']
                else:
                    # Keep original ETF (high-multiplier clients will get qty)
                    print(f"  💰 {row['SYMBOL']} (₹{current_price:.2f}) - keeping for high-multiplier clients (lowest alt: ₹{lowest['LTP']:.2f})")

    # Recalculate final amounts based on actual quantities
    filtered_etfs['FINAL_AMOUNT'] = filtered_etfs['QTY'] * filtered_etfs['LTP']

    # Final check on total amount
    final_total = filtered_etfs['FINAL_AMOUNT'].sum()

    # Detailed results table
    print("\nETF Selection Results:")
    result_table = filtered_etfs[['SYMBOL', '%CHNG', 'AVG_FALL', 'SEVERITY', 'ALLOCATED_AMOUNT', 'QTY', 'FINAL_AMOUNT']]
    print(result_table.to_string(index=False))

    print(f"\nETFs selected: {len(filtered_etfs)}")
    print(f"Total investment: ₹{final_total:.2f}")

    try:
        from dynamic_fall_calculator import store_daily_etf_data, ENABLE_DYNAMIC_FALL
        if ENABLE_DYNAMIC_FALL:
            original_etf_data.columns = original_etf_data.columns.str.strip().str.replace(" ", "_").str.upper()
            store_daily_etf_data(original_etf_data)
            logging.info("📊 Phase 1: Daily ETF data stored for historical tracking")
    except Exception as e:
        logging.warning(f"Failed to store daily ETF data (non-critical): {e}")

    return filtered_etfs