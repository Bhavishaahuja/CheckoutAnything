// "Reset demo" in the top bar, for judges and for us between takes. It asks first, because it voids
// real sandbox holds, shows how far it got while it runs, then says what it did. The strip sits
// under the header, like the Checkout Anything app's notices.

import { LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ResetControls } from '../lib/useResetDemo'
import type { ResetStatus } from '../types'

function plural(count: number, word: string): string {
  return count + ' ' + word + (count === 1 ? '' : 's')
}

function describeSummary(summary: ResetStatus): string {
  let captured = 0
  let approved = 0
  let rejected = 0
  for (const order of summary.orders) {
    if (order.review_state === 'auto_approved') captured += 1
    if (order.review_state === 'approved') approved += 1
    if (order.review_state === 'rejected') rejected += 1
  }
  const agents = new Set(summary.orders.map((order) => order.agent_name))
  let text =
    'Demo reset. ' +
    plural(summary.orders.length, 'fresh order') +
    ' from ' +
    plural(agents.size, 'agent') +
    ': ' +
    captured +
    ' auto-captured, ' +
    approved +
    ' approved and ' +
    rejected +
    ' rejected by the demo seed. Nothing is waiting on a human.'
  if (summary.voided_holds > 0) {
    text += ' Voided ' + plural(summary.voided_holds, 'old hold') + ' first.'
  }
  return text
}

function describeProgress(progress: ResetStatus | null): string {
  if (!progress || !progress.step) {
    return 'Resetting the demo...'
  }
  return progress.step + '...'
}

function seedProblems(summary: ResetStatus): string[] {
  const problems: string[] = []
  for (const order of summary.orders) {
    if (order.problem) problems.push(order.name + ': ' + order.problem)
  }
  return problems
}

export function ResetButton({ controls }: { controls: ResetControls }) {
  const busy = controls.state.step === 'resetting'
  return (
    <button
      type="button"
      className="ca-header__tool"
      onClick={controls.ask}
      disabled={busy}
      aria-expanded={controls.state.step === 'confirming'}
    >
      <span className="topbar__reset-long">Reset demo</span>
      <span className="topbar__reset-short">Reset</span>
    </button>
  )
}

export function ResetStrip({ controls }: { controls: ResetControls }) {
  const state = controls.state
  const warning = state.step === 'confirming' || state.step === 'resetting' || state.step === 'error'

  // always rendered, so screen readers hear the result through aria-live
  return (
    <div
      className={cn(
        state.step === 'idle' ? 'hidden' : 'border-t border-border',
        warning ? 'bg-bad-soft' : 'bg-muted',
      )}
      aria-live="polite"
    >
      {state.step !== 'idle' && (
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 text-[13px]">
          {state.step === 'confirming' && (
            <>
              <p className="min-w-0 flex-1 basis-80">
                Reset the demo? This voids every open hold in the PayPal sandbox, clears out the demo orders and
                places a fresh set through Check. The order with the sandbox dispute stays. Takes a minute or two.
              </p>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={controls.dismiss}>
                  Cancel
                </Button>
                <Button size="sm" variant="danger" onClick={controls.confirm}>
                  Yes, reset
                </Button>
              </div>
            </>
          )}
          {state.step === 'resetting' && (
            <p className="flex min-w-0 flex-1 items-center gap-2 text-bad" role="status">
              <LoaderCircle className="spin-slow size-4 shrink-0" aria-hidden />
              {describeProgress(state.progress)}
            </p>
          )}
          {state.step === 'done' && (
            <>
              <div className="min-w-0 flex-1 basis-80">
                <p>{describeSummary(state.summary)}</p>
                {seedProblems(state.summary).map((problem) => (
                  <p key={problem} className="text-bad">
                    Didn't land as planned: {problem}
                  </p>
                ))}
              </div>
              <Button size="sm" variant="outline" onClick={controls.dismiss}>
                OK
              </Button>
            </>
          )}
          {state.step === 'error' && (
            <>
              <p className="min-w-0 flex-1 basis-80 text-bad" role="alert">
                Couldn't reset: {state.message}
              </p>
              <Button size="sm" variant="outline" onClick={controls.dismiss}>
                OK
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
