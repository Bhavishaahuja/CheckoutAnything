// The grids' shared Motion pieces. One spring for everything that pops, so the two grids move
// the same way. <MotionConfig reducedMotion="user"> in main.tsx turns the movement off for
// anyone who asked their system for less of it.

import { AnimatePresence, motion } from "motion/react"
import type { ReactNode } from "react"

export const POP = { type: "spring", stiffness: 520, damping: 26 } as const
export const SOFT = { type: "spring", stiffness: 320, damping: 30 } as const

// A number that rolls when it changes: the old one drops out, the new one drops in.
export function CountRoll({ value, className }: { value: number | string; className?: string }) {
  return (
    <span className={"relative inline-flex overflow-hidden align-bottom tabular-nums " + (className || "")}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={value}
          className="inline-block"
          initial={{ y: "-100%", opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: "100%", opacity: 0 }}
          transition={POP}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

// A button wrapper that presses in. The button inside keeps its own semantics.
export function Press({ children, disabled, className }: { children: ReactNode; disabled?: boolean; className?: string }) {
  return (
    <motion.span
      className={"inline-flex " + (className || "")}
      whileHover={disabled ? undefined : { y: -1 }}
      whileTap={disabled ? undefined : { scale: 0.94 }}
      transition={POP}
    >
      {children}
    </motion.span>
  )
}

// Fades and lifts its content in. Used for things that appear: popovers, hints, overlays.
export function Rise({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SOFT, delay }}>
      {children}
    </motion.div>
  )
}
