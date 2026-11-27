
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  UserCircle,
  LogOut,
  Scale,
  FileText,
} from 'lucide-react'

import { useEffect, useState } from 'react'
import api from '../services/api'
import './RoleLayout.css'

function RoleLayout({ role }) {
  const navigate = useNavigate()
  const [user, setUser] = useState(null)

  const roleNames = {
    client: 'Client',
    lawyer: 'Lawyer',
    judge: 'Judge',
  }

  const currentRole = roleNames[role]

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await api.get('/users/me')
        setUser(response.data)
      } catch (error) {
        console.error('Unable to load user information:', error)
      }
    }

    fetchUser()
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('access_token')
    navigate('/login', { replace: true })
  }

  const menuItems = [
    {
      name: 'Dashboard',
      path: `/${role}`,
      icon: LayoutDashboard,
    },
    ...(role === 'lawyer'
      ? [{ name: 'Drafts', path: '/lawyer/drafts', icon: FileText }]
      : []),
    {
      name: 'Profile',
      path: `/${role}/profile`,
      icon: UserCircle,
    },
  ]

  const displayName =
    user?.display_name || user?.full_name || currentRole

  return (
    <div className="role-layout">
      <aside className="role-sidebar">
        <div className="role-sidebar-brand">
          <Scale size={26} />
          <div>
            <h2>LawPilot AI</h2>
            <span>{currentRole} Portal</span>
          </div>
        </div>

        <nav className="role-sidebar-nav">
          <p className="role-sidebar-section-title">MAIN MENU</p>

          {menuItems.map((item) => {
            const Icon = item.icon

            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === `/${role}`}
                className={({ isActive }) =>
                  isActive
                    ? 'role-nav-item active'
                    : 'role-nav-item'
                }
              >
                <Icon size={19} />
                <span>{item.name}</span>
              </NavLink>
            )
          })}
        </nav>

        <button
          className="role-logout-button"
          onClick={handleLogout}
        >
          <LogOut size={19} />
          <span>Logout</span>
        </button>
      </aside>

      <div className="role-main">
        <header className="role-topbar">
          <div>
            <span className="role-topbar-label">
              {currentRole.toUpperCase()}
            </span>
            <h3>{currentRole} Dashboard</h3>
          </div>

          <div className="role-user">
            <div className="role-avatar">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <span>{displayName}</span>
          </div>
        </header>

        <main className="role-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default RoleLayout
