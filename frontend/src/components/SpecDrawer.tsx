import { useEffect, useState, type ReactNode } from 'react'
import { getSpec } from '../api'
import type { Run, SpecItem, SpecResponse } from '../types'

interface Props {
  storeId: number
  itemId: string
  // changes when the run moves on, so the drawer reloads
  refreshKey: number
  onClose: () => void
}

interface ItemVersion {
  version: number
  note: string
  item: SpecItem
}

// the versions of the spec in which this one item actually changed
function itemHistory(spec: SpecResponse, itemId: string): ItemVersion[] {
  const history: ItemVersion[] = []
  let previous = ''
  for (const version of spec.versions) {
    const item = version.spec.items.find((one) => one.id === itemId)
    if (!item) continue
    const asText = JSON.stringify(item)
    if (asText !== previous) {
      history.push({ version: version.version, note: version.note, item })
      previous = asText
    }
  }
  return history
}

// the item as JSON, with the source_quote value marked
function highlightedJson(item: SpecItem): ReactNode {
  const text = JSON.stringify(item, null, 2)
  const quote = JSON.stringify(item.source_quote)
  const at = text.indexOf(quote)
  if (at === -1) return text
  return (
    <>
      {text.slice(0, at)}
      <mark>{quote}</mark>
      {text.slice(at + quote.length)}
    </>
  )
}

function describeRun(run: Run): string {
  if (run.ok) return 'Passed. PayPal order ' + run.paypal_order_id
  return run.reason ?? 'Failed'
}

export default function SpecDrawer({ storeId, itemId, refreshKey, onClose }: Props) {
  const [spec, setSpec] = useState<SpecResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getSpec(storeId)
      .then((loaded) => {
        if (!cancelled) {
          setSpec(loaded)
          setError(null)
        }
      })
      .catch((failure: Error) => {
        if (!cancelled) setError(failure.message)
      })
    return () => {
      cancelled = true
    }
  }, [storeId, itemId, refreshKey])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const item = spec?.spec?.items.find((one) => one.id === itemId) ?? null
  const history = spec ? itemHistory(spec, itemId) : []
  const runs = spec ? spec.runs.filter((run) => run.item_id === itemId) : []

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Item spec">
        <div className="drawer__head">
          <div>
            <div className="eyebrow">store_spec item</div>
            <h2>{item?.name ?? itemId}</h2>
          </div>
          <button className="button button--quiet" onClick={onClose}>
            Close
          </button>
        </div>

        {error && <div className="banner banner--bad">{error}</div>}
        {!spec && !error && <p className="faint">Loading...</p>}

        {item && (
          <>
            <section className="drawer__section">
              <h3>What Claude wrote</h3>
              <pre className="json">{highlightedJson(item)}</pre>
              <p className="hint">
                The highlighted <code>source_quote</code> has to appear on the page, and the
                price in it has to equal <code>unit_price</code>. Fixed code checks that, then
                creates a real PayPal sandbox order to check the amount, currency and name.
              </p>
            </section>

            <section className="drawer__section">
              <h3>Verification attempts</h3>
              {runs.length === 0 && <p className="faint">Not checked yet.</p>}
              <ol className="attempts">
                {runs.map((run, index) => (
                  <li key={index} className={run.ok ? 'attempt attempt--ok' : 'attempt attempt--bad'}>
                    <span className="attempt__label">
                      {run.attempt === 0 ? 'First try' : 'After repair ' + run.attempt}
                    </span>
                    <span>{describeRun(run)}</span>
                  </li>
                ))}
              </ol>
            </section>

            {history.length > 1 && (
              <section className="drawer__section">
                <h3>Version history</h3>
                {history.map((entry) => (
                  <details key={entry.version} className="version">
                    <summary>
                      Spec v{entry.version}: {entry.note}, price {entry.item.unit_price}
                    </summary>
                    <pre className="json">{JSON.stringify(entry.item, null, 2)}</pre>
                  </details>
                ))}
              </section>
            )}
          </>
        )}

        {spec && spec.extraction_notes.length > 0 && (
          <section className="drawer__section">
            <h3>Extraction notes for the whole store</h3>
            <ul className="notes">
              {spec.extraction_notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </>
  )
}
