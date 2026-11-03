// Fake data for USE_MOCKS mode, shaped exactly like the real API responses.
// The mix covers every state the UI has to handle: clean auto-captures, orders
// waiting on the human, a rejected order, and one still waiting for its check.

import type { Approval, Decision, MandateSummary, OrderDetail, OrderItem, OrderStatus } from './types'

// timestamps are relative to page load so the demo always looks recent
function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString()
}

function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString()
}

function mandate(
  id: number,
  buyerLabel: string,
  rawRequest: string,
  maxPrice: string | null,
  rules: Record<string, unknown>,
  createdMinutesAgo: number,
): MandateSummary {
  return {
    id,
    buyer_label: buyerLabel,
    raw_request: rawRequest,
    rules,
    max_price: maxPrice,
    merchant: 'Fernwood Supply Co',
    expires_at: null,
    created_at: minutesAgo(createdMinutesAgo),
  }
}

function decision(
  id: number,
  verdict: Decision['verdict'],
  riskScore: number,
  reason: string,
  checkedBy: Decision['checked_by'],
  createdMinutesAgo: number,
): Decision {
  return {
    id,
    verdict,
    risk_score: riskScore,
    reason,
    checked_by: checkedBy,
    created_at: minutesAgo(createdMinutesAgo),
  }
}

interface MockOrderInput {
  id: number
  mandate: MandateSummary
  items: OrderItem[]
  total: string
  status: OrderStatus
  createdMinutesAgo: number
  decisions: Decision[]
  approvalAction?: 'approve' | 'reject'
  decisionMs?: number
}

function order(input: MockOrderInput): OrderDetail {
  const createdAt = minutesAgo(input.createdMinutesAgo)
  const isHeldOrDone = input.status !== 'created' && input.status !== 'failed'

  const approvals: Approval[] = []
  if (input.approvalAction) {
    approvals.push({
      id: input.id * 10,
      action: input.approvalAction,
      decided_by: input.mandate.buyer_label,
      opened_at: minutesAgo(input.createdMinutesAgo - 2),
      decided_at: minutesAgo(input.createdMinutesAgo - 3),
      decision_ms: input.decisionMs ?? null,
    })
  }

  return {
    id: input.id,
    mandate_id: input.mandate.id,
    paypal_order_id: 'MOCK' + String(input.id).padStart(13, '0'),
    authorization_id: isHeldOrDone ? 'MOCKAUTH' + input.id : null,
    capture_id: input.status === 'captured' ? 'MOCKCAP' + input.id : null,
    vault_id: 'MOCKVAULT',
    items: input.items,
    total: input.total,
    currency: 'USD',
    status: input.status,
    authorization_expires_at: input.status === 'authorized' ? daysFromNow(29) : null,
    created_at: createdAt,
    mandate: input.mandate,
    decisions: input.decisions,
    approvals,
  }
}

const shoesForMaya = mandate(
  1,
  'Maya R.',
  "Trail running shoes for my sister, women's size 8, under $120. Any color but pink.",
  '120.00',
  { category: 'footwear', size: "women's 8", excluded_colors: ['pink'] },
  240,
)

const cabinBlanket = mandate(
  2,
  'Jordan T.',
  'A warm blanket for the cabin, nothing synthetic, up to $90.',
  '90.00',
  { category: 'bedding', materials_excluded: ['synthetic'] },
  200,
)

const campMugs = mandate(
  3,
  'Priya S.',
  'Four enamel camp mugs, under $15 each.',
  '60.00',
  { category: 'kitchen', quantity: 4, max_unit_price: '15.00' },
  180,
)

const fieldTote = mandate(
  4,
  'Sam K.',
  'A canvas tote for the farmers market, under $60.',
  '60.00',
  { category: 'bags', material: 'canvas' },
  150,
)

const headlamp = mandate(
  5,
  'Alex M.',
  'A rechargeable headlamp for night hikes, up to $45.',
  '45.00',
  { category: 'lighting', power: 'rechargeable' },
  60,
)

export const mockOrders: OrderDetail[] = [
  order({
    id: 101,
    mandate: shoesForMaya,
    items: [{ name: 'Ridgeline trail runner', color: 'slate', size: "women's 8", quantity: 1, unit_price: '109.00' }],
    total: '109.00',
    status: 'captured',
    createdMinutesAgo: 230,
    decisions: [decision(1, 'match', 6, 'Size, color and price all match the mandate.', 'rules', 229)],
  }),
  order({
    id: 102,
    mandate: shoesForMaya,
    items: [{ name: 'Ridgeline trail runner', color: 'slate', size: "women's 9", quantity: 1, unit_price: '109.00' }],
    total: '109.00',
    status: 'authorized',
    createdMinutesAgo: 42,
    decisions: [decision(2, 'mismatch', 74, "Size 9 ordered, the mandate says women's size 8.", 'rules', 41)],
  }),
  order({
    id: 103,
    mandate: cabinBlanket,
    items: [{ name: 'Hearthside camp blanket', color: 'charcoal', size: null, quantity: 1, unit_price: '88.00' }],
    total: '88.00',
    status: 'authorized',
    createdMinutesAgo: 18,
    decisions: [
      decision(3, 'unsure', 48, 'Listed as an 80% wool blend, the mandate asked for nothing synthetic.', 'claude', 17),
    ],
  }),
  order({
    id: 104,
    mandate: campMugs,
    items: [{ name: 'Enamel camp mug', color: 'speckled blue', size: null, quantity: 4, unit_price: '12.00' }],
    total: '48.00',
    status: 'captured',
    createdMinutesAgo: 170,
    decisions: [decision(4, 'match', 4, 'Four mugs at $12 each, inside the per-mug limit.', 'rules', 169)],
  }),
  order({
    id: 105,
    mandate: fieldTote,
    items: [{ name: 'Waxed canvas field tote', color: 'olive', size: null, quantity: 1, unit_price: '74.50' }],
    total: '74.50',
    status: 'voided',
    createdMinutesAgo: 140,
    decisions: [decision(5, 'mismatch', 81, '$74.50 is over the $60 cap.', 'rules', 139)],
    approvalAction: 'reject',
    decisionMs: 6400,
  }),
  order({
    id: 106,
    mandate: headlamp,
    items: [{ name: 'Lumen 300 headlamp', color: 'black', size: null, quantity: 1, unit_price: '39.00' }],
    total: '39.00',
    status: 'authorized',
    createdMinutesAgo: 2,
    // the mandate check hasn't run yet
    decisions: [],
  }),
]
