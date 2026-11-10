# The store_spec: a declarative description of what a store sells. This is the ONLY thing
# Claude ever writes. Everything that touches PayPal is fixed code that reads a validated spec.
#
# Anything that doesn't fit the schema is rejected, and the serialized spec is capped at 32 KB.

import json
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SPEC_BYTES = 32 * 1024

# prices are strings with exactly 2 decimals, PayPal wants strings. never floats
PRICE_PATTERN = r"^\d{1,7}\.\d{2}$"
ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
# PayPal truncates item names past 127 characters, so a longer one could never match on read back
MAX_NAME_LENGTH = 127


class SpecError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Variant(StrictModel):
    id: str = Field(pattern=ID_PATTERN, max_length=60)
    label: str = Field(min_length=1, max_length=80)
    # the full price of this variant, it replaces the item's unit_price
    unit_price: str = Field(pattern=PRICE_PATTERN)

    @field_validator("unit_price")
    @classmethod
    def price_above_zero(cls, price):
        if Decimal(price) <= 0:
            raise ValueError("a price has to be above 0.00")
        return price


class AddOn(StrictModel):
    id: str = Field(pattern=ID_PATTERN, max_length=60)
    label: str = Field(min_length=1, max_length=80)
    # added on top of the item or variant price, per unit
    price: str = Field(pattern=PRICE_PATTERN)


class Item(StrictModel):
    id: str = Field(pattern=ID_PATTERN, max_length=60)
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    description: str = Field(default="", max_length=300)
    unit_price: str = Field(pattern=PRICE_PATTERN)
    available: bool = True
    variants: list[Variant] = Field(default_factory=list, max_length=20)
    add_ons: list[AddOn] = Field(default_factory=list, max_length=20)
    # a short exact snippet from the page that contains the price. the verifier checks it
    source_quote: str = Field(min_length=1, max_length=300)

    @field_validator("unit_price")
    @classmethod
    def price_above_zero(cls, price):
        if Decimal(price) <= 0:
            raise ValueError("a price has to be above 0.00")
        return price

    @model_validator(mode="after")
    def ids_are_unique(self):
        check_unique("variant", [variant.id for variant in self.variants])
        check_unique("add-on", [add_on.id for add_on in self.add_ons])
        return self


class Merchant(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class Shipping(StrictModel):
    # flat rate only for now. "none" means nothing is added
    type: Literal["flat", "none"]
    amount: str = Field(pattern=PRICE_PATTERN)
    notes: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def none_means_zero(self):
        if self.type == "none" and Decimal(self.amount) != 0:
            raise ValueError("shipping type none has to have amount 0.00")
        return self


class StoreSpec(StrictModel):
    spec_version: Literal[1]
    source_url: str = Field(min_length=1, max_length=2048)
    merchant: Merchant
    items: list[Item] = Field(min_length=1, max_length=60)
    shipping: Shipping
    # every judgment call the extractor made. shown in the UI
    extraction_notes: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("extraction_notes")
    @classmethod
    def notes_are_short(cls, notes):
        for note in notes:
            if len(note) > 400:
                raise ValueError("an extraction note is longer than 400 characters")
        return notes

    @model_validator(mode="after")
    def ids_are_unique(self):
        check_unique("item", [item.id for item in self.items])
        return self

    def find_item(self, item_id):
        for item in self.items:
            if item.id == item_id:
                return item
        return None


def check_unique(kind, ids):
    seen = set()
    for one_id in ids:
        if one_id in seen:
            raise ValueError("two " + kind + "s share the id " + one_id)
        seen.add(one_id)


def spec_to_json(spec):
    return json.dumps(spec.model_dump(), separators=(",", ":"), ensure_ascii=False)


def parse_spec(data):
    # data is a dict (from Claude's tool call, a fixture, or the database). raises SpecError
    # with a readable reason on anything that doesn't fit
    try:
        spec = StoreSpec.model_validate(data)
    except ValueError as error:
        raise SpecError(readable_errors(error)) from error

    size = len(spec_to_json(spec).encode("utf-8"))
    if size > MAX_SPEC_BYTES:
        raise SpecError(
            "The spec is " + str(size) + " bytes, the cap is " + str(MAX_SPEC_BYTES)
        )
    return spec


def parse_item(data):
    try:
        return Item.model_validate(data)
    except ValueError as error:
        raise SpecError(readable_errors(error)) from error


def readable_errors(error):
    # pydantic's own message is long. keep "where: what" per problem
    if not hasattr(error, "errors"):
        return str(error)
    lines = []
    for problem in error.errors():
        where = ".".join(str(part) for part in problem["loc"])
        lines.append((where + ": " if where else "") + problem["msg"])
    return "; ".join(lines)


def slugify(text):
    # for item ids Claude didn't give us in the right shape
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"
