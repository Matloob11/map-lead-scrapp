from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable

from .config import (
    EVENING_LEADS_FILE,
    FINAL_LEADS_FILE,
    FULL_LEAD_LOG_FILE,
    LEGACY_OUTREACH_CONTACTS_FILE,
    MORNING_LEADS_FILE,
)
from .deduplication import contact_key
from .models import Lead


FULL_LEAD_FIELDS = [field.name for field in fields(Lead)]
FINAL_LEAD_FIELDS = [
    "lead_id",
    "store_title",
    "profession",
    "phone_number",
    "email",
    "opening_time",
    "closing_time",
    "opening_period",
    "map_link",
    "search_query",
]


@dataclass
class SaveResult:
    scanned_count: int
    actionable_count: int
    saved_count: int
    duplicate_count: int
    morning_count: int
    evening_count: int
    unknown_hours_count: int
    final_path: Path
    morning_path: Path
    evening_path: Path
    full_log_path: Path


def save_leads(
    leads: Iterable[Lead],
    final_path: Path = FINAL_LEADS_FILE,
    full_log_path: Path = FULL_LEAD_LOG_FILE,
) -> SaveResult:
    saver = IncrementalLeadSaver(final_path, full_log_path)
    for lead in leads:
        saver.save_lead(lead)
    return saver.get_result()

class IncrementalLeadSaver:
    def __init__(
        self,
        final_path: Path = FINAL_LEADS_FILE,
        full_log_path: Path = FULL_LEAD_LOG_FILE,
        morning_path: Path = MORNING_LEADS_FILE,
        evening_path: Path = EVENING_LEADS_FILE,
        max_saved: int | None = None,
    ):
        self.final_path = final_path
        self.full_log_path = full_log_path
        self.morning_path = morning_path
        self.evening_path = evening_path
        self.max_saved = max_saved
        self.existing_contact_keys = _read_existing_contact_keys(
            [
                final_path,
                full_log_path,
                morning_path,
                evening_path,
                LEGACY_OUTREACH_CONTACTS_FILE,
            ]
        )
        self.scanned_count = 0
        self.actionable_count = 0
        self.saved_count = 0
        self.duplicate_count = 0
        self.morning_count = 0
        self.evening_count = 0
        self.unknown_hours_count = 0
        import threading
        self._lock = threading.Lock()
        _ensure_csv_schema(self.final_path, FINAL_LEAD_FIELDS)
        _ensure_csv_schema(self.full_log_path, FULL_LEAD_FIELDS)
        _ensure_csv_schema(self.morning_path, FINAL_LEAD_FIELDS)
        _ensure_csv_schema(self.evening_path, FINAL_LEAD_FIELDS)

    def save_lead(self, lead: Lead) -> bool:
        with self._lock:
            self.scanned_count += 1
            lead.finalize_identity()
            if not lead.is_target or not lead.has_contact:
                return False

            self.actionable_count += 1
            from .deduplication import lead_contact_key
            key = lead_contact_key(lead)

            if self.max_saved is not None and self.saved_count >= self.max_saved:
                return False
            if key in self.existing_contact_keys:
                self.duplicate_count += 1
                return False

            self.existing_contact_keys.add(key)
            self.saved_count += 1

            _append_csv(self.full_log_path, FULL_LEAD_FIELDS, [lead.as_full_row()])
            _append_csv(self.final_path, FINAL_LEAD_FIELDS, [lead.as_final_row()])
            if lead.opening_period == "morning":
                self.morning_count += 1
                _append_csv(self.morning_path, FINAL_LEAD_FIELDS, [lead.as_final_row()])
            elif lead.opening_period == "evening":
                self.evening_count += 1
                _append_csv(self.evening_path, FINAL_LEAD_FIELDS, [lead.as_final_row()])
            else:
                self.unknown_hours_count += 1

            logging.info(
                "Saved lead: %s | %s | %s | %s",
                lead.lead_id,
                lead.phone_number or lead.email or "-",
                lead.business_name or "-",
                lead.map_link or "-",
            )
            return True

    def get_result(self) -> SaveResult:
        return SaveResult(
            scanned_count=self.scanned_count,
            actionable_count=self.actionable_count,
            saved_count=self.saved_count,
            duplicate_count=self.duplicate_count,
            morning_count=self.morning_count,
            evening_count=self.evening_count,
            unknown_hours_count=self.unknown_hours_count,
            final_path=self.final_path,
            morning_path=self.morning_path,
            evening_path=self.evening_path,
            full_log_path=self.full_log_path,
        )


def _read_existing_contact_keys(paths: list[Path]) -> set[str]:
    contact_keys: set[str] = set()
    for path in dict.fromkeys(paths):
        if not path.exists():
            continue

        with path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                continue

            for row in reader:
                key = contact_key(
                    phone_number=row.get("phone_number", ""),
                    email=row.get("email", ""),
                    lead_id=row.get("lead_id", ""),
                )
                if key and key != "id:":
                    contact_keys.add(key)
    return contact_keys


def _append_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    _ensure_csv_schema(path, fieldnames)

    with path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerows(rows)


def _ensure_csv_schema(path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
        return

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []
        if existing_fieldnames == fieldnames:
            return
        merged_fieldnames = list(dict.fromkeys(fieldnames + existing_fieldnames))
        rows = list(reader)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=merged_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)
