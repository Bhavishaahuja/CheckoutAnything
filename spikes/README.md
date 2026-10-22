# Spikes

Throwaway scripts that prove one PayPal flow works in sandbox before we build it for real. Each one runs on its own with the keys in `.env`.

| Script | Proves |
| --- | --- |
| `spike1_authorize.py` | Authorize an order, then capture or void it |
| `spike2_vault.py` | Save the buyer's PayPal once, then the agent pays later with no buyer popup |

## Spike 2 findings

Run status: **confirmed in sandbox on 2026-10-21.** Two full runs and two `reuse` runs, every step passed: wallet saved as `VAULTED`, order 2 authorized with zero buyer clicks, every authorization voided and read back as `VOIDED`.

### Sandbox setup (one time)

The app needs Vault turned on or order 1 won't hand back a vault id.

1. Go to developer.paypal.com and log in. Open **Apps & Credentials** with the **Sandbox** toggle on.
2. Click your app's name under **REST API apps**.
3. Under **Sandbox App Settings** > **App Feature Options**, make sure **Accept payments** is checked.
4. Expand **Advanced options** and make sure **Vault** is checked. Save.

If your dashboard shows the newer layout instead: **Features** > **Payment capabilities** > turn on **Save payment methods**, then **Features** > **Payment methods** > turn on **PayPal and Venmo**.

### How to run

```powershell
python spikes/spike2_vault.py          # full flow, approve once in the browser as the sandbox buyer
python spikes/spike2_vault.py reuse    # skip order 1, pay again with the saved vault id
```

### What worked (confirmed in sandbox)

- **Order 1** (`$18.00`, intent `AUTHORIZE`) with `payment_source.paypal.attributes.vault` set to `store_in_vault: ON_SUCCESS`, `usage_type: MERCHANT`, `customer_type: CONSUMER`, `usage_pattern: IMMEDIATE`. Create returns `PAYER_ACTION_REQUIRED` and a `payer-action` link. The buyer approves once, we call `/authorize`, and the response carries `payment_source.paypal.attributes.vault` with `id`, `status: VAULTED` and `customer.id`.
- **Order 2** (`$24.00`, intent `AUTHORIZE`) with only `payment_source.paypal.vault_id` plus a `stored_credential` (`payment_initiator: MERCHANT`, `usage: SUBSEQUENT`, `usage_pattern: IMMEDIATE`). Confirmed **single step**: create returns `status: COMPLETED` with `purchase_units[0].payments.authorizations[0]` already present (`status: CREATED`). No approval link, no `/authorize` call, the fallback in the script never fired. That's the "agent pays without a popup" moment.
- `reuse` works: a later run with only the saved vault id authorizes again with no browser.
- Void + read back work the same as spike 1 (`POST /v2/payments/authorizations/{id}/void`, then GET shows `VOIDED`).
- Authorizations expire **29 days** after they're created (`expiration_time`). That's our outer limit for the human to approve a flagged order.

Sandbox output from the second full run (vault id and customer id redacted):

```
Order 1 created: 69C607189A9551146 | status: PAYER_ACTION_REQUIRED
PayPal confirms the buyer approved.

Order 1 authorized!
  order status: COMPLETED
  authorization id: 9Y730309503246338
  authorization status: CREATED
  expires: 2026-11-20T01:56:52Z

PayPal saved the wallet!
  vault id: XXXX
  vault status: VAULTED
  customer id: XXXX

Order 2 created: 6D481471RE3820347 | status: COMPLETED

Order 2 authorized with zero buyer clicks!
  order status: COMPLETED
  authorization id: 1J1905088C2319210
  authorization status: CREATED
  expires: 2026-11-20T01:56:55Z

Voiding 2 authorization(s) so the sandbox stays clean...
  9Y730309503246338: VOIDED
  1J1905088C2319210: VOIDED
```

### Gotchas

- **Save happens after the money step.** `ON_SUCCESS` means PayPal only vaults once the authorization succeeds, so the vault id shows up in the **authorize** response, not the create response.
- **Vault can lag.** The docs say authorize can succeed with `vault.status: APPROVED` and no `id` yet. The script re-reads the order a few times. In the real app, also listen for the `VAULT.PAYMENT-TOKEN.CREATED` webhook. (Didn't happen in our runs, it came back `VAULTED` right away every time.)
- **Same buyer, same vault id.** Running order 1 again with the same sandbox buyer returned the **same** vault id and customer id as the earlier run, not new ones. That fits `permit_multiple_payment_tokens` defaulting to `false`. In the DB, treat the vault id as unique per buyer: update the existing row, don't insert a duplicate.
- **Need `Prefer: return=representation`** or the vault block isn't in the response.
- **Order 2 is already authorized when created.** Don't call `/authorize` on it. The script only does that as a fallback if no authorization comes back.
- **Odd line in PayPal's doc:** the save-with-purchase page has a box saying "Don't save PayPal as a payment method during purchase" and points to their best practices guide. The alternative is Vault v3 setup tokens (save without a purchase). Fine for sandbox; worth a look before we pitch this as the production flow.
- **Live needs extra approval.** Saving PayPal wallets needs reference transactions enabled on the live account, and customer-initiated token payments need Risk Data Acquisition (FraudNet/Magnes). Sandbox doesn't need either. Our agent orders are merchant-initiated (`stored_credential.payment_initiator: MERCHANT`).
- `spikes/.vault_token.json` holds the sandbox vault id. It's gitignored, keep it that way.

### Fields we'll store in the DB

**Saved wallet** (one row per human, from order 1's authorize response):

| Column | Response field |
| --- | --- |
| `paypal_vault_id` | `payment_source.paypal.attributes.vault.id` |
| `vault_status` | `payment_source.paypal.attributes.vault.status` (`VAULTED` or `APPROVED`) |
| `paypal_customer_id` | `payment_source.paypal.attributes.vault.customer.id` |
| `paypal_payer_id` | `payer.payer_id` |
| `payer_email` | `payment_source.paypal.email_address` |
| `first_order_id` | `id` of order 1 |

**Agent order** (one row per order, from order 2's create response):

| Column | Response field |
| --- | --- |
| `paypal_order_id` | `id` |
| `order_status` | `status` (expect `COMPLETED`) |
| `authorization_id` | `purchase_units[0].payments.authorizations[0].id` |
| `authorization_status` | `purchase_units[0].payments.authorizations[0].status` (`CREATED`, later `CAPTURED` or `VOIDED`) |
| `amount_value`, `amount_currency` | `purchase_units[0].payments.authorizations[0].amount.value` / `.currency_code` |
| `authorization_expires_at` | `purchase_units[0].payments.authorizations[0].expiration_time` |
| `seller_protection_status` | `purchase_units[0].payments.authorizations[0].seller_protection.status` |
| `paypal_request_id` | the `PayPal-Request-Id` header we sent, so retries stay idempotent |

On any error, also log `debug_id` from the error body. PayPal support asks for it.
