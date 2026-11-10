export function money(amount: string | number, currency = "USD") {
  const value = typeof amount === "string" ? Number(amount) : amount
  if (Number.isNaN(value)) return String(amount)
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value)
}

export function clockTime(iso: string | null) {
  if (!iso) return ""
  const date = new Date(iso)
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })
}

export function hostAndPath(url: string) {
  try {
    const parsed = new URL(url)
    return parsed.host + parsed.pathname.replace(/\/$/, "")
  } catch {
    return url
  }
}
