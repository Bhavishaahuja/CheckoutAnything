import type { AgentAnswer, AppConfig, Mode, Order, SpecResponse, Store } from './types'

export const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

// the API answers errors as {"detail": "..."} or {"detail": {"message": "..."}}
async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail.message === 'string') return detail.message
    if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) return detail[0].msg
  } catch {
    // not JSON, fall through
  }
  return 'The API answered ' + response.status
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(API_URL + path, options)
  } catch {
    throw new Error("Can't reach the API at " + API_URL)
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<T>
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getConfig() {
  return request<AppConfig>('/config')
}

export async function getStores() {
  const body = await request<{ stores: Store[] }>('/stores')
  return body.stores
}

export function getSpec(storeId: number) {
  return request<SpecResponse>('/stores/' + storeId + '/spec')
}

export function connectStore(url: string, mode: Mode) {
  return post<{ store_id: number; mode: Mode }>('/stores/connect', { url, mode })
}

export function eventsUrl(storeId: number) {
  return API_URL + '/stores/' + storeId + '/events'
}

export async function getOrders() {
  const body = await request<{ orders: Order[] }>('/orders')
  return body.orders
}

export function resetDemo(mode: Mode) {
  return post<{ mode: Mode; stores: { store_id: number; url: string }[] }>('/demo/reset', { mode })
}

export function agentChat(messages: { role: 'user' | 'assistant'; content: string }[]) {
  return post<AgentAnswer>('/agent/chat', { messages })
}
