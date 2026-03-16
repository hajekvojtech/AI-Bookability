"""
JSON-based checkpoint/resume state management.
Enables safe interruption and restart of the crawl pipeline.
"""
from __future__ import annotations

import json
import os
import signal
import sys
from datetime import datetime, timezone


class StateStore:
    def __init__(self, state_path: str):
        self.path = state_path
        self.data = {"version": 1, "started_at": "", "last_updated": "", "merchants": {}}
        self._dirty = False
        self._load()
        self._setup_signal_handler()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                self.data = json.load(f)
            print(f"  Resumed state: {len(self.data['merchants'])} merchants loaded")
        else:
            self.data["started_at"] = datetime.now(timezone.utc).isoformat()

    def save(self):
        """Save state to disk."""
        self.data["last_updated"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # Write to temp file first, then rename (atomic on most filesystems)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, default=str)
        os.replace(tmp, self.path)
        self._dirty = False

    def _setup_signal_handler(self):
        """Save state on Ctrl+C."""
        original_handler = signal.getsignal(signal.SIGINT)

        def handler(signum, frame):
            print("\n\nInterrupted! Saving state...")
            self.save()
            print(f"State saved to {self.path}")
            # Call original handler or exit
            if callable(original_handler) and original_handler not in (
                signal.SIG_DFL,
                signal.SIG_IGN,
            ):
                original_handler(signum, frame)
            else:
                sys.exit(1)

        signal.signal(signal.SIGINT, handler)

    def get_result(self, url: str) -> dict | None:
        """Get the stored result for a merchant URL."""
        return self.data["merchants"].get(url)

    def is_completed(self, url: str, stage: int = 2) -> bool:
        """Check if a merchant has completed the given stage or beyond."""
        result = self.data["merchants"].get(url)
        if not result:
            return False
        return result.get("stage_completed", 0) >= stage

    def needs_stage3(self, url: str) -> bool:
        """Check if a merchant needs Stage 3 processing."""
        result = self.data["merchants"].get(url)
        if not result:
            return False
        return result.get("needs_stage3", False) and result.get("stage_completed", 0) < 3

    def set_result(self, url: str, result: dict):
        """Store a result for a merchant URL."""
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.data["merchants"][url] = result
        self._dirty = True

    def update_result(self, url: str, updates: dict):
        """Update specific fields of an existing result."""
        if url in self.data["merchants"]:
            self.data["merchants"][url].update(updates)
            self.data["merchants"][url]["timestamp"] = (
                datetime.now(timezone.utc).isoformat()
            )
            self._dirty = True

    def get_all_results(self) -> dict:
        """Get all merchant results."""
        return self.data["merchants"]

    def count_by_category(self) -> dict:
        """Count merchants by category."""
        counts = {}
        for result in self.data["merchants"].values():
            cat = result.get("category", "unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def count_by_stage(self) -> dict:
        """Count merchants by completed stage."""
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        for result in self.data["merchants"].values():
            stage = result.get("stage_completed", 0)
            counts[stage] = counts.get(stage, 0) + 1
        return counts

    def save_if_dirty(self):
        """Save only if there are unsaved changes."""
        if self._dirty:
            self.save()
