import { ArrowLeftRight, Check, CircleSlash, LoaderCircle, Sparkles, TriangleAlert, X } from 'lucide-react'
import { motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router'
import { ApiError, acceptFix, approveReview, getReview, markReviewOpened, rejectReview } from '../api'
import { Card, Pill } from '@/components/bits'
import { BrandMark } from '../components/BrandMark'
import { Button } from '@/components/ui/button'
import { formatDuration, formatEventDate, formatMoney, sizeLabel } from '../lib/format'
import { tellParentReviewDecided } from '../lib/parentMessage'
import { useAsync } from '../lib/useAsync'
import { cn } from '@/lib/utils'
import type { AcceptFixResult, ApprovalAction, OrderItem, ReviewView } from '../types'

// The human's mobile page, opened from a one-time review link on their phone. Shows what the
// agent ordered next to what they asked for, and two big buttons: approve captures the money,
// reject releases the hold. When Check found a fix in the catalog there is a third, Accept fix,
// which swaps the order for the right one. Designed at 390px wide, and it also has to work at the
// review drawer's ~480px inside the Checkout Anything app. Styled with that app's tokens.
export function ConfirmPage() {
  const { token } = useParams()

  if (!token) {
    return (
      <ConfirmFrame>
        <Notice tone="error" title="This link is incomplete">
          Open the link the store sent you again, all the way to the end.
        </Notice>
      </ConfirmFrame>
    )
  }

  // key resets everything if the token in the URL changes
  return <ConfirmReview key={token} token={token} />
}

function ConfirmReview({ token }: { token: string }) {
  const load = useCallback(() => getReview(token), [token])
  const review = useAsync(load)

  if (review.status === 'loading') {
    return (
      <ConfirmFrame>
        <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="spin-slow size-4" aria-hidden /> Loading your order...
        </p>
      </ConfirmFrame>
    )
  }

  if (review.status === 'error') {
    return (
      <ConfirmFrame>
        <LoadError error={review.error} />
      </ConfirmFrame>
    )
  }

  return <Decide token={token} order={review.data} />
}

type Phase =
  | { kind: 'deciding' }
  | { kind: 'sending'; action: ApprovalAction }
  | { kind: 'done'; action: 'approve' | 'reject'; order: ReviewView; decisionMs: number }
  // the fix was accepted: the original is voided and the replacement has been placed and checked
  | { kind: 'fixed'; result: AcceptFixResult; decisionMs: number }
  // fixGone: the fix can't be placed anymore but nothing moved, so approve and reject still work
  | { kind: 'failed'; action: ApprovalAction; title: string; message: string; canRetry: boolean; fixGone?: boolean }

function Decide({ token, order }: { token: string; order: ReviewView }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'deciding' })
  // when the order was really on screen. the server keeps its own clock from the /opened call,
  // this one is only what we send along and show back to the human
  const shownAt = useRef<number | null>(null)
  const openedSent = useRef(false)

  useEffect(() => {
    shownAt.current = performance.now()
    // start the server's attention clock now that the order is rendered. the ref stops React's
    // dev double-run from sending it twice (the server ignores repeats anyway). a failure here
    // must not block the buttons: the decision still works, it just records 0
    if (!openedSent.current) {
      openedSent.current = true
      markReviewOpened(token).catch(() => {})
    }
  }, [token])

  async function decide(action: ApprovalAction) {
    // the buttons are disabled while sending, this is a second guard against a fast double tap
    if (phase.kind === 'sending') {
      return
    }
    const decisionMs = shownAt.current === null ? 0 : performance.now() - shownAt.current
    setPhase({ kind: 'sending', action })
    try {
      if (action === 'accept_fix') {
        const result = await acceptFix(token, decisionMs)
        // show how the new order turned out first, then tell the parent, same as approve and reject
        setPhase({ kind: 'fixed', result, decisionMs })
        tellParentReviewDecided(action, result.order.status, result.order.review_state)
        return
      }
      const send = action === 'approve' ? approveReview : rejectReview
      const updated = await send(token, decisionMs)
      setPhase({ kind: 'done', action, order: updated, decisionMs })
      // inside the Checkout Anything review drawer this closes it and refreshes the row. on a
      // phone there is no parent and nothing is sent
      tellParentReviewDecided(action, updated.status, updated.review_state)
    } catch (error) {
      setPhase({ kind: 'failed', action, ...describeDecideError(error, action) })
    }
  }

  if (phase.kind === 'fixed') {
    return (
      <ConfirmFrame>
        <Fixed result={phase.result} decisionMs={phase.decisionMs} />
      </ConfirmFrame>
    )
  }

  if (phase.kind === 'done') {
    return (
      <ConfirmFrame>
        <Done action={phase.action} order={phase.order} decisionMs={phase.decisionMs} />
      </ConfirmFrame>
    )
  }

  const sending = phase.kind === 'sending' ? phase.action : null
  const total = formatMoney(order.total, order.currency)
  const check = order.intent_check
  // no suggested fix from Check, no button. it also goes once the server says the fix is gone
  const fix = phase.kind === 'failed' && phase.fixGone ? null : (check?.suggested_fix ?? null)

  const flagged = new Set(check?.mismatched_fields ?? [])
  const blocked = phase.kind === 'failed' && !phase.canRetry

  return (
    <ConfirmFrame
      footer={
        <div className="flex flex-col gap-3">
          {phase.kind === 'failed' && (
            <p className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad" role="alert">
              <strong className="font-semibold">{phase.title}</strong> {phase.message}
            </p>
          )}
          {!blocked && fix && (
            <div className="flex flex-col gap-2.5 rounded-xl border border-primary/25 bg-info-soft p-3">
              <p className="flex items-start gap-2 text-sm font-medium">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                {fix.sentence}
              </p>
              <Button
                size="lg"
                className="w-full text-[15px]"
                onClick={() => decide('accept_fix')}
                disabled={sending !== null}
              >
                {sending === 'accept_fix' ? (
                  <>
                    <LoaderCircle className="spin-slow" /> Swapping the order...
                  </>
                ) : (
                  <>
                    <ArrowLeftRight /> Accept fix
                  </>
                )}
              </Button>
            </div>
          )}
          {!blocked && (
            <div className="grid grid-cols-[2fr_3fr] gap-2.5">
              <Button
                size="lg"
                variant="danger"
                className="text-[15px]"
                onClick={() => decide('reject')}
                disabled={sending !== null}
              >
                {sending === 'reject' ? 'Rejecting...' : 'Reject'}
              </Button>
              <Button
                size="lg"
                variant="ok"
                className="text-[15px]"
                onClick={() => decide('approve')}
                disabled={sending !== null}
              >
                {sending === 'approve' ? 'Approving...' : 'Approve ' + total}
              </Button>
            </div>
          )}
        </div>
      }
    >
      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">
          {order.merchant ? (
            <>
              Your agent wants to buy from{' '}
              <Field flagged={flagged.has('merchant')}>{order.merchant}</Field>
            </>
          ) : (
            'Your agent wants to buy'
          )}
        </p>
        <ul className="mt-2 flex flex-col gap-1">
          {order.items.map((item, index) => (
            <li key={index} className="text-[15px] leading-snug font-medium">
              <ItemLine item={item} flagged={flagged} />
            </li>
          ))}
        </ul>
        <p className="mt-3 text-3xl font-semibold tracking-tight tabular-nums">
          <Field flagged={flagged.has('price') || flagged.has('currency')}>{total}</Field>
        </p>
        {order.shipping_amount !== null && Number(order.shipping_amount) > 0 && (
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            Includes {formatMoney(order.shipping_amount, order.currency)} shipping
          </p>
        )}
      </Card>

      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">You asked for</p>
        <blockquote className="mt-1.5 border-l-2 border-primary pl-3 text-[15px] leading-relaxed">
          {order.mandate.raw_request}
        </blockquote>
      </Card>

      <div
        className={cn(
          'flex gap-2.5 rounded-xl p-4',
          check ? 'bg-warn-soft text-warn' : 'bg-muted text-muted-foreground',
        )}
      >
        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div>
          <p className="text-xs font-medium tracking-wide uppercase opacity-90">Why we're asking you</p>
          <p className="mt-1 text-[15px] leading-snug font-semibold">
            {check
              ? check.reason
              : "We couldn't save why this order was flagged. Compare the two above before you decide."}
          </p>
        </div>
      </div>

      <p className="text-[13px] leading-relaxed text-muted-foreground">
        Approve pays for the order. Reject cancels it and you won't be charged.
        {fix && ' Accept fix cancels this order and places the suggested one instead.'}
      </p>
    </ConfirmFrame>
  )
}

// which check fields point at which part of an item line
const NAME_FIELDS = ['item', 'extra_item', 'substitution', 'instructions_in_order']

// "Ridgeline trail runner, slate, size women's 9", with the part Check flagged marked in warn.
// the same words as describeItem, split up so one part can stand out
function ItemLine({ item, flagged }: { item: OrderItem; flagged: Set<string> }) {
  let nameFlagged = false
  for (const field of NAME_FIELDS) {
    if (flagged.has(field)) {
      nameFlagged = true
    }
  }
  const parts: { key: string; text: string; flagged: boolean }[] = []
  parts.push({ key: 'name', text: item.name, flagged: nameFlagged })
  if (item.color) {
    parts.push({ key: 'color', text: item.color, flagged: flagged.has('color') })
  }
  if (item.size) {
    parts.push({ key: 'size', text: sizeLabel(item.size), flagged: flagged.has('size') })
  }
  if (item.model) {
    parts.push({ key: 'model', text: 'model ' + item.model, flagged: flagged.has('model') })
  }
  if (item.event_date) {
    parts.push({ key: 'date', text: formatEventDate(item.event_date), flagged: flagged.has('event_date') })
  }
  return (
    <>
      {item.quantity > 1 && (
        <Field flagged={flagged.has('quantity')}>
          <span className="font-mono">{item.quantity} x </span>
        </Field>
      )}
      {parts.map((part, index) => (
        <span key={part.key}>
          {index > 0 && ', '}
          <Field flagged={part.flagged}>{part.text}</Field>
        </span>
      ))}
    </>
  )
}

// a value Check flagged: warn tint and underline, plus words for screen readers
function Field({ flagged, children }: { flagged: boolean; children: ReactNode }) {
  if (!flagged) {
    return <>{children}</>
  }
  return (
    <mark className="rounded bg-warn-soft px-0.5 text-warn underline decoration-warn/60 decoration-2 underline-offset-4">
      {children}
      <span className="sr-only"> (doesn't match what you asked for)</span>
    </mark>
  )
}

function Done({ action, order, decisionMs }: { action: ApprovalAction; order: ReviewView; decisionMs: number }) {
  const approved = action === 'approve'
  return (
    <Outcome
      tone={approved ? 'ok' : 'bad'}
      icon={approved ? <Check strokeWidth={3} /> : <X strokeWidth={3} />}
      title={approved ? 'Approved' : 'Rejected'}
      decisionMs={decisionMs}
    >
      <p className="text-[15px] text-muted-foreground">
        {approved
          ? 'You paid ' + formatMoney(order.total, order.currency) + '. Your order is on its way.'
          : "The order is cancelled and the hold is released. You won't be charged."}
      </p>
    </Outcome>
  )
}

// the end screens share a shape: an icon that pops in, a title, what happened, the time taken
function Outcome({
  tone,
  icon,
  title,
  decisionMs,
  children,
}: {
  tone: 'ok' | 'bad' | 'info'
  icon: ReactNode
  title: string
  decisionMs: number
  children: ReactNode
}) {
  const iconTone = { ok: 'bg-ok-soft text-ok', bad: 'bg-bad-soft text-bad', info: 'bg-info-soft text-primary' }[tone]
  return (
    <Card className="flex flex-col items-center gap-3 px-5 py-8 text-center" >
      <div role="status" className="contents">
        <motion.span
          className={cn('flex size-14 items-center justify-center rounded-full [&_svg]:size-7', iconTone)}
          initial={{ scale: 0.4, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 420, damping: 20 }}
          aria-hidden="true"
        >
          {icon}
        </motion.span>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {children}
        <p className="text-[13px] text-muted-foreground">
          You decided in <span className="font-medium text-foreground tabular-nums">{formatDuration(Math.round(decisionMs))}</span>.
        </p>
        <p className="text-[13px] text-muted-foreground">You can close this page.</p>
      </div>
    </Card>
  )
}

// what the replacement order's two state fields mean for the human, in their words
function replacementOutcome(replacement: AcceptFixResult['replacement']): { label: string; tone: 'ok' | 'warn'; text: string } {
  const total = formatMoney(replacement.total, replacement.currency)
  if (replacement.status === 'captured') {
    return {
      label: 'Auto-captured',
      tone: 'ok',
      text: 'It matches what you asked for, so it went through on its own. You paid ' + total + '.',
    }
  }
  if (replacement.review_state === 'needs_review') {
    return {
      label: 'Needs review',
      tone: 'warn',
      text: "Something about the new order still needs a look, so it is on hold. You won't be charged " + total + ' unless it is approved.',
    }
  }
  return {
    label: 'On hold',
    tone: 'warn',
    text: total + " is on hold for it. You haven't been charged yet.",
  }
}

function Fixed({ result, decisionMs }: { result: AcceptFixResult; decisionMs: number }) {
  const replacement = result.replacement
  const outcome = replacementOutcome(replacement)
  return (
    <Outcome tone="info" icon={<ArrowLeftRight strokeWidth={2.5} />} title="Fix accepted" decisionMs={decisionMs}>
      <p className="text-[15px] text-muted-foreground">The first order is cancelled and its hold is released.</p>
      <div className="w-full rounded-xl border border-border bg-background p-3.5 text-left">
        <Pill tone={outcome.tone}>New order: {outcome.label}</Pill>
        <ul className="mt-2.5 flex flex-col gap-1 text-[15px] font-medium">
          {replacement.items.map((item, index) => (
            <li key={index}>
              <ItemLine item={item} flagged={new Set()} />
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[13px] text-muted-foreground">{outcome.text}</p>
      </div>
    </Outcome>
  )
}

interface ErrorDetail {
  message: string | null
  status: string | null
  // only on a failed accept-fix: the original was voided before the replacement failed
  voidedOrderId: number | null
}

function readDetail(error: ApiError): ErrorDetail {
  // review errors carry {"detail": {"message": ..., "status": ..., "review_state": ...}}
  const detail = error.detail
  if (detail && typeof detail === 'object') {
    const fields = detail as { message?: unknown; status?: unknown; voided_order_id?: unknown }
    return {
      message: typeof fields.message === 'string' ? fields.message : null,
      status: typeof fields.status === 'string' ? fields.status : null,
      voidedOrderId: typeof fields.voided_order_id === 'number' ? fields.voided_order_id : null,
    }
  }
  return { message: typeof detail === 'string' ? detail : null, status: null, voidedOrderId: null }
}

function describeDecideError(
  error: unknown,
  action: ApprovalAction,
): { title: string; message: string; canRetry: boolean; fixGone?: boolean } {
  if (!(error instanceof ApiError)) {
    // fetch itself failed: no signal, or the server is waking up. nothing changed, so it's safe to go again
    return { title: "Couldn't reach the store.", message: 'Check your connection and try again.', canRetry: true }
  }

  const { message, status, voidedOrderId } = readDetail(error)
  if (action === 'accept_fix' && error.status === 409 && status === null) {
    // the fix can't be placed (sold out, price changed). nothing moved and the link still works,
    // so the two plain buttons stay
    return {
      title: "That fix isn't available anymore.",
      message: (message ?? 'The suggested item changed.') + ' You can still approve or reject this order.',
      canRetry: true,
      fixGone: true,
    }
  }
  if (voidedOrderId !== null) {
    // the swap got half way: the original is cancelled, the new order failed. the link is used up
    return {
      title: 'The first order is cancelled, but the new one failed.',
      message: 'Nothing was charged for either. Ask your agent to order again.',
      canRetry: false,
    }
  }
  if (error.status === 404) {
    return {
      title: "This link isn't valid anymore.",
      message: 'The store may have sent you a newer one.',
      canRetry: false,
    }
  }
  if (error.status === 410) {
    return { title: 'This link has expired.', message: 'Ask the store for a new one.', canRetry: false }
  }
  if (error.status === 409) {
    return { title: 'Already decided.', message: message ?? 'This order was already approved or rejected.', canRetry: false }
  }
  if (error.status === 502) {
    if (status === 'failed') {
      // PayPal declined the capture. going again just gets a 409
      return { title: 'PayPal declined the payment.', message: "You weren't charged.", canRetry: false }
    }
    if (status !== null) {
      // PayPal failed and the order is unchanged, the same link is safe to try again
      return { title: 'PayPal had a problem.', message: (message ?? 'Nothing changed.') + ' Try again.', canRetry: true }
    }
    // PayPal went through but saving failed. the link is used up, the store has to send a new one
    return {
      title: 'Almost done.',
      message: (message ?? 'Your choice went through but we could not save it.') + " Don't tap again.",
      canRetry: false,
    }
  }
  // a 422 means we sent a bad decision_ms, which is our bug, not theirs
  return { title: 'Something went wrong.', message: message ?? 'Try again in a moment.', canRetry: true }
}

function LoadError({ error }: { error: Error }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <Notice tone="error" title="This link isn't valid">
        The store may have sent you a newer link. Check your messages for the latest one.
      </Notice>
    )
  }
  if (error instanceof ApiError && error.status === 410) {
    return (
      <Notice tone="muted" title="Nothing to decide here">
        This link has expired or was already used, so the order is no longer waiting on you.
      </Notice>
    )
  }
  return (
    <Notice tone="error" title="Couldn't load your order">
      {error instanceof ApiError ? error.message : 'Check your connection and reload the page.'}
    </Notice>
  )
}

function Notice({ tone, title, children }: { tone: 'error' | 'muted'; title: string; children: ReactNode }) {
  return (
    <Card className="flex flex-col items-center gap-3 px-5 py-8 text-center">
      <div className="contents" role={tone === 'error' ? 'alert' : 'status'}>
        <span
          className={cn(
            'flex size-12 items-center justify-center rounded-full [&_svg]:size-6',
            tone === 'error' ? 'bg-bad-soft text-bad' : 'bg-muted text-muted-foreground',
          )}
          aria-hidden="true"
        >
          {tone === 'error' ? <TriangleAlert /> : <CircleSlash />}
        </span>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="text-[15px] text-muted-foreground">{children}</p>
      </div>
    </Card>
  )
}

// the page around every state: the brand on top, one column of cards, and the decision bar
// pinned to the bottom so the buttons are always under the thumb
function ConfirmFrame({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 w-full max-w-lg items-center gap-2 px-4">
          <BrandMark size={24} />
          <span className="text-[15px] font-semibold tracking-tight">Checkout Anything</span>
          <Pill tone="info" className="ml-auto">
            Check
          </Pill>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-lg flex-1 flex-col gap-3 px-4 py-4">{children}</main>
      {footer && (
        <div className="sticky bottom-0 border-t border-border bg-card/95 backdrop-blur-sm">
          <div className="mx-auto w-full max-w-lg px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">{footer}</div>
        </div>
      )}
    </div>
  )
}
