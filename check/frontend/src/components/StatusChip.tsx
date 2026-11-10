import type { OrderStatus } from '../types'

// "needs review" isn't a backend status: it's an authorized order whose check didn't come back clean
// "fixed" isn't one either: a voided order whose human accepted the suggested fix, so there is
// a replacement order to point at
export type DisplayStatus = OrderStatus | 'needs_review' | 'fixed'

const LABELS: Record<DisplayStatus, string> = {
  // created means the buyer still has to approve at PayPal before there's a hold
  created: 'Waiting on buyer',
  authorized: 'On hold',
  captured: 'Captured',
  voided: 'Voided',
  failed: 'Failed',
  needs_review: 'Needs review',
  fixed: 'Fixed',
}

// label replaces the stock text, for a held order's "Held: wrong size"
export function StatusChip({ status, label }: { status: DisplayStatus; label?: string }) {
  return (
    <span className={'chip chip--' + status}>
      <span className="chip__dot" aria-hidden="true" />
      {label ?? LABELS[status]}
    </span>
  )
}
