# Record the judge-mode fixtures: connect each demo store live (real page fetch, real Claude,
# real PayPal sandbox orders) and save what happened to backend/fixtures/<slug>.json.
#
#   python backend/scripts/record_fixtures.py
#
# Needs the API running with RECORD_FIXTURES=1 and the demo stores being served. Commit the
# fixture files afterwards. A store only gets a fixture if at least one of its items verified.

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.demo import fixture_path  # noqa: E402

API = "http://127.0.0.1:8000"


def main():
    api = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else API
    config = requests.get(api + "/config", timeout=10).json()
    all_ok = True

    for url in config["demo_store_urls"]:
        print("Connecting", url)
        started = requests.post(
            api + "/stores/connect", json={"url": url, "mode": "live"}, timeout=10
        )
        if started.status_code != 202:
            print("  refused:", started.text)
            all_ok = False
            continue
        store_id = started.json()["store_id"]

        # follow the same event stream the UI does
        with requests.get(api + "/stores/" + str(store_id) + "/events", stream=True,
                          timeout=300) as stream:
            for line in stream.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    print("  " + json.loads(line[len("data: "):])["message"])

        # the fixture is written right after the last event
        time.sleep(1)
        path = fixture_path(url)
        if path.exists():
            print("  saved", path)
        else:
            print("  NO FIXTURE SAVED. Is RECORD_FIXTURES=1 set on the API, and did an item "
                  "verify?")
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
