
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom'

import LoginPage from './pages/LoginPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import VerifyEmailPage from './pages/VerifyEmailPage.jsx'

// Admin components
import AdminLayout from './components/AdminLayout.jsx'
import AdminOverview from './pages/admin/AdminOverview.jsx'
import AdminUsers from './pages/admin/AdminUsers.jsx'
import AdminLegalSources from './pages/admin/AdminLegalSources.jsx'
import AdminProfile from './pages/admin/AdminProfile.jsx'

// Shared role components
import RoleLayout from './components/RoleLayout.jsx'
import RoleProfile from './components/RoleProfile.jsx'

// Client pages
import ClientDashboard from './pages/client/ClientDashboard.jsx'

// Lawyer pages
import LawyerDashboard from './pages/lawyer/LawyerDashboard.jsx'

// Judge pages
import JudgeDashboard from './pages/judge/JudgeDashboard.jsx'
import ForgotPasswordPage from './pages/ForgotPasswordPage.jsx'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Authentication pages */}
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />

        {/* Admin dashboard */}
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminOverview />} />
          <Route path="users" element={<AdminUsers />} />
          <Route path="legal-sources" element={<AdminLegalSources />} />
          <Route path="profile" element={<AdminProfile />} />
        </Route>

        {/* Client dashboard */}
        <Route
          path="/client"
          element={<RoleLayout role="client" />}
        >
          <Route index element={<ClientDashboard />} />
          <Route path="profile" element={<RoleProfile />} />
        </Route>

        {/* Lawyer dashboard */}
        <Route
          path="/lawyer"
          element={<RoleLayout role="lawyer" />}
        >
          <Route index element={<LawyerDashboard />} />
          <Route path="profile" element={<RoleProfile />} />
        </Route>

        {/* Judge dashboard */}
        <Route
          path="/judge"
          element={<RoleLayout role="judge" />}
        >
          <Route index element={<JudgeDashboard />} />
          <Route path="profile" element={<RoleProfile />} />
        </Route>

        {/* Unknown URLs */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
