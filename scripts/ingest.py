#!/usr/bin/env python3
"""Fetch events from configured sources, deduplicate, and write JSON artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
EVENTS_PATH = DATA_DIR / "events.json"
LAST_RUN_PATH = DATA_DIR / "last-run.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def make_event_id(source_id: str, url: str, start_iso: str | None) -> str:
    raw = f"{source_id}|{url}|{start_iso or ''}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}"


def parse_datetime(value: str | None, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except (TypeError, ValueError, OverflowError):
        return None


def entry_start_from_parsed(entry: Any, tz: ZoneInfo) -> datetime | None:
    if getattr(entry, "published_parsed", None):
        try:
            t = entry.published_parsed
            return datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=tz)
        except (TypeError, ValueError):
            pass
    return parse_datetime(getattr(entry, "published", None), tz)


def fetch_rss(
    source: dict[str, Any],
    config: dict[str, Any],
    session: requests.Session,
) -> list[dict[str, Any]]:
    tz_name = config.get("timezone", "Europe/Berlin")
    tz = ZoneInfo(tz_name)
    user_agent = config.get("user_agent", "event-calender-manager/1.0")

    response = session.get(
        source["url"],
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)

    events: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    discovered_at = now.isoformat().replace("+00:00", "Z")

    for entry in feed.entries:
        link = getattr(entry, "link", None) or ""
        title = getattr(entry, "title", None) or "Unbekannte Veranstaltung"
        summary = getattr(entry, "summary", None) or ""
        start_dt = entry_start_from_parsed(entry, tz)
        start_iso = start_dt.isoformat() if start_dt else None

        location = source.get("city") or source.get("region") or config.get("region", "")

        events.append(
            {
                "id": make_event_id(source["id"], link, start_iso),
                "source": source["id"],
                "title": title.strip(),
                "start": start_iso,
                "end": None,
                "location": location,
                "url": link,
                "city": source.get("city"),
                "region": source.get("region") or "Baden-Württemberg",
                "description": re.sub(r"<[^>]+>", "", summary).strip()[:500] or None,
                "discovered_at": discovered_at,
            }
        )

    return events


def passes_keyword_filter(event: dict[str, Any], keywords: list[str]) -> bool:
    text = " ".join(filter(None, [event.get("title", ""), event.get("description", "")])).lower()
    return any(re.search(r"\b" + re.escape(kw.lower()) + r"\b", text) for kw in keywords)


def fetch_eventbrite(
    source: dict[str, Any],
    config: dict[str, Any],
    session: requests.Session,
) -> list[dict[str, Any]]:
    user_agent = config.get("user_agent", "event-calender-manager/1.0")
    max_pages = int(source.get("max_pages", 3))
    base_url = source["url"].rstrip("/")
    tz_name = config.get("timezone", "Europe/Berlin")
    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)
    discovered_at = now.isoformat().replace("+00:00", "Z")

    events: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}/?page={page}" if page > 1 else f"{base_url}/"
        resp = session.get(url, headers={"User-Agent": user_agent}, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        page_events: list[dict[str, Any]] = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            for item in data.get("itemListElement", []):
                ev = item.get("item", item)
                name = (ev.get("name") or "").strip()
                if not name:
                    continue

                event_url = ev.get("url") or ""
                description = (ev.get("description") or "")[:500]

                loc_data = ev.get("location") or {}
                addr = loc_data.get("address") or {} if isinstance(loc_data, dict) else {}
                location_str = ", ".join(filter(None, [
                    addr.get("streetAddress") if isinstance(addr, dict) else None,
                    addr.get("addressLocality") if isinstance(addr, dict) else None,
                ])) or source.get("city") or "Stuttgart"

                def _parse_eb_date(raw: str | None) -> str | None:
                    if not raw:
                        return None
                    try:
                        suffix = "T00:00:00" if "T" not in raw else ""
                        dt = datetime.fromisoformat(raw + suffix)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=tz)
                        return dt.isoformat()
                    except ValueError:
                        return raw

                start_iso = _parse_eb_date(ev.get("startDate"))
                end_iso = _parse_eb_date(ev.get("endDate"))

                page_events.append({
                    "id": make_event_id(source["id"], event_url, start_iso),
                    "source": source["id"],
                    "title": name[:200],
                    "start": start_iso,
                    "end": end_iso,
                    "location": location_str,
                    "url": event_url,
                    "city": source.get("city"),
                    "region": source.get("region") or "Baden-Württemberg",
                    "description": description or None,
                    "discovered_at": discovered_at,
                })

        if not page_events:
            break
        events.extend(page_events)

    return events


def fetch_html(
    source: dict[str, Any],
    config: dict[str, Any],
    session: requests.Session,
) -> list[dict[str, Any]]:
    user_agent = config.get("user_agent", "event-calender-manager/1.0")
    max_items = int(source.get("max_items", 25))
    now = datetime.now(timezone.utc)
    discovered_at = now.isoformat().replace("+00:00", "Z")

    response = session.get(
        source["url"],
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    events: list[dict[str, Any]] = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        title = anchor.get_text(strip=True)
        if not href or not title or len(title) < 5:
            continue
        if "event" not in href.lower() and "/events" not in href.lower():
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(source["url"], href)
        if not href.startswith("http"):
            continue

        events.append(
            {
                "id": make_event_id(source["id"], href, None),
                "source": source["id"],
                "title": title[:200],
                "start": None,
                "end": None,
                "location": source.get("region") or "Baden-Württemberg",
                "url": href,
                "city": source.get("city"),
                "region": source.get("region") or "Baden-Württemberg",
                "description": None,
                "discovered_at": discovered_at,
            }
        )
        if len(events) >= max_items:
            break

    return events


def within_horizon(start_iso: str | None, horizon_end: datetime, tz: ZoneInfo) -> bool:
    if not start_iso:
        return True
    try:
        start = datetime.fromisoformat(start_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        return start <= horizon_end
    except ValueError:
        return True


def main() -> int:
    config = load_config()
    tz_name = config.get("timezone", "Europe/Berlin")
    tz = ZoneInfo(tz_name)
    horizon_days = int(config.get("horizon_days", 30))

    now_local = datetime.now(tz)
    horizon_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_end = horizon_start + timedelta(days=horizon_days)

    state = load_json(STATE_PATH, {"seen_ids": []})
    seen_ids: set[str] = set(state.get("seen_ids", []))

    session = requests.Session()
    all_events: list[dict[str, Any]] = []
    all_event_ids: set[str] = set()
    errors: list[dict[str, str]] = []
    new_count = 0
    skipped_count = 0

    kf = config.get("keyword_filter", {})
    kf_enabled = kf.get("enabled", False)
    kf_keywords: list[str] = kf.get("keywords", [])

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        source_id = source.get("id", "unknown")
        try:
            if source.get("type") == "rss":
                fetched = fetch_rss(source, config, session)
            elif source.get("type") == "eventbrite":
                fetched = fetch_eventbrite(source, config, session)
            elif source.get("type") == "html":
                fetched = fetch_html(source, config, session)
            else:
                errors.append({"source": source_id, "message": f"Unknown type: {source.get('type')}"})
                continue
        except Exception as exc:  # noqa: BLE001 — collect per-source errors for last-run.json
            errors.append({"source": source_id, "message": str(exc)})
            continue

        apply_kf = source.get("apply_keyword_filter", kf_enabled)
        if apply_kf and kf_keywords:
            fetched = [e for e in fetched if passes_keyword_filter(e, kf_keywords)]

        for event in fetched:
            event_id = event["id"]
            if event_id in seen_ids:
                skipped_count += 1
            else:
                seen_ids.add(event_id)
                new_count += 1

            start_iso = event.get("start")
            if start_iso:
                try:
                    start = datetime.fromisoformat(start_iso)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=tz)
                    if start < horizon_start:
                        continue
                except ValueError:
                    pass

            if within_horizon(start_iso, horizon_end, tz) and event_id not in all_event_ids:
                all_events.append(event)
                all_event_ids.add(event_id)

    all_events.sort(key=lambda e: e.get("start") or "9999")

    ran_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_json(
        EVENTS_PATH,
        {
            "updated_at": ran_at,
            "count": len(all_events),
            "events": all_events,
        },
    )
    save_json(STATE_PATH, {"seen_ids": sorted(seen_ids)})
    save_json(
        LAST_RUN_PATH,
        {
            "ran_at": ran_at,
            "new": new_count,
            "skipped": skipped_count,
            "total_in_horizon": len(all_events),
            "errors": errors,
        },
    )

    print(
        f"Ingest complete: {len(all_events)} events in horizon, "
        f"{new_count} new ids, {skipped_count} already seen, {len(errors)} errors"
    )
    return 1 if errors and not all_events else 0


if __name__ == "__main__":
    sys.exit(main())
