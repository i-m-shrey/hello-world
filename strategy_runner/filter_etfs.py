import pandas as pd
import os
import logging

# Constants
DAILY_SIP_MIN = 200
DAILY_SIP_MAX = 6500

# Parameters for caps (modifiable)
MAX_CAP = 1000  # Maximum allocation for a single ETF
MIN_CAP = 200  # Minimum allocation for a single ETF
MIN_VOLUME = 70000  # Minimum volume threshold for filtering
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


# def calculate_quantities_old(filtered_etfs):
#     """
#     Filter ETFs based on criteria:
#     - Match UNDERLYING_ASSET with INDEX_NAME using substring checks.
#     - Retain ETFs with sufficient trading volume.
#     - Deduplicate ETFs for the same underlying asset, keeping the one with the highest volume.
#     - Allocate SIP dynamically with caps for single and multiple ETFs.
#     """
#     if filtered_etfs.empty:
#         print("No ETFs to allocate.")
#         return None
#
#     # Clean column names: remove whitespace and standardize
#     filtered_etfs.columns = (
#         filtered_etfs.columns.str.strip()
#                               .str.replace(" ", "_")
#                               .str.upper()
#     )
#
#     # Ensure numeric and clean data
#     filtered_etfs['%CHNG'] = pd.to_numeric(filtered_etfs['%CHNG'], errors='coerce').fillna(0)
#     filtered_etfs['LTP'] = pd.to_numeric(filtered_etfs['LTP'], errors='coerce').fillna(0)
#     filtered_etfs['VOLUME'] = pd.to_numeric(filtered_etfs['VOLUME'].str.replace(',', ''), errors='coerce').fillna(0)
#
#     # Filter out ETFs with LTP <= 0 or low volume
#     filtered_etfs = filtered_etfs[(filtered_etfs['LTP'] > 0) & (filtered_etfs['VOLUME'] >= MIN_VOLUME)]
#
#     # Remove assets containing any DEBT_KEYWORDS
#     pattern = "|".join(DEBT_KEYWORDS)
#     filtered_etfs = filtered_etfs[~filtered_etfs['UNDERLYING_ASSET'].str.contains(pattern, case=False, na=False)]
#
#     # Load and clean average fall data
#     avg_fall_df = pd.read_csv('average_percentage_fall_indices.csv')
#     avg_fall_df.columns = avg_fall_df.columns.str.strip().str.replace(" ", "_").str.upper()
#
#     # Match UNDERLYING_ASSET to INDEX_NAME
#     filtered_etfs['MATCHED_INDEX'] = filtered_etfs['UNDERLYING_ASSET'].apply(
#         lambda x: match_index_name(x, avg_fall_df)
#     )
#
#     # Map average fall values to the ETFs
#     avg_fall_dict = dict(zip(avg_fall_df['INDEX_NAME'], avg_fall_df['AVERAGE_FALL_(%)']))
#     filtered_etfs['AVG_FALL'] = filtered_etfs['MATCHED_INDEX'].map(avg_fall_dict).fillna(GENERIC_AVERAGE_FALL)
#
#     # Filter based on avg fall
#     filtered_etfs = filtered_etfs[filtered_etfs['%CHNG'] < filtered_etfs['AVG_FALL']]
#
#     # Deduplicate by 'MATCHED_INDEX', keeping the row with the highest volume
#     filtered_etfs['MATCHED_INDEX_SAFE'] = filtered_etfs['MATCHED_INDEX'].fillna('NO_MATCH')
#
#     # Use the safe version for groupby
#     filtered_etfs = filtered_etfs.loc[filtered_etfs.groupby('MATCHED_INDEX_SAFE')['VOLUME'].idxmax()]
#
#     # Calculate severity
#     def calculate_severity(row):
#         return (row['AVG_FALL'] - row['%CHNG']) / abs(row['AVG_FALL'])
#
#     filtered_etfs['SEVERITY'] = filtered_etfs.apply(calculate_severity, axis=1)
#
#     # Allocate SIP with caps for single or multiple ETFs
#     num_etfs = len(filtered_etfs)
#     def allocate_sip(row, total_severity, num_etfs):
#         if num_etfs == 1:  # Single ETF scenario
#             if row['SEVERITY'] > 1:  # High severity
#                 return min(MAX_CAP, row['SEVERITY'] * MAX_CAP)
#             else:  # Low severity
#                 return max(MIN_CAP, row['SEVERITY'] * MIN_CAP)
#         else:  # Multiple ETFs
#             return MAX_CAP * row['SEVERITY'] / total_severity
#
#     total_severity = filtered_etfs['SEVERITY'].sum()
#     filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs.apply(
#         allocate_sip, axis=1, total_severity=total_severity, num_etfs=num_etfs
#     )
#
#     # Calculate quantities safely
#     filtered_etfs['QTY'] = filtered_etfs.apply(
#         lambda row: int(row['ALLOCATED_AMOUNT'] / row['LTP']) if row['LTP'] > 0 else 0,
#         axis=1
#     )
#
#     return filtered_etfs
#
#
# def calculate_quantities_(filtered_etfs):
#     """
#     Filter ETFs based on criteria and allocate investment amounts with constraints.
#     More conservative allocation for moderate severity situations.
#     """
#     if filtered_etfs.empty:
#         print("No ETFs to allocate.")
#         return None
#
#     # Clean column names: remove whitespace and standardize
#     filtered_etfs.columns = (
#         filtered_etfs.columns.str.strip()
#         .str.replace(" ", "_")
#         .str.upper()
#     )
#
#     # Ensure numeric and clean data
#     filtered_etfs['%CHNG'] = pd.to_numeric(filtered_etfs['%CHNG'], errors='coerce').fillna(0)
#     filtered_etfs['LTP'] = pd.to_numeric(filtered_etfs['LTP'], errors='coerce').fillna(0)
#     filtered_etfs['VOLUME'] = pd.to_numeric(filtered_etfs['VOLUME'].str.replace(',', ''), errors='coerce').fillna(0)
#
#     # Filter out ETFs with LTP <= 0 or low volume
#     filtered_etfs = filtered_etfs[(filtered_etfs['LTP'] > 0) & (filtered_etfs['VOLUME'] >= MIN_VOLUME)]
#
#     # Remove assets containing any DEBT_KEYWORDS
#     pattern = "|".join(DEBT_KEYWORDS)
#     filtered_etfs = filtered_etfs[~filtered_etfs['UNDERLYING_ASSET'].str.contains(pattern, case=False, na=False)]
#
#     # Load and clean average fall data
#     avg_fall_df = pd.read_csv('average_percentage_fall_indices.csv')
#
#     # Make sure we process the average fall columns correctly
#     avg_fall_df.columns = avg_fall_df.columns.str.strip().str.replace(" ", "_").str.upper()
#
#     # DEBUG: Print column names to verify
#     print("Average fall data columns:", avg_fall_df.columns.tolist())
#
#     # Rename columns if needed to ensure consistent naming
#     if 'INDEX_NAME' in avg_fall_df.columns:
#         index_name_col = 'INDEX_NAME'
#     else:
#         # Try to find the appropriate column
#         index_name_col = [col for col in avg_fall_df.columns if 'INDEX' in col or 'NAME' in col][0]
#         print(f"Using '{index_name_col}' as index name column")
#
#     if 'AVERAGE_FALL_(%)' in avg_fall_df.columns:
#         avg_fall_col = 'AVERAGE_FALL_(%)'
#     else:
#         # Try to find the appropriate column
#         avg_fall_col = [col for col in avg_fall_df.columns if 'FALL' in col or 'AVERAGE' in col][0]
#         print(f"Using '{avg_fall_col}' as average fall column")
#
#     # Create a clean map for index names to average falls
#     avg_fall_dict = dict(zip(avg_fall_df[index_name_col], avg_fall_df[avg_fall_col]))
#
#     # Match UNDERLYING_ASSET to INDEX_NAME
#     filtered_etfs['MATCHED_INDEX'] = filtered_etfs['UNDERLYING_ASSET'].apply(
#         lambda x: match_index_name(x, avg_fall_df)
#     )
#
#     # Add AVG_FALL column with GENERIC_AVERAGE_FALL as default
#     filtered_etfs['AVG_FALL'] = filtered_etfs['MATCHED_INDEX'].map(avg_fall_dict).fillna(GENERIC_AVERAGE_FALL)
#
#     # DEBUG: Check if AVG_FALL column exists and has valid values
#     print("Sample of filtered ETFs with AVG_FALL:")
#     print(filtered_etfs[['SYMBOL', 'UNDERLYING_ASSET', 'MATCHED_INDEX', 'AVG_FALL']].head())
#
#     # Filter based on avg fall
#     filtered_etfs = filtered_etfs[filtered_etfs['%CHNG'] < filtered_etfs['AVG_FALL']]
#
#     # If no ETFs meet criteria, return empty DataFrame
#     if filtered_etfs.empty:
#         print("No ETFs meet the criteria (falling more than their average).")
#         return filtered_etfs
#
#     # Handle deduplication with NULL/None MATCHED_INDEX values
#     filtered_etfs['MATCHED_INDEX_SAFE'] = filtered_etfs['MATCHED_INDEX'].fillna('NO_MATCH')
#
#     # Use the safe version for deduplication
#     filtered_etfs = filtered_etfs.loc[filtered_etfs.groupby('MATCHED_INDEX_SAFE')['VOLUME'].idxmax()]
#
#     # Calculate severity
#     def calculate_severity(row):
#         return (row['AVG_FALL'] - row['%CHNG']) / abs(row['AVG_FALL'])
#
#     filtered_etfs['SEVERITY'] = filtered_etfs.apply(calculate_severity, axis=1)
#
#     # Print severity values for selected ETFs
#     print("\nSelected ETFs with severity scores:")
#     print(filtered_etfs[['SYMBOL', '%CHNG', 'AVG_FALL', 'SEVERITY']].to_string())
#
#     # Calculate fall ratio
#     filtered_etfs['FALL_RATIO'] = filtered_etfs['%CHNG'] / filtered_etfs['AVG_FALL']
#
#     # Calculate initial allocations based on severity
#     def allocate_sip_conservative(row):
#         """
#         More conservative allocation function that scales allocation based on severity.
#         - For severity < 0.5: Scale from MIN_CAP up to mid-range
#         - For severity 0.5-1.0: Scale from mid-range up to MAX_CAP
#         - For severity > 1.0: Use MAX_CAP
#         """
#         # Define the severity thresholds
#         low_severity = 0.5
#         high_severity = 1.0
#
#         if row['SEVERITY'] >= high_severity:
#             # High severity (dip more than double the average) - use maximum allocation
#             return MAX_CAP
#         elif row['SEVERITY'] <= low_severity:
#             # Low severity (dip only slightly worse than average)
#             # Scale from MIN_CAP to mid-point based on severity percentage of threshold
#             mid_point = MIN_CAP + (MAX_CAP - MIN_CAP) / 2
#             return MIN_CAP + (row['SEVERITY'] / low_severity) * (mid_point - MIN_CAP)
#         else:
#             # Medium severity - scale from mid-point to MAX_CAP
#             mid_point = MIN_CAP + (MAX_CAP - MIN_CAP) / 2
#             severity_position = (row['SEVERITY'] - low_severity) / (high_severity - low_severity)
#             return mid_point + severity_position * (MAX_CAP - mid_point)
#
#     # Apply the conservative allocation to each ETF
#     filtered_etfs['INITIAL_ALLOCATION'] = filtered_etfs.apply(allocate_sip_conservative, axis=1)
#
#     # Print initial allocations
#     print("\nInitial allocations based on conservative approach:")
#     print(filtered_etfs[['SYMBOL', 'SEVERITY', 'INITIAL_ALLOCATION']].to_string())
#
#     # Check total allocation
#     total_allocated = filtered_etfs['INITIAL_ALLOCATION'].sum()
#     print(f"\nInitial total allocation: ₹{total_allocated:.2f}")
#
#     # Adjust if total allocation is outside the SIP range
#     if total_allocated < DAILY_SIP_MIN:
#         # Scale up all allocations proportionally, but respect MAX_CAP
#         scale_factor = min(DAILY_SIP_MIN / total_allocated,
#                            MAX_CAP / filtered_etfs['INITIAL_ALLOCATION'].max())
#
#         filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs.apply(
#             lambda row: min(MAX_CAP, row['INITIAL_ALLOCATION'] * scale_factor), axis=1
#         )
#         print(f"Scaled up by factor of {scale_factor:.2f} to meet minimum SIP")
#     elif total_allocated > DAILY_SIP_MAX:
#         # Scale down all allocations proportionally
#         scale_factor = DAILY_SIP_MAX / total_allocated
#         filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs['INITIAL_ALLOCATION'] * scale_factor
#         print(f"Scaled down by factor of {scale_factor:.2f} to meet maximum SIP")
#     else:
#         # No scaling needed, use initial allocations
#         filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs['INITIAL_ALLOCATION']
#
#     # Process ETFs that are below MIN_CAP
#     below_min = filtered_etfs[filtered_etfs['ALLOCATED_AMOUNT'] < MIN_CAP]
#
#     if not below_min.empty:
#         print(f"{len(below_min)} ETFs below minimum cap of ₹{MIN_CAP}")
#
#         # Calculate required funds to bring all to MIN_CAP
#         shortfall = (MIN_CAP - below_min['ALLOCATED_AMOUNT']).sum()
#
#         # Check if we have enough budget within DAILY_SIP_MAX
#         current_total = filtered_etfs['ALLOCATED_AMOUNT'].sum()
#         available_budget = DAILY_SIP_MAX - current_total
#
#         if shortfall <= available_budget:
#             # We can bring all to MIN_CAP
#             filtered_etfs.loc[filtered_etfs['ALLOCATED_AMOUNT'] < MIN_CAP, 'ALLOCATED_AMOUNT'] = MIN_CAP
#             print(f"Increased allocations to minimum cap using available budget")
#         else:
#             # Remove ETFs below MIN_CAP
#             filtered_etfs = filtered_etfs[filtered_etfs['ALLOCATED_AMOUNT'] >= MIN_CAP]
#             print(f"Removed ETFs below minimum cap due to budget constraints")
#
#     # Calculate quantities safely
#     filtered_etfs['QTY'] = filtered_etfs.apply(
#         lambda row: int(row['ALLOCATED_AMOUNT'] / row['LTP']) if row['LTP'] > 0 else 0,
#         axis=1
#     )
#
#     # Recalculate final amounts based on actual quantities
#     filtered_etfs['FINAL_AMOUNT'] = filtered_etfs['QTY'] * filtered_etfs['LTP']
#
#     # Final check on total amount
#     final_total = filtered_etfs['FINAL_AMOUNT'].sum()
#
#     # Detailed results table
#     print("\nETF Selection Results:")
#     result_table = filtered_etfs[['SYMBOL', '%CHNG', 'AVG_FALL', 'SEVERITY', 'ALLOCATED_AMOUNT', 'QTY', 'FINAL_AMOUNT']]
#     print(result_table.to_string(index=False))
#
#     print(f"\nETFs selected: {len(filtered_etfs)}")
#     print(f"Total investment: ₹{final_total:.2f}")
#     print(f"Target range: ₹{DAILY_SIP_MIN} to ₹{DAILY_SIP_MAX}")
#
#     return filtered_etfs
#

def calculate_quantities(filtered_etfs):
    """
    Filter ETFs based on criteria and allocate investment amounts with constraints.
    Dynamic allocation based on severity without hardcoded thresholds.
    """
    if filtered_etfs.empty:
        print("No ETFs to allocate.")
        # Return empty DataFrame instead of None to avoid attribute errors upstream
        return filtered_etfs

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

    # Load and clean average fall data
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
        raise FileNotFoundError('average_percentage_fall_indices.csv not found in expected locations. Set AVG_FALL_CSV env to override.')
    logging.info(f"Using average fall CSV: {csv_path}")
    avg_fall_df = pd.read_csv(csv_path)

    # Make sure we process the average fall columns correctly
    avg_fall_df.columns = avg_fall_df.columns.str.strip().str.replace(" ", "_").str.upper()

    # DEBUG: Print column names to verify
    print("Average fall data columns:", avg_fall_df.columns.tolist())

    # Rename columns if needed to ensure consistent naming
    if 'INDEX_NAME' in avg_fall_df.columns:
        index_name_col = 'INDEX_NAME'
    else:
        # Try to find the appropriate column
        index_name_col = [col for col in avg_fall_df.columns if 'INDEX' in col or 'NAME' in col][0]
        print(f"Using '{index_name_col}' as index name column")

    if 'AVERAGE_FALL_(%)' in avg_fall_df.columns:
        avg_fall_col = 'AVERAGE_FALL_(%)'
    else:
        # Try to find the appropriate column
        avg_fall_col = [col for col in avg_fall_df.columns if 'FALL' in col or 'AVERAGE' in col][0]
        print(f"Using '{avg_fall_col}' as average fall column")

    # Create a clean map for index names to average falls
    avg_fall_dict = dict(zip(avg_fall_df[index_name_col], avg_fall_df[avg_fall_col]))

    # Match UNDERLYING_ASSET to INDEX_NAME
    filtered_etfs['MATCHED_INDEX'] = filtered_etfs['UNDERLYING_ASSET'].apply(
        lambda x: match_index_name(x, avg_fall_df)
    )

    # Add AVG_FALL column with GENERIC_AVERAGE_FALL as default
    filtered_etfs['AVG_FALL'] = filtered_etfs['MATCHED_INDEX'].map(avg_fall_dict).fillna(GENERIC_AVERAGE_FALL)

    # DEBUG: Check if AVG_FALL column exists and has valid values
    print("Sample of filtered ETFs with AVG_FALL:")
    print(filtered_etfs[['SYMBOL', 'UNDERLYING_ASSET', 'MATCHED_INDEX', 'AVG_FALL']].head())

    # Filter based on avg fall
    filtered_etfs = filtered_etfs[filtered_etfs['%CHNG'] < filtered_etfs['AVG_FALL']]

    # If no ETFs meet criteria, return empty DataFrame
    if filtered_etfs.empty:
        print("No ETFs meet the criteria (falling more than their average).")
        return filtered_etfs

    # Handle deduplication with NULL/None MATCHED_INDEX values
    filtered_etfs['MATCHED_INDEX_SAFE'] = filtered_etfs['MATCHED_INDEX'].fillna('NO_MATCH')

    # Use the safe version for deduplication
    filtered_etfs = filtered_etfs.loc[filtered_etfs.groupby('MATCHED_INDEX_SAFE')['VOLUME'].idxmax()]

    # Calculate severity
    def calculate_severity(row):
        return (row['AVG_FALL'] - row['%CHNG']) / abs(row['AVG_FALL'])

    filtered_etfs['SEVERITY'] = filtered_etfs.apply(calculate_severity, axis=1)

    # Print severity values for selected ETFs
    print("\nSelected ETFs with severity scores:")
    print(filtered_etfs[['SYMBOL', '%CHNG', 'AVG_FALL', 'SEVERITY']].to_string())

    # Calculate fall ratio for reference
    filtered_etfs['FALL_RATIO'] = filtered_etfs['%CHNG'] / filtered_etfs['AVG_FALL']

    # Direct linear scaling from MIN_CAP to MAX_CAP based on severity
    # This avoids hardcoded thresholds while maintaining a simple, proportional approach
    def allocate_based_on_severity(row):
        """
        Dynamically allocate based on severity without hardcoded thresholds.
        - The allocation scales linearly from MIN_CAP to MAX_CAP based on severity
        - The scaling is unrestricted - any severity > 0 will get at least MIN_CAP
        - As severity approaches 2.0, the allocation approaches MAX_CAP
        - At severity = 2.0 or above, MAX_CAP is used
        """
        # Use 2.0 as a reference point for MAX_CAP (when dip is 3x the average)
        max_severity_reference = 2.0

        # Calculate allocation with direct scaling
        if row['SEVERITY'] >= max_severity_reference:
            # Cap at MAX_CAP for very high severity
            return MAX_CAP
        else:
            # Scale linearly from MIN_CAP to MAX_CAP
            allocation_range = MAX_CAP - MIN_CAP
            severity_percentage = row['SEVERITY'] / max_severity_reference
            return MIN_CAP + (severity_percentage * allocation_range)

    # Apply the dynamic allocation to each ETF
    filtered_etfs['INITIAL_ALLOCATION'] = filtered_etfs.apply(allocate_based_on_severity, axis=1)

    # Print initial allocations
    print("\nInitial allocations based on dynamic scaling:")
    print(filtered_etfs[['SYMBOL', 'SEVERITY', 'INITIAL_ALLOCATION']].to_string())

    # Check total allocation
    total_allocated = filtered_etfs['INITIAL_ALLOCATION'].sum()
    print(f"\nInitial total allocation: ₹{total_allocated:.2f}")

    # Adjust if total allocation is outside the SIP range
    if total_allocated < DAILY_SIP_MIN:
        # Scale up all allocations proportionally, but respect MAX_CAP
        scale_factor = min(DAILY_SIP_MIN / total_allocated,
                           MAX_CAP / filtered_etfs['INITIAL_ALLOCATION'].max())

        filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs.apply(
            lambda row: min(MAX_CAP, row['INITIAL_ALLOCATION'] * scale_factor), axis=1
        )
        print(f"Scaled up by factor of {scale_factor:.2f} to meet minimum SIP")
    elif total_allocated > DAILY_SIP_MAX:
        # Scale down all allocations proportionally
        scale_factor = DAILY_SIP_MAX / total_allocated
        filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs['INITIAL_ALLOCATION'] * scale_factor
        print(f"Scaled down by factor of {scale_factor:.2f} to meet maximum SIP")
    else:
        # No scaling needed, use initial allocations
        filtered_etfs['ALLOCATED_AMOUNT'] = filtered_etfs['INITIAL_ALLOCATION']

    # Process ETFs that are below MIN_CAP
    below_min = filtered_etfs[filtered_etfs['ALLOCATED_AMOUNT'] < MIN_CAP]

    if not below_min.empty:
        print(f"{len(below_min)} ETFs below minimum cap of ₹{MIN_CAP}")

        # Calculate required funds to bring all to MIN_CAP
        shortfall = (MIN_CAP - below_min['ALLOCATED_AMOUNT']).sum()

        # Check if we have enough budget within DAILY_SIP_MAX
        current_total = filtered_etfs['ALLOCATED_AMOUNT'].sum()
        available_budget = DAILY_SIP_MAX - current_total

        if shortfall <= available_budget:
            # We can bring all to MIN_CAP
            filtered_etfs.loc[filtered_etfs['ALLOCATED_AMOUNT'] < MIN_CAP, 'ALLOCATED_AMOUNT'] = MIN_CAP
            print(f"Increased allocations to minimum cap using available budget")
        else:
            # Remove ETFs below MIN_CAP
            filtered_etfs = filtered_etfs[filtered_etfs['ALLOCATED_AMOUNT'] >= MIN_CAP]
            print(f"Removed ETFs below minimum cap due to budget constraints")

    # Calculate quantities safely
    filtered_etfs['QTY'] = filtered_etfs.apply(
        lambda row: int(row['ALLOCATED_AMOUNT'] / row['LTP']) if row['LTP'] > 0 else 0,
        axis=1
    )

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
    print(f"Target range: ₹{DAILY_SIP_MIN} to ₹{DAILY_SIP_MAX}")

    return filtered_etfs
