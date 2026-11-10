// Screen 4: every purchase made through connected stores, live. The grid is components/OrdersGrid.tsx,
// this page loads the orders, shows the totals and owns the review drawer.

import { AnimatePresence } from "motion/react"
import { useCallback, useEffect, useRef, useState } from "react"

import { Card, ErrorNote } from "@/components/bits"
import { NumberTicker } from "@/components/magicui/number-ticker"
import { OrdersGrid, type OrderRow } from "@/components/OrdersGrid"
import { ReviewDrawer } from "@/components/ReviewDrawer"
import { api } from "@/lib/api"

const POLL_MS = 3000

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card className="px-4 py-3.5">
      <div className="text-2xl font-semibold tabular-nums">{children}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </Card>
  )
}

function Ticker({ value, decimals = 0 }: { value: number; decimals?: number }) {
  if (value === 0) return <span>{decimals ? "0.00" : "0"}</span>
  return <NumberTicker value={value} decimalPlaces={decimals} />
}

export function OrdersPage({
  active,
  refreshKey,
  checkOn,
  reviewLinks,
  onGoToAgent,
}: {
  active: boolean
  refreshKey: number
  // agent orders go through Check, so the grid shows what it decided
  checkOn: boolean
  reviewLinks: boolean
  onGoToAgent: () => void
}) {
  // the order whose review drawer is open
  const [reviewId, setReviewId] = useState<number | null>(null)
  // bumped to load right away instead of waiting for the next poll
  const [nudge, setNudge] = useState(0)
  const [rows, setRows] = useState<OrderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const firstLoad = useRef(true)

  useEffect(() => {
    if (!active) return
    let cancelled = false

    const load = async () => {
      if (document.hidden) return
      try {
        const orders = await api.listOrders()
        if (cancelled) return
        setError(null)
        setLoaded(true)
        setRows((previous) => {
          const before = new Map(previous.map((row) => [row.id, row]))
          let changed = orders.length !== previous.length
          const next = orders.map((order) => {
            const old = before.get(order.id)
            if (
              old &&
              old.status === order.status &&
              old.capture_id === order.capture_id &&
              old.review_state === order.review_state &&
              old.check_verdict === order.check_verdict &&
              old.decision_ms === order.decision_ms &&
              old.review_action === order.review_action &&
              old.check_mismatched_fields.join() === order.check_mismatched_fields.join() &&
              old.replaced_by_order_id === order.replaced_by_order_id
            )
              return old
            changed = true
            // orders already there on first load don't flash, new ones do
            return { ...order, seen_at: firstLoad.current ? 0 : Date.now() }
          })
          firstLoad.current = false
          return changed ? next : previous
        })
      } catch (problem) {
        if (!cancelled) {
          setError(problem instanceof Error ? problem.message : "Couldn't load orders")
          setLoaded(true)
        }
      }
    }

    void load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [active, refreshKey, nudge])

  const openReview = useCallback((orderId: number) => setReviewId(orderId), [])
  const closeReview = useCallback(() => setReviewId(null), [])
  // the confirm page in the drawer finished a decision: read the row again now
  const reviewDecided = useCallback(() => setNudge((count) => count + 1), [])

  const reviewOrder = reviewId === null ? null : rows.find((row) => row.id === reviewId) || null

  let captured = 0
  let volume = 0
  let byAgent = 0
  let waiting = 0
  const storeIds = new Set<number>()
  for (const row of rows) {
    storeIds.add(row.store_id)
    if (row.created_by === "agent") byAgent += 1
    if (row.review_state === "needs_review") waiting += 1
    if (row.status === "captured") {
      captured += 1
      volume += Number(row.total)
    }
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every purchase from a connected store. Prices are computed by the API from the verified spec, then paid with
          the saved sandbox buyer and captured.
          {checkOn &&
            " An agent's order is held first and checked against what the buyer asked for: a clean match is captured, anything off waits for the buyer."}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="orders">
          <Ticker value={rows.length} />
        </Tile>
        <Tile label="captured">
          <span className="text-ok">
            <Ticker value={captured} />
          </span>
        </Tile>
        <Tile label="captured volume (sandbox USD)">
          $<Ticker value={volume} decimals={2} />
        </Tile>
        <Tile label={"bought by an agent, across " + storeIds.size + (storeIds.size === 1 ? " store" : " stores")}>
          <Ticker value={byAgent} />
        </Tile>
      </div>

      {checkOn && waiting > 0 && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          {waiting === 1 ? "1 order is" : waiting + " orders are"} on hold, waiting for the buyer to confirm. Nothing
          has been charged for {waiting === 1 ? "it" : "them"}.
        </p>
      )}

      {error && <ErrorNote>{error}</ErrorNote>}

      <Card className="h-[640px] overflow-hidden">
        <OrdersGrid rows={rows} loaded={loaded} checkOn={checkOn} reviewLinks={reviewLinks} onOpenReview={openReview} onGoToAgent={onGoToAgent} />
      </Card>

      <AnimatePresence>
        {reviewOrder && (
          <ReviewDrawer key={reviewOrder.id} order={reviewOrder} onClose={closeReview} onDecided={reviewDecided} />
        )}
      </AnimatePresence>
    </div>
  )
}
