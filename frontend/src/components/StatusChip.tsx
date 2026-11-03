import type { OrderStatus } from '../types'

// "needs review" isn't a backend status: it's an authorized order whose check didn't come back clean
export type DisplayStatus = OrderStatus | 'needs_review'

const LABELS: Record<DisplayStatus, string> = {
  created: 'Created',
  authorized: 'Authorized',
  captured: 'Captured',
  voided: 'Voided',
  failed: 'Failed',
  needs_review: 'Needs review',
}

export function StatusChip({ status }: { status: DisplayStatus }) {
  return (
    <span className={'chip chip--' + status}>
      <span className="chip__dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  )
}
