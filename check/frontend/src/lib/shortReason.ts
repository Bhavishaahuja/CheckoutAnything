// Check's short reason for holding an order, two or three words for the status chip:
// 'Held: wrong size'. It comes from the field names Check flagged (mismatched_fields), not
// from its one-line reason, which is a full sentence and has its own column.
//
// The Checkout Anything app has the same file (frontend/src/lib/shortReason.ts at the repo root). Keep the two
// the same, so an order reads the same in both grids.

const FIELD_REASONS: Record<string, string> = {
  size: 'wrong size',
  color: 'wrong color',
  model: 'wrong model',
  event_date: 'wrong date',
  date: 'wrong date',
  quantity: 'wrong quantity',
  item: 'wrong item',
  name: 'wrong item',
  category: 'wrong item',
  substitution: 'substituted item',
  extra_item: 'extra item',
  price: 'over budget',
  unit_price: 'over budget',
  total: 'over budget',
  max_price: 'over budget',
  shipping: 'shipping cost',
  merchant: 'wrong store',
  store: 'wrong store',
  currency: 'wrong currency',
  expiry: 'request expired',
  expires_at: 'request expired',
  instructions_in_order: 'suspicious text',
}

export function shortReason(fields: string[] | null | undefined, verdict: string | null | undefined): string {
  for (const field of fields || []) {
    const reason = FIELD_REASONS[field]
    // the first one Check named is the one it led with
    if (reason) {
      return reason
    }
  }
  if (verdict === 'unsure') {
    return 'not sure'
  }
  return 'needs a look'
}

export function heldLabel(fields: string[] | null | undefined, verdict: string | null | undefined): string {
  return 'Held: ' + shortReason(fields, verdict)
}
