// Display helpers. Money arrives as decimal strings ("109.00"), times as ISO strings.

import type { OrderItem } from '../types'

const moneyFormatters = new Map<string, Intl.NumberFormat>()

export function formatMoney(value: string | null, currency = 'USD'): string {
  if (value === null) {
    return 'No cap'
  }
  let formatter = moneyFormatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency })
    moneyFormatters.set(currency, formatter)
  }
  return formatter.format(Number(value))
}

const timeFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

export function formatTime(iso: string): string {
  return timeFormatter.format(new Date(iso))
}

export function describeItem(item: OrderItem): string {
  // same idea as item_display_name in the backend: "Ridgeline trail runner, slate, size women's 8"
  const parts = [item.name]
  if (item.color) {
    parts.push(item.color)
  }
  if (item.size) {
    parts.push('size ' + item.size)
  }
  return parts.join(', ')
}

export function summarizeItems(items: OrderItem[]): string {
  if (items.length === 0) {
    return 'No items'
  }
  const first = items[0]
  const label = first.quantity > 1 ? first.quantity + ' x ' + first.name : first.name
  if (items.length === 1) {
    return label
  }
  return label + ' + ' + (items.length - 1) + ' more'
}
