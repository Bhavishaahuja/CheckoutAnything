# Leash API: orders

What the frontend can rely on. Field names here are stable. Adding a field isn't a breaking change, so ignore ones you don't recognize. Anything that renames or removes a field gets called out to Shachi first.

Backend source: `backend/app/orders.py` and `backend/app/review.py`.

## Authentication

There are three kinds of caller. Sending the wrong key, or none, returns `401` with `{"detail": "Missing or wrong API key"}`.

| Caller | Sends | Can reach |
|---|---|---|
| Shopping agent | `X-API-Key: <AGENT_API_KEY>` | `POST /mandates`, `POST /orders`, `POST /orders/{id}/authorize` |
| Merchant dashboard | `X-API-Key: <MERCHANT_API_KEY>` | `GET /orders`, `GET /orders/{id}`, `GET /mandates/{id}`, `POST /orders/{id}/review-link` |
| Human on the confirm page | The token in the URL, no key | `GET /review/{token}`, `POST /review/{token}/approve`, `POST /review/{token}/reject` |

A key only works on its own row. The merchant key can't place orders, and the agent key can't read them.

`GET /health` needs nothing.

The confirm page must not send the merchant key. The human's phone only has the link.

## How a human reviews an order

1. An order lands in `needs_review`.
2. The dashboard calls `POST /orders/{id}/review-link` and gets a token. This is the only time the token is ever returned, so hold on to it long enough to send it.
3. The human opens a link to the confirm page, which calls `GET /review/{token}`.
4. They tap, and the page calls `POST /review/{token}/approve` or `/reject`.

The confirm page needs to take the token from its URL. The current `/confirm/:orderId` route should become `/confirm/:token`.

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
| `authorized` | `needs_review` | Money is on hold and a human has to decide | A way to get a review link |
| `captured` | `auto_approved` | Clean match, captured with no human involved | Done |
| `captured` | `approved` | A human approved, money taken | Done |
| `voided` | `rejected` | A human rejected, hold released | Done |
| `failed` | `null` | PayPal wouldn't place the hold | Failed |
| `failed` | `needs_review` | PayPal declined the capture | Failed |

Review links only work when `status` is `authorized` and `review_state` is `needs_review`.

## The order object

`GET /orders` returns a list of these, newest first, and `GET /orders/{id}` returns one. So do the agent's `POST /orders` and `POST /orders/{id}/authorize`. Order fields are at the top level, with `mandate`, `intent_check` and `approval` as named objects.

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
- **`approval`** is `null` until a human opens their link. It then exists with `action: null` until they decide. Auto-approved orders never have one.

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
| `action` | `approve`, `reject` or `null` | `null` means opened but not decided yet |
| `opened_at` | time | Stamped by the server the first time the link was opened. Refreshing doesn't move it |
| `decided_at` | time or `null` | When the tap reached the server |
| `decision_ms` | int or `null` | `decided_at` minus `opened_at`, on the server's clock. This is the attention number. `0` means the link was never opened |
| `client_decision_ms` | int or `null` | What the client said it measured. Not trusted, don't show it as the real number |
| `decided_by` | string or `null` | Always `null` for now, there are no logins |

## Merchant endpoints

### `GET /orders?limit=50`

The order object, newest first. `limit` is capped at 200.

### `GET /orders/{id}`

The order object, plus the full history. `intent_check` and `approval` are the newest entries in these lists, so prefer those two.

```json
{ "decisions": [ ], "approvals": [ ] }
```

### `POST /orders/{id}/review-link`

Creates a review link and returns it. No body. Success is a `201`:

```json
{
  "review_token": "kL0x...43 characters...",
  "expires_at": "2026-12-03T01:56:55Z"
}
```

This response is the only place the token ever appears. It isn't stored, so it can't be read back from `GET /orders`.

Calling this again makes a new token and kills the old one. That's how to recover a lost link, and also how to recover after a `502` that says to ask for a new link. Don't call it on every page load, or a link already sent to someone stops working.

`409` if the order isn't waiting for review, a payment is in progress, or the PayPal hold has expired. `404` if there's no such order.

### `GET /mandates/{id}`

The mandate, including `rules` and `max_price`.

## Review endpoints

These take the token in the path and no API key. Any error's `detail` has a `message` that's safe to show the human.

### `GET /review/{token}`

What the confirm page shows. The first call starts the attention clock, so only call it once the page is really in front of the human, not to pre-fetch or to build a link preview.

```json
{
  "id": 42,
  "items": [
    { "name": "Trail runner", "color": "red", "size": "women's 9", "quantity": 1, "unit_price": "110.00" }
  ],
  "total": "120.00",
  "shipping_amount": "10.00",
  "currency": "USD",
  "status": "authorized",
  "review_state": "needs_review",
  "authorization_expires_at": "2026-12-03T01:56:55Z",
  "mandate": {
    "buyer_label": "Sam",
    "raw_request": "Black trail runners, women's size 9, up to $120, from Fernwood"
  },
  "intent_check": {
    "verdict": "mismatch",
    "risk_score": 90,
    "reason": "Ordered red, mandate says black",
    "mismatched_fields": ["color"]
  }
}
```

`intent_check` can be `null`, so handle a missing reason. `authorization_expires_at` is also when the link stops working.

| Code | When |
|---|---|
| `200` | The link is good |
| `404` | No such link, or a newer one replaced it |
| `410` | The link expired, was already used, or the order isn't waiting for review anymore |

### `POST /review/{token}/approve` and `POST /review/{token}/reject`

Approve captures the money and reject releases the hold. The body is optional. If you send `decision_ms` it's saved as `client_decision_ms`, and has to be a whole number from 0 to 2147483647.

```json
{ "decision_ms": 4200 }
```

Success is a `200` with the same shape as `GET /review/{token}`, showing the new `status` and `review_state`.

| Code | When | What to do |
|---|---|---|
| `404` | No such link, or a newer one replaced it | Say the link isn't valid |
| `409` | Already used, not waiting for review, or a payment is in progress | Show the current state from `detail` |
| `410` | The link expired | Say it expired |
| `422` | `decision_ms` is invalid | A frontend bug |
| `502` | PayPal failed. The order is unchanged | Offer to try again with the same link, it's safe |

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
- **PayPal succeeded but saving failed:** only `message` is present. The link is used up, so the merchant has to create a new one after a couple of minutes. Going again with it is safe and won't charge twice.

Double taps are safe. Only one goes through, and the others get a `409`. Still disable the button while a request is in flight.

## Removed routes

These now return `404`. `captureOrder` and `voidOrder` in `frontend/src/api.ts` should be replaced with calls to the review endpoints.

- `POST /orders/{id}/capture`
- `POST /orders/{id}/void`
- `POST /orders/{id}/approve`
- `POST /orders/{id}/reject`

## Agent endpoints

### `POST /orders` and `POST /orders/{id}/authorize`

These return the order object after the check and any auto-capture, so they can take several seconds. `POST /orders` also has `payer_action_url`, set only when there's no `vault_id` and the buyer has to approve at PayPal.

A network failure talking to PayPal is a `502` with a `message`, and the `paypal_*` fields in `detail` are `null`. After a `502`, `POST /orders/{id}/authorize` can be retried, and `POST /orders` leaves that order as `failed`.
