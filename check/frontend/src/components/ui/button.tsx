// copied from frontend/src/components/ui/button.tsx, keep in sync

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:opacity-90",
        outline: "border border-border bg-card hover:bg-muted",
        ghost: "hover:bg-muted",
        danger: "bg-bad text-white hover:opacity-90 dark:text-background",
        // a go-ahead that moves money, like Check's Approve
        ok: "bg-ok text-white hover:opacity-90 dark:text-background",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-2.5 text-[13px]",
        lg: "h-11 px-5",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
)

export interface ButtonProps
  extends React.ComponentProps<"button">, VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
