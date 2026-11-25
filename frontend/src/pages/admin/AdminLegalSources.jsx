
import { useEffect, useState } from 'react'
import {
  BookOpen,
  RefreshCw,
  Search,
  Plus,
  X,
  Upload,
} from 'lucide-react'

import api from '../../services/api'
import './AdminLegalSources.css'

function AdminLegalSources() {
  const [sources, setSources] = useState([])
  const [documentsBySource, setDocumentsBySource] = useState({})
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [success, setSuccess] = useState('')

  const [form, setForm] = useState({
    title: '',
    source_type: '',
    jurisdiction: '',
    trust_tier: '',
    visibility: 'public',
    publisher: '',
    canonical_url: '',
    version_label: '',
    published_at: '',
    file: null,
  })

  const fetchSources = async () => {
    setLoading(true)
    setError('')

    try {
      const response = await api.get('/knowledge-sources')
      const loadedSources = response.data

      setSources(loadedSources)

      const documentResults = await Promise.all(
        loadedSources.map(async (source) => {
          try {
            const documentResponse = await api.get(
              `/knowledge-sources/${source.id}/documents`
            )

            return [source.id, documentResponse.data]
          } catch {
            return [source.id, []]
          }
        })
      )

      setDocumentsBySource(
        Object.fromEntries(documentResults)
      )
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Unable to load legal sources.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSources()
  }, [])

  const handleChange = (e) => {
    const { name, value } = e.target

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }))
  }

  const handleFileChange = (e) => {
    const selectedFile = e.target.files?.[0]

    if (!selectedFile) {
      setForm((previous) => ({
        ...previous,
        file: null,
      }))
      return
    }

    if (!selectedFile.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a PDF file.')
      e.target.value = ''
      return
    }

    if (selectedFile.size > 20 * 1024 * 1024) {
      setError('The PDF file must not exceed 20 MB.')
      e.target.value = ''
      return
    }

    setError('')

    setForm((previous) => ({
      ...previous,
      file: selectedFile,
    }))
  }

  const resetForm = () => {
    setForm({
      title: '',
      source_type: '',
      jurisdiction: '',
      trust_tier: '',
      visibility: 'public',
      publisher: '',
      canonical_url: '',
      version_label: '',
      published_at: '',
      file: null,
    })

    setError('')
    setShowForm(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    setError('')
    setSuccess('')

    if (!form.file) {
      setError('Please select a PDF document.')
      return
    }

    const formData = new FormData()

    formData.append('title', form.title.trim())
    formData.append('source_type', form.source_type.trim())
    formData.append('jurisdiction', form.jurisdiction.trim())
    formData.append('trust_tier', form.trust_tier.trim())
    formData.append('visibility', form.visibility)
    formData.append('file', form.file)

    if (form.publisher.trim()) {
      formData.append('publisher', form.publisher.trim())
    }

    if (form.canonical_url.trim()) {
      formData.append('canonical_url', form.canonical_url.trim())
    }

    if (form.version_label.trim()) {
      formData.append('version_label', form.version_label.trim())
    }

    if (form.published_at) {
      formData.append('published_at', form.published_at)
    }

    setUploading(true)

    try {
      await api.post('/knowledge-sources', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      resetForm()
      setSuccess('Legal source registered successfully.')
      await fetchSources()
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Failed to register legal source. Please try again.'
      )
    } finally {
      setUploading(false)
    }
  }

  const getVisibilityLabel = (visibility) => {
    const labels = {
      public: 'Public',
      internal: 'Internal',
      private: 'Private',
    }

    return labels[visibility?.toLowerCase()] || 'Not specified'
  }

  const filteredSources = sources.filter((source) => {
    const searchTerm = search.toLowerCase()

    const sourceMatches =
      source.title?.toLowerCase().includes(searchTerm) ||
      source.publisher?.toLowerCase().includes(searchTerm) ||
      source.jurisdiction?.toLowerCase().includes(searchTerm) ||
      source.source_type?.toLowerCase().includes(searchTerm)

    const documents = documentsBySource[source.id] || []

    const documentMatches = documents.some((document) =>
      document.filename?.toLowerCase().includes(searchTerm) ||
      document.visibility?.toLowerCase().includes(searchTerm)
    )

    return sourceMatches || documentMatches
  })

  return (
    <div className="legal-sources-page">
      <div className="legal-sources-heading">
        <div>
          <h1>Legal Sources</h1>
          <p>Manage official legal sources and registered documents.</p>
        </div>

        <button
          className="legal-sources-refresh"
          onClick={fetchSources}
          disabled={loading}
        >
          <RefreshCw size={16} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="legal-sources-summary">
        <div className="legal-sources-summary-icon">
          <BookOpen size={22} />
        </div>

        <div>
          <span>Total Registered Sources</span>
          <h2>{loading ? '...' : sources.length}</h2>
        </div>
      </div>

      <div className="legal-sources-toolbar">
        <div className="legal-sources-search">
          <Search size={18} />

          <input
            type="text"
            placeholder="Search legal sources or documents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <button
          className="legal-source-add-button"
          onClick={() => {
            setError('')
            setSuccess('')
            setShowForm(true)
          }}
        >
          <Plus size={17} />
          Add Legal Source
        </button>
      </div>

      {success && (
        <div className="legal-sources-success">
          {success}
        </div>
      )}

      {error && !showForm && (
        <div className="legal-sources-error">
          {error}
        </div>
      )}

      {showForm && (
        <div className="legal-source-form-container">
          <div className="legal-source-form-heading">
            <div>
              <h2>Register Legal Source</h2>
              <p>Enter source information and upload its PDF document.</p>
            </div>

            <button
              className="legal-source-close-button"
              type="button"
              onClick={resetForm}
              disabled={uploading}
              title="Close form"
            >
              <X size={20} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="legal-source-form">
            <div className="legal-source-form-grid">
              <div className="form-field">
                <label htmlFor="source-title">Source Title *</label>
                <input
                  id="source-title"
                  name="title"
                  value={form.title}
                  onChange={handleChange}
                  placeholder="e.g. Constitution of India"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-type">Source Type *</label>
                <input
                  id="source-type"
                  name="source_type"
                  value={form.source_type}
                  onChange={handleChange}
                  placeholder="e.g. Constitution, Act, Judgment"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-jurisdiction">Jurisdiction *</label>
                <input
                  id="source-jurisdiction"
                  name="jurisdiction"
                  value={form.jurisdiction}
                  onChange={handleChange}
                  placeholder="e.g. India, Kerala"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-trust-tier">Trust Tier *</label>
                <input
                  id="source-trust-tier"
                  name="trust_tier"
                  value={form.trust_tier}
                  onChange={handleChange}
                  placeholder="e.g. Official, Primary"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-visibility">
                  Document Access Level *
                </label>

                <select
                  id="source-visibility"
                  name="visibility"
                  value={form.visibility}
                  onChange={handleChange}
                  required
                >
                  <option value="public">
                    Public — All authenticated users
                  </option>

                  <option value="internal">
                    Internal — Lawyers and Judges
                  </option>

                  <option value="private">
                    Private — Admin and uploader
                  </option>
                </select>

                <small>
                  Choose which user roles can retrieve this document.
                </small>
              </div>

              <div className="form-field">
                <label htmlFor="source-publisher">Publisher</label>
                <input
                  id="source-publisher"
                  name="publisher"
                  value={form.publisher}
                  onChange={handleChange}
                  placeholder="Publishing authority"
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-url">Official URL</label>
                <input
                  id="source-url"
                  name="canonical_url"
                  type="url"
                  value={form.canonical_url}
                  onChange={handleChange}
                  placeholder="https://..."
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-version">Version Label</label>
                <input
                  id="source-version"
                  name="version_label"
                  value={form.version_label}
                  onChange={handleChange}
                  placeholder="e.g. 2024 amended version"
                />
              </div>

              <div className="form-field">
                <label htmlFor="source-published">Published Date</label>
                <input
                  id="source-published"
                  name="published_at"
                  type="date"
                  value={form.published_at}
                  onChange={handleChange}
                />
              </div>
            </div>

            <div className="form-field file-field">
              <label>PDF Document *</label>

              <label className="pdf-upload-area">
                <Upload size={24} />

                <span>
                  {form.file
                    ? form.file.name
                    : 'Click to select a PDF document'}
                </span>

                <small>PDF format · Maximum size 20 MB</small>

                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={handleFileChange}
                  required={!form.file}
                />
              </label>
            </div>

            {error && (
              <div className="legal-sources-error">
                {error}
              </div>
            )}

            <div className="legal-source-form-actions">
              <button
                type="button"
                className="legal-source-cancel-button"
                onClick={resetForm}
                disabled={uploading}
              >
                Cancel
              </button>

              <button
                type="submit"
                className="legal-source-submit-button"
                disabled={uploading}
              >
                {uploading ? 'Uploading...' : 'Register Source'}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="legal-sources-table-container">
        <table className="legal-sources-table">
          <thead>
            <tr>
              <th>Source Title</th>
              <th>Source Type</th>
              <th>Jurisdiction</th>
              <th>Trust Tier</th>
              <th>Documents & Access Level</th>
              <th>Publisher</th>
              <th>Registered</th>
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <tr>
                <td colSpan="7" className="legal-sources-message">
                  Loading legal sources...
                </td>
              </tr>
            ) : filteredSources.length === 0 ? (
              <tr>
                <td colSpan="7" className="legal-sources-message">
                  {search
                    ? 'No matching legal sources found.'
                    : 'No legal sources have been registered yet.'}
                </td>
              </tr>
            ) : (
              filteredSources.map((source) => {
                const documents = documentsBySource[source.id] || []

                return (
                  <tr key={source.id}>
                    <td>
                      <div className="legal-source-title">
                        {source.title}
                      </div>

                      {source.canonical_url && (
                        <a
                          href={source.canonical_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="legal-source-link"
                        >
                          View official source
                        </a>
                      )}
                    </td>

                    <td>{source.source_type}</td>
                    <td>{source.jurisdiction}</td>

                    <td>
                      <span className="trust-tier-badge">
                        {source.trust_tier}
                      </span>
                    </td>

                    <td>
                      <div className="source-documents-list">
                        {documents.length === 0 ? (
                          <span className="document-empty">
                            No documents found
                          </span>
                        ) : (
                          documents.map((document) => (
                            <div
                              className="source-document-item"
                              key={document.id}
                            >
                              <span className="document-filename">
                                {document.filename}
                              </span>

                              <span
                                className={`visibility-badge visibility-${document.visibility || 'unknown'}`}
                              >
                                {getVisibilityLabel(document.visibility)}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </td>

                    <td>{source.publisher || '—'}</td>

                    <td>
                      {source.created_at
                        ? new Date(source.created_at).toLocaleDateString()
                        : '—'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default AdminLegalSources
