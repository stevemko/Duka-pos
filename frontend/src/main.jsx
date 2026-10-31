import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/space-grotesk'
import '@fontsource-variable/manrope'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Only the built app registers a worker: during development Vite rewrites the
// bundle on every save, and a cached shell would keep serving yesterday's code.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
      // Without the worker the till still works on a live connection, and there
      // is nothing a cashier can do about a browser that blocks it.
    })
  })
}
