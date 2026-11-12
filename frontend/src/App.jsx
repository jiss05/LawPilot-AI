import LoginPage from './pages/LoginPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import VerifyEmailPage from './pages/VerifyEmailPage.jsx'
import './App.css'

function App() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'

  if (path === '/register') {
    return <RegisterPage />
  }

  if (path === '/verify-email') {
    return <VerifyEmailPage />
  }

  return <LoginPage />
}

export default App
