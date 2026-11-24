import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom'

import LoginPage from './pages/LoginPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import VerifyEmailPage from './pages/VerifyEmailPage.jsx'

import AdminLayout from './components/AdminLayout.jsx'
import AdminOverview from './pages/admin/AdminOverview.jsx'
import AdminUsers from './pages/admin/AdminUsers.jsx'
import AdminLegalSources from './pages/admin/AdminLegalSources.jsx'
import AdminProfile from './pages/admin/AdminProfile.jsx'

import './App.css'

function PlaceholderPage({ title }) {
  return (
    <div>
      <h1>{title}</h1>
      <p>This section is under development.</p>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Authentication pages */}
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />

        {/* Admin dashboard */}
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminOverview />} />

          <Route
            path="users"
            element={<AdminUsers />}
          />

          <Route
            path="legal-sources"
            element={<AdminLegalSources />}
          />

          <Route
            path="profile"
            element={<AdminProfile />}
          />
        </Route>

        {/* Client dashboard */}
        <Route
          path="/client"
          element={<PlaceholderPage title="Client Dashboard" />}
        />

        {/* Lawyer dashboard */}
        <Route
          path="/lawyer"
          element={<PlaceholderPage title="Lawyer Dashboard" />}

        />

        {/* Judge dashboard */}
        <Route
          path="/judge"
          element={<PlaceholderPage title="Judge Dashboard" />}
        />



        {/* Unknown URLs */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App