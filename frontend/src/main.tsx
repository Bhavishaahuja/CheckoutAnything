import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// AG Grid Community only. Nothing here needs an Enterprise licence
ModuleRegistry.registerModules([AllCommunityModule])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
