"""
session_cache.py
----------------
Persistent cache of already-processed Google Maps place URLs, keyed by
search query.  Stored as a plain JSON file so it survives restarts.

On every new search run the scraper loads the cache, skips every URL
already present, and appends newly-visited URLs so the next run can
continue exactly where the previous one stopped.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .config import ROOT_DIR

_CACHE_FILE = ROOT_DIR / ".scraper_session_cache.json"
_lock = threading.Lock()


def _load_raw() -> dict[str, list[str]]:
    if _CACHE_FILE.exists():
        try:
            with _CACHE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logging.warning("Could not read session cache: %s", exc)
    return {}


def _save_raw(data: dict[str, list[str]]) -> None:
    try:
        with _CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logging.warning("Could not write session cache: %s", exc)


def get_seen_urls(query: str) -> set[str]:
    """Return the set of place URLs already processed for *query*."""
    with _lock:
        data = _load_raw()
        return set(data.get(query, []))


def mark_url_seen(query: str, url: str) -> None:
    """Append *url* to the persistent list for *query*."""
    with _lock:
        data = _load_raw()
        urls = data.setdefault(query, [])
        if url not in urls:
            urls.append(url)
        _save_raw(data)


def clear_query(query: str) -> None:
    """Reset the cache for a specific query (start fresh)."""
    with _lock:
        data = _load_raw()
        if query in data:
            del data[query]
            _save_raw(data)
            logging.info("Session cache cleared for: %s", query)


def clear_all() -> None:
    """Wipe the entire cache."""
    with _lock:
        _save_raw({})
        logging.info("Session cache fully cleared.")


def summary() -> dict[str, int]:
    """Return {query: urls_seen_count} for display purposes."""
    with _lock:
        data = _load_raw()
        return {q: len(v) for q, v in data.items()}
