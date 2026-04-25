# GROWW TOTP Integration - COMPLETE

## Overview
Groww broker is now fully integrated with TOTP-based daily token generation.
Client provides API Key + TOTP Secret ONCE, system handles daily token refresh automatically.

---

## Flow Architecture

### 1. Morning Health Check (`morning_health_check.py`)
```
┌─────────────────────────────────────────────────────────────┐
│  8:30 AM Daily                                              │
│                                                             │
│  1. session_manager.initialize_all_sessions()               │
│     └── For GROWW: returns None (handles own tokens)        │
│                                                             │
│  2. _update_broker_balances()                               │
│     └── For each GROWW client:                              │
│         └── groww_broker_api.get_available_funds()          │
│             └── _get_groww() → auto-generates token if needed│
│                                                             │
│  3. Session check reports:                                    │
│     └── GROWW clients marked as "self-managed"              │
└─────────────────────────────────────────────────────────────┘
```

### 2. Order Execution (`etf_automated.py`)
```
┌─────────────────────────────────────────────────────────────┐
│  When placing orders (15:10 PM daily):                       │
│                                                             │
│  1. broker_api_module = get_executor_for_broker('GROWW')    │
│     └── Returns groww_broker_api module                     │
│                                                             │
│  2. broker_api_module.place_single_order_direct(client, ...)│
│     └── _get_groww(client) → checks/creates token           │
│     └── GrowwAPI(token).place_order(...)                    │
│                                                             │
│  3. On auth error (401/403):                                │
│     └── _invalidate_session()                               │
│     └── Retry with fresh token                              │
└─────────────────────────────────────────────────────────────┘
```

---

## File Changes Made

### 1. `groww_broker_api.py` ✅ UPDATED
**Location:** `/home/SmartETF_v6_1/SmartETF_Merged_Full_Project/groww_broker_api.py`

**Key Functions:**
- `generate_groww_token_daily(api_key, totp_secret)` - TOTP-based token generation
- `refresh_groww_token_for_client(client)` - Called by health check
- `place_single_order_direct(client, symbol, qty, ...)` - Order placement with auto-retry
- `get_holdings(client)` - Holdings with auto-refresh
- `get_available_funds(client)` - Funds with auto-refresh

**Token Flow:**
1. Check `_SESSION_CACHE` for valid token (< 12 hours old)
2. If missing/expired: call `generate_groww_token_daily()`
3. Generate TOTP code using `pyotp.TOTP(totp_secret).now()`
4. POST to `https://api.groww.in/v1/token/api/access`
5. Store token in cache (12-hour expiry)
6. Use `GrowwAPI(token)` for API calls

---

### 2. `session_manager.py` ✅ NO CHANGE NEEDED
**Location:** `/home/SmartETF_v6_1/SmartETF_Merged_Full_Project/session_manager.py`

**Line 147-148:**
```python
elif broker_name in ['UPSTOX', 'ANGEL', 'ANGELONE', 'ANGLE', 'GROWW']:
    return None  # These brokers handle their own sessions
```

✅ GROWW is correctly set to `None` - it manages its own token generation in `groww_broker_api.py`

---

### 3. `etf_automated.py` ✅ NO CHANGE NEEDED
**Location:** `/home/SmartETF_v6_1/SmartETF_Merged_Full_Project/etf_automated.py`

**Lines 1035, 1098, 1131:**
```python
broker_api_module = get_executor_for_broker(broker_name)
# ... later ...
return self.api_module.place_single_order_direct(self.client, symbol, qty)
```

✅ Already uses `broker_dispatcher` → `groww_broker_api.py` flow

---

### 4. `broker_dispatcher.py` ✅ NO CHANGE NEEDED
**Location:** `/home/SmartETF_v6_1/SmartETF_Merged_Full_Project/broker_dispatcher.py`

**Lines 48-50:**
```python
elif name == "GROWW":
    file_path = os.path.join(script_dir, "groww_broker_api.py")
    return _load_module_by_path("groww_broker_api", file_path)
```

✅ Already correctly routes to `groww_broker_api.py`

---

## Admin Panel Configuration

### SupportedBroker Table Settings for GROWW:

| Field | Value | Notes |
|-------|-------|-------|
| `requires_api_key` | ✅ True | API Key JWT |
| `requires_totp` | ✅ True | TOTP Secret (NEW - enable this!) |
| `requires_api_secret` | ❌ False | Not needed for TOTP |
| `requires_password` | ❌ False | Not needed |
| `requires_client_id` | ❌ False | Not needed |
| `requires_mobile` | ❌ False | Not needed |
| `requires_access_token` | ❌ False | Auto-generated |

**Help Text:**
- `help_text_api_key`: "The API Key JWT from Groww (long string starting with eyJ...)"
- `help_text_totp`: "The TOTP Secret shown when generating TOTP token on Groww website"

---

## Client Data Structure (Broker Table)

| Field | Populated By | Used By |
|-------|--------------|---------|
| `api_key` | Client enters API Key JWT | `generate_groww_token_daily()` |
| `totp_secret` | Client enters TOTP Secret | `generate_groww_token_daily()` |
| `access_token` | Auto-generated daily | Cached for 12 hours |
| `password` | Empty for Groww | Not used |
| `api_secret` | Empty for Groww | Not used |

---

## Credentials Client Needs to Provide (ONE TIME)

1. **Go to:** https://groww.in/trade-api/api-keys
2. **Click:** "Generate TOTP Token"
3. **Copy:**
   - API Key (long JWT starting with `eyJ...`)
   - TOTP Secret (base32 string like `NZW4QJUX...`)
4. **Paste in your app:**
   - API Key field → `api_key`
   - TOTP Secret field → `totp_secret`

---

## Testing

### Manual Test:
```bash
cd /home/test_groww
python test_groww_totp_final.py
```

Expected: All 7 tests pass ✅

### Integration Test:
1. Go to `/admin/broker/add`
2. Select broker: GROWW
3. Enter: API Key + TOTP Secret
4. Click: "Test Order"
5. Verify: Order placed successfully

---

## Daily Operation

### 8:30 AM - Morning Health Check:
```
For each GROWW client:
  - Check if access_token is valid (< 12 hours)
  - If expired: generate new token using api_key + totp_secret
  - Check available funds
  - Update Broker.available_balance
```

### 15:10 PM - Order Execution:
```
For each GROWW client:
  - Get cached token (or generate if expired)
  - Place orders using place_single_order_direct()
  - On auth error: refresh token and retry
```

---

## Key Benefits

| Before (Approval-type) | After (TOTP-type) |
|------------------------|-------------------|
| Client generates token every 5 days | ✅ Client enters credentials ONCE |
| Manual website visits | ✅ Fully automated |
| Token expires quickly | ✅ 24-hour token with auto-refresh |
| High maintenance | ✅ Zero maintenance after setup |

---

## Summary

✅ **All files updated and integrated**
✅ **Flow verified: morning_health_check → session_manager → groww_broker_api → etf_automated**
✅ **Client only provides API Key + TOTP Secret once**
✅ **System generates tokens automatically every day**

**Ready for production!**
