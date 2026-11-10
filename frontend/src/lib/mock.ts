// A pretend API for working on the UI with no backend (VITE_USE_MOCK=true). It plays scripted
// connect runs for the three fictional demo stores and keeps orders in memory. Nothing here
// talks to PayPal or Claude, and the app shows a "Mock data" badge whenever it is on.

import type { Api, EventSubscription } from "@/lib/api"
import type {
  AgentReply,
  AgentStep,
  FlagField,
  ItemPatch,
  Mode,
  Order,
  ReviewFlag,
  ReviewResponse,
  SpecItem,
  SpecResponse,
  SpecVersion,
  Store,
  StoreEvent,
  StoreSpec,
  VerificationRun,
} from "@/lib/types"

const BASE = "https://demo-stores.example"

// what goes wrong for one item before it verifies (or doesn't)
interface Stumble {
  reason: string
  page_check_ok: boolean
  paypal_check_ok: boolean | null
  fix?: Partial<SpecItem> // the repair Claude comes back with
  note?: string
}

interface Script {
  slug: string
  spec: StoreSpec
  stumbles: Record<string, Stumble[]>
  // true when the item never verifies, even after 3 repairs
  hopeless?: string[]
}

function item(
  id: string,
  name: string,
  unit_price: string,
  source_quote: string,
  extra: Partial<SpecItem> = {}
): SpecItem {
  return {
    id,
    name,
    description: "",
    unit_price,
    available: true,
    variants: [],
    add_ons: [],
    source_quote,
    ...extra,
  }
}

const SCRIPTS: Script[] = [
  {
    slug: "fernwood-thistle-goods",
    spec: {
      spec_version: 1,
      source_url: BASE + "/fernwood-thistle-goods/",
      merchant: { name: "Fernwood & Thistle Goods", currency: "USD" },
      items: [
        item("linen-apron", "Linen Apron", "38.00", "Linen Apron $38", {
          description: "Washed linen, cross-back straps",
        }),
        item("field-notebook", "Field Notebook", "12.00", "Field Notebook $12"),
        item("wool-socks", "Wool Camp Socks", "18.00", "Wool Camp Socks $18", {
          variants: [
            { id: "s", label: "Small", unit_price: "18.00" },
            { id: "m", label: "Medium", unit_price: "18.00" },
            { id: "l", label: "Large", unit_price: "20.00" },
          ],
        }),
        item("enamel-mug", "Enamel Mug", "14.00", "Enamel Mug $14"),
        item("beeswax-candle", "Beeswax Candle", "16.00", "Beeswax Candle $16"),
        item("canvas-tote", "Canvas Tote", "24.00", "Canvas Tote $24"),
      ],
      shipping: { type: "flat", amount: "6.00", notes: "Flat rate, US only" },
      extraction_notes: ["Wool Camp Socks: Large is $2 more, kept as its own variant price"],
    },
    stumbles: {},
  },
  {
    slug: "quill-pipkin-studio",
    spec: {
      spec_version: 1,
      source_url: BASE + "/quill-pipkin-studio/",
      merchant: { name: "Quill & Pipkin Studio", currency: "USD" },
      items: [
        item("headshot", "Headshot commission", "40.00", "Headshots are $40", {
          add_ons: [{ id: "background", label: "Background", price: "15.00" }],
        }),
        item("half-body", "Half body commission", "56.00", "half body $65", {
          add_ons: [{ id: "background", label: "Background", price: "15.00" }],
        }),
        item("full-body", "Full body commission", "90.00", "full body $90", {
          add_ons: [{ id: "background", label: "Background", price: "15.00" }],
        }),
        item("sticker-sheet", "Sticker sheet", "0.00", "Sticker sheets, ask me for pricing"),
      ],
      shipping: { type: "flat", amount: "0.00", notes: "Digital delivery" },
      extraction_notes: [
        "Extra character is +50%, a percentage rule the spec can't express, so it is left out",
        "Background is a flat $15 add-on on every commission size",
      ],
    },
    stumbles: {
      "half-body": [
        {
          reason: "The quote says $65 but unit_price is 56.00",
          page_check_ok: false,
          paypal_check_ok: null,
          fix: { unit_price: "65.00" },
          note: "Half body price corrected to match the page ($65)",
        },
      ],
      "sticker-sheet": [
        { reason: "No price found in the quote", page_check_ok: false, paypal_check_ok: null },
        { reason: "No price found in the quote", page_check_ok: false, paypal_check_ok: null },
        { reason: "No price found in the quote", page_check_ok: false, paypal_check_ok: null },
        { reason: "No price found in the quote", page_check_ok: false, paypal_check_ok: null },
      ],
    },
    hopeless: ["sticker-sheet"],
  },
  {
    slug: "hollowbrook-bakery",
    spec: {
      spec_version: 1,
      source_url: BASE + "/hollowbrook-bakery/",
      merchant: { name: "Hollowbrook Bakery", currency: "USD" },
      items: [
        item("sourdough-loaf", "Sourdough Loaf", "9.00", "Sourdough Loaf ... $9", {
          variants: [{ id: "half", label: "Half loaf", unit_price: "5.00" }],
          add_ons: [{ id: "sliced", label: "Sliced", price: "1.00" }],
        }),
        item("seeded-rye", "Seeded Rye", "8.00", "Seeded Rye $8 $7"),
        item("butter-croissant", "Butter Croissant", "4.50", "Butter Croissant $4.50 SOLD OUT", {
          available: false,
        }),
        item("cinnamon-knot", "Cinnamon Knot", "3.50", "Cinnamon Knot*"),
        item("oat-cookie", "Oat Cookie", "2.50", "Oat Cookie $2.50"),
      ],
      shipping: { type: "flat", amount: "6.00", notes: "Local delivery only" },
      extraction_notes: [
        "Butter Croissant is marked SOLD OUT, set available=false",
        "Seeded Rye was $8 crossed out, now $7, used $7",
        "Cinnamon Knot price comes from the footnote (*all knots $3.50)",
      ],
    },
    stumbles: {
      "seeded-rye": [
        {
          reason: "The quote has two prices ($8 and $7) and unit_price is the crossed-out one",
          page_check_ok: false,
          paypal_check_ok: null,
          fix: { unit_price: "7.00", source_quote: "now $7" },
          note: "Rye: used the current price, not the crossed-out one",
        },
      ],
      "cinnamon-knot": [
        {
          reason: "The quote doesn't contain a price",
          page_check_ok: false,
          paypal_check_ok: null,
          fix: { source_quote: "*all knots $3.50" },
          note: "Cinnamon Knot: quote now points at the footnote",
        },
      ],
    },
  },
]

// ---- in-memory state ----

interface MockStore {
  store: Store
  script: Script
  events: StoreEvent[]
  listeners: Set<(event: StoreEvent) => void>
  versions: SpecVersion[]
  runs: VerificationRun[]
  verified: Set<string>
  done: boolean
  // the merchant's side, made when the run ends
  reviews: Map<string, MockReview>
  labels: Record<string, string>
}

interface MockReview {
  position: number
  category: string | null
  stock: number | null
  published: boolean
  // flagged field -> how it was settled, same shape as the API keeps
  resolved: Partial<Record<FlagField, { by: "confirm" | "edit"; was?: string }>>
}

const CATEGORIES = ["Apparel", "Accessories", "Home", "Stationery", "Food and drink", "Art and prints", "Services", "Other"]

// field -> [default label, where it goes in the PayPal order]
const COLUMNS: Record<string, [string, string | null]> = {
  name: ["Item", "purchase_units[0].items[0].name"],
  category: ["Category", null],
  description: ["Description", null],
  unit_price: ["Price", "purchase_units[0].items[0].unit_amount.value"],
  stock: ["Stock", null],
  published: ["Live on PayPal", null],
  checked_at: ["Checked", null],
  paypal_order_id: ["PayPal order", "id"],
  status: ["Status", null],
}

let stores: MockStore[] = []
let orders: Order[] = []
let nextStoreId = 1
let nextOrderId = 1

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function fakeId(length: number) {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
  let out = ""
  for (let i = 0; i < length; i++) out += letters[Math.floor(Math.random() * letters.length)]
  return out
}

function now() {
  return new Date().toISOString()
}

function copy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function emit(target: MockStore, type: StoreEvent["type"], message: string, item_id: string | null = null, data: StoreEvent["data"] = {}) {
  const event: StoreEvent = {
    seq: target.events.length,
    type,
    store_id: target.store.id,
    item_id,
    message,
    data,
  }
  target.events.push(event)
  for (const listener of target.listeners) listener(event)
}

async function playRun(target: MockStore) {
  const { script } = target
  const spec = copy(script.spec)
  const currency = spec.merchant.currency
  const speed = 1

  emit(target, "fetch.started", "Fetching " + spec.source_url + ".")
  await sleep(600 * speed)
  emit(target, "fetch.done", "Got the page, 14 KB of readable text.")
  emit(target, "extract.started", "Claude is reading the page and writing the store spec.")
  await sleep(1500 * speed)

  target.store.merchant_name = spec.merchant.name
  target.versions.push({ version: 1, note: "First extraction", created_at: now(), spec: copy(spec) })
  emit(target, "extract.done", "Claude found " + spec.items.length + " items at " + spec.merchant.name + ".", null, {
    item_count: spec.items.length,
    spec: copy(spec),
    version: 1,
  })

  for (let position = 0; position < spec.items.length; position++) {
    let current = spec.items[position]
    if (!current.available) {
      target.store.counts.unavailable += 1
      continue
    }
    const stumbles = script.stumbles[current.id] || []
    let attempt = 0
    while (true) {
      emit(target, "item.checking", "Checking " + current.name + " against the page and PayPal.", current.id, {
        attempt,
        item: copy(current),
      })
      await sleep(850 * speed)
      const stumble = stumbles[attempt]
      const version = target.versions[target.versions.length - 1].version

      if (!stumble) {
        const paypal_order_id = fakeId(17)
        target.runs.push({
          item_id: current.id, attempt, spec_version: version, page_check_ok: true,
          paypal_check_ok: true, paypal_order_id, ok: true, reason: null, created_at: now(),
        })
        target.verified.add(current.id)
        target.store.counts.verified += 1
        emit(
          target,
          "item.verified",
          current.name + " verified at " + current.unit_price + " " + currency + ", PayPal order " + paypal_order_id + ".",
          current.id,
          { attempt, paypal_order_id, item: copy(current) }
        )
        break
      }

      target.runs.push({
        item_id: current.id, attempt, spec_version: version, page_check_ok: stumble.page_check_ok,
        paypal_check_ok: stumble.paypal_check_ok, paypal_order_id: null, ok: false,
        reason: stumble.reason, created_at: now(),
      })
      const final = attempt >= 3
      emit(target, "item.failed", current.name + " failed: " + stumble.reason + ".", current.id, {
        attempt,
        reason: stumble.reason,
        page_check_ok: stumble.page_check_ok,
        paypal_check_ok: stumble.paypal_check_ok,
        paypal_order_id: null,
        final,
      })
      if (final) {
        target.store.counts.failed += 1
        break
      }

      attempt += 1
      emit(target, "item.repairing", "Asking Claude to repair " + current.name + " (repair " + attempt + " of 3).", current.id, {
        attempt,
        reason: stumble.reason,
      })
      await sleep(1300 * speed)
      if (stumble.fix) {
        current = { ...current, ...stumble.fix }
        spec.items[position] = current
        target.versions.push({
          version: version + 1,
          note: stumble.note || "Repaired " + current.name,
          created_at: now(),
          spec: copy(spec),
        })
      }
    }
  }

  const counts = target.store.counts
  target.store.status = counts.verified > 0 ? "live" : "failed"
  ensureReviews(target)
  target.done = true
  emit(
    target,
    "store.ready",
    spec.merchant.name + " is " + (counts.verified > 0 ? "live" : "not live") + ": " + counts.verified + " verified, " +
      counts.failed + " failed, " + counts.unavailable + " unavailable.",
    null,
    { counts: { ...counts }, status: target.store.status, spec: copy(spec) }
  )
}

function startStore(url: string, mode: Mode): MockStore {
  let script = SCRIPTS[0]
  for (const candidate of SCRIPTS) {
    if (url.includes(candidate.slug)) script = candidate
  }
  const target: MockStore = {
    store: {
      id: nextStoreId++,
      source_url: url,
      merchant_name: "",
      status: "connecting",
      mode,
      error: null,
      counts: { verified: 0, failed: 0, unavailable: 0 },
      created_at: now(),
    },
    script: { ...script, spec: { ...copy(script.spec), source_url: url } },
    events: [],
    listeners: new Set(),
    versions: [],
    runs: [],
    verified: new Set(),
    done: false,
    reviews: new Map(),
    labels: {},
  }
  stores.push(target)
  void playRun(target)
  return target
}

function findStore(storeId: number): MockStore {
  for (const target of stores) {
    if (target.store.id === storeId) return target
  }
  throw new Error("There is no store " + storeId)
}

function latestSpec(target: MockStore): StoreSpec | null {
  if (target.versions.length === 0) return null
  return target.versions[target.versions.length - 1].spec
}

// ---- the merchant's review, the same rules as backend/app/review.py ----

function dollars(amount: string) {
  return "$" + Number(amount).toFixed(2)
}

function noteField(note: string): FlagField {
  const lowered = note.toLowerCase()
  if (/sold out|unavailable|not for sale|available/.test(lowered)) return "available"
  if (/\$\s?\d|price|cost|footnote|crossed/.test(lowered)) return "unit_price"
  return "name"
}

function flagsFor(target: MockStore, current: SpecItem): Partial<Record<FlagField, string[]>> {
  const flags: Partial<Record<FlagField, string[]>> = {}
  const add = (field: FlagField, reason: string) => {
    const reasons = flags[field] || (flags[field] = [])
    if (!reasons.includes(reason)) reasons.push(reason)
  }
  const runs = target.runs.filter((run) => run.item_id === current.id)
  const repairs = Math.max(0, ...runs.map((run) => run.attempt))
  if (repairs > 0) {
    const failure = runs.find((run) => !run.ok && run.reason)
    const why = failure ? " after a check failed: " + failure.reason : ""
    const first = target.versions[0].spec.items.find((entry) => entry.id === current.id)
    let repaired = first
    for (const version of target.versions) {
      if ((version.note || "").startsWith("Merchant edit")) continue
      repaired = version.spec.items.find((entry) => entry.id === current.id) || repaired
    }
    if (first && repaired && first.unit_price !== repaired.unit_price) {
      add("unit_price", "Claude first read " + dollars(first.unit_price) + ", then repaired it to " + dollars(repaired.unit_price) + why + ".")
    } else {
      add("unit_price", "It took " + (repairs === 1 ? "1 repair" : repairs + " repairs") + " to pass the checks" + why + ".")
    }
  }
  const spec = latestSpec(target)
  for (const note of spec ? spec.extraction_notes : []) {
    if (note.toLowerCase().includes(current.name.toLowerCase())) add(noteField(note), "Claude's note: " + note)
  }
  return flags
}

function ensureReviews(target: MockStore) {
  const spec = latestSpec(target)
  if (!spec) return
  for (const current of spec.items) {
    if (target.reviews.has(current.id)) continue
    const flagged = Object.keys(flagsFor(target, current)).length > 0
    target.reviews.set(current.id, {
      position: target.reviews.size,
      category: null,
      stock: null,
      published: current.available && target.verified.has(current.id) && !flagged,
      resolved: {},
    })
  }
}

function blockedReason(target: MockStore, current: SpecItem): string | null {
  if (!current.available) return current.name + " is not for sale on the page"
  if (!target.verified.has(current.id)) return current.name + " hasn't passed verification"
  const review = target.reviews.get(current.id)
  const open = Object.keys(flagsFor(target, current)).filter((field) => !review?.resolved[field as FlagField])
  if (open.length === 1) return current.name + " has 1 field that still needs a look"
  if (open.length > 1) return current.name + " has " + open.length + " fields that still need a look"
  return null
}

function reviewOf(target: MockStore): ReviewResponse {
  const spec = latestSpec(target)
  if (!spec) throw new Error("This store has no spec yet")
  if (target.done) ensureReviews(target)
  let needs_look = 0
  const items = spec.items.map((current, index) => {
    const review = target.reviews.get(current.id)
    const found = flagsFor(target, current)
    const flags: ReviewFlag[] = []
    for (const field of ["name", "unit_price", "available"] as FlagField[]) {
      const reasons = found[field]
      if (!reasons) continue
      const resolved = Boolean(review?.resolved[field])
      if (!resolved) needs_look += 1
      flags.push({ field, reasons, resolved })
    }
    const runs = target.runs.filter((run) => run.item_id === current.id)
    return {
      item_id: current.id,
      position: review ? review.position : index,
      category: review ? review.category : null,
      stock: review ? review.stock : null,
      published: review ? review.published : false,
      blocked_reason: blockedReason(target, current),
      flags,
      checked_at: runs.length > 0 ? runs[runs.length - 1].created_at : null,
    }
  })
  items.sort((a, b) => a.position - b.position)
  return copy({
    store_id: target.store.id,
    editable: target.done,
    categories: CATEGORIES,
    columns: Object.entries(COLUMNS).map(([field, [default_label, paypal_field]]) => ({
      field,
      label: target.labels[field] || default_label,
      default_label,
      paypal_field,
    })),
    needs_look,
    items,
  })
}

function cleanPrice(raw: string): string {
  const text = String(raw).trim().replace(/^\$/, "").replace(/,/g, "").trim()
  if (!text) throw new Error("A price can't be blank")
  if (!/^-?\d*\.?\d+$/.test(text)) throw new Error('"' + String(raw).trim() + '" is not a price')
  const value = Number(text)
  if (value <= 0) throw new Error("A price has to be above 0.00")
  if (Math.abs(value * 100 - Math.round(value * 100)) > 1e-6) throw new Error("A price can have 2 decimals at most")
  return value.toFixed(2)
}

function editItem(target: MockStore, itemId: string, body: ItemPatch) {
  if (!target.done) throw new Error("This store is still connecting, wait for it to finish")
  const spec = latestSpec(target)
  const current = spec?.items.find((entry) => entry.id === itemId)
  const review = target.reviews.get(itemId)
  if (!spec || !current || !review) throw new Error("This store has no item " + itemId)

  const updates: Partial<SpecItem> = {}
  if (body.name !== undefined) {
    const name = body.name.trim()
    if (!name) throw new Error("An item needs a name")
    if (name.length > 127) throw new Error("name: String should have at most 127 characters")
    if (name !== current.name) updates.name = name
  }
  if (body.description !== undefined) {
    const description = body.description.trim()
    if (description.length > 300) throw new Error("description: String should have at most 300 characters")
    if (description !== (current.description || "")) updates.description = description
  }
  if (body.unit_price !== undefined) {
    const price = cleanPrice(body.unit_price)
    if (price !== current.unit_price) updates.unit_price = price
  }
  if (body.category !== undefined && body.category !== null && !CATEGORIES.includes(body.category)) {
    throw new Error(body.category + " is not one of the categories")
  }
  if (body.stock !== undefined && body.stock !== null && (!Number.isInteger(body.stock) || body.stock < 0 || body.stock > 1_000_000)) {
    throw new Error("Stock has to be a whole number from 0 to 1000000")
  }

  if (Object.keys(updates).length > 0) {
    const version = target.versions[target.versions.length - 1].version
    const nextSpec = copy(spec)
    const index = nextSpec.items.findIndex((entry) => entry.id === itemId)
    const before = nextSpec.items[index]
    nextSpec.items[index] = { ...before, ...updates }
    target.versions.push({
      version: version + 1,
      note: "Merchant edit of " + current.name,
      created_at: now(),
      spec: nextSpec,
    })
    if (current.available && (updates.name !== undefined || updates.unit_price !== undefined)) {
      // the price the page check last passed at
      let backed: string | null = null
      for (const run of target.runs) {
        if (run.item_id !== itemId || !run.page_check_ok) continue
        const then = target.versions.find((entry) => entry.version === run.spec_version)
        const found = then?.spec.items.find((entry) => entry.id === itemId)
        if (found) backed = found.unit_price
      }
      const onPage = backed === nextSpec.items[index].unit_price
      const runs = target.runs.filter((run) => run.item_id === itemId)
      if (!target.verified.has(itemId)) {
        target.verified.add(itemId)
        target.store.counts.verified += 1
        target.store.counts.failed = Math.max(0, target.store.counts.failed - 1)
        target.store.status = "live"
      }
      target.runs.push({
        item_id: itemId,
        attempt: Math.max(0, ...runs.map((run) => run.attempt)),
        spec_version: version + 1,
        page_check_ok: onPage,
        paypal_check_ok: true,
        paypal_order_id: fakeId(17),
        ok: true,
        reason: onPage ? null : "Price set by the merchant" + (backed ? ", the page check last passed at " + dollars(backed) : ""),
        created_at: now(),
      })
    }
    for (const field of ["name", "unit_price"] as const) {
      const next = updates[field]
      if (next === undefined) continue
      const settled = review.resolved[field]
      if (!settled) review.resolved[field] = { by: "edit", was: current[field] }
      else if (settled.by === "edit" && settled.was === next) delete review.resolved[field]
    }
  }
  if (body.category !== undefined) review.category = body.category
  if (body.stock !== undefined) review.stock = body.stock
  for (const field of body.resolve || []) review.resolved[field] = { by: "confirm" }

  const after = (latestSpec(target) as StoreSpec).items.find((entry) => entry.id === itemId) as SpecItem
  const blocked = blockedReason(target, after)
  if (body.published === true) {
    if (blocked) throw new Error(blocked + ", so it can't go live yet")
    review.published = true
  } else if (body.published === false) {
    review.published = false
  } else if (blocked && review.published) {
    review.published = false
  }
}

function priceOrder(target: MockStore, item_id: string, variant_id: string | null, add_on_ids: string[], quantity: number) {
  const spec = latestSpec(target)
  if (!spec) throw new Error("This store has no spec yet")
  let found: SpecItem | null = null
  for (const candidate of spec.items) {
    if (candidate.id === item_id) found = candidate
  }
  if (!found || !target.verified.has(item_id)) throw new Error("That item isn't verified, so it can't be bought")
  const review = target.reviews.get(item_id)
  if (!review || !review.published) throw new Error(found.name + " isn't live on PayPal yet, the merchant hasn't published it")
  if (review.stock !== null && quantity > review.stock) {
    throw new Error(review.stock === 0 ? found.name + " is out of stock" : "Only " + review.stock + " of " + found.name + " left")
  }

  let unit = Number(found.unit_price)
  let description = found.name
  if (variant_id) {
    for (const variant of found.variants) {
      if (variant.id === variant_id) {
        unit = Number(variant.unit_price)
        description += " (" + variant.label + ")"
      }
    }
  }
  for (const add_on of found.add_ons) {
    if (add_on_ids.includes(add_on.id)) {
      unit += Number(add_on.price)
      description += " + " + add_on.label
    }
  }
  const shipping = Number(spec.shipping.amount)
  const total = unit * quantity + shipping
  return { description, unit, shipping, total: total.toFixed(2), currency: spec.merchant.currency }
}

function placeOrder(target: MockStore, item_id: string, variant_id: string | null, add_on_ids: string[], quantity: number, created_by: Order["created_by"]): Order {
  const quote = priceOrder(target, item_id, variant_id, add_on_ids, quantity)
  const order: Order = {
    id: nextOrderId++,
    store_id: target.store.id,
    store_name: target.store.merchant_name,
    item_id,
    variant_id,
    add_on_ids,
    description: quote.description,
    quantity,
    total: quote.total,
    currency: quote.currency,
    paypal_order_id: fakeId(17),
    capture_id: fakeId(17),
    status: "captured",
    error: null,
    created_by,
    created_at: now(),
    check_order_id: null,
    check_mandate_id: null,
    review_state: null,
    check_verdict: null,
    check_reason: null,
    check_mismatched_fields: [],
    decision_ms: null,
    review_action: null,
    replaced_by_order_id: null,
    replaces_order_id: null,
  }
  orders.unshift(order)
  const review = target.reviews.get(item_id)
  if (review && review.stock !== null) review.stock = Math.max(0, review.stock - quantity)
  return order
}

// a tiny scripted "agent": picks the store and item whose names show up in the request
function runAgent(text: string): AgentReply {
  const lowered = text.toLowerCase()
  const steps: AgentStep[] = []
  const live = stores.filter((target) => target.store.status === "live")

  steps.push({
    tool: "list_stores",
    input: {},
    output: {
      stores: live.map((target) => ({
        store_id: target.store.id,
        name: target.store.merchant_name,
        url: target.store.source_url,
        verified_items: target.store.counts.verified,
      })),
    },
    is_error: false,
  })
  if (live.length === 0) {
    return { reply: "No stores are live yet. Connect one on the Connect tab first.", steps, orders: [] }
  }

  let target = live[live.length - 1]
  for (const candidate of live) {
    const firstWord = candidate.store.merchant_name.toLowerCase().split(" ")[0]
    if (lowered.includes(firstWord)) target = candidate
  }
  const spec = latestSpec(target) as StoreSpec
  // what an agent can buy: verified, published, in the merchant's order
  const sellable = spec.items
    .filter((candidate) => target.verified.has(candidate.id) && target.reviews.get(candidate.id)?.published)
    .sort((a, b) => (target.reviews.get(a.id)?.position || 0) - (target.reviews.get(b.id)?.position || 0))
  if (sellable.length === 0) {
    return { reply: target.store.merchant_name + " has nothing published yet. Publish an item on the Connect tab first.", steps, orders: [] }
  }

  let picked = sellable[0]
  for (const candidate of sellable) {
    for (const word of candidate.name.toLowerCase().split(" ")) {
      if (word.length > 3 && lowered.includes(word)) picked = candidate
    }
  }
  steps.push({
    tool: "search_catalog",
    input: { store_id: target.store.id, query: picked.name.split(" ")[0].toLowerCase() },
    output: { store_id: target.store.id, merchant: spec.merchant, items: [picked] },
    is_error: false,
  })

  if (!/\b(buy|get|order|purchase)\b/.test(lowered)) {
    // just browsing, list everything and don't buy
    steps[steps.length - 1] = {
      tool: "search_catalog",
      input: { store_id: target.store.id, query: "" },
      output: { store_id: target.store.id, merchant: spec.merchant, items: sellable },
      is_error: false,
    }
    const lines = sellable.map((entry) => "- " + entry.name + ", " + entry.unit_price + " " + spec.merchant.currency)
    return {
      reply: target.store.merchant_name + " has " + sellable.length + " verified items:\n" + lines.join("\n") + "\nTell me which one to buy.",
      steps,
      orders: [],
    }
  }

  let variant_id: string | null = null
  for (const variant of picked.variants) {
    if (lowered.includes(variant.label.toLowerCase().split(" ")[0])) variant_id = variant.id
  }
  const add_on_ids: string[] = []
  for (const add_on of picked.add_ons) {
    if (lowered.includes(add_on.label.toLowerCase())) add_on_ids.push(add_on.id)
  }

  const order = placeOrder(target, picked.id, variant_id, add_on_ids, 1, "agent")
  steps.push({
    tool: "buy_item",
    input: { store_id: target.store.id, item_id: picked.id, variant_id, add_on_ids, quantity: 1 },
    output: {
      status: order.status,
      bought: order.description,
      quantity: 1,
      shipping: spec.shipping.amount,
      total: order.total,
      currency: order.currency,
      paypal_order_id: order.paypal_order_id,
      capture_id: order.capture_id,
      error: null,
    },
    is_error: false,
  })

  return {
    reply:
      "Done. I bought " + order.description + " from " + target.store.merchant_name + " for " + order.total + " " +
      order.currency + " including shipping. The payment was captured (capture " + order.capture_id + ").",
    steps,
    orders: [order],
  }
}

export const mockApi: Api = {
  async getConfig() {
    const urls = SCRIPTS.map((script) => script.spec.source_url)
    return {
      default_mode: "live",
      demo_store_urls: urls,
      fixture_urls: urls,
      paypal_configured: true,
      claude_configured: true,
      vault_configured: true,
      // the mock has no Check service, so it shows the app with the flag off
      check_configured: false,
      check_merchant_configured: false,
      check_review_links: false,
    }
  },

  async listStores() {
    return stores.map((target) => copy(target.store))
  },

  async connectStore(url, mode) {
    await sleep(200)
    if (!/^https?:\/\//.test(url)) throw new Error("Only http and https URLs can be connected")
    const target = startStore(url, mode)
    return { store_id: target.store.id, mode, events_url: "/stores/" + target.store.id + "/events" }
  },

  subscribe(storeId, onEvent): EventSubscription {
    const target = findStore(storeId)
    let open = true
    const listener = (event: StoreEvent) => {
      if (open) onEvent(event)
    }
    // history first, like the real stream, then whatever comes next
    queueMicrotask(() => {
      for (const event of [...target.events]) listener(event)
      if (open) target.listeners.add(listener)
    })
    return {
      close: () => {
        open = false
        target.listeners.delete(listener)
      },
    }
  },

  async getSpec(storeId): Promise<SpecResponse> {
    const target = findStore(storeId)
    const spec = latestSpec(target)
    return copy({
      store: target.store,
      spec,
      extraction_notes: spec ? spec.extraction_notes : [],
      versions: target.versions,
      runs: target.runs,
      verified_item_ids: [...target.verified].sort(),
    })
  },

  async getReview(storeId) {
    return reviewOf(findStore(storeId))
  },

  async patchItem(storeId, itemId, body) {
    await sleep(350)
    const target = findStore(storeId)
    editItem(target, itemId, body)
    return reviewOf(target)
  },

  async publishItems(storeId, itemIds, published) {
    await sleep(500)
    const target = findStore(storeId)
    const spec = latestSpec(target) as StoreSpec
    if (published) {
      const blocked = []
      for (const itemId of itemIds) {
        const current = spec.items.find((entry) => entry.id === itemId)
        const reason = current ? blockedReason(target, current) : "This store has no item " + itemId
        if (reason) blocked.push(reason)
      }
      if (blocked.length > 0) {
        throw new Error(blocked.length + (blocked.length === 1 ? " item" : " items") + " can't be published: " + blocked.join("; "))
      }
    }
    for (const itemId of itemIds) {
      const review = target.reviews.get(itemId)
      if (review) review.published = published
    }
    return reviewOf(target)
  },

  async reorderItems(storeId, itemIds) {
    await sleep(200)
    const target = findStore(storeId)
    if (itemIds.length !== target.reviews.size) throw new Error("The new order has to list every item of the store exactly once")
    itemIds.forEach((itemId, position) => {
      const review = target.reviews.get(itemId)
      if (!review) throw new Error("The new order has to list every item of the store exactly once")
      review.position = position
    })
    return reviewOf(target)
  },

  async renameColumn(storeId, field, label) {
    await sleep(200)
    const target = findStore(storeId)
    if (!COLUMNS[field]) throw new Error(field + " is not a catalog column")
    const cleaned = label.trim().replace(/\s+/g, " ")
    if (cleaned.length > 40) throw new Error("A column name can be 40 characters at most")
    if (!cleaned || cleaned === COLUMNS[field][0]) delete target.labels[field]
    else target.labels[field] = cleaned
    return reviewOf(target)
  },

  async createOrder(storeId, body) {
    await sleep(900)
    return placeOrder(findStore(storeId), body.item_id, body.variant_id || null, body.add_on_ids || [], body.quantity, "manual")
  },

  async listOrders() {
    return copy(orders)
  },

  async agentChat(messages) {
    await sleep(2200)
    return runAgent(messages[messages.length - 1].content)
  },

  async resetDemo(mode) {
    stores = []
    orders = []
    const started = []
    for (const script of SCRIPTS) {
      const target = startStore(script.spec.source_url, mode)
      started.push({ store_id: target.store.id, url: script.spec.source_url })
    }
    return { mode, stores: started }
  },

  hasSession() {
    return false
  },

  async logIn() {
    throw new Error("The mock has no Check service")
  },

  async reviewLink() {
    throw new Error("The mock has no Check service")
  },

  async listDisputes() {
    return []
  },

  async syncDisputes() {
    return { orders_checked: 0, disputes_found: 0, created: 0, updated: 0, errors: [] }
  },

  async disputeEvidence() {
    throw new Error("The mock has no Check service")
  },

  async redraftDispute() {
    throw new Error("The mock has no Check service")
  },

  async submitDisputeEvidence() {
    throw new Error("The mock has no Check service")
  },
}
