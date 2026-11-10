import copy

import pytest

from backend.app.spec import MAX_SPEC_BYTES, SpecError, parse_spec, spec_to_json
from backend.tests.fakes import FERNWOOD_SPEC, HOLLOWBROOK_SPEC, QUILL_SPEC


def broken(change):
    data = copy.deepcopy(HOLLOWBROOK_SPEC)
    change(data)
    return data


def test_demo_specs_are_valid():
    for data in (FERNWOOD_SPEC, QUILL_SPEC, HOLLOWBROOK_SPEC):
        spec = parse_spec(copy.deepcopy(data))
        assert spec.spec_version == 1
        assert len(spec_to_json(spec).encode("utf-8")) < MAX_SPEC_BYTES


@pytest.mark.parametrize("price", ["9", "9.0", "9.000", "$9.00", "9,00", "-9.00", "", "nine"])
def test_price_has_to_be_a_two_decimal_string(price):
    def change(data):
        data["items"][0]["unit_price"] = price

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_price_cant_be_a_float():
    def change(data):
        data["items"][0]["unit_price"] = 9.0

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_zero_price_is_rejected():
    def change(data):
        data["items"][0]["unit_price"] = "0.00"

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_unknown_fields_are_rejected():
    def change(data):
        data["items"][0]["on_click"] = "alert(1)"

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_top_level_unknown_fields_are_rejected():
    def change(data):
        data["code"] = "import os"

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_duplicate_item_ids_are_rejected():
    def change(data):
        data["items"][1]["id"] = data["items"][0]["id"]

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_duplicate_variant_ids_are_rejected():
    def change(data):
        data["items"][0]["variants"].append(
            {"id": "half", "label": "Another half", "unit_price": "5.00"}
        )

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_bad_ids_are_rejected():
    def change(data):
        data["items"][0]["id"] = "Sourdough Loaf"

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_missing_source_quote_is_rejected():
    def change(data):
        del data["items"][0]["source_quote"]

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_needs_at_least_one_item():
    def change(data):
        data["items"] = []

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_shipping_none_has_to_be_zero():
    def change(data):
        data["shipping"] = {"type": "none", "amount": "6.00", "notes": ""}

    with pytest.raises(SpecError):
        parse_spec(broken(change))


def test_spec_over_32kb_is_rejected():
    def change(data):
        # each field fits its own limit, together they are too much
        template = data["items"][0]
        data["items"] = []
        for number in range(60):
            item = copy.deepcopy(template)
            item["id"] = "item-" + str(number)
            item["description"] = "d" * 300
            item["source_quote"] = "q" * 300
            data["items"].append(item)

    with pytest.raises(SpecError) as error:
        parse_spec(broken(change))
    assert "cap" in str(error.value)
