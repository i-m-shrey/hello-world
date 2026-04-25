"""
Dynamic Average Fall Calculator
Stores historical ETF data and calculates rolling average falls dynamically
"""
import os
import pandas as pd
from datetime import datetime as dt, timedelta
import logging


# ==================== CONFIGURATION ====================
ROLLING_DAYS = 365  # Use 365-day rolling average
MIN_DATA_DAYS = 90  # Need 90 days before switching from hardcoded
BLEND_PERIOD = 90  # Blend hardcoded + dynamic for 90 days after MIN_DATA_DAYS

HISTORICAL_FOLDER = "historical_fall_data"
ENABLE_DYNAMIC_FALL = 1

# Fallback: If dynamic calculation fails, use hardcoded CSV
HARDCODED_CSV_PATH = None  # Will be set by filter_etfs.py
# =======================================================


def ensure_historical_folder():
    """Create historical data folder if it doesn't exist"""
    os.makedirs(HISTORICAL_FOLDER, exist_ok=True)


def get_historical_csv_path(date=None):
    """Get path for a specific date's historical data"""
    if date is None:
        date = dt.now()
    
    date_str = date.strftime('%Y-%m-%d')
    filename = f"{date_str}.csv"
    return os.path.join(HISTORICAL_FOLDER, filename)


def store_daily_etf_data(etf_dataframe):
    """
    Store today's ETF data for historical tracking
    Includes MATCHED_INDEX (80 specific indices) and CATEGORY (38 broad groups)
    
    Args:
        etf_dataframe: DataFrame with columns: SYMBOL, UNDERLYING_ASSET, %CHNG, VOLUME, LTP, MATCHED_INDEX
    """
    if not ENABLE_DYNAMIC_FALL:
        return False
    
    try:
        ensure_historical_folder()
        
        # Select relevant columns
        columns_to_store = ['SYMBOL', 'UNDERLYING_ASSET', '%CHNG', 'VOLUME', 'LTP']
        if 'MATCHED_INDEX' in etf_dataframe.columns:
            columns_to_store.append('MATCHED_INDEX')
        
        available_columns = [col for col in columns_to_store if col in etf_dataframe.columns]
        
        if not available_columns:
            logging.warning("No relevant columns found in ETF dataframe for historical storage")
            return False
        
        data_to_store = etf_dataframe[available_columns].copy()
        
        # Add CATEGORY column for order fallback (38 broad groups)
        try:
            from etf_categorizer import get_etf_category
            data_to_store['CATEGORY'] = data_to_store.apply(
                lambda row: get_etf_category(row['SYMBOL'], row.get('UNDERLYING_ASSET', '')),
                axis=1
            )
            logging.info("Added CATEGORY column for order fallback")
        except Exception as e:
            logging.warning(f"Could not add CATEGORY column: {e}")
            data_to_store['CATEGORY'] = None
        
        # Add date column
        data_to_store['DATE'] = dt.now().strftime('%Y-%m-%d')
        
        # Save to CSV
        csv_path = get_historical_csv_path()
        data_to_store.to_csv(csv_path, index=False)
        
        logging.info(f"Stored daily ETF data: {csv_path} ({len(data_to_store)} records)")
        return True
        
    except Exception as e:
        logging.error(f"Error storing daily ETF data: {e}")
        return False


def get_available_historical_days():
    """Count how many days of historical data we have"""
    if not os.path.exists(HISTORICAL_FOLDER):
        return 0
    
    try:
        files = [f for f in os.listdir(HISTORICAL_FOLDER) if f.endswith('.csv')]
        return len(files)
    except Exception as e:
        logging.error(f"Error counting historical data: {e}")
        return 0


def load_historical_data(days=ROLLING_DAYS):
    """
    Load historical data for the last N days
    
    Returns:
        DataFrame with columns: DATE, SYMBOL, UNDERLYING_ASSET, %CHNG, VOLUME, LTP
    """
    try:
        ensure_historical_folder()
        
        # Get list of date files
        files = sorted([f for f in os.listdir(HISTORICAL_FOLDER) if f.endswith('.csv')])
        
        if not files:
            logging.warning("No historical data files found")
            return None
        
        # Load last N days
        files_to_load = files[-days:] if len(files) > days else files
        
        dfs = []
        for filename in files_to_load:
            try:
                file_path = os.path.join(HISTORICAL_FOLDER, filename)
                df = pd.read_csv(file_path)
                dfs.append(df)
            except Exception as e:
                logging.warning(f"Error loading {filename}: {e}")
                continue
        
        if not dfs:
            logging.warning("No valid historical data loaded")
            return None
        
        # Combine all dataframes
        combined_df = pd.concat(dfs, ignore_index=True)
        
        logging.info(f"Loaded {len(dfs)} days of historical data ({len(combined_df)} total records)")
        return combined_df
        
    except Exception as e:
        logging.error(f"Error loading historical data: {e}")
        return None


def calculate_dynamic_average_fall_by_category(category, historical_df):
    """
    Calculate rolling average fall for a specific CATEGORY (GOLD, SILVER, etc.)
    This covers all 30+ categories from etf_categorizer
    
    Args:
        category: Category name (e.g., "GOLD", "SILVER", "NIFTY_BANK")
        historical_df: Historical data DataFrame with CATEGORY column
    
    Returns:
        float: Average fall percentage (e.g., -1.5 means -1.5%)
    """
    try:
        if historical_df is None or historical_df.empty:
            return None
        
        if 'CATEGORY' not in historical_df.columns:
            return None
        
        # Filter for this category
        category_data = historical_df[historical_df['CATEGORY'] == category]
        
        if category_data.empty or len(category_data) < 5:  # Need at least 5 data points
            return None
        
        # Calculate average of %CHNG for all ETFs in this category
        avg_fall = category_data['%CHNG'].mean()
        
        return float(avg_fall)
        
    except Exception as e:
        logging.error(f"Error calculating dynamic average fall for category {category}: {e}")
        return None


def calculate_dynamic_average_fall(underlying_asset, historical_df):
    """
    Calculate rolling average fall for a specific underlying asset
    LEGACY function - kept for backward compatibility
    
    Args:
        underlying_asset: Name of underlying asset (e.g., "NIFTY 50")
        historical_df: Historical data DataFrame
    
    Returns:
        float: Average fall percentage (e.g., -1.5 means -1.5%)
    """
    try:
        if historical_df is None or historical_df.empty:
            return None
        
        # Filter for this underlying asset
        asset_data = historical_df[historical_df['UNDERLYING_ASSET'] == underlying_asset]
        
        if asset_data.empty or len(asset_data) < 5:  # Need at least 5 data points
            return None
        
        # Calculate average of %CHNG
        avg_fall = asset_data['%CHNG'].mean()
        
        return float(avg_fall)
        
    except Exception as e:
        logging.error(f"Error calculating dynamic average fall for {underlying_asset}: {e}")
        return None


def get_dynamic_average_fall_dict(historical_df=None, use_categories=True):
    """
    Generate a dictionary of index_name -> average_fall
    Uses MATCHED_INDEX (80 specific indices) for granular avg fall calculation
    CATEGORY (38 broad groups) is stored for order fallback only
    
    Args:
        historical_df: Historical data DataFrame
        use_categories: Kept for compatibility but now uses MATCHED_INDEX
    
    Returns:
        dict: {index_name: avg_fall_percentage}
    """
    try:
        if historical_df is None:
            historical_df = load_historical_data(days=ROLLING_DAYS)
        
        if historical_df is None or historical_df.empty:
            return {}
        
        avg_fall_dict = {}
        
        # Prefer MATCHED_INDEX (80 specific indices) for avg fall calculation
        if 'MATCHED_INDEX' in historical_df.columns:
            unique_indices = historical_df['MATCHED_INDEX'].dropna().unique()
            
            for index_name in unique_indices:
                index_data = historical_df[historical_df['MATCHED_INDEX'] == index_name]
                if not index_data.empty and len(index_data) >= 5:
                    avg_fall = index_data['%CHNG'].mean()
                    avg_fall_dict[index_name] = float(avg_fall)
            
            logging.info(f"Calculated dynamic average falls for {len(avg_fall_dict)} specific indices (80 coverage)")
        
        # Fallback: Use UNDERLYING_ASSET (legacy mode)
        else:
            unique_assets = historical_df['UNDERLYING_ASSET'].unique()
            
            for asset in unique_assets:
                avg_fall = calculate_dynamic_average_fall(asset, historical_df)
                if avg_fall is not None:
                    avg_fall_dict[asset] = avg_fall
            
            logging.info(f"Calculated dynamic average falls for {len(avg_fall_dict)} underlying assets")
        
        return avg_fall_dict
        
    except Exception as e:
        logging.error(f"Error generating dynamic average fall dictionary: {e}")
        return {}


def blend_hardcoded_and_dynamic(hardcoded_dict, dynamic_dict, blend_ratio=0.5):
    """
    Blend hardcoded and dynamic average falls
    
    Args:
        hardcoded_dict: Dictionary from hardcoded CSV
        dynamic_dict: Dictionary from historical data
        blend_ratio: 0.0 = all hardcoded, 1.0 = all dynamic, 0.5 = 50/50
    
    Returns:
        dict: Blended average falls
    """
    try:
        blended_dict = {}
        
        # Get all unique keys
        all_keys = set(hardcoded_dict.keys()) | set(dynamic_dict.keys())
        
        for key in all_keys:
            hardcoded_val = hardcoded_dict.get(key)
            dynamic_val = dynamic_dict.get(key)
            
            if hardcoded_val is not None and dynamic_val is not None:
                # Both available - blend
                blended_dict[key] = hardcoded_val * (1 - blend_ratio) + dynamic_val * blend_ratio
            elif dynamic_val is not None:
                # Only dynamic available
                blended_dict[key] = dynamic_val
            elif hardcoded_val is not None:
                # Only hardcoded available
                blended_dict[key] = hardcoded_val
        
        logging.info(f"Blended {len(blended_dict)} average falls (ratio: {blend_ratio:.2f})")
        return blended_dict
        
    except Exception as e:
        logging.error(f"Error blending hardcoded and dynamic data: {e}")
        return hardcoded_dict  # Fallback to hardcoded


def get_average_fall_dict(hardcoded_csv_path=None):
    """
    Main function to get average fall dictionary
    Implements phased approach:
    - Phase 1 (0-MIN_DATA_DAYS): Use hardcoded CSV
    - Phase 2 (MIN_DATA_DAYS to MIN_DATA_DAYS+BLEND_PERIOD): Blend hardcoded + dynamic
    - Phase 3 (MIN_DATA_DAYS+BLEND_PERIOD+): Use fully dynamic
    
    Args:
        hardcoded_csv_path: Path to hardcoded CSV file
    
    Returns:
        dict: {underlying_asset_or_index_name: avg_fall_percentage}
    """
    try:
        # Check if dynamic fall is enabled
        if not ENABLE_DYNAMIC_FALL:
            logging.info("Dynamic fall calculation DISABLED - using hardcoded CSV only")
            return load_hardcoded_csv(hardcoded_csv_path)
        
        # Count available historical days
        available_days = get_available_historical_days()
        
        logging.info(f"Dynamic fall status: {available_days} days of historical data available")
        logging.info(f"Config: MIN_DATA_DAYS={MIN_DATA_DAYS}, BLEND_PERIOD={BLEND_PERIOD}, ROLLING_DAYS={ROLLING_DAYS}")
        
        # Load hardcoded CSV
        hardcoded_dict = load_hardcoded_csv(hardcoded_csv_path)
        
        # PHASE 1: Not enough data yet - use hardcoded only
        if available_days < MIN_DATA_DAYS:
            logging.info(f"PHASE 1: Using hardcoded CSV (need {MIN_DATA_DAYS - available_days} more days)")
            return hardcoded_dict
        
        # Load historical data
        historical_df = load_historical_data(days=ROLLING_DAYS)
        
        if historical_df is None or historical_df.empty:
            logging.warning("Failed to load historical data - falling back to hardcoded CSV")
            return hardcoded_dict
        
        # Calculate dynamic averages
        dynamic_dict = get_dynamic_average_fall_dict(historical_df)
        
        if not dynamic_dict:
            logging.warning("Failed to calculate dynamic averages - falling back to hardcoded CSV")
            return hardcoded_dict
        
        # PHASE 2: Blend hardcoded + dynamic
        if available_days < (MIN_DATA_DAYS + BLEND_PERIOD):
            # Calculate blend ratio (0.0 to 1.0)
            days_into_blend = available_days - MIN_DATA_DAYS
            blend_ratio = days_into_blend / BLEND_PERIOD
            
            logging.info(f"PHASE 2: Blending hardcoded + dynamic (ratio: {blend_ratio:.2f})")
            return blend_hardcoded_and_dynamic(hardcoded_dict, dynamic_dict, blend_ratio)
        
        # PHASE 3: Use fully dynamic
        logging.info(f"PHASE 3: Using fully dynamic average falls (last {ROLLING_DAYS} days)")
        
        # Fallback: If dynamic dict is missing too many keys, blend with hardcoded
        if len(dynamic_dict) < len(hardcoded_dict) * 0.5:  # Less than 50% coverage
            logging.warning(f"Dynamic coverage low ({len(dynamic_dict)}/{len(hardcoded_dict)}) - blending with hardcoded")
            return blend_hardcoded_and_dynamic(hardcoded_dict, dynamic_dict, blend_ratio=0.7)
        
        return dynamic_dict
        
    except Exception as e:
        logging.error(f"Error in get_average_fall_dict: {e}")
        logging.error("Falling back to hardcoded CSV")
        return load_hardcoded_csv(hardcoded_csv_path)


def load_hardcoded_csv(csv_path):
    """
    Load hardcoded average fall CSV
    
    Returns:
        dict: {index_name: avg_fall_percentage}
    """
    try:
        if not csv_path or not os.path.exists(csv_path):
            logging.error(f"Hardcoded CSV not found: {csv_path}")
            return {}
        
        df = pd.read_csv(csv_path)
        
        # Clean column names
        df.columns = df.columns.str.strip().str.replace(" ", "_").str.upper()
        
        # Find column names
        index_col = None
        fall_col = None
        
        for col in df.columns:
            if 'INDEX' in col or 'NAME' in col:
                index_col = col
            if 'FALL' in col or 'AVERAGE' in col:
                fall_col = col
        
        if not index_col or not fall_col:
            logging.error(f"Cannot find required columns in hardcoded CSV: {df.columns.tolist()}")
            return {}
        
        # Create dictionary
        avg_fall_dict = dict(zip(df[index_col], df[fall_col]))
        
        logging.info(f"Loaded {len(avg_fall_dict)} entries from hardcoded CSV")
        return avg_fall_dict
        
    except Exception as e:
        logging.error(f"Error loading hardcoded CSV: {e}")
        return {}


if __name__ == "__main__":
    # Test dynamic fall calculator
    print("="*80)
    print("DYNAMIC AVERAGE FALL CALCULATOR - TEST")
    print("="*80)
    
    print(f"\nConfiguration:")
    print(f"  ROLLING_DAYS: {ROLLING_DAYS}")
    print(f"  MIN_DATA_DAYS: {MIN_DATA_DAYS}")
    print(f"  BLEND_PERIOD: {BLEND_PERIOD}")
    print(f"  ENABLE_DYNAMIC_FALL: {ENABLE_DYNAMIC_FALL}")
    
    print(f"\nHistorical Data Status:")
    available = get_available_historical_days()
    print(f"  Available days: {available}")
    
    if available == 0:
        print("\n⚠️  No historical data yet. System will use hardcoded CSV.")
    elif available < MIN_DATA_DAYS:
        print(f"\n📊 PHASE 1: Collecting data (need {MIN_DATA_DAYS - available} more days)")
    elif available < (MIN_DATA_DAYS + BLEND_PERIOD):
        days_into_blend = available - MIN_DATA_DAYS
        blend_ratio = days_into_blend / BLEND_PERIOD
        print(f"\n🔄 PHASE 2: Blending hardcoded + dynamic (ratio: {blend_ratio:.2f})")
    else:
        print(f"\n✅ PHASE 3: Using fully dynamic calculations")
    
    print("\n" + "="*80)