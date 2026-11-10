# Judge mode. A connect run in replay mode doesn't fetch the page or call Claude, it replays a
# fixture recorded from a real run: the page text, the spec Claude wrote, and every repair it
# made. The verify loop and all PayPal sandbox calls still run for real.
#
# Fixtures live in backend/fixtures/<slug>.json. Record them with RECORD_FIXTURES=1 and a live
# connect of each demo store (or backend/scripts/record_fixtures.py). They are never written
# by hand, and a store with no fixture fails out loud in replay mode.

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from backend.app.extractor import ExtractionError
from backend.app.fetcher import FetchedPage
from backend.app.spec import parse_item, parse_spec

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def slug_for_url(url):
    # the last folder in the path, "https://x.onrender.com/hollowbrook-bakery/" ->
    # "hollowbrook-bakery". the host is left out so a fixture recorded locally works hosted
    parts = urlsplit(url)
    segments = []
    for segment in parts.path.split("/"):
        if segment and segment.lower() not in ("index.html", "index.htm"):
            segments.append(segment)
    if segments:
        name = segments[-1]
    else:
        name = parts.hostname or "store"
    cleaned = ""
    for character in name.lower():
        if character.isalnum() or character == "-":
            cleaned += character
        else:
            cleaned += "-"
    return cleaned.strip("-") or "store"


def fixture_path(url, fixture_dir=None):
    return (fixture_dir or FIXTURE_DIR) / (slug_for_url(url) + ".json")


def load_fixture(url, fixture_dir=None):
    path = fixture_path(url, fixture_dir)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ReplayAI:
    # stands in for ClaudeExtractor, answering from a fixture
    def __init__(self, fixture, url):
        self.fixture = fixture
        self.url = url
        self.repairs_left = list(fixture.get("repairs") or [])

    def page(self):
        page = self.fixture["page"]
        return FetchedPage(
            url=self.url, final_url=self.url, title=page.get("title", ""), text=page["text"]
        )

    def extract_spec(self, page):
        data = dict(self.fixture["spec"])
        data["source_url"] = self.url
        return parse_spec(data)

    def repair_item(self, item, reason, page_text):
        # the next recorded repair for this item, in the order they happened
        for index, repair in enumerate(self.repairs_left):
            if repair["item_id"] == item.id:
                del self.repairs_left[index]
                return parse_item(repair["item"]), repair.get("note", "")
        raise ExtractionError(
            "The fixture has no recorded repair for " + item.id + " (" + reason + ")"
        )


class RecordingAI:
    # wraps the real extractor and remembers everything it answered, so save() can write it
    def __init__(self, real_ai, url, fixture_dir=None):
        self.real_ai = real_ai
        self.url = url
        self.fixture_dir = fixture_dir
        self.page_seen = None
        self.spec = None
        self.repairs = []

    def extract_spec(self, page):
        self.page_seen = page
        self.spec = self.real_ai.extract_spec(page)
        return self.spec

    def repair_item(self, item, reason, page_text):
        repaired, note = self.real_ai.repair_item(item, reason, page_text)
        self.repairs.append({
            "item_id": item.id,
            "reason": reason,
            "item": repaired.model_dump(),
            "note": note,
        })
        return repaired, note

    def save(self):
        if self.page_seen is None or self.spec is None:
            return None
        fixture = {
            "label": "FIXTURE",
            "slug": slug_for_url(self.url),
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recorded_from": self.url,
            "page": {"title": self.page_seen.title, "text": self.page_seen.text},
            "spec": self.spec.model_dump(),
            "repairs": self.repairs,
        }
        path = fixture_path(self.url, self.fixture_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fixture, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path
