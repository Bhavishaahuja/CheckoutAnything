// Turns the two backend state fields (status: where's the money, review_state: who decided)
// into what the dashboard shows. See the combinations table in docs/api.md.

import type { DisplayStatus } from '../components/StatusChip'
import type { Order } from '../types'
import { heldLabel } from './shortReason'

// approvals faster than this look like a rubber stamp, not a real look at the order
export const RUBBER_STAMP_MS = 2000

// who an approval says decided it when Reset demo's seed made the call (SEED_DECIDER in
// backend/app/rubber_stamp.py). not a person, so never timed and never part of the watch
export const SEED_DECIDER = 'demo seed'

export function displayStatus(order: Order): DisplayStatus {
  if (order.status === 'authorized' && order.review_state === 'needs_review') {
    return 'needs_review'
  }
  if (wasFixed(order)) {
    return 'fixed'
  }
  return order.status
}

// what the status chip says. an order held for a human says why in two or three words, from the
// fields the check flagged: "Held: wrong size". undefined means the chip's own stock label
export function statusLabel(order: Order): string | undefined {
  if (displayStatus(order) !== 'needs_review') {
    return undefined
  }
  return heldLabel(order.intent_check?.mismatched_fields, order.intent_check?.verdict)
}

// the human took the suggested fix: this order was voided and a new one placed instead
export function wasFixed(order: Order): boolean {
  return order.status === 'voided' && order.replaced_by_order_id !== null
}

export type DecisionKind = 'auto' | 'approved' | 'rejected' | 'fixed' | 'opened' | 'waiting' | 'none'

export function decisionKind(order: Order): DecisionKind {
  if (order.review_state === 'auto_approved') {
    return 'auto'
  }
  if (order.review_state === 'approved') {
    return 'approved'
  }
  if (wasFixed(order) || order.approval?.action === 'accept_fix') {
    // the backend files it under rejected, since the original was voided. the human didn't say
    // no though, they said "the other one"
    return 'fixed'
  }
  if (order.review_state === 'rejected') {
    return 'rejected'
  }
  if (order.review_state === 'needs_review') {
    // an approval row with no action yet means the human has the page open
    if (order.approval && order.approval.action === null) {
      return 'opened'
    }
    return 'waiting'
  }
  return 'none'
}

export const DECISION_LABELS: Record<DecisionKind, string> = {
  auto: 'Auto-captured',
  approved: 'Approved',
  rejected: 'Rejected',
  fixed: 'Fix accepted',
  opened: 'Opened, deciding',
  waiting: 'Waiting on human',
  none: 'Not needed',
}

// the server's number, only once they've actually decided. 0 means the page never reported
// it opened, so there's nothing honest to show
export function decisionMs(order: Order): number | null {
  const approval = order.approval
  if (!approval || approval.action === null || approval.decision_ms === null) {
    return null
  }
  return approval.decision_ms
}

export function isRubberStamp(order: Order): boolean {
  const ms = decisionMs(order)
  return order.review_state === 'approved' && ms !== null && ms > 0 && ms < RUBBER_STAMP_MS
}

// money in the mandate can be in another currency, and null there means USD
export function mandateCurrency(order: Order): string {
  const currency = order.mandate.rules.currency
  return typeof currency === 'string' && currency ? currency : 'USD'
}

// "held" means Leash didn't let the order through on its own: it went to a human, whatever they
// decided. per agent, that share is the trust score: an agent that gets held a lot buys the wrong thing
// a fixed order counts: the agent ordered the wrong thing and a human had to step in, even though
// the right thing got bought in the end
export function wasHeld(order: Order): boolean {
  if (wasFixed(order)) {
    return true
  }
  return order.review_state === 'needs_review' || order.review_state === 'approved' || order.review_state === 'rejected'
}

// what an order adds to its agent's held rate: 1 held, 0 let through, null not counted. the
// replacement for a fixed order isn't counted at all. the human picked it by accepting the fix, so
// it says nothing about the agent, and counting it as a clean order would halve the held rate of
// exactly the agent that got it wrong (1 held of 2 instead of 1 of 1)
export function heldRateValue(order: Order): number | null {
  if (order.replaces_order_id !== null) {
    return null
  }
  return wasHeld(order) ? 1 : 0
}

export interface HeldRate {
  held: number
  total: number
  // what AG Grid sorts by, and what a plain text export shows
  toString(): string
}

// AG Grid aggFunc for the "Held by Leash" column. each leaf value is 1 (held) or 0
export function heldRateAgg(params: { values: unknown[] }): HeldRate {
  let held = 0
  let total = 0
  for (const value of params.values) {
    // a nested group passes up its own HeldRate, a leaf passes 1 or 0
    if (value && typeof value === 'object' && 'held' in value) {
      const inner = value as HeldRate
      held += inner.held
      total += inner.total
    } else if (typeof value === 'number') {
      held += value
      total += 1
    }
  }
  return {
    held,
    total,
    toString: () => (total === 0 ? '' : Math.round((held / total) * 100) + '%'),
  }
}
