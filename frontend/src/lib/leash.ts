// Talks to the Leash API (leash/docs/api.md): the orders an agent placed, held at PayPal until
// they match what the shopper asked for. The dashboard logs in with the demo password and keeps
// the session token in sessionStorage, never the password. With VITE_USE_MOCK=true the calls
// are answered by lib/leashMock.ts.

import { USE_MOCK } from "@/lib/api"
import { leashMock } from "@/lib/leashMock"

export const LEASH_URL = (import.meta.env.VITE_LEASH_API_URL || "http://127.0.0.1:8001").replace(/\/$/, "")

export interface LeashItem {
  name: string
  color: string | null
  size: string | null
  model?: string | null
  event_date?: string | null
  quantity: number
  unit_price: string
}

export interface LeashMandate {
  id: number
  buyer_label: string | null
  raw_request: string
  rules: { item?: string | null; color?: string | null; size?: string | null; quantity?: number | null; currency?: string | null; [key: string]: unknown }
  max_price: string | null
  max_price_inclusive: boolean
  merchant: string | null
}

export interface LeashIntentCheck {
  verdict: "match" | "mismatch" | "unsure"
  risk_score: number | null
  reason: string
  mismatched_fields: string[] | null
  checked_by: string
}

export interface LeashApproval {
  action: "approve" | "reject" | "accept_fix" | null
  opened_at: string | null
  decided_at: string | null
  // opened to tap, on the server's clock. 0 means the page never said it opened
  decision_ms: number | null
}

export interface LeashOrder {
  id: number
  paypal_order_id: string | null
  merchant: string | null
  agent_name: string | null
  items: LeashItem[]
  total: string
  shipping_amount: string | null
  currency: string
  status: "created" | "authorized" | "captured" | "voided" | "failed"
  review_state: "needs_review" | "auto_approved" | "approved" | "rejected" | null
  watch_mode: "normal" | "sharp"
  created_at: string
  mandate: LeashMandate | null
  intent_check: LeashIntentCheck | null
  approval: LeashApproval | null
}

export interface LeashStats {
  fast_streak: number
  rubber_stamp_active: boolean
  fast_threshold_ms: number
}

export interface LeashDispute {
  id: number
  order_id: number
  status: string
}

export class LeashError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const SESSION_KEY = "leash.session"

function readSession(): string | null {
  try {
    return window.sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function writeSession(token: string | null) {
  try {
    if (token) window.sessionStorage.setItem(SESSION_KEY, token)
    else window.sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // no storage: the session lasts until the page is closed
  }
}

let session = readSession()

async function call<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = {}
  if (init.body) headers["Content-Type"] = "application/json"
  if (auth && session) headers["Authorization"] = "Bearer " + session
  let response: Response
  try {
    response = await fetch(LEASH_URL + path, { ...init, headers })
  } catch {
    throw new LeashError("Can't reach the Leash API at " + LEASH_URL, 0)
  }
  if (response.status === 401 && auth) {
    session = null
    writeSession(null)
  }
  if (!response.ok) {
    let message = response.statusText || "Request failed"
    try {
      const detail = (await response.json()).detail
      if (typeof detail === "string") message = detail
      else if (detail && typeof detail.message === "string") message = detail.message
    } catch {
      // not JSON
    }
    throw new LeashError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface LeashApi {
  signedIn(): boolean
  login(password: string): Promise<void>
  listOrders(): Promise<LeashOrder[]>
  stats(): Promise<LeashStats>
  listDisputes(): Promise<LeashDispute[]>
  // makes a review link for an order and starts its attention clock. returns the token
  openReview(orderId: number): Promise<string>
  decide(token: string, action: "approve" | "reject", clientMs: number): Promise<void>
  // places one of Leash's fixed demo orders. resolves when it has been checked
  demoOrder(): Promise<void>
}

const DEMO_SCENARIOS = ["wrong_color", "clean", "wrong_size", "over_cap", "clean"]
let demoCount = 0

const realLeash: LeashApi = {
  signedIn: () => session !== null,

  async login(password) {
    const answer = await call<{ session_token: string }>("/auth/session", { method: "POST", body: JSON.stringify({ password }) }, false)
    session = answer.session_token
    writeSession(session)
  },

  listOrders: () => call<LeashOrder[]>("/orders?limit=200"),
  stats: () => call<LeashStats>("/stats"),
  listDisputes: () => call<LeashDispute[]>("/disputes?limit=200"),

  async openReview(orderId) {
    const link = await call<{ review_token: string }>("/orders/" + orderId + "/review-link", { method: "POST" })
    // the clock starts here: the order is on screen with its buttons
    await call<void>("/review/" + link.review_token + "/opened", { method: "POST" }, false).catch(() => {})
    return link.review_token
  },

  async decide(token, action, clientMs) {
    await call<unknown>("/review/" + token + "/" + action, { method: "POST", body: JSON.stringify({ decision_ms: clientMs }) }, false)
  },

  async demoOrder() {
    const mandates = await call<{ id: number }[]>("/mandates?limit=50")
    if (mandates.length === 0) {
      throw new LeashError("Leash has no mandates yet. Seed the demo first: python backend/scripts/seed_demo.py (in leash/)", 409)
    }
    const scenario = DEMO_SCENARIOS[demoCount % DEMO_SCENARIOS.length]
    demoCount += 1
    await call<unknown>("/demo/orders", { method: "POST", body: JSON.stringify({ mandate_id: mandates[0].id, scenario }) })
  },
}

export const leash: LeashApi = USE_MOCK ? leashMock : realLeash
