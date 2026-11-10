import type { ICellRendererParams } from 'ag-grid-community'
import type { CatalogRow, CheckState, Order, RowStatus } from '../types'

const CHECK_LABEL: Record<CheckState, string> = {
  pending: 'Waiting',
  ok: 'Passed',
  fail: 'Failed',
  skipped: 'Not run',
}

const CHECK_ICON: Record<CheckState, string> = {
  pending: '·',
  ok: '✓',
  fail: '✗',
  skipped: '–',
}

export function CheckCell(params: ICellRendererParams<CatalogRow, CheckState>) {
  const state = params.value ?? 'pending'
  return (
    <span className={'check check--' + state}>
      <span aria-hidden="true">{CHECK_ICON[state]}</span> {CHECK_LABEL[state]}
    </span>
  )
}

const STATUS_LABEL: Record<RowStatus, string> = {
  queued: 'Queued',
  checking: 'Checking',
  repairing: 'Repairing',
  verified: 'Verified',
  failed: 'Failed',
  unavailable: 'Unavailable',
}

const STATUS_ICON: Record<RowStatus, string> = {
  queued: '·',
  checking: '⟳',
  repairing: '⟳',
  verified: '✓',
  failed: '✗',
  unavailable: '–',
}

export function StatusCell(params: ICellRendererParams<CatalogRow, RowStatus>) {
  const status = params.value ?? 'queued'
  const busy = status === 'checking' || status === 'repairing'
  return (
    <span className={'pill pill--' + status} title={params.data?.reason ?? undefined}>
      <span className={busy ? 'spin' : undefined} aria-hidden="true">
        {STATUS_ICON[status]}
      </span>{' '}
      {STATUS_LABEL[status]}
    </span>
  )
}

export function MonoCell(params: ICellRendererParams) {
  if (!params.value) return <span className="faint">–</span>
  return <span className="mono">{params.value}</span>
}

export function OrderStatusCell(params: ICellRendererParams<Order, string>) {
  const captured = params.value === 'captured'
  return (
    <span
      className={'pill pill--' + (captured ? 'verified' : 'failed')}
      title={params.data?.error ?? undefined}
    >
      <span aria-hidden="true">{captured ? '✓' : '✗'}</span> {captured ? 'Captured' : 'Failed'}
    </span>
  )
}

export function CreatedByCell(params: ICellRendererParams<Order, string>) {
  const agent = params.value === 'agent'
  return <span className={'tag' + (agent ? ' tag--agent' : '')}>{agent ? 'Agent' : 'Manual'}</span>
}
