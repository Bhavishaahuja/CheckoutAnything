import copy

import pytest

from backend.app.demo import RecordingAI, ReplayAI, load_fixture, slug_for_url
from backend.app.extractor import ExtractionError
from backend.app.spec import parse_item
from backend.tests.fakes import HOLLOWBROOK_SPEC, FakeAI, demo_page


def test_slug_ignores_the_host_and_index_html():
    assert slug_for_url("https://x.onrender.com/hollowbrook-bakery/") == "hollowbrook-bakery"
    assert slug_for_url("http://localhost:5174/hollowbrook-bakery/index.html") == \
        "hollowbrook-bakery"
    assert slug_for_url("https://shop.example/") == "shop-example"
    assert slug_for_url("https://shop.example/../../etc/passwd") == "passwd"


def test_a_recorded_run_replays_the_same_answers(tmp_path):
    page = demo_page("hollowbrook-bakery")
    fixed = copy.deepcopy(HOLLOWBROOK_SPEC["items"][1])
    wrong = copy.deepcopy(HOLLOWBROOK_SPEC)
    wrong["items"][1]["unit_price"] = "8.00"
    real = FakeAI(wrong, {"seeded-rye": [(fixed, "Used $7")]})

    recording = RecordingAI(real, page.url, fixture_dir=tmp_path)
    spec = recording.extract_spec(page)
    recording.repair_item(spec.items[1], "The page says 7.00", page.text)
    path = recording.save()
    assert path.name == "hollowbrook-bakery.json"

    # another host, same store: the fixture still matches
    other_url = "https://somewhere-else.example/hollowbrook-bakery/"
    fixture = load_fixture(other_url, fixture_dir=tmp_path)
    assert fixture["label"] == "FIXTURE"

    replay = ReplayAI(fixture, other_url)
    replayed_page = replay.page()
    assert replayed_page.text == page.text
    replayed = replay.extract_spec(replayed_page)
    assert replayed.source_url == other_url
    assert replayed.items[1].unit_price == "8.00"
    repaired, note = replay.repair_item(replayed.items[1], "whatever", page.text)
    assert repaired.unit_price == "7.00"
    assert note == "Used $7"


def test_replay_fails_out_loud_when_a_repair_wasnt_recorded(tmp_path):
    fixture = {"page": {"title": "", "text": "x"}, "spec": HOLLOWBROOK_SPEC, "repairs": []}
    replay = ReplayAI(fixture, "https://x.example/hollowbrook-bakery/")
    item = parse_item(copy.deepcopy(HOLLOWBROOK_SPEC["items"][0]))
    with pytest.raises(ExtractionError):
        replay.repair_item(item, "a reason", "x")


def test_no_fixture_means_none(tmp_path):
    assert load_fixture("https://x.example/never-recorded/", fixture_dir=tmp_path) is None
