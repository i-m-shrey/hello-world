import os
import time
import json
from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple

import requests


class DhanApiError(RuntimeError):
    pass


@dataclass
class DhanAuth:
    client_id: str
    access_token: str


class DhanAPI:
    """Minimal DHAN (DhanHQ) API wrapper used by SmartETFAlgo.

    Uses v2 endpoints and the documented headers:
      - 'access-token': <token>
      - 'dhanClientId': <client id>

    Notes:
      - For order placement we need a securityId. We map symbol -> securityId using the DHAN scrip master.
    """

    BASE_URL = os.getenv('DHAN_BASE_URL', 'https://api.dhan.co')

    SCRIP_MASTER_URL = os.getenv(
        'DHAN_SCRIP_MASTER_URL',
        'https://images.dhan.co/api-data/api-scrip-master.csv'
    )

    def __init__(self, auth: DhanAuth, timeout: int = 20, proxy_url: str = None):
        self.auth = auth
        self.timeout = timeout
        self.session = requests.Session()
        if proxy_url:
            self.session.proxies = {
                'http': proxy_url,
                'https': proxy_url,
            }

    def _headers(self) -> Dict[str, str]:
        return {
            'access-token': self.auth.access_token,
            'dhanClientId': self.auth.client_id
        }

    def _request(self, method: str, path: str, payload: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        url = self.BASE_URL.rstrip('/') + path
        headers = self._headers()
        
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        
        kwargs = {
            'method': method,
            'url': url,
            'headers': headers,
            'params': params,
            'timeout': self.timeout
        }
        
        if payload is not None:
            kwargs['json'] = payload
        
        resp = self.session.request(**kwargs)
        
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {'raw': resp.text}
        if resp.status_code >= 400:
            raise DhanApiError(f"DHAN API {method} {path} failed: HTTP {resp.status_code} | {data}")
        return data

    def renew_token(self) -> str:
        """Renew the current access token. Returns the new token string."""
        data = self._request('POST', '/v2/RenewToken', payload=None)
        new_token = data.get('accessToken') or data.get('access_token') or data.get('token')
        if not new_token:
            raise DhanApiError(f"Renew token response did not include new token: {data}")
        self.auth.access_token = new_token
        return new_token

    def get_fund_limit(self) -> dict:
        return self._request('GET', '/v2/fundlimit')

    def place_order(self, payload: dict) -> dict:
        return self._request('POST', '/v2/orders', payload=payload)
    
    def generate_access_token(self, client_id: str, api_key: str, api_secret: str) -> str:
        """Generate access token from API key and secret. Returns the new token."""
        endpoints_to_try = [
            ('/v2/token', {'clientId': client_id, 'apiKey': api_key, 'secretKey': api_secret}),
            ('/v2/login', {'clientId': client_id, 'apiKey': api_key, 'secretKey': api_secret}),
            ('/v2/generateToken', {'clientId': client_id, 'apiKey': api_key, 'apiSecret': api_secret}),
            ('/v2/edis/login', {'dhanClientId': client_id, 'apiKey': api_key, 'secretKey': api_secret})
        ]
        
        last_error = None
        for endpoint, payload in endpoints_to_try:
            try:
                url = self.BASE_URL.rstrip('/') + endpoint
                resp = self.session.post(url, json=payload, timeout=self.timeout)
                data = resp.json() if resp.text else {}
                
                if resp.status_code == 200:
                    token = data.get('accessToken') or data.get('access_token') or data.get('token') or data.get('data', {}).get('token')
                    if token:
                        self.auth.access_token = token
                        return token
                last_error = data
            except Exception as e:
                last_error = str(e)
                continue
        
        raise DhanApiError(f"Failed to generate access token from all endpoints. Last error: {last_error}")


def _normalize_symbol(s: str) -> str:
    return (s or '').strip().upper()


# In-memory cache for scrip master map — loaded once per process run,
# never re-read from disk during order execution.
_scrip_master_cache: Dict[Tuple[str, str], int] = {}
_scrip_master_loaded: bool = False


def load_scrip_master_map(cache_path: str = 'data/dhan_scrip_master.csv', max_age_seconds: int = 24 * 3600) -> Dict[Tuple[str, str], int]:
    """Returns a map: (exchange_segment, trading_symbol) -> security_id

    exchange_segment examples: 'NSE_EQ', 'BSE_EQ', 'NSE_FNO' etc.
    
    The map is loaded from disk ONCE per process run and cached in memory.
    Subsequent calls return the cached map instantly (no disk I/O).
    """
    global _scrip_master_cache, _scrip_master_loaded

    if _scrip_master_loaded and _scrip_master_cache:
        return _scrip_master_cache
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    use_cache = False
    if os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age <= max_age_seconds:
            use_cache = True

    if not use_cache:
        url = os.getenv('DHAN_SCRIP_MASTER_URL', DhanAPI.SCRIP_MASTER_URL)
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(cache_path, 'wb') as f:
            f.write(r.content)

    import csv

    out: Dict[Tuple[str, str], int] = {}
    with open(cache_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            exchange = row.get('ExchangeSegment') or row.get('exchangeSegment') or row.get('exchange_segment') or row.get('exchange')
            sym = row.get('TradingSymbol') or row.get('tradingSymbol') or row.get('trading_symbol') or row.get('symbol')
            sec = row.get('SecurityId') or row.get('securityId') or row.get('security_id') or row.get('securityid')
            
            if not exchange:
                exch_id = row.get('SEM_EXM_EXCH_ID', '').strip()
                segment = row.get('SEM_SEGMENT', '').strip()
                if exch_id and segment:
                    seg_map = {'C': 'EQ', 'D': 'EQ', 'E': 'EQ', 'F': 'FNO', 'O': 'FNO'}
                    exchange = f"{exch_id}_{seg_map.get(segment, segment)}"
            
            if not sym:
                sym = row.get('SEM_TRADING_SYMBOL', '').strip()
            
            if not sec:
                sec = row.get('SEM_SMST_SECURITY_ID', '').strip()
            
            if not exchange or not sym or not sec:
                continue
            try:
                sec_id = int(str(sec).strip())
            except Exception:
                continue
            out[(exchange.strip().upper(), _normalize_symbol(sym))] = sec_id

    if not out:
        raise DhanApiError("Could not build scrip master map (empty). Check DHAN_SCRIP_MASTER_URL / file format.")

    _scrip_master_cache = out
    _scrip_master_loaded = True
    return out


def get_security_id(symbol: str, exchange_segment: str = 'NSE_EQ', cache_path: str = 'data/dhan_scrip_master.csv') -> int:
    smap = load_scrip_master_map(cache_path=cache_path)
    key = (exchange_segment.strip().upper(), _normalize_symbol(symbol))
    if key in smap:
        return smap[key]

    raise DhanApiError(f"SecurityId not found for {exchange_segment}:{symbol}")