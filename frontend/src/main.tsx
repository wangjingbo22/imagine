import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './styles/premium.css'
import './styles/white-web.css'
import './styles/motion.css'
import App from './App.tsx'
import { AccountSessionProvider } from './session/AccountSessionProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AccountSessionProvider>
        <App />
      </AccountSessionProvider>
    </BrowserRouter>
  </StrictMode>,
)
