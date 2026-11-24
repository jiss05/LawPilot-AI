import { useEffect, useState } from 'react'
import { Users, RefreshCw, Search } from 'lucide-react'

import api from '../../services/api'
import './AdminUsers.css'

function AdminUsers() {
  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchUsers = async () => {
    setLoading(true)
    setError('')

    try {
      const response = await api.get('/users/admin/list', {
        params: {
          search: search || undefined,
          role: role || undefined,
          limit: 100,
          offset: 0,
        },
      })

      setUsers(response.data.users)
      setTotal(response.data.total)
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Unable to load users. Please try again.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
  }, [search, role])

  return (
    <div className="admin-users-page">
      <div className="admin-users-heading">
        <div>
          <h1>User Management</h1>
          <p>View and manage registered LawPilot AI users.</p>
        </div>

        <button
          className="users-refresh-button"
          onClick={fetchUsers}
          disabled={loading}
        >
          <RefreshCw size={16} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="users-summary-card">
        <div className="users-summary-icon">
          <Users size={22} />
        </div>

        <div>
          <span className="users-summary-label">Total Users</span>
          <h2>{loading ? '...' : total}</h2>
        </div>
      </div>

      <div className="users-toolbar">
        <div className="users-search">
          <Search size={18} />

          <input
            type="text"
            placeholder="Search by name or email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="">All Roles</option>
          <option value="CLIENT">Client</option>
          <option value="LAWYER">Lawyer</option>
          <option value="JUDGE">Judge</option>
          <option value="ADMIN">Admin</option>
        </select>
      </div>

      {error && (
        <div className="users-error">
          {error}
        </div>
      )}

      <div className="users-table-container">
        <table className="users-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Professional ID</th>
              <th>Email Verification</th>
              <th>Account Status</th>
              <th>Registered</th>
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6" className="users-message">
                  Loading users...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan="6" className="users-message">
                  No users found.
                </td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <div className="user-info">
                      <div className="user-avatar">
                        {user.display_name?.charAt(0).toUpperCase() || 'U'}
                      </div>

                      <div className="user-details">
                        <span className="user-name">
                          {user.display_name}
                        </span>

                        <span className="user-email">
                          {user.email}
                        </span>
                      </div>
                    </div>
                  </td>

                  <td>
                    <span className={`role-badge role-${user.role?.toLowerCase()}`}>
                      {user.role}
                    </span>

                    {user.roles?.length > 1 && (
                      <div className="additional-roles">
                        {user.roles
                          .filter((r) => r !== user.role)
                          .join(', ')}
                      </div>
                    )}
                  </td>

                  <td>
                    {user.professional_id || '—'}
                  </td>

                  <td>
                    <span
                      className={`verification-badge ${
                        user.email_verified ? 'verified' : 'unverified'
                      }`}
                    >
                      {user.email_verified ? 'Verified' : 'Not verified'}
                    </span>
                  </td>

                  <td>
                    <span
                      className={`account-status ${
                        user.is_active ? 'active' : 'inactive'
                      }`}
                    >
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>

                  <td>
                    {user.created_at
                      ? new Date(user.created_at).toLocaleDateString()
                      : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default AdminUsers