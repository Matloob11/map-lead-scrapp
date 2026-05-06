import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import customtkinter as ctk
from tkinter import ttk

from backend.config import (
    ALERT_AUDIO_FILE,
    DEFAULT_MAX_RESULTS,
    DEFAULT_WORKERS,
    SUGGESTED_BUSINESS_TYPES,
)
from backend.query_builder import build_search_queries, parse_keywords
from backend.scraper import ScraperControl, run_single_search
from backend.session_cache import clear_all, clear_query, get_seen_urls
from backend.storage import IncrementalLeadSaver, SaveResult


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Website Gap Lead Finder")
        self.geometry("1180x760")
        self.minsize(980, 680)

        self.scraper_control = None
        self._is_paused = False

        self.title_label = ctk.CTkLabel(
            self,
            text="Website Gap Lead Finder",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.pack(pady=(22, 4))

        self.subtitle_label = ctk.CTkLabel(
            self,
            text="Find Google Maps businesses with no website and export clean client-ready leads.",
            font=ctk.CTkFont(size=14),
            text_color="#94a3b8",
        )
        self.subtitle_label.pack(pady=(0, 18))

        self.search_entry = ctk.CTkEntry(
            self,
            placeholder_text="Business keywords, comma separated, e.g. restaurants, cafes, plumbers",
            width=620,
            height=42,
        )
        self.search_entry.pack(pady=8)
        self.search_entry.bind("<KeyRelease>", self.check_suggestions)

        self.suggestions_frame = ctk.CTkScrollableFrame(
            self,
            width=600,
            height=150,
            fg_color="#111827",
            corner_radius=6,
        )
        self.suggestions = SUGGESTED_BUSINESS_TYPES

        self.settings_frame = ctk.CTkFrame(self, fg_color="#111827", corner_radius=8)
        self.settings_frame.pack(pady=12, padx=24, fill="x")
        self.settings_frame.grid_columnconfigure(1, weight=1)

        self.loc_label = ctk.CTkLabel(self.settings_frame, text="Locations")
        self.loc_label.grid(row=0, column=0, padx=14, pady=(14, 8), sticky="w")

        self.loc_entry = ctk.CTkEntry(
            self.settings_frame,
            placeholder_text="Lahore, Karachi, Islamabad",
            height=36,
        )
        self.loc_entry.grid(row=0, column=1, padx=14, pady=(14, 8), sticky="ew")

        self.results_label = ctk.CTkLabel(self.settings_frame, text="Target saved leads")
        self.results_label.grid(row=1, column=0, padx=14, pady=8, sticky="w")

        self.results_entry = ctk.CTkEntry(self.settings_frame, width=110, height=34)
        self.results_entry.insert(0, str(DEFAULT_MAX_RESULTS))
        self.results_entry.grid(row=1, column=1, padx=14, pady=8, sticky="w")

        self.threads_label = ctk.CTkLabel(self.settings_frame, text="Browser workers")
        self.threads_label.grid(row=2, column=0, padx=14, pady=(8, 14), sticky="w")

        self.threads_entry = ctk.CTkEntry(self.settings_frame, width=110, height=34)
        self.threads_entry.insert(0, str(DEFAULT_WORKERS))
        self.threads_entry.grid(row=2, column=1, padx=14, pady=(8, 14), sticky="w")

        self.headless_label = ctk.CTkLabel(self.settings_frame, text="Background Mode (Headless)")
        self.headless_label.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="w")

        self.headless_switch = ctk.CTkSwitch(self.settings_frame, text="", width=50)
        self.headless_switch.select()
        self.headless_switch.grid(row=3, column=1, padx=14, pady=(0, 14), sticky="w")

        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.pack(pady=14)

        self.search_button = ctk.CTkButton(
            self.controls_frame,
            text="Find Leads",
            height=42,
            width=140,
            command=self.start_search,
            fg_color="#0f766e",
            hover_color="#115e59",
        )
        self.search_button.grid(row=0, column=0, padx=8)

        self.pause_button = ctk.CTkButton(
            self.controls_frame,
            text="Pause",
            height=42,
            width=100,
            command=self.toggle_pause,
            fg_color="#fbbf24",
            hover_color="#d97706",
            text_color="#1e293b",
            state="disabled",
        )
        self.pause_button.grid(row=0, column=1, padx=8)

        self.stop_button = ctk.CTkButton(
            self.controls_frame,
            text="Stop",
            height=42,
            width=100,
            command=self.stop_search,
            fg_color="#ef4444",
            hover_color="#b91c1c",
            state="disabled",
        )
        self.stop_button.grid(row=0, column=2, padx=8)

        self.clear_cache_button = ctk.CTkButton(
            self.controls_frame,
            text="Clear Cache",
            height=42,
            width=120,
            command=self.clear_session_cache,
            fg_color="#475569",
            hover_color="#334155",
        )
        self.clear_cache_button.grid(row=0, column=3, padx=8)

        self.status_label = ctk.CTkLabel(self, text="", text_color="#cbd5e1")
        self.status_label.pack(pady=(2, 0))

        self.progress_bar = ctk.CTkProgressBar(self, width=620)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview",
            background="#0f172a",
            foreground="#e2e8f0",
            rowheight=28,
            fieldbackground="#0f172a",
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground="#f8fafc",
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#0f766e")])

        columns = (
            "lead_id",
            "store_title",
            "profession",
            "phone_number",
            "opening_time",
            "closing_time",
            "email",
            "map_link",
        )
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=12)

        headings = {
            "lead_id": "Lead ID",
            "store_title": "Store Title",
            "profession": "Profession",
            "phone_number": "Phone",
            "opening_time": "Opens",
            "closing_time": "Closes",
            "email": "Email",
            "map_link": "Map URL",
        }
        widths = {
            "lead_id": 130,
            "store_title": 210,
            "profession": 180,
            "phone_number": 135,
            "opening_time": 90,
            "closing_time": 90,
            "email": 180,
            "map_link": 240,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=90, stretch=True)

        self.tree.pack(pady=10, padx=24, fill="both", expand=True)

    def check_suggestions(self, _event):
        typed = self._current_keyword_fragment(self.search_entry.get()).lower()
        if not typed:
            self.suggestions_frame.place_forget()
            return

        matches = [item for item in self.suggestions if typed in item.lower()]
        matches = list(dict.fromkeys(matches))[:8]

        if not matches:
            self.suggestions_frame.place_forget()
            return

        for widget in self.suggestions_frame.winfo_children():
            widget.destroy()

        for match in matches:
            button = ctk.CTkButton(
                self.suggestions_frame,
                text=match,
                fg_color="transparent",
                hover_color="#1e293b",
                text_color="#f8fafc",
                anchor="w",
                command=lambda value=match: self.select_suggestion(value),
            )
            button.pack(fill="x", padx=6, pady=2)

        x = self.search_entry.winfo_x()
        y = self.search_entry.winfo_y() + self.search_entry.winfo_height() + 2
        self.suggestions_frame.place(x=x, y=y)
        self.suggestions_frame.lift()

    def select_suggestion(self, value):
        updated_value = self._replace_last_keyword_fragment(self.search_entry.get(), value)
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, updated_value)
        self.suggestions_frame.place_forget()

    def start_search(self):
        raw_keywords = self.search_entry.get().strip()
        if not parse_keywords(raw_keywords):
            self.set_status("Please enter at least one business keyword.", "#f87171")
            return

        try:
            target_saved_str = self.results_entry.get().strip()
            target_saved = int(target_saved_str) if target_saved_str else None
            if target_saved is not None and target_saved <= 0:
                raise ValueError

            workers_str = self.threads_entry.get().strip()
            workers = int(workers_str) if workers_str else 1
            if workers <= 0:
                raise ValueError
        except ValueError:
            self.set_status("Target saved leads and browser workers must be valid positive numbers.", "#f87171")
            return

        locations = self.parse_locations(self.loc_entry.get())
        queries = build_search_queries(raw_keywords, locations)
        if not queries:
            self.set_status("No valid search queries could be built from the keywords provided.", "#f87171")
            return

        workers = min(workers, len(queries))
        is_headless = bool(self.headless_switch.get())

        resume_counts = [len(get_seen_urls(query)) for query in queries]
        resumed_queries = sum(1 for count in resume_counts if count)
        total_skipped = sum(resume_counts)
        resume_msg = (
            f" - resuming {resumed_queries} cached searches with {total_skipped} scanned URLs"
            if resumed_queries
            else ""
        )
        target_msg = f" until {target_saved} saved leads" if target_saved else ""

        self.search_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")

        def on_auto_pause(message):
            self.after(0, lambda: self._handle_auto_pause(message))

        self.scraper_control = ScraperControl(on_auto_pause=on_auto_pause)
        self._is_paused = False

        self.progress_bar.set(0)
        self.clear_table()
        self.set_status(
            f"Starting {len(queries)} map searches{target_msg}{resume_msg}...",
            "#cbd5e1",
        )

        thread = threading.Thread(
            target=self.run_scraping,
            args=(queries, target_saved, workers, is_headless),
            daemon=True,
        )
        thread.start()

    def run_scraping(self, queries, target_saved, workers, is_headless):
        started_at = time.time()
        saver = IncrementalLeadSaver(max_saved=target_saved)
        failed_queries: list[str] = []

        def on_lead_extracted(lead):
            saved = saver.save_lead(lead)
            if saved:
                self.after(0, lambda: self.add_single_lead_to_table(lead))

            if target_saved:
                self.update_progress(min(saver.saved_count / target_saved, 1))

            self.set_status(
                self._build_processing_status(saver, target_saved),
                "#cbd5e1",
            )

            if (
                target_saved
                and saver.saved_count >= target_saved
                and self.scraper_control
                and not self.scraper_control.is_stopped()
            ):
                self.scraper_control.stop(reason="target_reached")

            return saved

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_query = {
                    executor.submit(
                        run_single_search,
                        search_query,
                        target_saved,
                        on_lead_extracted,
                        self.scraper_control,
                        is_headless,
                    ): search_query
                    for search_query in queries
                }

                for completed, future in enumerate(as_completed(future_to_query), start=1):
                    search_query = future_to_query[future]
                    try:
                        future.result()
                    except Exception as exc:
                        failed_queries.append(search_query)
                        logging.exception("Search failed for %s", search_query)
                        self.set_status(f"Search failed for {search_query}: {exc}", "#f87171")

                    if not target_saved:
                        self.update_progress(completed / len(queries))

            duration = round(time.time() - started_at, 1)
            stop_reason = self.scraper_control.stop_reason() if self.scraper_control else ""
            result = saver.get_result()
            failure_summary = self._build_failure_summary(failed_queries)

            if stop_reason == "manual":
                self.set_status(
                    f"Search stopped manually. Saved {result.saved_count} leads.{failure_summary}",
                    "#fbbf24",
                )
            elif result.saved_count:
                if target_saved and result.saved_count >= target_saved:
                    self.set_status(
                        f"Done in {duration}s. Target reached with {result.saved_count}/{target_saved} saved leads. {self._build_export_summary(result)}{failure_summary}",
                        "#34d399",
                    )
                else:
                    target_text = f"{result.saved_count}/{target_saved}" if target_saved else str(result.saved_count)
                    self.set_status(
                        f"Done in {duration}s. Saved {target_text} leads. {self._build_export_summary(result)}{failure_summary}",
                        "#34d399",
                    )
            elif result.actionable_count:
                self.set_status(
                    (
                        "Done. Contacts were found, but every phone/email already exists. "
                        f"Duplicates skipped: {result.duplicate_count}.{failure_summary}"
                    ),
                    "#fbbf24",
                )
            else:
                if target_saved:
                    self.set_status(
                        f"Done. Search exhausted before reaching {target_saved} saved leads.{failure_summary}",
                        "#fbbf24",
                    )
                else:
                    self.set_status(
                        f"Done. No businesses without a website and phone/email were found.{failure_summary}",
                        "#fbbf24",
                    )
        finally:
            def reset_buttons():
                self.search_button.configure(state="normal")
                self.pause_button.configure(state="disabled", text="Pause")
                self.stop_button.configure(state="disabled")

            self.after(0, reset_buttons)

    def toggle_pause(self):
        if not self.scraper_control:
            return

        if self._is_paused:
            self.scraper_control.resume()
            self._is_paused = False
            self.pause_button.configure(text="Pause")
            self.set_status("Resumed search...", "#cbd5e1")
        else:
            self.scraper_control.pause()
            self._is_paused = True
            self.pause_button.configure(text="Resume")
            self.set_status("Paused search...", "#fbbf24")

    def _handle_auto_pause(self, message):
        self._is_paused = True
        self.pause_button.configure(text="Resume")
        self.set_status(message, "#fbbf24")

        def play_sound():
            try:
                if ALERT_AUDIO_FILE.exists():
                    import pygame

                    pygame.mixer.init()
                    pygame.mixer.music.load(str(ALERT_AUDIO_FILE))
                    pygame.mixer.music.play()
                else:
                    import winsound

                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception as exc:
                logging.warning("Could not play sound: %s", exc)

        threading.Thread(target=play_sound, daemon=True).start()

    def stop_search(self):
        if self.scraper_control:
            self.scraper_control.stop(reason="manual")
            self.set_status("Stopping search (waiting for current tasks to exit)...", "#ef4444")
            self.pause_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")

    def clear_session_cache(self):
        raw_keywords = self.search_entry.get().strip()
        locations = self.parse_locations(self.loc_entry.get())
        queries = build_search_queries(raw_keywords, locations) if raw_keywords else []

        if queries:
            for query in queries:
                clear_query(query)
            self.set_status(
                f"Cache cleared for {len(queries)} query variation(s). Next run will start fresh.",
                "#34d399",
            )
        else:
            clear_all()
            self.set_status("All session cache cleared. Next run will start fresh.", "#34d399")

    @staticmethod
    def parse_locations(raw_locations):
        return [
            location.strip()
            for location in raw_locations.replace("\n", ",").split(",")
            if location.strip()
        ]

    @staticmethod
    def _current_keyword_fragment(raw_value: str) -> str:
        index = max(raw_value.rfind(","), raw_value.rfind(";"), raw_value.rfind("\n"))
        return raw_value[index + 1 :].strip() if index >= 0 else raw_value.strip()

    @staticmethod
    def _replace_last_keyword_fragment(raw_value: str, value: str) -> str:
        index = max(raw_value.rfind(","), raw_value.rfind(";"), raw_value.rfind("\n"))
        if index < 0:
            return value

        prefix = raw_value[: index + 1]
        spacer = "" if prefix.endswith((" ", "\n")) else " "
        return f"{prefix}{spacer}{value}"

    @staticmethod
    def _build_processing_status(saver: IncrementalLeadSaver, target_saved: int | None) -> str:
        saved_text = f"{saver.saved_count}/{target_saved}" if target_saved else str(saver.saved_count)
        return (
            f"Processing... Saved: {saved_text} | Morning: {saver.morning_count} | "
            f"Evening: {saver.evening_count} | Duplicates: {saver.duplicate_count} | "
            f"Scanned: {saver.scanned_count}"
        )

    @staticmethod
    def _build_export_summary(result: SaveResult) -> str:
        summary = (
            f"final_leads.csv updated. Morning: {result.morning_count} -> {result.morning_path.name}, "
            f"Evening: {result.evening_count} -> {result.evening_path.name}."
        )
        if result.unknown_hours_count:
            summary += f" Hours unavailable for {result.unknown_hours_count} lead(s)."
        return summary

    @staticmethod
    def _build_failure_summary(failed_queries: list[str]) -> str:
        if not failed_queries:
            return ""
        count = len(failed_queries)
        sample = ", ".join(failed_queries[:2])
        suffix = "..." if count > 2 else ""
        return f" Failed queries: {count} ({sample}{suffix})."

    def set_status(self, text, color="#cbd5e1"):
        self.after(0, lambda: self.status_label.configure(text=text, text_color=color))

    def update_progress(self, value):
        self.after(0, lambda: self.progress_bar.set(value))

    def clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def update_table_async(self, leads):
        self.after(0, lambda: self.update_table(leads))

    def update_table(self, leads):
        self.clear_table()
        for lead in leads[:100]:
            self.add_single_lead_to_table(lead, "end")

    def add_single_lead_to_table(self, lead, index=0):
        if len(self.tree.get_children()) >= 100:
            last_item = self.tree.get_children()[-1]
            self.tree.delete(last_item)

        self.tree.insert(
            "",
            index,
            values=(
                lead.lead_id,
                lead.store_title,
                lead.profession,
                lead.phone_number,
                lead.opening_time,
                lead.closing_time,
                lead.email,
                lead.map_link,
            ),
        )
