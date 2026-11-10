// Turning specs, runs and live events into catalog grid rows.

import type { CatalogRow, Run, SpecItem, StoreSpec } from './types'

export function rowFromItem(item: SpecItem, currency: string): CatalogRow {
  return {
    id: item.id,
    name: item.name,
    price: item.unit_price,
    currency,
    variantCount: item.variants.length,
    addOnCount: item.add_ons.length,
    pageCheck: item.available ? 'pending' : 'skipped',
    paypalCheck: item.available ? 'pending' : 'skipped',
    repairs: 0,
    paypalOrderId: null,
    status: item.available ? 'queued' : 'unavailable',
    reason: item.available ? null : 'The page says this is not available',
    flash: null,
  }
}

// rows for a store that already finished connecting, from what the database kept
export function rowsFromSpec(spec: StoreSpec, runs: Run[]): CatalogRow[] {
  const rows: CatalogRow[] = []
  for (const item of spec.items) {
    const row = rowFromItem(item, spec.merchant.currency)
    let last: Run | null = null
    for (const run of runs) {
      if (run.item_id === item.id) last = run
    }
    if (item.available && last) {
      row.repairs = last.attempt
      row.pageCheck = last.page_check_ok ? 'ok' : 'fail'
      if (last.paypal_check_ok === null) row.paypalCheck = 'skipped'
      else row.paypalCheck = last.paypal_check_ok ? 'ok' : 'fail'
      row.paypalOrderId = last.paypal_order_id
      row.status = last.ok ? 'verified' : 'failed'
      row.reason = last.reason
    }
    rows.push(row)
  }
  return rows
}
