"""
Per-client static proxy routing for SEBI compliance.

SEBI circular requires each client's order placement to originate from a
dedicated static IP. This module provides a context manager that sets
HTTP_PROXY / HTTPS_PROXY environment variables for the duration of a single
client's execution block.

Since etf_automated.py processes clients SEQUENTIALLY (not in parallel),
env-var swapping is thread-safe here.

Proxy URL format:
  http://username:password@host:port     (authenticated HTTP proxy)
  http://host:port                        (unauthenticated HTTP proxy)
  socks5://username:password@host:port   (SOCKS5 proxy)

All requests-based broker SDKs (Dhan, Zerodha KiteConnect, Angel SmartApi,
Groww, Upstox, Finvasia NorenRestApiPy) inherit proxy settings from env vars
automatically because requests.Session.trust_env defaults to True.
"""

import os
import contextlib
import logging

logger = logging.getLogger(__name__)

_PROXY_ENV_KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')


@contextlib.contextmanager
def client_proxy_context(proxy_url: str):
    """
    Context manager that routes all outbound HTTP/HTTPS through proxy_url
    for the duration of the block.

    Usage:
        with client_proxy_context(client.get('proxy_ip', '')):
            broker_api.place_order(...)

    If proxy_url is empty/None, this is a no-op (no proxy, normal routing).
    """
    if not proxy_url or not proxy_url.strip():
        yield
        return

    proxy_url = proxy_url.strip()
    saved = {k: os.environ.get(k) for k in _PROXY_ENV_KEYS}

    for k in _PROXY_ENV_KEYS:
        os.environ[k] = proxy_url

    logger.info(f"[proxy] Routing through static proxy: {_mask_proxy_url(proxy_url)}")
    print(f"  🔒 Proxy ACTIVE: {_mask_proxy_url(proxy_url)}")
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        print(f"  🔓 Proxy DONE: env vars restored")
        logger.debug("[proxy] Proxy env vars restored to previous state")


def get_client_proxy(client: dict) -> str:
    """Extract and return the proxy URL from client data dict."""
    return (client.get('proxy_ip') or '').strip()


def _mask_proxy_url(url: str) -> str:
    """Mask password in proxy URL for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.password:
            masked = parsed._replace(netloc=f"{parsed.username}:****@{parsed.hostname}:{parsed.port}")
            return urlunparse(masked)
    except Exception:
        pass
    return url


def validate_proxy_url(url: str) -> dict:
    """
    Validate proxy URL format and optionally test connectivity.
    Returns {'valid': bool, 'error': str | None}
    """
    if not url or not url.strip():
        return {'valid': True, 'error': None}

    url = url.strip()
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https', 'socks5', 'socks4'):
            return {'valid': False, 'error': f"Unsupported proxy scheme '{parsed.scheme}'. Use http, https, or socks5."}
        if not parsed.hostname:
            return {'valid': False, 'error': 'Missing proxy hostname.'}
        if not parsed.port:
            return {'valid': False, 'error': 'Missing proxy port.'}
        return {'valid': True, 'error': None}
    except Exception as e:
        return {'valid': False, 'error': str(e)}


def test_proxy_connectivity(proxy_url: str, test_url: str = 'https://httpbin.org/ip', timeout: int = 10) -> dict:
    """
    Test if a proxy is reachable and returns the expected static IP.
    Returns {'ok': bool, 'ip': str | None, 'error': str | None}
    """
    import requests
    try:
        resp = requests.get(test_url, proxies={'http': proxy_url, 'https': proxy_url}, timeout=timeout)
        data = resp.json()
        return {'ok': True, 'ip': data.get('origin', ''), 'error': None}
    except Exception as e:
        return {'ok': False, 'ip': None, 'error': str(e)}
