"""Rate limiting and retry helpers for all scrapers."""

import asyncio
import random
import time

import httpx

DEFAULT_DELAY = 0.5
MAX_RETRIES = 3
BACKOFF_BASE = 2  # exponential: 2s, 4s, 8s


# ── Sync helpers ──────────────────────────────────────────────


def polite_delay(base: float = DEFAULT_DELAY):
    """Sleep with a small random jitter so requests don't look robotic."""
    jitter = random.uniform(0, base * 0.5)
    time.sleep(base + jitter)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_retries: int = MAX_RETRIES,
    delay: float = DEFAULT_DELAY,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with retry on 429 and 5xx."""
    for attempt in range(max_retries + 1):
        resp = client.request(method, url, **kwargs)

        if resp.status_code < 400:
            polite_delay(delay)
            return resp

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else BACKOFF_BASE ** (attempt + 1)
            print(f"  Rate limited (429). Waiting {wait}s... (retry {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = BACKOFF_BASE ** (attempt + 1)
            print(f"  Server error ({resp.status_code}). Waiting {wait}s... (retry {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue

        resp.raise_for_status()

    resp.raise_for_status()
    return resp


# ── Async helpers ─────────────────────────────────────────────


async def async_polite_delay(base: float = DEFAULT_DELAY):
    """Async sleep with jitter."""
    jitter = random.uniform(0, base * 0.5)
    await asyncio.sleep(base + jitter)


async def async_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = MAX_RETRIES,
    delay: float = DEFAULT_DELAY,
    **kwargs,
) -> httpx.Response:
    """Async HTTP request with retry on 429 and 5xx."""
    for attempt in range(max_retries + 1):
        resp = await client.request(method, url, **kwargs)

        if resp.status_code < 400:
            await async_polite_delay(delay)
            return resp

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else BACKOFF_BASE ** (attempt + 1)
            print(f"  Rate limited (429). Waiting {wait}s... (retry {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = BACKOFF_BASE ** (attempt + 1)
            print(f"  Server error ({resp.status_code}). Waiting {wait}s... (retry {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)
            continue

        resp.raise_for_status()

    resp.raise_for_status()
    return resp
