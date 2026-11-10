// Turns the SSE events of one connect run into what the Connect screen draws:
// the step log, the catalog rows, the counters and which stage the pipeline is at.

import { useEffect, useReducer, useRef } from "react"

import { api } from "@/lib/api"
import type {
  CatalogRow,
  Counts,
  SpecItem,
  SpecResponse,
  StoreEvent,
  StoreStatus,
  VerificationRun,
} from "@/lib/types"

export type Stage = "idle" | "fetch" | "extract" | "verify" | "ready" | "error"

export interface RunState {
  storeId: number | null
  status: StoreStatus | "idle"
  stage: Stage
  merchantName: string
  currency: string
  events: StoreEvent[]
  rows: CatalogRow[]
  counts: Counts
  error: string | null
  // the full answer of GET /spec, loaded when the run ends (or for a store from earlier)
  detail: SpecResponse | null
}

export const EMPTY_RUN: RunState = {
  storeId: null,
  status: "idle",
  stage: "idle",
  merchantName: "",
  currency: "USD",
  events: [],
  rows: [],
  counts: { verified: 0, failed: 0, unavailable: 0 },
  error: null,
  detail: null,
}

type Action =
  | { kind: "start"; storeId: number }
  | { kind: "event"; event: StoreEvent }
  | { kind: "detail"; detail: SpecResponse }
  | { kind: "clear" }

function rowFromItem(item: SpecItem, currency: string): CatalogRow {
  return {
    item_id: item.id,
    name: item.name,
    variant_count: item.variants.length,
    add_on_count: item.add_ons.length,
    unit_price: item.unit_price,
    currency,
    page_check: "pending",
    paypal_check: "pending",
    repairs: 0,
    paypal_order_id: null,
    status: "checking",
    reason: null,
    flash: null,
    flash_at: 0,
  }
}

function countRows(rows: CatalogRow[]): Counts {
  const counts = { verified: 0, failed: 0, unavailable: 0 }
  for (const row of rows) {
    if (row.status === "verified") counts.verified += 1
    if (row.status === "failed") counts.failed += 1
    if (row.status === "unavailable") counts.unavailable += 1
  }
  return counts
}

// the rows as the database has them: every item of the latest spec plus its last check
export function rowsFromDetail(detail: SpecResponse, previous: CatalogRow[]): CatalogRow[] {
  if (!detail.spec) return previous
  const currency = detail.spec.merchant.currency
  const lastRun: Record<string, VerificationRun> = {}
  for (const run of detail.runs) {
    const seen = lastRun[run.item_id]
    if (!seen || run.attempt >= seen.attempt) lastRun[run.item_id] = run
  }
  const before: Record<string, CatalogRow> = {}
  for (const row of previous) before[row.item_id] = row

  const rows: CatalogRow[] = []
  for (const item of detail.spec.items) {
    const row = rowFromItem(item, currency)
    const run = lastRun[item.id]
    if (!item.available) {
      row.status = "unavailable"
      row.page_check = "skipped"
      row.paypal_check = "skipped"
      row.reason = "Not for sale on the page"
    } else if (run) {
      row.repairs = run.attempt
      row.page_check = run.page_check_ok ? "ok" : "fail"
      row.paypal_check = run.paypal_check_ok === null ? "skipped" : run.paypal_check_ok ? "ok" : "fail"
      row.paypal_order_id = run.paypal_order_id
      row.status = run.ok ? "verified" : "failed"
      row.reason = run.reason
    } else if (detail.store.status !== "connecting") {
      row.status = "failed"
      row.reason = "Never checked"
    }
    // keep the flash of a row that didn't change, so it doesn't flash twice
    const old = before[item.id]
    if (old && old.status === row.status) {
      row.flash = old.flash
      row.flash_at = old.flash_at
    }
    rows.push(row)
  }
  return rows
}

function applyEvent(state: RunState, event: StoreEvent): RunState {
  if (state.events.length > 0 && event.seq <= state.events[state.events.length - 1].seq) {
    return state // a reconnect replayed something we already have
  }
  const next: RunState = { ...state, events: [...state.events, event] }
  const data = event.data || {}

  if (event.type === "fetch.started" || event.type === "fetch.done") next.stage = "fetch"
  if (event.type === "extract.started") next.stage = "extract"
  if (event.type === "extract.done") {
    next.stage = "verify"
    if (typeof data.merchant_name === "string") next.merchantName = data.merchant_name
  }
  if (event.type === "error") {
    next.stage = "error"
    next.status = "failed"
    next.error = event.message
  }
  if (event.type === "store.ready") {
    next.stage = "ready"
    next.status = state.rows.some((row) => row.status === "verified") ? "live" : "failed"
  }

  if (event.item_id) {
    next.stage = "verify"
    const rows = [...state.rows]
    let index = rows.findIndex((row) => row.item_id === event.item_id)
    if (index === -1) {
      if (!data.item) return next
      rows.push({ ...rowFromItem(data.item, state.currency), flash: "new", flash_at: Date.now() })
      index = rows.length - 1
    }
    const row = { ...rows[index] }
    if (data.item) {
      // a repair can change the name, the price or the variants
      row.name = data.item.name
      row.unit_price = data.item.unit_price
      row.variant_count = data.item.variants.length
      row.add_on_count = data.item.add_ons.length
    }
    if (typeof data.attempt === "number") row.repairs = Math.max(row.repairs, data.attempt)

    if (event.type === "item.checking") {
      row.status = "checking"
      row.page_check = "running"
      row.paypal_check = "running"
      row.reason = null
    }
    if (event.type === "item.verified") {
      row.status = "verified"
      row.page_check = "ok"
      row.paypal_check = "ok"
      row.paypal_order_id = data.paypal_order_id || null
      row.reason = null
      row.flash = "ok"
      row.flash_at = Date.now()
    }
    if (event.type === "item.failed") {
      row.page_check = data.page_check_ok === false ? "fail" : data.page_check_ok ? "ok" : row.page_check
      if (data.paypal_check_ok === true) row.paypal_check = "ok"
      else if (data.paypal_check_ok === false) row.paypal_check = "fail"
      else row.paypal_check = "skipped"
      if (row.page_check === "running") row.page_check = "fail"
      row.reason = data.reason || event.message
      if (data.paypal_order_id) row.paypal_order_id = data.paypal_order_id
      if (data.final) {
        row.status = data.unavailable ? "unavailable" : "failed"
        row.flash = "bad"
        row.flash_at = Date.now()
      }
    }
    if (event.type === "item.repairing") {
      row.status = "repairing"
    }
    rows[index] = row
    next.rows = rows
    next.counts = countRows(rows)
  }
  return next
}

function reducer(state: RunState, action: Action): RunState {
  if (action.kind === "clear") return EMPTY_RUN
  if (action.kind === "start") return { ...EMPTY_RUN, storeId: action.storeId, status: "connecting" }
  if (action.kind === "event") {
    if (action.event.store_id !== state.storeId) return state
    return applyEvent(state, action.event)
  }
  // detail
  const detail = action.detail
  if (detail.store.id !== state.storeId) return state
  const rows = rowsFromDetail(detail, state.rows)
  const finished = detail.store.status !== "connecting"
  return {
    ...state,
    detail,
    rows,
    counts: finished ? detail.store.counts : countRows(rows),
    merchantName: detail.store.merchant_name || detail.spec?.merchant.name || state.merchantName,
    currency: detail.spec?.merchant.currency || state.currency,
    status: detail.store.status,
    stage: detail.store.status === "live" ? "ready" : finished && state.stage !== "ready" ? "error" : state.stage,
    error: detail.store.error || state.error,
  }
}

// Follows one store: opens its event stream (the server replays the history first), and
// loads GET /spec when the run ends or when the live log is gone.
export function useRun(storeId: number | null, onFinished?: () => void): RunState {
  const [state, dispatch] = useReducer(reducer, EMPTY_RUN)
  const finishedRef = useRef(onFinished)
  useEffect(() => {
    finishedRef.current = onFinished
  }, [onFinished])

  useEffect(() => {
    if (storeId === null) {
      dispatch({ kind: "clear" })
      return
    }
    let cancelled = false
    dispatch({ kind: "start", storeId })

    const loadDetail = () => {
      api
        .getSpec(storeId)
        .then((detail) => {
          if (!cancelled) dispatch({ kind: "detail", detail })
        })
        .catch(() => {})
        .finally(() => {
          if (!cancelled) finishedRef.current?.()
        })
    }

    const subscription = api.subscribe(
      storeId,
      (event) => {
        if (cancelled) return
        dispatch({ kind: "event", event })
        if (event.type === "store.ready" || event.type === "error") loadDetail()
      },
      loadDetail
    )
    return () => {
      cancelled = true
      subscription.close()
    }
  }, [storeId])

  return state
}
