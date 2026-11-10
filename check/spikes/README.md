# Spikes

Throwaway scripts that prove one PayPal flow works in sandbox before we build it for real. Each one runs on its own with the keys in `.env`.

| Script | Proves |
| --- | --- |
| `spike1_authorize.py` | Authorize an order, then capture or void it |
| `spike2_vault.py` | Save the buyer's PayPal once, then the agent pays later with no buyer popup |
| `spike3_disputes.py` | List and read disputes, file evidence (notes + PDF) on one |

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

## Spike 3 findings

Run status: `list` and `show` work against a real sandbox INR dispute on a spike 1 capture. The first `evidence` run sent `OTHER` and PayPal rejected it (`400 INVALID_REQUEST`, `EVIDENCE_TYPE_IS_NOT_ALLOWED`) because the dispute asked for `PROOF_OF_FULFILLMENT`. The script now sends the requested type by default. Re-run `evidence` and update "Does evidence work in sandbox" with the output.

### Sandbox setup (one time)

1. developer.paypal.com > **Apps & Credentials** (Sandbox toggle on) > click your app.
2. **Features** > **Add-on services** > make sure **Customer disputes** is checked. It's on by default, and `list` already works, so this is probably fine.

### Create a dispute as the sandbox buyer

Use one of the $42.00 payments you **captured** in spike 1 (a voided one has nothing to dispute).

1. In a private/incognito window, go to https://www.sandbox.paypal.com and log in as the **sandbox personal (buyer)** account from `SANDBOX_BUYER_EMAIL`.
2. Open **Activity** (or **Summary** > **Recent activity**) and click the **$42.00** payment to **Fernwood Supply Co**.
3. Click **Report a problem**. If you don't see it, go to https://www.sandbox.paypal.com/resolutioncenter, click **Report a Problem**, and pick that $42.00 payment.
4. Choose **I didn't receive an item I bought** (Item Not Received, "INR"). PayPal's sandbox evidence tests are written for INR cases.
5. Fill in whatever it asks (any text is fine) and submit. The full $42.00 is fine as the amount.
6. Back in PowerShell:

   ```powershell
   python spikes/spike3_disputes.py list
   python spikes/spike3_disputes.py show PP-R-XXXX-XXXXXXXX
   python spikes/spike3_disputes.py evidence PP-R-XXXX-XXXXXXXX
   ```

   It can take a minute or two for a new dispute to show up in `list`. If `evidence` says there's no `provide_evidence` link, run `show` and check the status (see the table below).

Fallback if the UI fights you: there's a sandbox-only `POST /v1/customer/disputes` that creates a dispute as the buyer, using a `PayPal-Auth-Assertion` header plus the buyer-side transaction ID (https://developer.paypal.com/disputes/test-go-live). PayPal lists dispute creation as limited release, so try the UI first.

### Does evidence work in sandbox

From the docs and schema: **yes, but only with the evidence type PayPal requested.** PayPal's sandbox test plan files `PROOF_OF_FULFILLMENT`, `PROOF_OF_REFUND` or `OTHER` on an INR case, each one only when the dispute's `evidences[]` lists that type as `REQUESTED_FROM_SELLER`. Our INR dispute only requested `PROOF_OF_FULFILLMENT`, so `OTHER` bounced. Confirm the `PROOF_OF_FULFILLMENT` run goes through.

**PayPal only accepts the requested evidence type.** Read `evidences[]` from show dispute details, take the `evidence_type` of entries where `source` is `REQUESTED_FROM_SELLER`, and send that. Anything else gets `EVIDENCE_TYPE_IS_NOT_ALLOWED`. The script does this by default, `--type` overrides it for experiments:

```powershell
python spikes/spike3_disputes.py evidence PP-R-XXXX-XXXXXXXX               # sends what PayPal asked for
python spikes/spike3_disputes.py evidence PP-R-XXXX-XXXXXXXX --type OTHER  # force a type
```

For `PROOF_OF_FULFILLMENT` the script sends `evidence_info.tracking_info` with `carrier_name: OTHER`, `carrier_name_other: Fernwood Freight` and a made-up `FWF...` tracking number, plus the notes and the PDF. `carrier_name` and `tracking_number` are required. `carrier_name` is an enum of real carriers, so `OTHER` + `carrier_name_other` (required with `OTHER`) keeps it fictional.

How it works:
- `POST /v1/customer/disputes/{id}/provide-evidence`, `multipart/form-data`.
- Part `input`: JSON, `{"evidences": [{"evidence_type": "OTHER", "notes": "...", "documents": [{"name": "file.pdf"}]}]}`.
- One part per file. The schema calls it `evidence-file`, the docs sample uses `file1`. The script uses `evidence-file`. If PayPal rejects it, try `file1`.
- Response is just a `self` link. Read the dispute back to see the evidence land.

### Which states allow evidence

Only when **status is `WAITING_FOR_SELLER_RESPONSE`**, and only when **show dispute details includes a `provide_evidence` link**. No link means no evidence, whatever the status says.

| Stage | Status | Can we file evidence? |
| --- | --- | --- |
| `INQUIRY` | `OPEN` | No (just created) |
| `INQUIRY` | `WAITING_FOR_SELLER_RESPONSE` | **Yes** (also message, offer, accept, escalate) |
| `CHARGEBACK` / `PRE_ARBITRATION` / `ARBITRATION` | `WAITING_FOR_SELLER_RESPONSE` | **Yes** (also accept, offer, appeal) |
| `CHARGEBACK` / `PRE_ARBITRATION` / `ARBITRATION` | `UNDER_REVIEW` | No, use `provide-supporting-info` instead |
| any | `WAITING_FOR_BUYER_RESPONSE` | No |
| any | `RESOLVED` | No |

Source: the stage/status table in https://developer.paypal.com/platforms/disputes/handle-disputes/use-disputes-api

### Gotchas

- **No `.txt` files.** Evidence files must be `.jpg`, `.jpeg`, `.gif`, `.png` or `.pdf`, under 10 MB each and 50 MB per call. The script builds a tiny one-page PDF by hand so we don't need a PDF library. Leash's real evidence will be a PDF too.
- **Don't set Content-Type yourself** on the multipart call. Let `requests` do it, it has to include the boundary.
- **Send what PayPal asked for, nothing else.** Learned the hard way: `OTHER` on an INR case that requested `PROOF_OF_FULFILLMENT` got `400 EVIDENCE_TYPE_IS_NOT_ALLOWED`. The buyer's own entry shows up in `evidences[]` too (type `CREATE`, source `SUBMITTED_BY_BUYER`), so filter on `source`.
- **Our mandate proof fits `UNAUTHORISED` best.** That's the "I didn't authorize this" case, and it accepts `OTHER` (notes + documents), which is exactly the mandate PDF. INR does **not** accept `OTHER`, so on an INR case the mandate PDF has to ride along as the document on a `PROOF_OF_FULFILLMENT` submission.
- **`PROOF_OF_REFUND` needs a real refund id** (`evidence_info.refund_ids`). The script refuses it since the spike doesn't issue refunds.

### What each dispute reason asks for

From https://developer.paypal.com/platforms/disputes/reference/dispute-reasons:

| Dispute reason | Evidence types accepted | What to send |
| --- | --- | --- |
| `MERCHANDISE_OR_SERVICE_NOT_RECEIVED` (INR) | `PROOF_OF_FULFILLMENT`, `PROOF_OF_REFUND` | Fulfillment: carrier + tracking number, or notes/documents (e.g. proof of delivery signature). Refund: refund id |
| `MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED` (SNAD) | `OTHER`, `PROOF_OF_REFUND` | Other: notes/documents (product description, item URL, return policy, contract, affidavit). Refund: refund id |
| `UNAUTHORISED` | `PROOF_OF_FULFILLMENT`, `PROOF_OF_REFUND`, `OTHER` | Fulfillment: carrier + tracking. Refund: refund id. Other: notes/documents (e.g. proof of delivery signature, receipt copy). **Leash mandate proof goes here** |
| `CREDIT_NOT_PROCESSED` | `PROOF_OF_REFUND`, `OTHER` | Refund id, or notes/documents (e.g. credit due reason) |
| `DUPLICATE_TRANSACTION` | `PROOF_OF_REFUND`, `OTHER` | Refund id, or notes/documents |
| `INCORRECT_AMOUNT` | `PROOF_OF_REFUND`, `OTHER` | Refund id for the difference, or notes/documents (e.g. price difference reason) |
| `PAYMENT_BY_OTHER_MEANS` | `PROOF_OF_REFUND`, `OTHER` | Refund id, or notes/documents |
| `CANCELED_RECURRING_BILLING` | `PROOF_OF_REFUND`, `OTHER` | Refund id, or notes/documents (e.g. subscription agreement) |
| `OTHER` | `PROOF_OF_REFUND`, `OTHER` | Refund id, or notes/documents |

Even within a reason, PayPal decides per dispute which of these it requests. Always go by `REQUESTED_FROM_SELLER` on the actual dispute.
- **Watch the deadline.** `seller_response_due_date` is when the dispute auto-closes in the buyer's favor if we don't answer. That's the field the dashboard should count down.
- **List is a summary.** It doesn't include `disputed_transactions` or `evidences`. Call show for each dispute you care about.
- **Webhooks.** In the real app, subscribe to dispute events instead of polling `list`.

### Fields we'll store in the DB

**Dispute** (from show dispute details):

| Column | Response field |
| --- | --- |
| `paypal_dispute_id` | `dispute_id` |
| `reason` | `reason` (e.g. `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, `UNAUTHORIZED`) |
| `status` | `status` |
| `dispute_state` | `dispute_state` |
| `lifecycle_stage` | `dispute_life_cycle_stage` |
| `amount_value`, `amount_currency` | `dispute_amount.value` / `.currency_code` |
| `paypal_capture_id` | `disputed_transactions[0].seller_transaction_id`. **Confirmed it equals our capture id** (`0BF84704GR0419844`, captured in spike 1). This is the join to our order row. The buyer side has a different id (`buyer_transaction_id`), don't mix them up |
| `seller_response_due_at` | `seller_response_due_date` |
| `created_at`, `updated_at` | `create_time`, `update_time` |
| `outcome` | `dispute_outcome.outcome_code` once resolved |

**Evidence submission** (one row per time we file):

| Column | Value |
| --- | --- |
| `paypal_dispute_id` | which dispute |
| `evidence_type` | what we sent (`OTHER`) |
| `notes` | the text we sent |
| `document_name` | the PDF file name |
| `document_sha256` | hash of the PDF we sent, so we can prove what we filed |
| `requested_types` | what PayPal asked for (`evidences[].evidence_type` where `source` is `REQUESTED_FROM_SELLER`) |
| `paypal_request_id` | the `PayPal-Request-Id` header we sent |
| `submitted_at`, `http_status`, `debug_id` | how the call went |
