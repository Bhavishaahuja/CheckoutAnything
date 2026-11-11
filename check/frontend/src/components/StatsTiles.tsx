// The numbers row above the orders grid, from GET /stats. The last tile is the rubber-stamp
// watch: the Approval Trap made visible, so the merchant can see when approvals stopped being looks.

import { Zap } from 'lucide-react'
import { Card, ErrorNote } from '@/components/bits'
import { cn } from '@/lib/utils'
import { formatDuration } from '../lib/format'
import type { AsyncState } from '../lib/useAsync'
import type { Stats } from '../types'

// fast approvals in a row that turn the watch on. rubber_stamp.STREAK_TO_TRIGGER on the backend,
// the API doesn't send it, see docs/api.md
const STREAK_TO_TRIGGER = 3

interface StatsTilesProps {
  stats: AsyncState<Stats>
}

export function StatsTiles({ stats }: StatsTilesProps) {
  if (stats.status === 'loading') {
    // the same footprint as the tiles, so the grid doesn't jump when they arrive
    return (
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-[repeat(6,minmax(0,1fr))_minmax(260px,1.8fr)]" aria-hidden="true">
        {[0, 1, 2, 3, 4, 5, 6].map((index) => (
          <div key={index} className="h-[92px] animate-pulse rounded-xl border border-border bg-muted" />
        ))}
      </div>
    )
  }
  if (stats.status === 'error') {
    // the grid below still works without these, so a quiet note is enough
    return <ErrorNote>Couldn't load the numbers: {stats.error.message}</ErrorNote>
  }

  const data = stats.data
  const tiles: { label: string; value: string; note?: string }[] = [
    { label: 'Orders', value: String(data.total_orders) },
    { label: 'Auto-captured', value: String(data.auto_captured), note: 'no human needed' },
    { label: 'Needs review', value: String(data.needs_review), note: 'money on hold' },
    { label: 'Approved', value: String(data.approved), note: 'by a human' },
    { label: 'Voided', value: String(data.voided), note: 'never charged' },
    {
      label: 'Median time to decide',
      value: data.median_decision_ms === null ? 'None yet' : formatDuration(data.median_decision_ms),
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-[repeat(6,minmax(0,1fr))_minmax(260px,1.8fr)]">
      {tiles.map((tile) => (
        <Card key={tile.label} className="p-3.5">
          <p className="text-xs font-medium text-muted-foreground">{tile.label}</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{tile.value}</p>
          {tile.note && <p className="mt-0.5 text-xs text-muted-foreground">{tile.note}</p>}
        </Card>
      ))}
      <WatchTile stats={data} />
    </div>
  )
}

// the rubber-stamp watch, in the words and chips of the strip above the Checkout Anything Orders grid
function WatchTile({ stats }: { stats: Stats }) {
  const active = stats.rubber_stamp_active
  const threshold = formatDuration(stats.fast_threshold_ms)
  // the streak can run past 3, the dots only need to show progress toward turning on
  const filled = Math.min(stats.fast_streak, STREAK_TO_TRIGGER)

  const dots = []
  for (let index = 0; index < STREAK_TO_TRIGGER; index += 1) {
    dots.push(
      <span
        key={index}
        className={cn('h-1.5 flex-1 rounded-full', index < filled ? 'bg-warn' : 'bg-border')}
      />,
    )
  }

  return (
    <Card className={cn('col-span-2 flex flex-col gap-2 p-3.5 sm:col-span-3 xl:col-span-1', active && 'border-warn/40 bg-warn-soft/40')}>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Zap className="size-3.5" aria-hidden /> Rubber-stamp watch
        </p>
        <span
          role="status"
          className={cn(
            'flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[13px] whitespace-nowrap',
            active ? 'bg-warn-soft font-medium text-warn' : 'bg-muted text-muted-foreground',
          )}
        >
          <span className={cn('size-1.5 rounded-full', active ? 'bg-warn' : 'bg-muted-foreground/50')} aria-hidden />
          {active ? 'Sharp mode on: asking less, but sharper' : 'Sharp mode off'}
        </span>
      </div>
      <div className="flex gap-1" role="img" aria-label={filled + ' of ' + STREAK_TO_TRIGGER + ' fast approvals in a row'}>
        {dots}
      </div>
      <p className="text-xs text-muted-foreground">
        {active
          ? 'The last ' + stats.fast_streak + ' approvals took under ' + threshold + '. Check now asks less often, but more pointedly.'
          : filled + ' of ' + STREAK_TO_TRIGGER + ' approvals in a row under ' + threshold + '. Turns on at ' + STREAK_TO_TRIGGER + '.'}
      </p>
    </Card>
  )
}
