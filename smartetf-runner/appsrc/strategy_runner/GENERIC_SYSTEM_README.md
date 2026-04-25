# Generic Broker-Agnostic Order Execution System

## Architecture Overview

**Centralized retry logic** - All brokers use the same fallback system.  
**Broker-specific code only** - Simple API wrappers for each broker.  
**Per-symbol processing** - Each symbol independently retried across all alternatives.

## How It Works

### Flow for Each Client

```
For Client 1 (FINVASIA):
  For Symbol 1 (GOLDSHARE):
    1. Try GOLDSHARE → FAILED
    2. Try GOLDBEES (mapped) → FAILED
    3. Try SETFGOLD (2nd volume) → SUCCESS ✅
  
  For Symbol 2 (AUTOIETF):
    1. Try AUTOIETF → SUCCESS ✅
  
  ✅ Client 1 complete

For Client 2 (ZERODHA):
  For Symbol 1 (GOLDSHARE):
    1. Try GOLDSHARE → SUCCESS ✅
  
  For Symbol 2 (BADSYMBOL):
    1. Try BADSYMBOL → FAILED
    2. Try ALT1 (2nd volume) → FAILED
    3. Try ALT2 (3rd volume) → FAILED
    4. Try ALT3 → FAILED
    ❌ Max 3 alternatives tried, queuing for admin email
  
  ✅ Client 2 complete (with 1 failed symbol)
```

### Per-Symbol Retry Logic

**Same for ALL brokers:**

1. **Try original symbol**
2. **If fails → try up to 3 alternatives:**
   - Manual mapping (if exists)
   - 2nd highest volume (same underlying)
   - 3rd highest volume (same underlying)
3. **After 3 attempts → stop**
4. **If all fail → queue for admin email**
5. **Move to next symbol**

**Max alternatives: 3**

## File Structure

### Core Generic System

**order_executor_generic.py**
- `GenericOrderExecutor` class
- Handles all retry logic
- Works with any broker
- Calls broker API wrapper
- Logs all results

### Broker API Wrappers (Simple!)

**zerodha_broker_api.py**
```python
def place_single_order_direct(client, symbol, qty):
    # Just place order, raise exception if fails
    # NO retry logic here
    return order_id
```

**dhan_broker_api.py**
```python
def place_single_order_direct(client, symbol, qty):
    # Just place order
    return order_id
```

**finvasia_broker_api.py**
```python
def place_single_order_direct(client, symbol, qty):
    # Just place order
    return order_id
```

### Configuration

**symbol_config.py**
- Exclusion list
- Manual mappings (global + broker-specific)
- Alternative discovery by underlying asset

**order_tracker.py**
- Log all order results to file
- JSON format with full details

**admin_notification.py**
- Auto-email admin on failures
- Group by reason
- Show alternatives tried

## Adding New Broker

**Example: Add mStock support**

1. Create `mstock_broker_api.py`:

```python
def place_single_order_direct(client, symbol, qty):
    # mStock-specific API call
    api = MStockAPI(client['api_key'])
    order_id = api.place_order(symbol, qty)
    return order_id

def get_available_funds(client):
    # mStock balance check
    return balance
```

2. Update `broker_dispatcher.py`:

```python
elif name == "MSTOCK":
    file_path = os.path.join(script_dir, "mstock_broker_api.py")
    return _load_module_by_path("mstock_broker_api", file_path)
```

3. **That's it!** Generic executor handles everything else.

## Benefits

✅ **No code duplication** - Retry logic written once  
✅ **Easy to add brokers** - Just create simple API wrapper  
✅ **Consistent behavior** - All brokers work the same way  
✅ **Easy debugging** - All logic in one place  
✅ **Centralized logging** - One log format for all  
✅ **Centralized notifications** - One email system  

## Configuration

### 1. Exclude Symbols

```python
# symbol_config.py
EXCLUDED_SYMBOLS = [
    'GOLDSHARE',
    'BADSYMBOL',
]
```

### 2. Manual Mappings

```python
# Global (all brokers)
GLOBAL_SYMBOL_MAPPING = {
    'GOLDSHARE': 'GOLDBEES',
}

# Broker-specific (overrides global)
BROKER_SPECIFIC_MAPPING = {
    'ZERODHA': {
        'GOLDSHARE': 'GOLDBEES',
    },
    'DHAN': {
        'GOLDSHARE': 'SETFGOLD',
    },
}
```

### 3. Automatic Fallback

If no mapping or mapping fails:
- Find all ETFs with same underlying asset
- Sort by volume (highest first)
- Try 2nd, 3rd, 4th... until one works

## Logging

**File:** `logs/order_execution_YYYYMMDD.log`

**Format:**
```json
{
  "timestamp": "2025-01-08T...",
  "customer_id": "smartetf_user_10013",
  "broker": "FINVASIA",
  "symbol": "GOLDSHARE",
  "status": "REPLACED",
  "actual_symbol": "SETFGOLD",
  "original_qty": 2,
  "actual_qty": 3,
  "reason": "Auto-discovered (underlying: Gold)",
  "order_id": "123456"
}
```

## Admin Notifications

**Triggered when:**
- Any FAILED orders
- Any REPLACED orders

**Email includes:**
- Overall statistics
- List of replacements
- Failed orders grouped by reason
- Alternatives tried for each

## Files Modified

1. **order_executor_generic.py** (NEW) - Central retry logic
2. **zerodha_broker_api.py** (NEW) - Simple Zerodha wrapper
3. **dhan_broker_api.py** (NEW) - Simple DHAN wrapper
4. **finvasia_broker_api.py** (NEW) - Simple FINVASIA wrapper
5. **broker_dispatcher.py** - Route to new wrappers
6. **etf_automated.py** - Use GenericOrderExecutor
7. **symbol_config.py** - Updated fallback function
8. **order_tracker.py** - Logging
9. **admin_notification.py** - Emails

## Testing

1. Add test symbol to exclusions
2. Run order execution
3. Check log file for fallback chain
4. Verify admin email received

## Dynamic Quantity Calculation

**Amount is always preserved:**

- Original: GOLDSHARE × 2 @ ₹150 = ₹300
- Alternative: GOLDBEES @ ₹100  
- New Qty: ₹300 ÷ ₹100 = **3 shares**

This ensures investment amount remains consistent across alternatives.

## Summary

✨ **One system, all brokers**  
✨ **Add new broker in 2 minutes**  
✨ **Consistent, reliable, maintainable**
