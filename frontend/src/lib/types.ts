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
  // the rest is only set on an order that went through Check, and null otherwise
  check_order_id: number | null
  check_mandate_id: number | null
  review_state: ReviewState | null
  check_verdict: "match" | "mismatch" | "unsure" | null
  check_reason: string | null
  // how long the human took to decide, in milliseconds
  decision_ms: number | null
  // what the human tapped on the confirm page
  review_action: "approve" | "reject" | "accept_fix" | null
  // an accepted fix voids the order and Check places the suggested one instead. these are the
  // ids of the two rows in this grid: on the voided order, the new one. on the new one, the old
  replaced_by_order_id: number | null
  replaces_order_id: number | null
}

export type ReviewState = "needs_review" | "auto_approved" | "approved" | "rejected"

export interface ReviewLink {
  url: string
  expires_at: string | null
}

// Disputes come from the Check service as they are (check/docs/api.md).
export interface Dispute {
  id: number
  paypal_dispute_id: string
  order_id: number
  reason: string | null
  status: string | null
  evidence_submitted: boolean
  evidence_submitted_at: string | null
  evidence_type: string | null
  has_summary: boolean
  seller_response_due_at: string | null
  created_at: string | null
}

export interface DisputeEvidence {
  dispute: Dispute
  packet: {
    mandate?: { raw_request?: string; merchant?: string | null; max_price?: string | null } | null
    order?: { store?: string; total?: string; currency?: string; status?: string } | null
    intent_check?: { verdict?: string; risk_score?: number | null; reason?: string } | null
    decision?: { released_by?: string; decision_ms?: number | null; decided_at?: string | null } | null
  }
  summary: string
}

export interface DisputeSync {
  orders_checked: number
  disputes_found: number
  created: number
  updated: number
  errors: { order_id: number; message: string }[]
}

export interface AppConfig {
  default_mode: Mode
  demo_store_urls: string[]
  fixture_urls: string[]
  paypal_configured: boolean
  claude_configured: boolean
  vault_configured: boolean
  // agent orders go through Check (CHECK_URL is set on the API)
  check_configured: boolean
  // the API can read check results and disputes
  check_merchant_configured: boolean
  // the API can make links to the buyer's confirm page
  check_review_links: boolean
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

export interface CatalogRow {
  item_id: string
  name: string
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
