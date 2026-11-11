// The title block every merchant page opens with, and the card a page shows while loading, when
// something failed, or when there's nothing yet. Built from the shared bits so every page in the
// Check app looks like the Checkout Anything app.

import { LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card, ErrorNote } from '@/components/bits'

export function PageHead({ title, lede, actions }: { title: string; lede: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-pretty text-muted-foreground">{lede}</p>
      </div>
      {actions}
    </div>
  )
}

export function StateCard({ kind, children }: { kind: 'loading' | 'error' | 'empty'; children: ReactNode }) {
  if (kind === 'error') {
    return (
      <Card className="p-4">
        <ErrorNote>{children}</ErrorNote>
      </Card>
    )
  }
  return (
    <Card className="px-4 py-10">
      <p className="flex items-center justify-center gap-2 text-center text-sm text-muted-foreground" role="status">
        {kind === 'loading' && <LoaderCircle className="spin-slow size-4 shrink-0" aria-hidden />}
        {children}
      </p>
    </Card>
  )
}
