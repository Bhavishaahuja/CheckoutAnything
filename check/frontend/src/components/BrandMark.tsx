// Small mark: a ring with a short tether, i.e. something held, not locked.
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="2.2" />
      <path d="M13 13 L19.5 19.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="19.5" cy="19.5" r="1.8" fill="currentColor" />
    </svg>
  )
}
