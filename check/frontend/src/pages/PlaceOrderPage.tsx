import { LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { Card } from '@/components/bits'
import { cn } from '@/lib/utils'
import { PageHead, StateCard } from '../components/pageBits'
import { ApiError, listMandates, placeDemoOrder } from '../api'
import { ReviewLinkBox } from '../components/ReviewLinkBox'
import { StatusChip, type DisplayStatus } from '../components/StatusChip'
import { SCENARIOS, scenarioBlocker, scenarioDescription } from '../lib/demoScenarios'
import { SEED_LABEL_PREFIX, describeItem, formatMoney, formatTime } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import type { DemoScenario, MandateSummary, PlacedOrder } from '../types'

// stable loader identity so useAsync fetches once
const loadMandates = () => listMandates()

function isExpiredSession(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

// Demo stand-in for the shopping agent: pick a mandate, pick how the order should go wrong, and it
// runs through the same hold, check and auto-decide as a real agent order.
//
// The login gate lives in MerchantLayout now, so this page can assume a session. If one runs out
// mid-page, api.ts tells the layout and it swaps this page for the login form.
export function PlaceOrderPage() {
  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-4">
      <PageHead title="Place a demo order" lede="Stands in for the shopping agent. Every order is a real sandbox hold." />

      <PlaceOrderForm />
    </section>
  )
}

function PlaceOrderForm() {
  const mandates = useAsync(loadMandates)

  if (mandates.status === 'loading') {
    return <StateCard kind="loading">Loading mandates...</StateCard>
  }
  if (mandates.status === 'error') {
    return <StateCard kind="error">Couldn't load mandates: {mandates.error.message}</StateCard>
  }
  if (mandates.data.length === 0) {
    return <StateCard kind="empty">No mandates yet. Run the seed script or create one first.</StateCard>
  }

  return <ScenarioPicker mandates={mandates.data} />
}

interface ScenarioPickerProps {
  mandates: MandateSummary[]
}

// seed_demo.py's trick buyers (injection in the name and so on) are labeled "seed-demo:sneaky: ...".
// the list is newest first and the seed makes those last, so without this a fresh demo opens on
// the injection test buyer
function defaultMandateId(mandates: MandateSummary[]): number {
  for (const mandate of mandates) {
    if (!mandate.buyer_label.startsWith(SEED_LABEL_PREFIX + 'sneaky:')) {
      return mandate.id
    }
  }
  return mandates[0].id
}

function ScenarioPicker({ mandates }: ScenarioPickerProps) {
  const [mandateId, setMandateId] = useState(() => defaultMandateId(mandates))
  const [placing, setPlacing] = useState<DemoScenario | null>(null)
  const [result, setResult] = useState<PlacedOrder | null>(null)
  const [error, setError] = useState<string | null>(null)

  const mandate = mandates.find((row) => row.id === mandateId) ?? mandates[0]

  function chooseMandate(nextId: number) {
    setMandateId(nextId)
    // the old result was for a different mandate, it shouldn't look like it belongs to this one
    setResult(null)
    setError(null)
  }

  async function place(scenario: DemoScenario) {
    setPlacing(scenario)
    setResult(null)
    setError(null)
    try {
      setResult(await placeDemoOrder(mandate.id, scenario))
    } catch (caught) {
      if (isExpiredSession(caught)) {
        // the layout is already swapping to the login form, no point flashing an error first
        return
      }
      setError(caught instanceof Error ? caught.message : 'The order failed')
    } finally {
      setPlacing(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-2 p-4">
        <label className="text-[13px] font-medium" htmlFor="demo-mandate">
          Mandate
        </label>
        <select
          id="demo-mandate"
          className="h-10 w-full min-w-0 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary disabled:opacity-60"
          value={mandate.id}
          disabled={placing !== null}
          onChange={(event) => chooseMandate(Number(event.target.value))}
        >
          {mandates.map((row) => (
            <option key={row.id} value={row.id}>
              #{row.id}: {row.raw_request}
            </option>
          ))}
        </select>
        <p className="text-[13px] text-muted-foreground">{summarizeMandate(mandate)}</p>
      </Card>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {SCENARIOS.map((scenario) => {
          const blocker = scenarioBlocker(mandate, scenario.id)
          return (
            <button
              key={scenario.id}
              type="button"
              className={cn(
                'flex min-h-24 flex-col items-start gap-1 rounded-xl border border-border bg-card p-4 text-left transition-colors',
                'hover:border-primary hover:bg-info-soft disabled:hover:border-border',
                blocker !== null ? 'bg-muted text-muted-foreground disabled:hover:bg-muted' : 'disabled:hover:bg-card',
                placing === scenario.id && 'border-primary bg-info-soft',
              )}
              disabled={placing !== null || blocker !== null}
              onClick={() => place(scenario.id)}
            >
              <span className="text-[15px] font-semibold tracking-tight">{scenario.title}</span>
              <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                {placing === scenario.id && <LoaderCircle className="spin-slow size-3.5" aria-hidden />}
                {placing === scenario.id ? 'Placing...' : (blocker ?? scenarioDescription(mandate, scenario))}
              </span>
            </button>
          )
        })}
      </div>

      <div aria-live="polite" className="flex flex-col gap-4">
        {placing && (
          <StateCard kind="loading">Placing the hold and checking the order. This can take around 30 seconds.</StateCard>
        )}
        {error && <StateCard kind="error">{error}</StateCard>}
        {result && <ResultCard order={result} />}
      </div>
    </div>
  )
}

function summarizeMandate(mandate: MandateSummary): string {
  const parts: string[] = []
  // the cap can be in another currency, see docs/api.md
  const currency = typeof mandate.rules.currency === 'string' ? mandate.rules.currency : 'USD'
  parts.push(mandate.max_price === null ? 'No cap' : 'Cap ' + formatMoney(mandate.max_price, currency))
  parts.push(mandate.merchant ?? 'Any store')
  parts.push(mandate.expires_at === null ? 'No expiry' : 'Expires ' + formatTime(mandate.expires_at))
  return parts.join(' · ')
}

function displayStatus(order: PlacedOrder): DisplayStatus {
  // "needs review" lives in review_state. a declined capture is failed + needs_review, and that
  // one's over, so it has to read as failed
  if (order.status === 'authorized' && order.review_state === 'needs_review') {
    return 'needs_review'
  }
  return order.status
}

function ResultCard({ order }: { order: PlacedOrder }) {
  const status = displayStatus(order)
  const check = order.intent_check
  // colored by verdict like the side panel, so a clean match doesn't read as a warning
  const verdictTone = !check ? 'text-muted-foreground' : check.verdict === 'match' ? 'text-ok' : 'text-warn'

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[13px] text-muted-foreground">Order #{order.id}</span>
        <StatusChip status={status} />
      </div>

      <p className={cn('text-[15px] leading-snug font-semibold', verdictTone)}>
        {check ? check.reason : 'No check result on this order.'}
      </p>

      {check && (
        <dl className="grid grid-cols-3 gap-2">
          <div className="rounded-lg bg-muted px-3 py-2">
            <dt className="text-xs text-muted-foreground">Verdict</dt>
            <dd className="text-sm font-medium capitalize">{check.verdict}</dd>
          </div>
          <div className="rounded-lg bg-muted px-3 py-2">
            <dt className="text-xs text-muted-foreground">Risk score</dt>
            <dd className="text-sm font-medium tabular-nums">{check.risk_score ?? 'None'}</dd>
          </div>
          <div className="rounded-lg bg-muted px-3 py-2">
            <dt className="text-xs text-muted-foreground">Total</dt>
            <dd className="text-sm font-medium tabular-nums">{formatMoney(order.total, order.currency)}</dd>
          </div>
        </dl>
      )}

      <ul className="flex flex-col gap-0.5 text-sm">
        {order.items.map((item, index) => (
          <li key={index}>{describeItem(item)}</li>
        ))}
      </ul>
      {order.merchant && <p className="text-[13px] text-muted-foreground">At {order.merchant}</p>}

      {status === 'needs_review' && (
        <ReviewLinkBox key={order.id} orderId={order.id} />
      )}
    </Card>
  )
}
