// The one header both frontends wear, so Checkout Anything and Check feel like one product:
// the mark, the name, and the same four links in the same order. Connect and Orders live in the
// Checkout Anything app, Check lives in the Check app, and each app links across to the other
// with a URL from its env (VITE_CHECK_URL here, VITE_CONNECT_URL there).
//
// This file and app-header.css exist twice, in frontend/src/components and in
// check/frontend/src/components, and have to stay identical (CI compares them). Anything that
// belongs to one app only, like its reset button, comes in through `tools`.

import type { MouseEvent, ReactNode } from "react"

import { BrandMark } from "./BrandMark"
import "./app-header.css"

export type Section = "connect" | "orders" | "check" | "disputes"

export interface HeaderLink {
  // always a real URL, so open-in-new-tab and copy-link work
  href: string
  // set when the section is inside this app: a plain click switches screens without a page load
  onNavigate?: () => void
}

const SECTIONS: { id: Section; label: string }[] = [
  { id: "connect", label: "Connect" },
  { id: "orders", label: "Orders" },
  { id: "check", label: "Check" },
  { id: "disputes", label: "Disputes" },
]

function navigate(event: MouseEvent<HTMLAnchorElement>, link: HeaderLink) {
  // leave ctrl/cmd/shift/middle clicks to the browser
  if (!link.onNavigate || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return
  }
  event.preventDefault()
  link.onNavigate()
}

export function AppHeader({
  current,
  links,
  tools,
  children,
}: {
  // the section to highlight, or null on a screen that is none of the four
  current: Section | null
  links: Record<Section, HeaderLink>
  // this app's own controls, on the right
  tools?: ReactNode
  // strips under the bar, like a notice or a confirm
  children?: ReactNode
}) {
  return (
    <header className="ca-header">
      <div className="ca-header__bar">
        <a className="ca-header__brand" href={links.connect.href} onClick={(event) => navigate(event, links.connect)}>
          <BrandMark size={24} />
          <span className="ca-header__name">Checkout Anything</span>
        </a>

        <nav className="ca-header__nav" aria-label="Sections">
          {SECTIONS.map((section) => (
            <a
              key={section.id}
              className="ca-header__link"
              href={links[section.id].href}
              aria-current={current === section.id ? "page" : undefined}
              onClick={(event) => navigate(event, links[section.id])}
            >
              {section.label}
            </a>
          ))}
        </nav>

        {tools && <div className="ca-header__tools">{tools}</div>}
      </div>
      {children}
    </header>
  )
}
