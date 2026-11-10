// Shapes of what the Checkout Anything API returns (backend/app/main.py and shop.py).

export type Mode = "live" | "replay"

export type EventType =
  | "fetch.started"
  | "fetch.done"
  | "extract.started"
  | "extract.done"
  | "item.checking"
  | "item.verified"
  | "item.failed"
  | "item.repairing"
  | "store.ready"
  | "error"

export const EVENT_TYPES: EventType[] = [
  "fetch.started",
  "fetch.done",
  "extract.started",
  "extract.done",
  "item.checking",
  "item.verified",
  "item.failed",
  "item.repairing",
  "store.ready",
  "error",
]

export interface SpecVariant {
  id: string
  label: string
  unit_price: string
}

export interface SpecAddOn {
  id: string
  label: string
  price: string
}

export interface SpecItem {
  id: string
  name: string
  description?: string
  unit_price: string
  available: boolean
  variants: SpecVariant[]
  add_ons: SpecAddOn[]
  source_quote: string
}

export interface StoreSpec {
  spec_version: number
  source_url: string
  merchant: { name: string; currency: string }
  items: SpecItem[]
  shipping: { type: string; amount: string; notes?: string }
  extraction_notes: string[]
}

export interface StoreEvent {
  seq: number
  type: EventType
  store_id: number
  item_id: string | null
  message: string
  data: {
    attempt?: number
    item?: SpecItem
    reason?: string
    page_check_ok?: boolean
    paypal_check_ok?: boolean | null
    paypal_order_id?: string | null
    final?: boolean
    unavailable?: boolean
    [key: string]: unknown
  }
}

export interface Counts {
  verified: number
  failed: number
  unavailable: number
}

export type StoreStatus = "connecting" | "live" | "failed"

export interface Store {
  id: number
  source_url: string
  merchant_name: string
  status: StoreStatus
  mode: Mode
  error: string | null
  counts: Counts
  created_at: string | null
}

export interface VerificationRun {
  item_id: string
  attempt: number
  spec_version: number
  page_check_ok: boolean
  paypal_check_ok: boolean | null
  paypal_order_id: string | null
  ok: boolean
  reason: string | null
  created_at: string | null
}

export interface SpecVersion {
  version: number
  note: string | null
  created_at: string | null
  spec: StoreSpec
}

export interface SpecResponse {
  store: Store
  spec: StoreSpec | null
  extraction_notes: string[]
  versions: SpecVersion[]
  runs: VerificationRun[]
  verified_item_ids: string[]
}

export interface Order {
  id: number
  store_id: number
  store_name: string | null
  item_id: string
  variant_id: string | null
  add_on_ids: string[]
  description: string
  quantity: number
  total: string
  currency: string
  paypal_order_id: string | null
  capture_id: string | null
  status: string
  error: string | null
  created_by: "agent" | "manual"
  created_at: string | null
}

export interface AppConfig {
  default_mode: Mode
  demo_store_urls: string[]
  fixture_urls: string[]
  paypal_configured: boolean
  claude_configured: boolean
  vault_configured: boolean
}

export interface ConnectResponse {
  store_id: number
  mode: Mode
  events_url: string
}

export interface AgentStep {
  tool: string
  input: Record<string, unknown>
  output: Record<string, unknown>
  is_error: boolean
}

export interface AgentReply {
  reply: string
  steps: AgentStep[]
  orders: Order[]
}

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export interface OrderRequest {
  item_id: string
  variant_id?: string | null
  add_on_ids?: string[]
  quantity: number
}

export interface ResetResponse {
  mode: Mode
  stores: { store_id: number; url: string }[]
}

// One row of the catalog grid on the Connect screen.
export type CheckState = "pending" | "running" | "ok" | "fail" | "skipped"
export type RowStatus = "checking" | "repairing" | "verified" | "failed" | "unavailable"

// ---- the merchant's review (backend/app/review.py) ----

// the spec fields the agent can be unsure about
export type FlagField = "name" | "unit_price" | "available"

export interface ReviewFlag {
  field: FlagField
  // why the cell needs a look. never empty
  reasons: string[]
  resolved: boolean
}

export interface ReviewItem {
  item_id: string
  position: number
  category: string | null
  // null when stock isn't tracked
  stock: number | null
  published: boolean
  // why it can't be published right now, or null when it can
  blocked_reason: string | null
  flags: ReviewFlag[]
  checked_at: string | null
}

export interface ReviewColumn {
  field: string
  label: string
  default_label: string
  // where the value goes in the PayPal order, null when it stays on our side
  paypal_field: string | null
}

export interface ReviewResponse {
  store_id: number
  editable: boolean
  categories: string[]
  columns: ReviewColumn[]
  needs_look: number
  items: ReviewItem[]
}

export interface ItemPatch {
  name?: string
  description?: string
  unit_price?: string
  category?: string | null
  stock?: number | null
  published?: boolean
  resolve?: FlagField[]
}

export interface CatalogRow {
  item_id: string
  name: string
  description: string
  category: string | null
  stock: number | null
  published: boolean
  blocked_reason: string | null
  checked_at: string | null
  position: number
  // only the fields that have a flag
  flags: Partial<Record<FlagField, { reasons: string[]; resolved: boolean }>>
  variant_count: number
  add_on_count: number
  unit_price: string
  currency: string
  page_check: CheckState
  paypal_check: CheckState
  repairs: number
  paypal_order_id: string | null
  status: RowStatus
  reason: string | null
  // set when the status last changed, so the row can flash once
  flash: "ok" | "bad" | "new" | null
  flash_at: number
}
