import { MotionConfig } from "motion/react"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* motion follows the system setting for reduced motion, everywhere */}
    <MotionConfig reducedMotion="user">
      <App />
    </MotionConfig>
  </StrictMode>
)
