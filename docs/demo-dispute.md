# Demo dispute: open one on a real Checkout Anything order

The dispute in the video has to be on an order Checkout Anything really placed, so the evidence
tells the true story: the buyer asked for the Medium blanket, Check held the Large, and the buyer
approved it themselves. Sandbox only. Commands are Windows cmd, run from the `check` folder.

## Can it be scripted?

Mostly. PayPal's sandbox has an API for each step
([test and go live](https://developer.paypal.com/disputes/test-go-live),
[escalate](https://developer.paypal.com/api/customer-disputes/v1/disputes-escalate),
[require-evidence](https://developer.paypal.com/api/customer-disputes/v1/disputes-require-evidence)):

| Step | Call | Notes |
|---|---|---|
| Open as the buyer | `POST /v1/customer/disputes` | Sandbox only. Needs a `PayPal-Auth-Assertion` header naming the buyer and the **buyer's** transaction id. The API reference calls it limited release, so PayPal may answer 403. Then open it by hand (step 4 below). |
| Inquiry to claim | `POST /v1/customer/disputes/{id}/escalate` | Only while the stage is `INQUIRY`. |
| Claim to "your turn" | `POST /v1/customer/disputes/{id}/require-evidence` with `SELLER_EVIDENCE` | Sandbox only. Only while the status is `UNDER_REVIEW` and the dispute has a `require-evidence` link. Moves it to `WAITING_FOR_SELLER_RESPONSE`. |

`backend\scripts\demo_dispute.py` does all three: `open`, `show`, `advance` (one step), and
`wait` (advances and polls every 30 seconds until Check can file, up to 15 minutes). It needs
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and `SANDBOX_BUYER_EMAIL` in `check\.env`. It has
been tested offline but not yet against the sandbox, so keep the by-hand route ready.

## Checklist

1. **Reset demo** in the main app. Wait until Check's reset says done.

2. **Agent page, Sloppy agent ON.** Ask: "Buy me the Medium Wool Camp Blanket from Fernwood &
   Thistle Goods." The agent orders the Large and Check holds it. If the blanket isn't live yet,
   confirm its price and publish it first.

3. **Orders tab: Review, then Approve.** Read the confirm page for a few seconds before you tap
   Approve, so the evidence shows a real decision and not a 0.5 second rubber stamp. Note the
   order's number in the `#` column (Check's id, e.g. `#41`) and its total.

4. **Open the dispute as the buyer.** Either:

   **By script** (copy the buyer's transaction id first: log into
   https://www.sandbox.paypal.com as the sandbox buyer, Activity, click the Fernwood & Thistle
   Goods payment, copy "Transaction ID"):

   ```bash
   .venv\Scripts\python.exe backend\scripts\demo_dispute.py open <buyer transaction id> <total>
   ```

   **Or by hand:** in a private window, log into https://www.sandbox.paypal.com as the sandbox
   buyer. Go to https://www.sandbox.paypal.com/resolutioncenter, **Report a problem**, pick the
   Fernwood & Thistle Goods payment, choose **the item is significantly not as described**, and
   say something like "I asked for the Medium blanket and got the Large." Submit.

5. **Get it to WAITING_FOR_SELLER_RESPONSE.** Find the dispute id: the script prints it, or in
   the main app open **Disputes** and click **Sync with PayPal** (it may take a minute or two to
   appear). Then:

   ```bash
   .venv\Scripts\python.exe backend\scripts\demo_dispute.py wait PP-R-XXX-12345678
   ```

   By hand instead: in the buyer's Resolution Center, open the case and **Escalate to claim**.
   Then wait for PayPal (see the timing below) and run `show` to check.

6. **Protect the order.** On Render, `check-api`, Environment, set `PROTECTED_ORDER_IDS` to the
   Check id from step 3 (just the number, e.g. `41`). Save, and wait for the redeploy. From now on
   Reset demo keeps this order, its mandate, check, decision and dispute, and the seed skips its
   own blanket order so there's only one blanket story in the grid.

7. **File the evidence.** In the main app, **Disputes**, **Sync with PayPal**, open the dispute.
   It drafts the summary. Read it: it must name Fernwood & Thistle Goods, the agent "Checkout
   Anything", and "Check", and say the buyer approved it after a few seconds. If anything is off,
   **Redraft summary**. When it reads right, **Submit to PayPal**. Check files once per dispute
   and refuses a second submit, so read before you send.

8. **Check the reset.** Reset demo once more and confirm the blanket order and its dispute are
   still there, and no week1-e2e / Unknown agent row is.

## What each status means

| Stage | Status | Meaning | What to do |
|---|---|---|---|
| `INQUIRY` | `OPEN` | Just opened | Wait, or `advance` (escalate) |
| `INQUIRY` | `WAITING_FOR_BUYER_RESPONSE` | PayPal is waiting on the buyer | Wait, or `advance` (escalate) |
| `INQUIRY` | `WAITING_FOR_SELLER_RESPONSE` | Your turn | **Ready to file** if it has a `provide-evidence` link |
| `CHARGEBACK` (claim) | `UNDER_REVIEW` | PayPal is looking at it | `advance` (require-evidence), or wait |
| `CHARGEBACK` | `WAITING_FOR_SELLER_RESPONSE` | Your turn | **Ready to file** |
| any | `WAITING_FOR_BUYER_RESPONSE` | Buyer's turn | Wait |
| any | `RESOLVED` | Closed | Open a new dispute on a new order |

Ready means both: the status is `WAITING_FOR_SELLER_RESPONSE` **and** the dispute has a
`provide-evidence` link. Check refuses to submit otherwise, and `demo_dispute.py show` says
which one is missing. Watch `seller_response_due_date`: miss it and the dispute closes in the
buyer's favor.

## How long it takes

PayPal doesn't publish sandbox timings. From our own runs (spike 3): a new dispute shows up in
Sync within a minute or two. An escalated claim can sit in `UNDER_REVIEW` until something moves
it, which is what `require-evidence` is for. Without the script, give it 10 to 30 minutes, and
budget the evening for it rather than the hour before recording.

## If PayPal asks for evidence Check won't send

Check files the type PayPal asked for, and treats "nothing asked for" as `OTHER`. It never sends
`PROOF_OF_FULFILLMENT` (needs a carrier and tracking number), `PROOF_OF_REFUND` (needs a refund
id) or `PROOF_OF_RETURN`, because Checkout Anything has none of those and inventing them would be
fake evidence. If the dispute only asks for those, Submit gives a 409 saying so.

- "Not as described" disputes accept `OTHER`, which is why step 4 picks that reason and not
  "item not received" (that one only takes fulfillment or refund proof).
- If PayPal still asks only for proof types: don't fake them. Open a fresh "not as described"
  dispute on a new order, and use the script so the claim gets to `WAITING_FOR_SELLER_RESPONSE`
  through `require-evidence`. For the video, the draft summary and PDF can still be shown from
  the Disputes tab without submitting.
