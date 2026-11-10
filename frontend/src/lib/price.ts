// What counts as a price in an editor. The API does the same check again (review.py), this
// one is here so the mistake shows up while typing, before anything is sent.

const MAX_PRICE = 9_999_999.99

// null when the text is a price, else what is wrong with it
export function priceError(text: string): string | null {
  const cleaned = text.trim().replace(/^\$/, "").replace(/,/g, "").trim()
  if (!cleaned) return "A price can't be blank"
  if (/^-/.test(cleaned)) return "A price can't be negative"
  if (!/^\d*\.?\d+$/.test(cleaned)) return "Use a number, like 29.00"
  const value = Number(cleaned)
  if (value === 0) return "A price has to be above 0.00"
  if (/\.\d{3,}$/.test(cleaned)) return "2 decimals at most"
  if (value > MAX_PRICE) return "That's more than an order can hold"
  return null
}

// "29", "$29.5" -> "29.00", "29.50". only call it on text that passed priceError
export function normalizePrice(text: string): string {
  return Number(text.trim().replace(/^\$/, "").replace(/,/g, "")).toFixed(2)
}
