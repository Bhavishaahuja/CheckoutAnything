# Leash API: orders

What the frontend can rely on. Field names here are stable. Adding a field isn't a breaking change, so ignore ones you don't recognize. Anything that renames or removes a field gets called out to Shachi first.

Backend source: `backend/app/orders.py`.

## Two states on every order

An order has two separate state fields. Show both.

| Field | Answers | Values |
|---|---|---|
| `status` | Where is the money? | `created`, `authorized`, `captured`, `voided`, `failed` |
| `review_state` | Who decided? | `needs_review`, `auto_approved`, `approved`, `rejected`, or `null` |

`review_state` is `null` until there's a hold to decide about. It's also `null` on orders captured or voided before this field existed.

The combinations you'll see:

| `status` | `review_state` | Meaning | Show |
|---|---|---|---|
| `created` | `null` | Waiting for the buyer to approve at `payer_action_url` | Waiting on buyer |
| `authorized` | `needs_review` | Money is on hold and a human has to decide | Approve and Reject buttons |
| `captured` | `auto_approved` | Clean match, captured with no human involved | Done |
| `captured` | `approved` | A human approved, money taken | Done |
| `voided` | `rejected` | A human rejected, hold released | Done |
| `failed` | `null` | PayPal wouldn't place the hold | Failed |
| `failed` | `needs_review` | PayPal declined the capture | Failed. Approve and Reject return 409 |

Only show Approve and Reject when `status` is `authorized` and `review_state` is `needs_review`. Any other combination gets a 409.

## The order object

`GET /orders` returns a list of these, newest first. `GET /orders/{id}`, `POST /orders`, `POST /orders/{id}/authorize`, `POST /orders/{id}/approve` and `POST /orders/{id}/reject` all return one. Order fields are at the top level, with `mandate`, `intent_check` and `approval` as named objects.

```json
{
  "id": 42,
  "mandate_id": 7,
  "paypal_order_id": "5O190127TN364715T",
  "authorization_id": "0AW2184448108334S",
  "capture_id": null,
  "void_result": null,
  "vault_id": "abc123",
  "items": [
    {
      "name": "Trail runner",
      "color": "red",
      "size": "women's 9",
      "quantity": 1,
      "unit_price": "110.00"
    }
  ],
  "total": "120.00",
  "shipping_amount": "10.00",
  "currency": "USD",
  "status": "authorized",
  "review_state": "needs_review",
  "authorization_expires_at": "2026-12-03T01:56:55Z",
  "created_at": "2026-11-05T15:04:05Z",
  "mandate": {
    "id": 7,
    "buyer_label": "Sam",
    "raw_request": "Black trail runners, women's size 9, up to $120, from Fernwood",
    "rules": { "item": "trail runners", "color": "black", "currency": "USD" },
    "max_price": "120.00",
    "max_price_inclusive": true,
    "merchant": "Fernwood",
    "expires_at": "2026-11-08T23:59:59Z",
    "created_at": "2026-11-05T15:00:00Z"
  },
  "intent_check": {
    "id": 91,
    "verdict": "mismatch",
    "risk_score": 90,
    "reason": "Ordered red, mandate says black",
    "mismatched_fields": ["color"],
    "rule_results": [
      {
        "rule": "price",
        "passed": true,
        "reason": "Order is $120.00 ($110.00 item + $10.00 shipping), within the $120.00 cap"
      },
      { "rule": "merchant", "passed": true, "reason": "Mandate store matches Fernwood Supply Co" },
      { "rule": "expiry", "passed": true, "reason": "Mandate is valid until 2026-11-08 23:59 UTC" },
      { "rule": "currency", "passed": true, "reason": "Both are in USD" }
    ],
    "latency_ms": 1940,
    "checked_by": "ai",
    "created_at": "2026-11-05T15:04:07Z"
  },
  "approval": null
}
```

### Fields that need care

- **Money** (`total`, `shipping_amount`, `unit_price`, `max_price`) is a string like `"120.00"`. Don't parse it to a float for anything but display.
- **Times** are ISO 8601 strings in UTC.
- **`capture_id`** is set once money is taken. **`void_result`** is PayPal's status, normally `"VOIDED"`, once a hold is released. Both can be `null`.
- **`shipping_amount`** is `null` on orders from before it was saved.
- **`max_price`** can be in another currency, so don't hardcode `$`. Read `mandate.rules.currency`. If that's `null`, treat it as USD.
- **`max_price_inclusive`**: `true` means "up to" and `false` means "under".
- **`intent_check`** is `null` before the order is checked. It's also `null` if saving the result failed, and that order will be in `needs_review` with nothing to explain why, so handle a missing reason.
- **`approval`** is `null` unless a human decided. Auto-approved orders never have one.

### `intent_check`

| Field | Type | Notes |
|---|---|---|
| `verdict` | `match`, `mismatch`, `unsure` | |
| `risk_score` | int or `null` | 0 to 100, higher means more likely the human didn't want this |
| `reason` | string | One line, written for the human. Show this one |
| `mismatched_fields` | list or `null` | What differs. Rule names (`price`, `merchant`, `expiry`, `currency`) when `checked_by` is `rules`. Otherwise `item`, `color`, `size`, `quantity`, `extra_item`, `substitution` or `instructions_in_order` |
| `rule_results` | list or `null` | Every hard rule, including the ones that passed. Empty if the rules themselves crashed |
| `latency_ms` | int or `null` | How long the whole check took |
| `checked_by` | `rules`, `ai` | Note: this used to be `claude` |

`reason` can end in `(+2 more)` when several rules failed. The full list is in `rule_results`.

### `approval`

| Field | Type | Notes |
|---|---|---|
| `action` | `approve`, `reject` | |
| `decision_ms` | int | What the client sent: page open to tap |
| `decided_at` | time | When the tap reached the server |
| `opened_at` | time | Worked out as `decided_at` minus `decision_ms`, since the server never sees the page open |
| `decided_by` | string or `null` | Always `null` for now, there are no logins |

## Endpoints

### `GET /orders?limit=50`

The order object, newest first. `limit` is capped at 200.

### `GET /orders/{id}`

The order object, plus the full history. `intent_check` and `approval` are the newest entries in these lists, so prefer those two.

```json
{ "decisions": [ ], "approvals": [ ] }
```

### `POST /orders/{id}/approve` and `POST /orders/{id}/reject`

Approve captures the money and reject releases the hold. Both take the same body, and `decision_ms` is required: milliseconds from the page opening to the tap, measured on the client. It must be a whole number from 0 to 2147483647.

```json
{ "decision_ms": 4200 }
```

Success is a `200` with the updated order object.

Errors are all under `detail`, and `message` is safe to show the human:

| Code | When | What to do |
|---|---|---|
| `404` | No such order | |
| `409` | Not waiting for review, or a payment is already in progress | Refresh the order and show its current state |
| `422` | `decision_ms` is missing or invalid | A frontend bug |
| `502` | PayPal failed. The order is unchanged | Offer to try again, it's safe |

The `409` and most `502` bodies carry the current states:

```json
{
  "detail": {
    "message": "PayPal capture failed, the order is still waiting for review",
    "status": "authorized",
    "review_state": "needs_review"
  }
}
```

Two `502` cases are different:

- **PayPal declined the capture:** `status` comes back as `failed`, and trying again gets a `409`.
- **PayPal succeeded but saving failed:** only `message` is present. Trying again is safe, but it returns a `409` for up to 2 minutes first.

Double taps are safe. Only one goes through, and the others get a `409`. Still disable the button while a request is in flight.

### Removed: `POST /orders/{id}/capture` and `POST /orders/{id}/void`

These now return `404`. Use approve and reject. `captureOrder` and `voidOrder` in `frontend/src/api.ts` should be replaced.

### For the agent: `POST /orders`, `POST /orders/{id}/authorize`

These return the order object after the check and any auto-capture, so they can take several seconds. `POST /orders` also has `payer_action_url`, set only when there's no `vault_id` and the buyer has to approve at PayPal.
