// Turns the SSE events of one connect run into what the Connect screen draws:
// the step log, the catalog rows, the counters and which stage the pipeline is at.

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react"

import { api } from "@/lib/api"
import type {
  CatalogRow,
  Counts,
  ReviewResponse,
  SpecItem,
  SpecResponse,
  StoreEvent,
  StoreSpec,
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
  // the merchant's review (flags, publish state, order, column names), loaded with detail
  review: ReviewResponse | null
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
  review: null,
}

type Action =
  | { kind: "start"; storeId: number }
  | { kind: "event"; event: StoreEvent }
  | { kind: "detail"; detail: SpecResponse; review: ReviewResponse | null }
  | { kind: "clear" }

function rowFromItem(item: SpecItem, currency: string): CatalogRow {
  return {
    item_id: item.id,
    name: item.name,
    description: item.description || "",
    category: null,
    stock: null,
    published: false,
    blocked_reason: null,
    checked_at: null,
    position: 0,
    flags: {},
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

// puts the merchant's side on the rows and sorts them the way the merchant ordered them
export function withReview(rows: CatalogRow[], review: ReviewResponse | null): CatalogRow[] {
  if (!review) return rows
  const byId = new Map(review.items.map((entry) => [entry.item_id, entry]))
  const merged = rows.map((row, index) => {
    const entry = byId.get(row.item_id)
    if (!entry) return { ...row, position: index }
    const flags: CatalogRow["flags"] = {}
    for (const flag of entry.flags) flags[flag.field] = { reasons: flag.reasons, resolved: flag.resolved }
    return {
      ...row,
      position: entry.position,
      category: entry.category,
      stock: entry.stock,
      published: entry.published,
      blocked_reason: entry.blocked_reason,
      checked_at: entry.checked_at,
      flags,
    }
  })
  merged.sort((a, b) => a.position - b.position)
  return merged
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
      // an ok run without the page check is a value the merchant set by hand
      row.page_check = run.page_check_ok ? "ok" : run.ok ? "skipped" : "fail"
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
    // the API sends the whole spec here, so the store's name shows before any item is checked
    const spec = data.spec as StoreSpec | undefined
    if (spec?.merchant) {
      next.merchantName = spec.merchant.name
      next.currency = spec.merchant.currency
    }
  }
  if (event.type === "error") {
    next.stage = "error"
    next.status = "failed"
    next.error = event.message
  }
  if (event.type === "store.ready") {
    next.stage = "ready"
    if (data.status === "live" || data.status === "failed") next.status = data.status
    else next.status = state.rows.some((row) => row.status === "verified") ? "live" : "failed"
  }

  if (event.item_id) {
    next.stage = "verify"
    const rows = [...state.rows]
    let index = rows.findIndex((row) => row.item_id === event.item_id)
    if (index === -1) {
      if (!data.item) return next
      rows.push({ ...rowFromItem(data.item, next.currency), flash: "new", flash_at: Date.now() })
      index = rows.length - 1
    }
    const row = { ...rows[index] }
    if (data.item) {
      // a repair can change the name, the price or the variants
      row.name = data.item.name
      row.description = data.item.description || ""
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
  const review = action.review || state.review
  const rows = withReview(rowsFromDetail(detail, state.rows), review)
  const finished = detail.store.status !== "connecting"
  return {
    ...state,
    detail,
    review,
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
export function useRun(storeId: number | null, onFinished?: () => void): RunState & { reload: () => Promise<void> } {
  const [state, dispatch] = useReducer(reducer, EMPTY_RUN)
  const reloadRef = useRef<() => Promise<void>>(() => Promise.resolve())
  const reload = useCallback(() => reloadRef.current(), [])
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

    // the spec with its runs, and the merchant's review of it. the review only exists once
    // there is a spec, so a store that failed before that has none
    const load = async () => {
      const [detail, review] = await Promise.all([
        api.getSpec(storeId),
        api.getReview(storeId).catch(() => null),
      ])
      if (!cancelled) dispatch({ kind: "detail", detail, review })
    }
    reloadRef.current = load
    const loadDetail = () => {
      load()
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

  return useMemo(() => ({ ...state, reload }), [state, reload])
}
