// "Reset demo" in the top bar, for judges and for us between takes. It asks first, because it voids
// real sandbox holds, then says what it did. The strip sits under the header, like the Checkout
// Anything app's notices.

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ResetControls } from '../lib/useResetDemo'
import type { ResetSummary } from '../types'

function plural(count: number, word: string): string {
  return count + ' ' + word + (count === 1 ? '' : 's')
}

function describeSummary(summary: ResetSummary): string {
  if (summary.deleted_orders === 0 && summary.deleted_mandates === 0) {
    return 'Nothing to reset, there was no seeded demo data.'
  }
  let removed = plural(summary.deleted_orders, 'order') + ' and ' + plural(summary.deleted_mandates, 'mandate')
  if (summary.deleted_disputes > 0) {
    removed = plural(summary.deleted_orders, 'order') + ', ' + plural(summary.deleted_mandates, 'mandate')
    removed += ' and ' + plural(summary.deleted_disputes, 'dispute')
  }
  return 'Demo reset. Voided ' + plural(summary.voided_holds, 'hold') + ', removed ' + removed + '. Place new orders from Place order.'
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
                Reset the demo? This voids every open seeded hold in the PayPal sandbox and deletes the seeded
                orders, mandates and disputes.
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
          {state.step === 'resetting' && <p className="min-w-0 flex-1 text-bad">Resetting, voiding holds at PayPal...</p>}
          {state.step === 'done' && (
            <>
              <p className="min-w-0 flex-1 basis-80">{describeSummary(state.summary)}</p>
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
