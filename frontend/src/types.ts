// Shapes of what the API sends. Keep in step with backend/app.

export type Mode = 'live' | 'replay'

export interface Variant {
  id: string
  label: string
  unit_price: string
}

export interface AddOn {
  id: string
  label: string
  price: string
}

export interface SpecItem {
  id: string
  name: string
  description: string
  unit_price: string
  available: boolean
  variants: Variant[]
  add_ons: AddOn[]
  source_quote: string
}

export interface StoreSpec {
  spec_version: number
  source_url: string
  merchant: { name: string; currency: string }
  items: SpecItem[]
  shipping: { type: 'flat' | 'none'; amount: string; notes: string }
  extraction_notes: string[]
}

export interface Counts {
  verified: number
  failed: number
  unavailable: number
}

export interface Store {
  id: number
  source_url: string
  merchant_name: string
  status: 'connecting' | 'live' | 'failed'
  mode: Mode
  error: string | null
  counts: Counts
  created_at: string | null
}

export interface Run {
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
  note: string
  created_at: string | null
  spec: StoreSpec
}

export interface SpecResponse {
  store: Store
  spec: StoreSpec | null
  extraction_notes: string[]
  versions: SpecVersion[]
  runs: Run[]
  verified_item_ids: string[]
}

export interface RunEvent {
  seq: number
  type: string
  store_id: number
  item_id: string | null
  message: string
  // loose on purpose, each event type carries its own fields
  data: Record<string, any>
}

export interface Order {
  id: number
  store_id: number
  store_name: string | null
  item_id: string
  description: string
  quantity: number
  total: string
  currency: string
  paypal_order_id: string | null
  capture_id: string | null
  status: 'captured' | 'failed'
  error: string | null
  created_by: 'agent' | 'manual'
  created_at: string | null
}

export interface AgentStep {
  tool: string
  input: Record<string, unknown>
  output: Record<string, any>
  is_error: boolean
}

export interface AgentAnswer {
  reply: string
  steps: AgentStep[]
  orders: Order[]
}

export interface AppConfig {
  default_mode: Mode
  demo_store_urls: string[]
  fixture_urls: string[]
  paypal_configured: boolean
  claude_configured: boolean
  vault_configured: boolean
}

export type CheckState = 'pending' | 'ok' | 'fail' | 'skipped'
export type RowStatus = 'queued' | 'checking' | 'repairing' | 'verified' | 'failed' | 'unavailable'

// one row of the catalog grid
export interface CatalogRow {
  id: string
  name: string
  price: string
  currency: string
  variantCount: number
  addOnCount: number
  pageCheck: CheckState
  paypalCheck: CheckState
  repairs: number
  paypalOrderId: string | null
  status: RowStatus
  reason: string | null
  // set for a moment after a row verifies or fails, so it flashes
  flash: 'ok' | 'fail' | null
}
