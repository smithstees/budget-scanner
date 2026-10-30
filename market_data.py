"""Public-data transport: bounded retries, pacing and expiring successful caches.

Cache age is not quote age. Never use a retrieval time as an exchange quote time.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(os.environ.get('SCANNER_CACHE_DIR', '.market-data-cache'))
EVENTS = []
_last_request = 0.0


def reset_events():
    EVENTS.clear()


def health():
    return dict(Counter(e['status'] for e in EVENTS))


def get_json(url, timeout=15, headers=None, ttl=0):
    global _last_request
    parts = urllib.parse.urlsplit(url)
    params = urllib.parse.parse_qs(parts.query)
    cache_url = url
    if params.get('interval') == ['1d']:
        # Rolling epoch parameters change every second; daily history still
        # needs a stable cache identity within this UTC day.
        params.pop('period1', None); params.pop('period2', None)
        params['cache_day'] = [datetime.now(timezone.utc).date().isoformat()]
        cache_url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params, doseq=True)))
    key = hashlib.sha256(cache_url.encode()).hexdigest()
    path = CACHE / (key + '.json')
    source = urllib.parse.urlsplit(url).hostname
    if ttl:
        try:
            saved = json.loads(path.read_text())
            if 0 <= time.time() - saved['saved_at'] <= ttl:
                EVENTS.append(dict(source=source, status='cache_hit'))
                return saved['data']
        except (OSError, ValueError, KeyError, TypeError):
            pass
    request_headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    request_headers.update(headers or {})
    for attempt in range(3):
        time.sleep(max(0, 0.5 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        retry_after = 0
        try:
            req = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())
            if not isinstance(data, dict):
                raise ValueError('Expected JSON object')
            if any(isinstance(data.get(k), dict) and data[k].get('error')
                   for k in ('chart', 'quoteSummary')):
                EVENTS.append(dict(source=source, status='provider_error'))
                return None
            EVENTS.append(dict(source=source, status='success'))
            if ttl:
                try:
                    CACHE.mkdir(parents=True, exist_ok=True)
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps(dict(saved_at=time.time(), data=data)))
                    temp.replace(path)
                except OSError:
                    pass  # A cache write is optional; never replace a good response.
            return data
        except urllib.error.HTTPError as exc:
            status = 'http_' + str(exc.code)
            retry = exc.code in (408, 429, 500, 502, 503, 504)
            try:
                retry_after = min(30, max(0, float(exc.headers.get('Retry-After', 0))))
            except (ValueError, TypeError, AttributeError):
                retry_after = 0
        except (OSError, ValueError) as exc:
            status = 'invalid_json' if isinstance(exc, ValueError) else 'network_error'
            retry = not isinstance(exc, ValueError)
        EVENTS.append(dict(source=source, status=status))
        if not retry or attempt == 2:
            return None
        time.sleep(max(retry_after, 2 ** (attempt + 1)))


def quote_time(value):
    """Only explicit timezone-aware quote timestamps; no stock last-trade fallback."""
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return None


def fresh_option(quote, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = quote_time(quote.get('quote_as_of'))
    return stamp is not None and 0 <= (now - datetime.fromisoformat(stamp)).total_seconds() <= 1800
