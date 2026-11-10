import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { agentChat } from '../api'
import type { AgentStep } from '../types'

const DEMO_PROMPT = 'Get me a half sourdough loaf, sliced, from Hollowbrook Bakery.'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  steps: AgentStep[]
  failed?: boolean
}

// one line saying what a tool call came back with
function summarize(step: AgentStep): string {
  const output = step.output
  if (step.is_error && output.error) return String(output.error)
  if (step.tool === 'list_stores') {
    const names = (output.stores ?? []).map((store: { name: string }) => store.name)
    return names.length > 0 ? names.join(', ') : 'No live stores'
  }
  if (step.tool === 'search_catalog') {
    const count = (output.items ?? []).length
    return count + (count === 1 ? ' item' : ' items') + ' at ' + (output.merchant?.name ?? 'the store')
  }
  if (step.tool === 'buy_item') {
    if (output.status === 'captured') {
      return output.bought + ', ' + output.total + ' ' + output.currency + ', capture ' + output.capture_id
    }
    return 'Not captured: ' + (output.error ?? 'unknown reason')
  }
  if (step.tool === 'check_payment') {
    return 'PayPal says ' + output.status + (output.amount ? ', ' + output.amount : '')
  }
  return ''
}

function Steps({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null
  return (
    <ol className="steps">
      {steps.map((step, index) => {
        const captured = step.tool === 'buy_item' && step.output.status === 'captured'
        return (
          <li key={index} className={'step' + (step.is_error ? ' step--bad' : '') + (captured ? ' step--captured' : '')}>
            <details>
              <summary>
                <span className="step__icon" aria-hidden="true">{step.is_error ? '✗' : '✓'}</span>
                <span className="mono step__tool">{step.tool}</span>
                <span className="step__summary">{summarize(step)}</span>
              </summary>
              <div className="step__io">
                <div className="eyebrow">Input</div>
                <pre className="json">{JSON.stringify(step.input, null, 2)}</pre>
                <div className="eyebrow">Output</div>
                <pre className="json">{JSON.stringify(step.output, null, 2)}</pre>
              </div>
            </details>
          </li>
        )
      })}
    </ol>
  )
}

export default function AgentPage() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)
  const end = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' })
  }, [turns.length, thinking])

  const send = useCallback(
    async (text: string) => {
      const content = text.trim()
      if (!content || thinking) return
      const next: Turn[] = [...turns, { role: 'user', content, steps: [] }]
      setTurns(next)
      setDraft('')
      setThinking(true)
      try {
        // only the words go back as history. failed turns are left out
        const history = next
          .filter((turn) => !turn.failed && turn.content)
          .map((turn) => ({ role: turn.role, content: turn.content }))
        const answer = await agentChat(history)
        setTurns([...next, { role: 'assistant', content: answer.reply, steps: answer.steps }])
      } catch (error) {
        setTurns([
          ...next,
          { role: 'assistant', content: (error as Error).message, steps: [], failed: true },
        ])
      } finally {
        setThinking(false)
      }
    },
    [thinking, turns],
  )

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void send(draft)
  }

  return (
    <div className="agent">
      <div className="agent__intro">
        <h1>Shopping agent</h1>
        <p className="hero__sub">
          A Claude agent that can only see stores connected here. It picks the item, our code
          works out the price from the verified spec and pays with a saved PayPal sandbox wallet.
        </p>
      </div>

      <div className="chat">
        {turns.length === 0 && (
          <div className="chat__empty">
            <p className="faint">Ask it to buy something from a connected store.</p>
            <button className="button" onClick={() => void send(DEMO_PROMPT)}>
              {DEMO_PROMPT}
            </button>
          </div>
        )}
        {turns.map((turn, index) => (
          <div key={index} className={'turn turn--' + turn.role + (turn.failed ? ' turn--failed' : '')}>
            <div className="turn__who">{turn.role === 'user' ? 'You' : 'Agent'}</div>
            <div className="turn__body">
              <Steps steps={turn.steps} />
              <p>{turn.content}</p>
            </div>
          </div>
        ))}
        {thinking && (
          <div className="turn turn--assistant">
            <div className="turn__who">Agent</div>
            <div className="turn__body faint">
              <span className="spin" aria-hidden="true">⟳</span> Shopping...
            </div>
          </div>
        )}
        <div ref={end} />
      </div>

      <form className="urlform" onSubmit={onSubmit}>
        <input
          className="input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="What should the agent buy?"
          aria-label="Message to the shopping agent"
          maxLength={4000}
        />
        <button className="button button--primary" type="submit" disabled={thinking || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
