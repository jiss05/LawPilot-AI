import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  Users,
  Scale,
  BookOpen,
  FileText,
  Clock,
  RefreshCw,
  UserRound,
  Gavel,
  ShieldCheck,
} from 'lucide-react'

import api from '../../services/api'
import './AdminOverview.css'

function AdminOverview() {
  const navigate = useNavigate()

  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchDashboard = async () => {
    setLoading(true)
    setError('')

    try {
      const response = await api.get('/admin/dashboard')
      setStats(response.data.stats)
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          'Unable to load dashboard statistics. Please try again.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDashboard()
  }, [])

  const statCards = [
    {
      title: 'Total Users',
      value: stats?.total_users,
      description: 'All registered accounts',
      icon: Users,
    },
    {
      title: 'Clients',
      value: stats?.clients,
      description: 'Registered client accounts',
      icon: UserRound,
    },
    {
      title: 'Lawyers',
      value: stats?.lawyers,
      description: 'Registered legal professionals',
      icon: Scale,
    },
    {
      title: 'Judges',
      value: stats?.judges,
      description: 'Registered judges',
      icon: Gavel,
    },
    {
      title: 'Admins',
      value: stats?.admins,
      description: 'Administrative accounts',
      icon: ShieldCheck,
    },
    {
      title: 'Legal Sources',
      value: stats?.legal_sources,
      description: 'Sources in the registry',
      icon: BookOpen,
    },
    {
      title: 'Documents',
      value: stats?.documents,
      description: 'Registered legal documents',
      icon: FileText,
    },
  ]

  const documentStatuses = stats?.documents_by_status || {}

  return (
    <div className="overview-page">
      <div className="overview-heading">
        <div>
          <h1>Overview</h1>
          <p>Welcome to the LawPilot AI administration panel.</p>
        </div>

        <button
          className="overview-refresh-button"
          onClick={fetchDashboard}
          disabled={loading}
        >
          <RefreshCw size={16} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="overview-error">
          {error}
        </div>
      )}

      <div className="stats-grid">
        {statCards.map((stat) => {
          const Icon = stat.icon

          return (
            <div className="stat-card" key={stat.title}>
              <div className="stat-card-top">
                <div className="stat-icon">
                  <Icon size={21} />
                </div>
              </div>

              <h3>{stat.title}</h3>

              <div className="stat-value">
                {loading ? '...' : stat.value ?? 0}
              </div>

              <p>{stat.description}</p>
            </div>
          )
        })}
      </div>

      <div className="overview-bottom-grid">
        <section className="overview-panel">
          <div className="panel-heading">
            <h2>System Overview</h2>
          </div>

          <div className="system-row">
            <div>
              <span className="system-label">Backend API</span>
              <span className="system-description">
                FastAPI application
              </span>
            </div>
            <span className="status-badge">Configured</span>
          </div>

          <div className="system-row">
            <div>
              <span className="system-label">Database</span>
              <span className="system-description">
                PostgreSQL
              </span>
            </div>
            <span className="status-badge">Configured</span>
          </div>

          <div className="system-row">
            <div>
              <span className="system-label">Authentication</span>
              <span className="system-description">
                JWT authentication
              </span>
            </div>
            <span className="status-badge">Configured</span>
          </div>

          <div className="system-row">
            <div>
              <span className="system-label">Document Processing</span>
              <span className="system-description">
                Pending documents
              </span>
            </div>
            <span className="status-badge">
              {loading ? '...' : documentStatuses.pending ?? 0}
            </span>
          </div>
        </section>

        <section className="overview-panel">
          <div className="panel-heading">
            <Clock size={19} />
            <h2>Quick Actions</h2>
          </div>

          <div className="quick-actions">
            <button
              onClick={() => navigate('/admin/legal-sources')}
            >
              <BookOpen size={18} />
              Manage Legal Sources
            </button>

            <button
              onClick={() => navigate('/admin/users')}
            >
              <Users size={18} />
              Manage Users
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}

export default AdminOverview