# Spikes

Throwaway scripts that prove one PayPal flow works in sandbox before we build it for real. Each one runs on its own with the keys in `.env`.

| Script | Proves |
| --- | --- |
| `spike1_authorize.py` | Authorize an order, then capture or void it |
| `spike3_disputes.py` | List and read disputes, file evidence (notes + PDF) on one |

## Spike 3 findings

Run status: `list` runs against sandbox (200, zero disputes so far, so the app has Disputes API access). `show` and `evidence` are waiting on a buyer-created dispute. Update "Does evidence work in sandbox" with real output after running.

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

From the docs and schema: **yes**. PayPal's sandbox test plan has a merchant filing evidence type `OTHER` with notes and documents on a buyer-created INR case and getting a `200 OK`. Confirm with our own run.

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
- **Look at what PayPal asked for.** `evidences[]` entries with `source: REQUESTED_FROM_SELLER` say which `evidence_type` PayPal wants. INR cases can ask for `PROOF_OF_FULFILLMENT` (tracking) or `PROOF_OF_REFUND` (refund id). Our mandate proof is `OTHER`. The script prints the requested types so we learn which ones a sandbox INR asks for.
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
| `paypal_capture_id` | `disputed_transactions[0].seller_transaction_id`. This is the join to our order row, confirm it equals the spike 1 capture id |
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
