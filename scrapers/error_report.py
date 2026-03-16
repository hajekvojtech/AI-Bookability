"""
Structured error reporting for AI-assisted diagnosis.

When a scraper step fails, this module captures enough context
(DOM state, intercepted APIs, screenshot) for an AI agent to
diagnose and fix the issue without running the scraper again.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output/errors")


@dataclass
class ScrapeErrorReport:
    connector: str
    merchant_url: str
    step_failed: str
    error_type: str
    error_message: str
    selector_attempted: str = ""
    page_url_at_failure: str = ""
    screenshot_path: str = ""
    intercepted_apis: list = field(default_factory=list)
    dom_snapshot: list = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def save(self) -> str:
        """Save the error report as JSON. Returns the file path."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.connector}_{self.step_failed}_{ts}.json"
        path = OUTPUT_DIR / filename
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        print(f"[ErrorReport] Saved to {path}")
        return str(path)

    def to_ai_prompt(self) -> str:
        """Generate a prompt for an AI agent to diagnose and fix the issue."""
        dom_section = ""
        if self.dom_snapshot:
            dom_lines = json.dumps(self.dom_snapshot, indent=2)
            dom_section = f"""
DOM snapshot (interactive elements near the expected location):
{dom_lines}
"""

        api_section = ""
        if self.intercepted_apis:
            api_section = f"""
API calls intercepted before failure:
{json.dumps(self.intercepted_apis, indent=2)}
"""

        return f"""The {self.connector} connector failed at step '{self.step_failed}'.

Error: {self.error_type}: {self.error_message}
Selector that failed: {self.selector_attempted}
Page URL: {self.page_url_at_failure}
{dom_section}{api_section}
To fix this issue:
1. Read scrapers/{self.connector}/CONNECTOR_SPEC.md for context on how this connector works
2. Read scrapers/{self.connector}/selectors.py for current selector values
3. Compare the failed selector with the DOM snapshot above to find the correct new selector
4. Update the appropriate constant in selectors.py (or api_schema.py if it's an API field change)
5. Run the tests to verify: pytest scrapers/{self.connector}/tests/ -v
"""


async def capture_dom_snapshot(page, max_elements: int = 30) -> list[dict]:
    """Capture interactive elements from the current page for AI diagnosis."""
    try:
        return await page.evaluate(f"""() => {{
            const candidates = document.querySelectorAll(
                'button, a, input, select, [role="button"], [role="link"], '
                + '[class*="select"], [class*="dropdown"], [class*="service"], '
                + '[class*="date"], [class*="calendar"], [class*="slider"]'
            );
            return Array.from(candidates).slice(0, {max_elements}).map(el => ({{
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                classes: el.className || null,
                text: (el.textContent || '').trim().substring(0, 120),
                type: el.type || null,
                href: el.href || null,
                visible: el.offsetParent !== null,
                rect: el.getBoundingClientRect().toJSON(),
            }}));
        }}""")
    except Exception:
        return []


async def capture_screenshot(page, connector: str, step: str) -> str:
    """Take a screenshot and return the file path."""
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = OUTPUT_DIR / f"{connector}_{step}_{ts}.png"
        await page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:
        return ""
