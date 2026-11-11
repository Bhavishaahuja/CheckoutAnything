// Merchant side of a human review: makes the one-time link for the confirm page and shows it
// so it can be sent to the human. Used in the dashboard's order panel and on /place-order.
//
// The link is only made when the merchant clicks. Every new link kills the old one, so making
// one on page load would break a link already sitting in someone's messages.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { USE_MOCKS, createReviewLink } from '../api'
import { ErrorNote } from '@/components/bits'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '../lib/format'
import type { ReviewLink } from '../types'

// a link that looks like the outline Button
const OUTLINE_LINK =
  'inline-flex h-9 items-center justify-center rounded-lg border border-border bg-card px-3.5 text-sm font-medium whitespace-nowrap transition-colors hover:bg-muted'

type LinkState =
  | { status: 'idle' }
  | { status: 'creating' }
  | { status: 'ready'; link: ReviewLink }
  | { status: 'error'; message: string }

function confirmUrl(token: string): string {
  return window.location.origin + '/confirm/' + encodeURIComponent(token)
}

export function ReviewLinkBox({ orderId }: { orderId: number }) {
  const [state, setState] = useState<LinkState>({ status: 'idle' })
  const [copied, setCopied] = useState(false)
  const copiedTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    return () => window.clearTimeout(copiedTimer.current)
  }, [])

  async function create() {
    setState({ status: 'creating' })
    setCopied(false)
    try {
      const link = await createReviewLink(orderId)
      setState({ status: 'ready', link })
    } catch (error) {
      setState({ status: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      window.clearTimeout(copiedTimer.current)
      copiedTimer.current = window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard blocked (http, or permissions). the link is selectable text, so it can be copied by hand
    }
  }

  if (state.status === 'ready') {
    const url = confirmUrl(state.link.review_token)
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-background p-3">
        <label className="text-[13px] font-medium" htmlFor={'review-link-' + orderId}>
          Send this link to the shopper
        </label>
        <input
          id={'review-link-' + orderId}
          className="h-9 w-full min-w-0 rounded-lg border border-border bg-card px-3 font-mono text-xs outline-none focus:border-primary"
          readOnly
          value={url}
          onFocus={(event) => event.target.select()}
        />
        <div className="flex gap-2">
          <Button onClick={() => copy(url)}>{copied ? 'Copied' : 'Copy link'}</Button>
          {USE_MOCKS ? (
            // mock links live in this tab's memory, so open them here rather than in a new tab
            <Link className={OUTLINE_LINK} to={'/confirm/' + encodeURIComponent(state.link.review_token)}>
              Open
            </Link>
          ) : (
            <a className={OUTLINE_LINK} href={url} target="_blank" rel="noreferrer">
              Open
            </a>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Works once, until {formatDateTime(state.link.expires_at)}. Making a new link turns this one off.{' '}
          <button type="button" className="font-medium text-primary underline-offset-2 hover:underline" onClick={create}>
            Make a new link
          </button>
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <Button className="self-start" onClick={create} disabled={state.status === 'creating'}>
        {state.status === 'creating' ? 'Making link...' : 'Get review link'}
      </Button>
      {state.status === 'error' && <ErrorNote>Couldn't make a link: {state.message}</ErrorNote>}
    </div>
  )
}
