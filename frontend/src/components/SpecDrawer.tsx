// The drawer for one catalog row: what Claude wrote for it, the exact quote it leaned on,
// every check that ran, and how the item changed across repairs.

import { Check, Quote, ShoppingBag, X } from "lucide-react"
import { motion } from "motion/react"
import { useEffect, useState, type ReactNode } from "react"

import { CheckMark, CopyId, ErrorNote, Pill, RowStatusPill } from "@/components/bits"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { money } from "@/lib/format"
import type { CatalogRow, Order, SpecItem, SpecResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

function findItem(items: SpecItem[], itemId: string): SpecItem | null {
  for (const item of items) {
    if (item.id === itemId) return item
  }
  return null
}

// the quote with anything that looks like a price marked
function QuoteText({ quote }: { quote: string }) {
  const pieces = quote.split(/(\$?\d+(?:\.\d{1,2})?%?)/g)
  return (
    <>
      {pieces.map((piece, index) =>
        /\d/.test(piece) ? (
          <mark key={index} className="rounded bg-warn-soft px-1 font-medium text-warn">
            {piece}
          </mark>
        ) : (
          <span key={index}>{piece}</span>
        )
      )}
    </>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  const lines = JSON.stringify(value, null, 2).split("\n")
  return (
    <pre className="calm-scroll overflow-x-auto rounded-lg border border-border bg-muted/60 py-2 font-mono text-xs leading-relaxed">
      {lines.map((line, index) => {
        const isQuote = line.trimStart().startsWith('"source_quote"')
        const match = line.match(/^(\s*)("[^"]+")(: )(.*)$/)
        return (
          <div key={index} className={cn("px-3", isQuote && "border-l-2 border-warn bg-warn-soft")}>
            {match ? (
              <>
                {match[1]}
                <span className="text-primary">{match[2]}</span>
                {match[3]}
                {match[4]}
              </>
            ) : (
              line
            )}
          </div>
        )
      })}
    </pre>
  )
}

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

// what changed between two versions of the same item, field by field
function changedFields(before: SpecItem, after: SpecItem) {
  const changes: { field: string; from: string; to: string }[] = []
  const keys = Object.keys(after) as (keyof SpecItem)[]
  for (const key of keys) {
    const from = JSON.stringify(before[key])
    const to = JSON.stringify(after[key])
    if (from !== to) changes.push({ field: key, from, to })
  }
  return changes
}

function TestBuy({ storeId, item, currency, onBought }: { storeId: number; item: SpecItem; currency: string; onBought: () => void }) {
  const [variantId, setVariantId] = useState<string | null>(null)
  const [addOnIds, setAddOnIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [order, setOrder] = useState<Order | null>(null)
  const [error, setError] = useState<string | null>(null)

  const chip = (on: boolean) =>
    cn(
      "h-8 rounded-full border px-3 text-[13px] transition-colors",
      on ? "border-primary bg-info-soft text-primary" : "border-border hover:bg-muted"
    )

  const buy = async () => {
    setBusy(true)
    setError(null)
    setOrder(null)
    try {
      const placed = await api.createOrder(storeId, {
        item_id: item.id,
        variant_id: variantId,
        add_on_ids: addOnIds,
        quantity: 1,
      })
      setOrder(placed)
      onBought()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The order failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
      {(item.variants.length > 0 || item.add_ons.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {item.variants.length > 0 && (
            <button type="button" className={chip(variantId === null)} onClick={() => setVariantId(null)}>
              Standard, {money(item.unit_price, currency)}
            </button>
          )}
          {item.variants.map((variant) => (
            <button
              type="button"
              key={variant.id}
              className={chip(variantId === variant.id)}
              onClick={() => setVariantId(variant.id)}
            >
              {variant.label}, {money(variant.unit_price, currency)}
            </button>
          ))}
          {item.add_ons.map((addOn) => {
            const on = addOnIds.includes(addOn.id)
            return (
              <button
                type="button"
                key={addOn.id}
                aria-pressed={on}
                className={chip(on)}
                onClick={() => setAddOnIds(on ? addOnIds.filter((id) => id !== addOn.id) : [...addOnIds, addOn.id])}
              >
                {on ? "✓ " : "+ "}
                {addOn.label}, {money(addOn.price, currency)}
              </button>
            )
          })}
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Buys 1 with the saved sandbox buyer. The API works out the total, the browser never sends a price.
        </p>
        <Button size="sm" onClick={buy} disabled={busy} className="shrink-0">
          <ShoppingBag /> {busy ? "Paying" : "Test buy"}
        </Button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {order && (
        <div className="flex flex-col gap-1 rounded-md bg-ok-soft px-3 py-2 text-[13px] text-ok">
          <span className="flex items-center gap-1.5 font-medium">
            <Check className="size-4" strokeWidth={3} /> Captured {money(order.total, order.currency)} for{" "}
            {order.description}
          </span>
          <span className="flex items-center gap-2 text-xs">
            Capture <CopyId value={order.capture_id} className="text-ok" />
          </span>
        </div>
      )}
    </div>
  )
}

export function SpecDrawer({
  row,
  detail,
  storeId,
  onClose,
  onBought,
}: {
  row: CatalogRow
  detail: SpecResponse | null
  storeId: number
  onClose: () => void
  onBought: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const item = detail?.spec ? findItem(detail.spec.items, row.item_id) : null
  const currency = detail?.spec?.merchant.currency || row.currency
  const runs = detail ? detail.runs.filter((run) => run.item_id === row.item_id) : []

  // the versions where this item actually changed
  const history: { version: number; note: string | null; item: SpecItem; changes: ReturnType<typeof changedFields> }[] = []
  if (detail) {
    let previous: SpecItem | null = null
    for (const version of detail.versions) {
      const then = findItem(version.spec.items, row.item_id)
      if (!then) continue
      if (previous === null) {
        history.push({ version: version.version, note: version.note, item: then, changes: [] })
      } else {
        const changes = changedFields(previous, then)
        if (changes.length > 0) history.push({ version: version.version, note: version.note, item: then, changes })
      }
      previous = then
    }
  }

  // notes that mention this item first, the rest after
  const notes = detail?.extraction_notes || []
  const firstWord = row.name.toLowerCase().split(" ")[0]
  const aboutThis = notes.filter((note) => note.toLowerCase().includes(firstWord))
  const otherNotes = notes.filter((note) => !aboutThis.includes(note))

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.aside
        role="dialog"
        aria-label={"Spec for " + row.name}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-border bg-card shadow-2xl"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", stiffness: 380, damping: 38 }}
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold">{row.name}</h2>
              <RowStatusPill status={row.status} />
            </div>
            <p className="mt-0.5 font-mono text-xs text-muted-foreground">
              {row.item_id} · {money(row.unit_price, currency)}
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X />
          </Button>
        </header>

        <div className="calm-scroll flex flex-1 flex-col gap-6 overflow-y-auto px-5 py-5">
          {row.reason && row.status !== "verified" && <ErrorNote>{row.reason}</ErrorNote>}

          {!item && (
            <p className="text-[13px] text-muted-foreground">
              The saved spec loads when the run finishes. Until then the grid row shows the latest state.
            </p>
          )}

          {item && (
            <Section title="Source quote" aside={<span className="text-[11px] text-muted-foreground">exact text from the page</span>}>
              <blockquote className="flex gap-2.5 rounded-lg border border-border px-3 py-2.5 text-sm">
                <Quote className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span>
                  <QuoteText quote={item.source_quote} />
                </span>
              </blockquote>
            </Section>
          )}

          {runs.length > 0 && (
            <Section title="Checks">
              <ol className="flex flex-col gap-1.5">
                {runs.map((run, index) => (
                  <li key={index} className="rounded-lg border border-border px-3 py-2 text-[13px]">
                    <div className="flex items-center gap-3">
                      <span className="w-16 shrink-0 text-xs text-muted-foreground">
                        {run.attempt === 0 ? "First try" : "Repair " + run.attempt}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <CheckMark state={run.page_check_ok ? "ok" : "fail"} label="Page check" /> Page
                      </span>
                      <span className="flex items-center gap-1.5">
                        <CheckMark
                          state={run.paypal_check_ok === null ? "skipped" : run.paypal_check_ok ? "ok" : "fail"}
                          label="PayPal check"
                        />{" "}
                        PayPal
                      </span>
                      <span className="ml-auto text-xs text-muted-foreground">spec v{run.spec_version}</span>
                    </div>
                    {run.reason && <p className="mt-1.5 text-xs text-bad">{run.reason}</p>}
                    {run.paypal_order_id && (
                      <p className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
                        Sandbox order <CopyId value={run.paypal_order_id} />
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {item && (
            <Section title="Spec JSON" aside={<Pill tone="muted">written by Claude</Pill>}>
              <JsonBlock value={item} />
            </Section>
          )}

          {history.length > 1 && (
            <Section title="Version history">
              <ol className="flex flex-col gap-2">
                {history.map((entry) => (
                  <li key={entry.version} className="rounded-lg border border-border px-3 py-2 text-[13px]">
                    <div className="flex items-center gap-2">
                      <Pill tone={entry.changes.length > 0 ? "warn" : "muted"}>v{entry.version}</Pill>
                      <span className="text-muted-foreground">{entry.note || (entry.changes.length ? "Repair" : "First extraction")}</span>
                    </div>
                    {entry.changes.map((change) => (
                      <div key={change.field} className="mt-2 font-mono text-xs">
                        <span className="text-muted-foreground">{change.field}: </span>
                        <span className="rounded bg-bad-soft px-1 text-bad line-through">{change.from}</span>
                        <span className="text-muted-foreground"> → </span>
                        <span className="rounded bg-ok-soft px-1 text-ok">{change.to}</span>
                      </div>
                    ))}
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {notes.length > 0 && (
            <Section title="Extraction notes" aside={<span className="text-[11px] text-muted-foreground">Claude's judgment calls</span>}>
              <ul className="flex flex-col gap-1.5 text-[13px]">
                {aboutThis.map((note) => (
                  <li key={note} className="rounded-lg bg-info-soft px-3 py-2">
                    {note}
                  </li>
                ))}
                {otherNotes.map((note) => (
                  <li key={note} className="rounded-lg bg-muted/60 px-3 py-2 text-muted-foreground">
                    {note}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {item && row.status === "verified" && (
            <Section title="Try it">
              <TestBuy key={item.id} storeId={storeId} item={item} currency={currency} onBought={onBought} />
            </Section>
          )}
        </div>
      </motion.aside>
    </>
  )
}
