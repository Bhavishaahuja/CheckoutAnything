// The path a store takes, drawn with Magic UI's AnimatedBeam. The beam runs along whichever
// hop is happening right now, and runs backwards while Claude is repairing an item.

import { Bot, FileJson2, Globe, ShieldCheck, Wallet } from "lucide-react"
import { useRef, type ReactNode, type RefObject } from "react"

import { AnimatedBeam } from "@/components/magicui/animated-beam"
import type { Stage } from "@/lib/run"
import { cn } from "@/lib/utils"

function Node({
  nodeRef,
  icon,
  title,
  hint,
  active,
  done,
}: {
  nodeRef: RefObject<HTMLDivElement | null>
  icon: ReactNode
  title: string
  hint: string
  active: boolean
  done: boolean
}) {
  return (
    <div className="z-10 flex w-16 flex-col items-center gap-2 text-center sm:w-28">
      <div
        ref={nodeRef}
        className={cn(
          "flex size-11 items-center justify-center rounded-full border bg-card transition-all duration-500 [&_svg]:size-5",
          active && "border-primary text-primary shadow-[0_0_0_5px_var(--info-soft)]",
          done && !active && "border-ok/50 text-ok",
          !active && !done && "border-border text-muted-foreground"
        )}
      >
        {icon}
      </div>
      <div>
        <div className={cn("text-xs font-medium sm:text-[13px]", !active && !done && "text-muted-foreground")}>
          {title}
        </div>
        <div className="hidden text-[11px] leading-tight text-muted-foreground sm:block">{hint}</div>
      </div>
    </div>
  )
}

const STAGE_ORDER: Stage[] = ["idle", "fetch", "extract", "verify", "ready"]

export function PipelineBeam({ stage, repairing }: { stage: Stage; repairing: boolean }) {
  const container = useRef<HTMLDivElement>(null)
  const page = useRef<HTMLDivElement>(null)
  const claude = useRef<HTMLDivElement>(null)
  const verifier = useRef<HTMLDivElement>(null)
  const paypal = useRef<HTMLDivElement>(null)
  const agents = useRef<HTMLDivElement>(null)

  const position = STAGE_ORDER.indexOf(stage)
  const reached = (wanted: Stage) => position >= STAGE_ORDER.indexOf(wanted)

  // which hops carry a moving beam right now
  const hops = [
    { from: page, to: claude, on: stage === "fetch" || stage === "extract", reverse: false },
    { from: claude, to: verifier, on: stage === "verify", reverse: repairing },
    { from: verifier, to: paypal, on: stage === "verify" && !repairing, reverse: false },
    { from: paypal, to: agents, on: stage === "ready", reverse: false },
  ]

  return (
    <div ref={container} className="relative flex items-start justify-between px-1 py-1">
      <Node nodeRef={page} icon={<Globe />} title="Store page" hint="any URL" active={stage === "fetch"} done={reached("extract")} />
      <Node
        nodeRef={claude}
        icon={<FileJson2 />}
        title="Claude"
        hint={repairing ? "repairing the spec" : "writes spec JSON only"}
        active={stage === "extract" || repairing}
        done={reached("verify")}
      />
      <Node
        nodeRef={verifier}
        icon={<ShieldCheck />}
        title="Verifier"
        hint="fixed, tested code"
        active={stage === "verify" && !repairing}
        done={reached("ready")}
      />
      <Node
        nodeRef={paypal}
        icon={<Wallet />}
        title="PayPal sandbox"
        hint="a real order per item"
        active={stage === "verify" && !repairing}
        done={reached("ready")}
      />
      <Node nodeRef={agents} icon={<Bot />} title="AI agents" hint="can buy now" active={stage === "ready"} done={false} />

      {hops.map((hop, index) => (
        <AnimatedBeam
          key={index + (hop.on ? "-on" : "-off") + (hop.reverse ? "-r" : "")}
          containerRef={container}
          fromRef={hop.from}
          toRef={hop.to}
          reverse={hop.reverse}
          duration={2.2}
          pathColor="var(--muted-foreground)"
          pathOpacity={0.25}
          pathWidth={2}
          gradientStartColor={hop.on ? (hop.reverse ? "var(--warn)" : "var(--primary)") : "transparent"}
          gradientStopColor={hop.on ? (hop.reverse ? "var(--warn)" : "var(--ok)") : "transparent"}
        />
      ))}
    </div>
  )
}
