// Talks to the Checkout Anything API. With VITE_USE_MOCK=true every call is answered by
// lib/mock.ts instead, so the UI can be worked on with no backend running.

import { mockApi } from "@/lib/mock"
import {
  EVENT_TYPES,
  type AgentReply,
  type AppConfig,
  type ChatMessage,
  type ConnectResponse,
  type Dispute,
  type DisputeEvidence,
  type DisputeSync,
  type Mode,
  type Order,
  type OrderRequest,
  type ResetResponse,
  type ReviewLink,
  type SpecResponse,
  type Store,
  type StoreEvent,
} from "@/lib/types"

export const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "")
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true"

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object") {
    const maybe = detail as { message?: unknown }
    if (typeof maybe.message === "string") return maybe.message
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  }
  return "Something went wrong"
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(API_URL + path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    })
  } catch {
    throw new ApiError("Can't reach the API at " + API_URL, 0)
  }
  if (!response.ok) {
    let message = response.statusText || "Request failed"
    try {
      const body = await response.json()
      message = detailToText(body.detail)
    } catch {
      // not JSON, keep the status text
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export interface EventSubscription {
  close: () => void
}

export interface Api {
  getConfig(): Promise<AppConfig>
  listStores(): Promise<Store[]>
  connectStore(url: string, mode: Mode): Promise<ConnectResponse>
  // onLost fires when the stream can't be opened or drops before a final event
  subscribe(storeId: number, onEvent: (event: StoreEvent) => void, onLost: () => void): EventSubscription
  getSpec(storeId: number): Promise<SpecResponse>
  createOrder(storeId: number, body: OrderRequest): Promise<Order>
  listOrders(): Promise<Order[]>
  agentChat(messages: ChatMessage[]): Promise<AgentReply>
  resetDemo(mode: Mode): Promise<ResetResponse>
  // Check and Defend. every call to reviewLink makes a new link and kills the one before
  reviewLink(orderId: number): Promise<ReviewLink>
  listDisputes(): Promise<Dispute[]>
  syncDisputes(): Promise<DisputeSync>
  disputeEvidence(disputeId: number): Promise<DisputeEvidence>
  redraftDispute(disputeId: number): Promise<DisputeEvidence>
  submitDisputeEvidence(disputeId: number): Promise<Dispute>
}

const realApi: Api = {
  getConfig: () => request<AppConfig>("/config"),

  listStores: async () => (await request<{ stores: Store[] }>("/stores")).stores,

  connectStore: (url, mode) =>
    request<ConnectResponse>("/stores/connect", {
      method: "POST",
      body: JSON.stringify({ url, mode }),
    }),

  subscribe(storeId, onEvent, onLost) {
    const source = new EventSource(API_URL + "/stores/" + storeId + "/events")
    let finished = false

    const handle = (raw: Event) => {
      const event = JSON.parse((raw as MessageEvent).data) as StoreEvent
      onEvent(event)
      if (event.type === "store.ready" || event.type === "error") {
        // the server closes the stream after these, don't let the browser reconnect
        finished = true
        source.close()
      }
    }
    for (const type of EVENT_TYPES) {
      if (type !== "error") source.addEventListener(type, handle)
    }
    // "error" is both one of our event names and the browser's own connection error event.
    // ours is a MessageEvent with data, the browser's is a bare Event
    source.addEventListener("error", (raw) => {
      if (raw instanceof MessageEvent && typeof raw.data === "string") {
        handle(raw)
        return
      }
      if (finished) return
      // a 410 (the log is gone) closes for good. a dropped connection retries by itself
      if (source.readyState === EventSource.CLOSED) {
        finished = true
        onLost()
      }
    })
    return {
      close: () => {
        finished = true
        source.close()
      },
    }
  },

  getSpec: (storeId) => request<SpecResponse>("/stores/" + storeId + "/spec"),

  createOrder: (storeId, body) =>
    request<Order>("/stores/" + storeId + "/orders", { method: "POST", body: JSON.stringify(body) }),

  listOrders: async () => (await request<{ orders: Order[] }>("/orders")).orders,

  agentChat: (messages) =>
    request<AgentReply>("/agent/chat", { method: "POST", body: JSON.stringify({ messages }) }),

  resetDemo: (mode) =>
    request<ResetResponse>("/demo/reset", { method: "POST", body: JSON.stringify({ mode }) }),

  reviewLink: (orderId) => request<ReviewLink>("/orders/" + orderId + "/review-link", { method: "POST" }),

  listDisputes: async () => (await request<{ disputes: Dispute[] }>("/disputes")).disputes,

  syncDisputes: () => request<DisputeSync>("/disputes/sync", { method: "POST" }),

  disputeEvidence: (disputeId) => request<DisputeEvidence>("/disputes/" + disputeId + "/evidence"),

  redraftDispute: (disputeId) =>
    request<DisputeEvidence>("/disputes/" + disputeId + "/redraft", { method: "POST" }),

  submitDisputeEvidence: (disputeId) =>
    request<Dispute>("/disputes/" + disputeId + "/submit-evidence", { method: "POST" }),
}

export const api: Api = USE_MOCK ? mockApi : realApi
