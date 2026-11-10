// The confirm page can be shown inside the Checkout Anything app's review drawer (an iframe).
// When the human finishes a decision the page tells that parent window, so the drawer can close
// and the grid can refresh the row.
//
// The message only ever goes to the Checkout Anything app's own origin (VITE_CONNECT_URL). On a
// phone there is no parent window, and with the variable unset there is nowhere safe to post, so
// in both cases nothing is sent. It carries no token and no order details, only that a decision
// happened and what kind.

import type { ApprovalAction, OrderStatus, ReviewState } from '../types'

// the drawer checks these two before it believes a message (frontend/src/components/ReviewDrawer.tsx)
export const MESSAGE_SOURCE = 'checkout-anything-check'
export const REVIEW_DECIDED = 'review-decided'

export interface ReviewDecidedMessage {
  source: typeof MESSAGE_SOURCE
  type: typeof REVIEW_DECIDED
  action: ApprovalAction
  // where the order this link was for ended up
  status: OrderStatus
  review_state: ReviewState | null
}

function connectOrigin(): string | null {
  const url = import.meta.env.VITE_CONNECT_URL
  if (!url) {
    return null
  }
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

export function tellParentReviewDecided(action: ApprovalAction, status: OrderStatus, reviewState: ReviewState | null): void {
  const origin = connectOrigin()
  if (origin === null || window.parent === window) {
    return
  }
  const message: ReviewDecidedMessage = {
    source: MESSAGE_SOURCE,
    type: REVIEW_DECIDED,
    action,
    status,
    review_state: reviewState,
  }
  // the second argument is the lock: a parent on any other origin never receives this
  window.parent.postMessage(message, origin)
}
