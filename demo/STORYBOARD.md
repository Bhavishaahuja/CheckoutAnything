# Checkout Anything: demo video script and storyboard

Target length 2:43 (hard limit under 3:00), 1920×1080, 30 fps. No music. Captions burned into one MP4; stems delivered separately.

**Capture rules.** Real screens from the hosted sandbox apps, captured at 2× (1440×900 viewport) so zooms stay sharp. Every beat zooms on its subject: about 2.5× on cells and buttons, 3× on single lines of text. Waiting time (connect run, agent thinking, PayPal calls, polling) is cut out. The merchant password is typed by the capture code from `DEMO_MERCHANT_PASSWORD`; the password field is never on screen (we cut from the empty login to the confirm page).

**Drawings.** Each one is full screen with a slow push (1.00 → 1.06 over the shot) and a one-line caption, then a match cut into the next screen.

**Timing.** "VO" is the line you record. Times are cumulative. Each line fits at about 2.5 words a second with room to breathe.

| # | Time | Shot | On screen, zoom on | VO (your line) | Caption |
|---|---|---|---|---|---|
| 1a | 0:00–0:04 | **Drawing_1** | Theo panicking | "Theo's mom turns sixty on Saturday. He wants her a wool blanket." | Theo needs a gift by Saturday |
| 1b | 0:04–0:08 | **Drawing_2** | Wren buried in email | "Wren makes exactly that blanket. She sells it by email." | Wren sells by email |
| 1c | 0:08–0:15 | Store page | Fernwood & Thistle Goods page, push to the blanket's three prices, then 3× on "To order, email us what you'd like and we'll send an invoice." | "No cart, no checkout. To an AI shopping agent, this store doesn't exist." | "To order, email us" |
| 2a | 0:15–0:18 | **Drawing_3** | | "Checkout Anything fixes that from just the URL." | One URL in, a store agents can buy from |
| 2b | 0:18–0:32 | Connect | Click **Reset demo** → **Yes, reset**. Fernwood connecting live: the overlay steps ("Step 2 of 3: Claude is writing the store spec"), then a zoom on the Live steps log and the **PayPal order** column filling in, one real sandbox order per item. Ends on **Agent-ready**, 6 verified. | "Claude reads the page and writes a spec. Fixed code then checks every price against the page and creates a real PayPal sandbox order for each item." | Every item: a real PayPal sandbox order |
| 3a | 0:32–0:35 | **Drawing_4** | | "Wren still gets the last word." | Wren checks the agent's work |
| 3b | 0:35–0:49 | Catalog | 2.6× on the amber **$85.00** cell of Wool Camp Blanket + the **Needs a look** tooltip ("Claude's note: … Small ($85) is treated as the base option…"). Click the check: "0 fields need a look". Tick the row, **Publish 1 to PayPal** → "1 published to PayPal". Cut to Agent sidebar, 3× on **Fernwood & Thistle Goods: 6 live**. | "Anything the agent doubted is amber, with the reason. She confirms the base price and publishes. All six items are now live." | Confirm, then publish |
| 4a | 0:49–0:59 | Agent | Type "Buy me the Enamel Camp Mug from Fernwood & Thistle Goods." Cut the wait. 3× on **Payment captured $20.00** and **PayPal order status: COMPLETED**. | "Now any agent can buy. Fourteen dollars plus shipping, captured through PayPal." | $14 mug + $6 shipping, captured |
| 4b | 0:59–1:07 | Agent | "Get me the Medium wool camp blanket from Fernwood & Thistle Goods, keep it under $100." Zoom on the reply refusing: the Medium is $120. | "Ask it to stay under a hundred, and it won't buy the hundred-and-twenty-dollar blanket." | Over the cap: it refuses |
| 5a | 1:07–1:10 | **Draw_5** | | "But what if the agent gets it wrong?" | What if the agent gets it wrong? |
| 5b | 1:10–1:35 | Sloppy agent → Orders → Review | Toggle **Sloppy agent (demo)** on (zoom on the DEMO pill). "Get me the Medium wool camp blanket from Fernwood & Thistle Goods." Cut to Orders: 2.5× on the pinned amber row, chip **Held: wrong size**. Click **Review** → **Log in to review** (field off screen) → confirm page: 3× on **You asked for** and the flagged size. Click **Accept fix** → back on the grid, green **Fixed**. | "We made this agent sloppy on purpose. It grabs the next size up. Check holds the payment, nothing is charged, and Theo sees what he actually asked for. One tap swaps in the right blanket." | Held: wrong size → Fixed |
| 6a | 1:35–1:38 | **Draw_6** | | "The last risk is the human." | Approving without reading |
| 6b | 1:38–2:03 | Place order → confirm ×3 → Orders → Check dashboard | Place order page: mandate **#104**, **Wrong store**, **Get review link**, confirm page, **Approve** in under a second. Shown in full once, then twice more in fast cuts with a 2/3, 3/3 counter. Orders: 3× on **Rubber-stamp risk: 3 approvals under 2s**. Check dashboard: zoom on **Sharp mode on: asking less, but sharper**, then the grid with **Group by agent** on and the held rate per agent. | "Approve three in under a second each, and Check notices. It flags the rubber-stamping, switches to sharp mode, asks less often, but more pointedly, and tracks each agent's held rate." | Rubber-stamp risk → sharp mode |
| 7a | 2:03–2:06 | **Draw_7** | | "Weeks later, a dispute." | A dispute arrives |
| 7b | 2:06–2:29 | Disputes | **Sync with PayPal** → zoom on the sync note. Open the dispute row. Zoom in turn on the four facts: What the buyer asked for, What was ordered, How it was checked, Who released the money. Then 2.5× on Claude's summary. Then the PDF (see open question 3). **Submit to PayPal is never clicked.** | "Wren already has the proof: what the buyer asked for, what was ordered, how it was checked, and who released the money. Claude drafts the summary for PayPal's reviewer." | The proof was recorded before the money moved |
| 8a | 2:29–2:33 | **Draw_8** | | "Theo's mom got her blanket." | Saturday, sorted |
| 8b | 2:33–2:38 | Connect | Store chips, all three with green dots. | "Any store, any agent, every order the one the human meant." | |
| 8c | 2:38–2:43 | End card | Checkout Anything. "Built with PayPal (sandbox) and Claude" | (none) | Built with PayPal (sandbox) and Claude |

Total 2:43, leaving 17 s of margin under 3:00 for your delivery pace.

## Deliverables

- `checkout-anything-demo.mp4`: the full cut with captions burned in, no audio.
- `checkout-anything-demo-clean.mp4`: the same cut with no captions and no audio, to lay your voice on.
- `checkout-anything-demo.srt`: one cue per VO line at the times above (retimed to the final cut).
- `SCRIPT-timed.md`: the VO lines with in and out times and the shot under each.

## Capture order and state

Scenes are captured in story order in one pass, because each one changes data in the sandbox: Reset demo (2b) reconnects the stores and puts the blanket back to amber, 3b publishes it, 4 and 5 create orders, 6 creates three approvals. The scene 3 test capture already published the blanket once; the Reset in 2b undoes that.
