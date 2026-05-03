import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import customtkinter as ctk
from tkinter import ttk

from backend.config import DEFAULT_MAX_RESULTS, DEFAULT_WORKERS, SUGGESTED_BUSINESS_TYPES

from backend.scraper import run_single_search, ScraperControl
from backend.storage import IncrementalLeadSaver
from backend.session_cache import get_seen_urls, clear_query, clear_all, summary as cache_summary


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Website Gap Lead Finder")
        self.geometry("1080x740")
        self.minsize(900, 660)

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
            placeholder_text="Business type, e.g. Restaurants, Plumbers, Dentists",
            width=560,
            height=42,
        )
        self.search_entry.pack(pady=8)
        self.search_entry.bind("<KeyRelease>", self.check_suggestions)

        self.suggestions_frame = ctk.CTkScrollableFrame(
            self,
            width=540,
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

        self.results_label = ctk.CTkLabel(self.settings_frame, text="Max results per location")
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
        self.headless_switch.select() # Default to Headless mode ON for performance
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

        self.progress_bar = ctk.CTkProgressBar(self, width=560)
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

        columns = ("lead_id", "phone_number", "profession", "store_title", "email", "map_link")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=12)

        headings = {
            "lead_id": "Lead ID",
            "phone_number": "Phone",
            "profession": "Profession",
            "store_title": "Store Title",
            "email": "Email",
            "map_link": "Map URL",
        }
        widths = {
            "lead_id": 130,
            "phone_number": 140,
            "profession": 150,
            "store_title": 220,
            "email": 180,
            "map_link": 260,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=90, stretch=True)

        self.tree.pack(pady=10, padx=24, fill="both", expand=True)

    def check_suggestions(self, _event):
        typed = self.search_entry.get().strip().lower()
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
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, value)
        self.suggestions_frame.place_forget()

    def start_search(self):
        query = self.search_entry.get().strip()
        if not query:
            self.set_status("Please enter a business type or search query.", "#f87171")
            return

        try:
            total_results_str = self.results_entry.get().strip()
            total_results = int(total_results_str) if total_results_str else None
            
            workers_str = self.threads_entry.get().strip()
            workers = int(workers_str) if workers_str else 1
            workers = max(1, workers)
        except ValueError:
            self.set_status("Results and browser workers must be valid numbers.", "#f87171")
            return

        locations = self.parse_locations(self.loc_entry.get())
        queries = [f"{query} in {location}" for location in locations] if locations else [query]
        workers = min(workers, len(queries))
        
        is_headless = bool(self.headless_switch.get())

        # Build resume hint
        resume_hints = []
        for q in queries:
            seen = len(get_seen_urls(q))
            if seen > 0:
                resume_hints.append(f"'{q}': {seen} skipped")
        resume_msg = f" (Resuming — {', '.join(resume_hints)})" if resume_hints else ""

        self.search_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")
        
        def on_auto_pause(msg):
            self.after(0, lambda: self._handle_auto_pause(msg))

        self.scraper_control = ScraperControl(on_auto_pause=on_auto_pause)
        self._is_paused = False
        
        self.progress_bar.set(0)
        self.clear_table()
        self.set_status(f"Starting browser {'(Headless)' if is_headless else ''}{resume_msg} and collecting listings...", "#cbd5e1")

        thread = threading.Thread(
            target=self.run_scraping,
            args=(queries, total_results, workers, is_headless),
            daemon=True,
        )
        thread.start()

    def run_scraping(self, queries, total_results, workers, is_headless):
        started_at = time.time()
        saver = IncrementalLeadSaver()

        def on_lead_extracted(lead):
            saved = saver.save_lead(lead)
            if saved:
                self.after(0, lambda: self.add_single_lead_to_table(lead))
            self.after(0, lambda: self.set_status(
                (
                    f"Processing... Saved: {saver.saved_count} | "
                    f"Duplicates: {saver.duplicate_count} | "
                    f"Scanned: {saver.scanned_count}"
                ),
                "#cbd5e1",
            ))

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_query = {
                    executor.submit(
                        run_single_search, 
                        search_query, 
                        total_results, 
                        on_lead_extracted,
                        self.scraper_control,
                        is_headless
                    ): search_query
                    for search_query in queries
                }

                for completed, future in enumerate(as_completed(future_to_query), start=1):
                    search_query = future_to_query[future]
                    try:
                        future.result()
                    except Exception as exc:
                        logging.exception("Search failed for %s", search_query)
                        self.set_status(f"Search failed for {search_query}: {exc}", "#f87171")

                    self.update_progress(completed / len(queries))

            duration = round(time.time() - started_at, 1)

            if self.scraper_control and self.scraper_control.is_stopped():
                self.set_status(f"Search stopped manually. Saved: {saver.saved_count}", "#fbbf24")
            elif saver.saved_count:
                self.set_status(
                    (
                        f"Done in {duration}s. Saved {saver.saved_count} contacts "
                        f"to {saver.final_path.name}. Study log: "
                        f"{saver.full_log_path.as_posix()}."
                    ),
                    "#34d399",
                )
            elif saver.actionable_count:
                self.set_status(
                    (
                        "Done. Contacts were found, but every phone/email already exists. "
                        f"Duplicates skipped: {saver.duplicate_count}."
                    ),
                    "#fbbf24",
                )
            else:
                self.set_status(
                    "Done. No businesses without a website and phone/email were found.",
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

    def _handle_auto_pause(self, msg):
        self._is_paused = True
        self.pause_button.configure(text="Resume")
        self.set_status(msg, "#fbbf24")
        
        def play_sound():
            try:
                import os
                if os.path.exists("alert.mp3"):
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load("alert.mp3")
                    pygame.mixer.music.play()
                else:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception as e:
                import logging
                logging.warning(f"Could not play sound: {e}")
                
        threading.Thread(target=play_sound, daemon=True).start()

    def stop_search(self):
        if self.scraper_control:
            self.scraper_control.stop()
            self.set_status("Stopping search (waiting for current tasks to exit)...", "#ef4444")
            self.pause_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")

    def clear_session_cache(self):
        query = self.search_entry.get().strip()
        locations = self.parse_locations(self.loc_entry.get())
        queries = [f"{query} in {loc}" for loc in locations] if locations else ([query] if query else [])

        if queries:
            for q in queries:
                clear_query(q)
            self.set_status(
                f"Cache cleared for {len(queries)} query(s). Next run will start fresh.",
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
        # If we have more than 100 items, maybe remove the last one
        if len(self.tree.get_children()) >= 100:
            last_item = self.tree.get_children()[-1]
            self.tree.delete(last_item)

        self.tree.insert(
            "",
            index,
            values=(
                lead.lead_id,
                lead.phone_number,
                lead.profession,
                lead.store_title,
                lead.email,
                lead.map_link,
            ),
        )
