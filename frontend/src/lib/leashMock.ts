// A pretend Leash for VITE_USE_MOCK=true: a handful of fictional orders in memory. Approving
// and rejecting work, the clock runs from when a review is opened, and a demo order is first
// held and then decided, so the grid's live updates can be seen with no backend.

import type { LeashApi, LeashOrder } from "@/lib/leash"

const FAST_MS = 2000
let nextId = 1
let orders: LeashOrder[] = []
const reviews = new Map<string, { orderId: number; opened: number }>()
const disputed = new Set<number>()

function ago(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString()
}

function paypalId() {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
  let out = ""
  for (let i = 0; i < 17; i++) out += letters[Math.floor(Math.random() * letters.length)]
  return out
}

interface Seed {
  asked: string
  rules: LeashOrder["mandate"] extends infer M ? (M extends { rules: infer R } ? R : never) : never
  cap: string
  item: string
  color: string | null
  size: string | null
  quantity?: number
  total: string
  store?: string | null
  agent: string
  verdict: "match" | "mismatch" | "unsure"
  risk: number
  reason: string
  mismatched: string[]
  state: "review" | "auto" | "approved" | "rejected" | "disputed"
  decisionMs?: number
  minutes: number
}

const SEEDS: Seed[] = [
  { asked: "Black trail runners, women's size 9, up to $120", rules: { item: "trail runners", color: "black", size: "9" }, cap: "120.00", item: "Trail runner", color: "red", size: "9", total: "118.00", agent: "Wren", verdict: "mismatch", risk: 90, reason: "Ordered red, mandate says black", mismatched: ["color"], state: "review", minutes: 2 },
  { asked: "White canvas sneakers, size M, under $70", rules: { item: "canvas sneakers", color: "white", size: "M" }, cap: "70.00", item: "Canvas low-top sneaker", color: "white", size: "L", total: "64.00", agent: "Pilot", verdict: "mismatch", risk: 80, reason: "Asked for size M, got L", mismatched: ["size"], state: "review", minutes: 4 },
  { asked: "Oat milk, 2 cartons, up to $12", rules: { item: "oat milk", quantity: 2 }, cap: "12.00", item: "Oat milk 1L", color: null, size: null, quantity: 2, total: "9.80", agent: "Wren", verdict: "match", risk: 4, reason: "Matches the mandate", mismatched: [], state: "auto", minutes: 9 },
  { asked: "Noise cancelling headphones, E45, up to $60", rules: { item: "headphones" }, cap: "60.00", item: "E40 headphones", color: "black", size: null, total: "59.00", agent: "Pilot", verdict: "mismatch", risk: 85, reason: "Mandate said E45, order has E40", mismatched: ["item"], state: "approved", decisionMs: 900, minutes: 14 },
  { asked: "Grey wool socks, size L, up to $25", rules: { item: "wool socks", color: "grey", size: "L" }, cap: "25.00", item: "Wool camp socks", color: "grey", size: "L", total: "27.50", agent: "Wren", verdict: "mismatch", risk: 70, reason: "Order is $27.50, over the $25.00 cap", mismatched: ["price"], state: "approved", decisionMs: 1400, minutes: 21 },
  { asked: "Linen apron in olive, up to $45", rules: { item: "linen apron", color: "olive" }, cap: "45.00", item: "Linen apron", color: "navy", size: null, total: "38.00", agent: "Sable", verdict: "mismatch", risk: 88, reason: "Mandate said olive, order has navy", mismatched: ["color"], state: "rejected", decisionMs: 9400, minutes: 33 },
  { asked: "Enamel mug, 2 of them, up to $30", rules: { item: "enamel mug", quantity: 2 }, cap: "30.00", item: "Enamel mug", color: "cream", size: null, quantity: 3, total: "29.00", agent: "Sable", verdict: "mismatch", risk: 65, reason: "Asked for 2, order has 3", mismatched: ["quantity"], state: "approved", decisionMs: 12800, minutes: 47 },
  { asked: "Beeswax candle from Fernwood, up to $20", rules: { item: "beeswax candle" }, cap: "20.00", item: "Beeswax candle", color: null, size: null, total: "16.00", agent: "Wren", verdict: "match", risk: 6, reason: "Matches the mandate", mismatched: [], state: "disputed", minutes: 95 },
  { asked: "Canvas tote, natural, up to $30", rules: { item: "canvas tote", color: "natural" }, cap: "30.00", item: "Canvas tote", color: "natural", size: null, total: "24.00", store: "Thistle Outfitters", agent: "Pilot", verdict: "mismatch", risk: 75, reason: "Mandate names Fernwood, order is at Thistle Outfitters", mismatched: ["merchant"], state: "approved", decisionMs: 1100, minutes: 120 },
]

function build(seed: Seed): LeashOrder {
  const id = nextId++
  const decided = seed.state === "approved" || seed.state === "rejected"
  const captured = seed.state === "auto" || seed.state === "approved" || seed.state === "disputed"
  if (seed.state === "disputed") disputed.add(id)
  return {
    id,
    paypal_order_id: paypalId(),
    merchant: seed.store || null,
    agent_name: seed.agent,
    items: [{ name: seed.item, color: seed.color, size: seed.size, quantity: seed.quantity || 1, unit_price: seed.total }],
    total: seed.total,
    shipping_amount: "0.00",
    currency: "USD",
    status: seed.state === "review" ? "authorized" : captured ? "captured" : "voided",
    review_state: seed.state === "review" ? "needs_review" : seed.state === "auto" || seed.state === "disputed" ? "auto_approved" : seed.state === "approved" ? "approved" : "rejected",
    watch_mode: "normal",
    created_at: ago(seed.minutes),
    mandate: {
      id,
      buyer_label: "Sam",
      raw_request: seed.asked,
      rules: { currency: "USD", ...seed.rules },
      max_price: seed.cap,
      max_price_inclusive: true,
      merchant: "Fernwood Supply Co",
    },
    intent_check: { verdict: seed.verdict, risk_score: seed.risk, reason: seed.reason, mismatched_fields: seed.mismatched, checked_by: "ai" },
    approval: decided
      ? { action: seed.state === "approved" ? "approve" : "reject", opened_at: ago(seed.minutes), decided_at: ago(seed.minutes), decision_ms: seed.decisionMs ?? null }
      : null,
  }
}

function reset() {
  nextId = 1
  reviews.clear()
  disputed.clear()
  orders = SEEDS.map(build)
}
reset()

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function find(orderId: number) {
  const order = orders.find((entry) => entry.id === orderId)
  if (!order) throw new Error("There is no order " + orderId)
  return order
}

function fastStreak() {
  const decisions = orders
    .filter((order) => order.approval && order.approval.action)
    .sort((a, b) => (b.approval!.decided_at || "").localeCompare(a.approval!.decided_at || ""))
  let streak = 0
  for (const order of decisions) {
    const approval = order.approval!
    if (approval.action !== "approve" || approval.decision_ms === null || approval.decision_ms >= FAST_MS) break
    streak += 1
  }
  return streak
}

const DEMO: Seed[] = [
  { asked: "Field notebook, dot grid, up to $15", rules: { item: "field notebook" }, cap: "15.00", item: "Field notebook", color: null, size: null, total: "12.00", agent: "Wren", verdict: "match", risk: 5, reason: "Matches the mandate", mismatched: [], state: "auto", minutes: 0 },
  { asked: "Wool blanket, size M, in green, up to $130", rules: { item: "wool blanket", color: "green", size: "M" }, cap: "130.00", item: "Wool camp blanket", color: "green", size: "L", total: "126.00", agent: "Pilot", verdict: "mismatch", risk: 82, reason: "Asked for size M, got L", mismatched: ["size"], state: "review", minutes: 0 },
  { asked: "Brass key hook, up to $15", rules: { item: "brass key hook" }, cap: "15.00", item: "Brass key hook", color: null, size: null, total: "12.00", agent: "Sable", verdict: "mismatch", risk: 60, reason: "Order is $18.00, over the $15.00 cap", mismatched: ["price"], state: "review", minutes: 0 },
]
let demoIndex = 0

export const leashMock: LeashApi = {
  signedIn: () => true,
  async login() {},

  async listOrders() {
    return JSON.parse(JSON.stringify([...orders].sort((a, b) => b.id - a.id))) as LeashOrder[]
  },

  async stats() {
    const streak = fastStreak()
    return { fast_streak: streak, rubber_stamp_active: streak >= 3, fast_threshold_ms: FAST_MS }
  },

  async listDisputes() {
    return [...disputed].map((order_id, index) => ({ id: index + 1, order_id, status: "WAITING_FOR_SELLER_RESPONSE" }))
  },

  async openReview(orderId) {
    find(orderId)
    const token = "mock-" + orderId + "-" + Math.random().toString(36).slice(2)
    reviews.set(token, { orderId, opened: Date.now() })
    return token
  },

  async decide(token, action) {
    const review = reviews.get(token)
    if (!review) throw new Error("This review link isn't valid any more")
    const decisionMs = Date.now() - review.opened
    await sleep(900)
    const order = find(review.orderId)
    if (order.review_state !== "needs_review") throw new Error("This order was already decided")
    reviews.delete(token)
    order.status = action === "approve" ? "captured" : "voided"
    order.review_state = action === "approve" ? "approved" : "rejected"
    order.approval = { action, opened_at: new Date(review.opened).toISOString(), decided_at: new Date().toISOString(), decision_ms: decisionMs }
  },

  async demoOrder() {
    await sleep(700)
    const seed = DEMO[demoIndex % DEMO.length]
    demoIndex += 1
    const order = build({ ...seed, state: "review" })
    // every order starts as a hold. the check then captures it or sends it to a human
    order.review_state = null
    order.intent_check = null
    orders.push(order)
    setTimeout(() => {
      order.intent_check = { verdict: seed.verdict, risk_score: seed.risk, reason: seed.reason, mismatched_fields: seed.mismatched, checked_by: "ai" }
      if (seed.state === "auto") {
        order.status = "captured"
        order.review_state = "auto_approved"
      } else {
        order.review_state = "needs_review"
      }
    }, 3500)
  },
}
