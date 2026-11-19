import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  BookOpen,
  UserCircle,
  LogOut,
  Scale,
} from 'lucide-react'

import './AdminLayout.css'

function AdminLayout() {
  const navigate = useNavigate()

  const handleLogout = () => {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  const menuItems = [
    { name: 'Overview', path: '/admin', icon: LayoutDashboard },
    { name: 'User Management', path: '/admin/users', icon: Users },
    { name: 'Legal Sources', path: '/admin/legal-sources', icon: BookOpen },
    { name: 'Profile', path: '/admin/profile', icon: UserCircle },
  ]

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="sidebar-brand">
          <Scale size={26} />
          <div>
            <h2>LawPilot AI</h2>
            <span>Administration</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <p className="sidebar-section-title">MAIN MENU</p>

          {menuItems.map((item) => {
            const Icon = item.icon

            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/admin'}
                className={({ isActive }) =>
                  isActive ? 'nav-item active' : 'nav-item'
                }
              >
                <Icon size={19} />
                <span>{item.name}</span>
              </NavLink>
            )
          })}
        </nav>

        <button className="logout-button" onClick={handleLogout}>
          <LogOut size={19} />
          <span>Logout</span>
        </button>
      </aside>

      <div className="admin-main">
        <header className="admin-topbar">
          <div>
            <span className="topbar-label">ADMINISTRATOR</span>
            <h3>Admin Dashboard</h3>
          </div>

          <div className="admin-user">
            <div className="admin-avatar">A</div>
            <span>Admin</span>
          </div>
        </header>

        <main className="admin-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default AdminLayout