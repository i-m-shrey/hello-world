"""
Integration Patch for filter_etfs.py
Adds dynamic average fall calculation WITHOUT breaking existing logic

HOW TO INTEGRATE:
1. Add this import at the top of filter_etfs.py (after other imports):
   from dynamic_fall_calculator import (
       store_daily_etf_data, 
       get_average_fall_dict, 
       ENABLE_DYNAMIC_FALL
   )

2. Replace the section that loads average_percentage_fall_indices.csv (~line 350-393)
   with the code below.

SAFETY:
- Wrapped in try-except (falls back to hardcoded CSV on any error)
- Stores historical data AFTER filtering logic completes
- Only modifies avg_fall_dict source, not filtering algorithm
- Can be disabled with env var: ENABLE_DYNAMIC_FALL=0
- Existing hardcoded CSV still used as fallback
"""

# This replaces lines ~350-393 in filter_etfs.py:

INTEGRATION_CODE = '''
    # ===== DYNAMIC FALL CALCULATION (with hardcoded CSV fallback) =====
    
    def _resolve_avg_fall_csv():
        """Find hardcoded average fall CSV"""
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
        raise FileNotFoundError('average_percentage_fall_indices.csv not found in expected locations. Set AVG_FALL_CSV env to override.')
    
    logging.info(f"Hardcoded average fall CSV: {csv_path}")
    
    # Try dynamic fall calculation (with fallback to hardcoded CSV)
    try:
        from dynamic_fall_calculator import (
            store_daily_etf_data,
            get_average_fall_dict,
            ENABLE_DYNAMIC_FALL
        )
        
        if ENABLE_DYNAMIC_FALL:
            logging.info("Dynamic fall calculation ENABLED - attempting to use historical data")
            avg_fall_dict = get_average_fall_dict(hardcoded_csv_path=csv_path)
            
            if not avg_fall_dict:
                logging.warning("Dynamic calculation returned empty - falling back to hardcoded CSV")
                raise ValueError("Empty dynamic fall dictionary")
            
            logging.info(f"Using average fall data: {'DYNAMIC' if len(avg_fall_dict) > 0 else 'HARDCODED'} ({len(avg_fall_dict)} entries)")
        else:
            logging.info("Dynamic fall calculation DISABLED - using hardcoded CSV")
            raise ImportError("Dynamic fall disabled by config")
    
    except Exception as e:
        # Fallback to hardcoded CSV (existing logic)
        logging.info(f"Using hardcoded CSV fallback (reason: {e})")
        
        avg_fall_df = pd.read_csv(csv_path)
        avg_fall_df.columns = avg_fall_df.columns.str.strip().str.replace(" ", "_").str.upper()
        
        if 'INDEX_NAME' in avg_fall_df.columns:
            index_name_col = 'INDEX_NAME'
        else:
            index_name_col = [col for col in avg_fall_df.columns if 'INDEX' in col or 'NAME' in col][0]
        
        if 'AVERAGE_FALL_(%)' in avg_fall_df.columns:
            avg_fall_col = 'AVERAGE_FALL_(%)'
        else:
            avg_fall_col = [col for col in avg_fall_df.columns if 'FALL' in col or 'AVERAGE' in col][0]
        
        avg_fall_dict = dict(zip(avg_fall_df[index_name_col], avg_fall_df[avg_fall_col]))
        logging.info(f"Loaded {len(avg_fall_dict)} entries from hardcoded CSV")
    
    # ===== END DYNAMIC FALL CALCULATION =====
    
    # Continue with existing matching logic...
    # (The code below this point remains UNCHANGED)
    
'''

# This code should be added at the END of calculate_quantities() function,
# AFTER all filtering is done but BEFORE return statement:

STORAGE_CODE = '''
    # ===== STORE DAILY ETF DATA (for future dynamic calculations) =====
    try:
        from dynamic_fall_calculator import store_daily_etf_data, ENABLE_DYNAMIC_FALL
        if ENABLE_DYNAMIC_FALL:
            store_daily_etf_data(etf_data)  # Store original ETF data, not filtered
            logging.info("Daily ETF data stored for historical tracking")
    except Exception as e:
        logging.warning(f"Failed to store daily ETF data (non-critical): {e}")
    # ===== END STORAGE =====
    
    return filtered_etfs
'''

print(__doc__)
print("\n" + "="*80)
print("CODE TO REPLACE LINES ~350-393 (average fall CSV loading):")
print("="*80)
print(INTEGRATION_CODE)

print("\n" + "="*80)
print("CODE TO ADD BEFORE RETURN STATEMENT (at end of calculate_quantities):")
print("="*80)
print(STORAGE_CODE)
print("="*80)
