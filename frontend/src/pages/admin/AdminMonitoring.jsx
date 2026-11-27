import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronRight, LoaderCircle, RefreshCw, RotateCcw } from 'lucide-react'
import {
  getDocumentStatus,
  getEvaluationReport,
  getFeedbackSummary,
  getIngestionSummary,
  getRuntimeStats,
  listEvaluationReports,
  listIngestionJobs,
  listSourceVersions,
  listSources,
  reprocessDocument,
} from '../../services/admin'
import { errorMessage } from '../../services/errors'
import '../../components/Workspace.css'
import './AdminMonitoring.css'

function when(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const secs = (ms) => (ms == null ? '—' : `${(ms / 1000).toFixed(1)} s`)

function Loading({ text = 'Loading...' }) {
  return (
    <div className="ws-loading">
      <LoaderCircle size={16} className="assistant-spinner" /> {text}
    </div>
  )
}

function ErrorBox({ message }) {
  if (!message) return null
  return (
    <div className="ws-alert ws-alert-error" role="alert">
      <AlertCircle size={17} />
      <span>{message}</span>
    </div>
  )
}

function useLoad(loader) {
  const [state, setState] = useState({ loading: true, data: null, error: '' })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let active = true
    loader()
      .then((data) => active && setState({ loading: false, data, error: '' }))
      .catch((err) => active && setState({ loading: false, data: null, error: errorMessage(err) }))
    return () => {
      active = false
    }
  }, [loader, tick])

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: '' }))
    setTick((t) => t + 1)
  }, [])

  return [state, reload]
}

/* ------------------------------------------------------------- ingestion */
function IngestionTab() {
  const loader = useCallback(
    () => Promise.all([getIngestionSummary(), listIngestionJobs({ limit: 25 })]),
    [],
  )
  const [{ loading, data, error }, reload] = useLoad(loader)
  const [message, setMessage] = useState('')

  async function reprocess(documentId) {
    setMessage('')
    try {
      const res = await reprocessDocument(documentId)
      setMessage(res.message || 'Reprocessing started.')
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  if (loading && !data) return <Loading text="Loading ingestion status..." />
  if (error) return <ErrorBox message={error} />
  const [summary, jobs] = data
  const failures = Object.entries(summary.failures_last_24h_by_code || {})

  return (
    <div className="ws-stack">
      <div className="monitor-toolbar">
        <button type="button" className="ws-btn ws-btn-secondary" onClick={reload} disabled={loading}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      <div className="ws-cards">
        <div className="ws-card">
          <span>Documents ready</span>
          <strong>{(summary.documents_by_status.ready || 0) + (summary.documents_by_status.completed || 0)}</strong>
          <small>{Object.entries(summary.documents_by_status).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'none'}</small>
        </div>
        <div className="ws-card">
          <span>In progress</span>
          <strong>{summary.in_progress}</strong>
        </div>
        <div className="ws-card">
          <span>Jobs in last 24 h</span>
          <strong>{Object.values(summary.jobs_last_24h).reduce((a, b) => a + b, 0)}</strong>
          <small>{Object.entries(summary.jobs_last_24h).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'none'}</small>
        </div>
        <div className="ws-card">
          <span>Failed documents</span>
          <strong className={summary.failed_documents.length ? 'ws-fail' : ''}>{summary.failed_documents.length}</strong>
        </div>
        <div className="ws-card">
          <span>Vector store</span>
          <strong className={summary.vector_store?.status === 'ok' ? 'ws-pass' : 'ws-fail'}>
            {summary.vector_store?.status || 'unknown'}
          </strong>
          {summary.vector_store?.points != null && <small>{summary.vector_store.points} vectors</small>}
        </div>
      </div>

      {message && <div className="ws-alert ws-alert-info">{message}</div>}

      <section className="ws-panel">
        <h2>Failed documents</h2>
        {failures.length > 0 && (
          <p className="ws-muted">Failures in the last 24 h: {failures.map(([k, v]) => `${k} (${v})`).join(', ')}</p>
        )}
        {summary.failed_documents.length === 0 ? (
          <p className="ws-empty">No failed documents.</p>
        ) : (
          <table className="ws-table">
            <thead>
              <tr><th>File</th><th>Source</th><th>Error</th><th>Failed</th><th /></tr>
            </thead>
            <tbody>
              {summary.failed_documents.map((d) => (
                <tr key={d.document_id}>
                  <td>{d.filename}</td>
                  <td>{d.source_title || '—'}</td>
                  <td className="monitor-error">{d.last_error || '—'}</td>
                  <td>{when(d.failed_at)}</td>
                  <td>
                    <button type="button" className="ws-btn ws-btn-secondary" onClick={() => reprocess(d.document_id)}>
                      <RotateCcw size={14} /> Retry
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="ws-panel">
        <h2>Recent ingestion jobs</h2>
        {jobs.items.length === 0 ? (
          <p className="ws-empty">No ingestion jobs yet.</p>
        ) : (
          <table className="ws-table">
            <thead>
              <tr><th>File</th><th>Stage</th><th>Status</th><th>Started</th><th>Duration</th><th>Error</th></tr>
            </thead>
            <tbody>
              {jobs.items.map((j) => (
                <tr key={j.id}>
                  <td>{j.filename || '—'}</td>
                  <td>{j.stage || '—'}</td>
                  <td><span className={`monitor-job monitor-job-${j.status}`}>{j.status}</span></td>
                  <td>{when(j.started_at)}</td>
                  <td>{secs(j.duration_ms)}</td>
                  <td className="monitor-error">{j.error_code ? `${j.error_code}: ${j.error_summary || ''}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

/* ------------------------------------------------------------- sources */
function SourceRow({ source }) {
  const [open, setOpen] = useState(false)
  const [versions, setVersions] = useState(null)
  const [status, setStatus] = useState({})
  const [error, setError] = useState('')

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && !versions) {
      try {
        setVersions(await listSourceVersions(source.id))
      } catch (err) {
        setError(errorMessage(err))
      }
    }
  }

  async function check(documentId) {
    try {
      const s = await getDocumentStatus(documentId)
      setStatus((m) => ({ ...m, [documentId]: s }))
    } catch (err) {
      setStatus((m) => ({ ...m, [documentId]: { error: errorMessage(err) } }))
    }
  }

  return (
    <>
      <tr className="monitor-source-row" onClick={toggle}>
        <td>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
        <td><strong>{source.title}</strong></td>
        <td>{source.source_type}</td>
        <td>{source.trust_tier}</td>
        <td>{source.jurisdiction}</td>
      </tr>
      {open && (
        <tr>
          <td />
          <td colSpan={4}>
            {error && <ErrorBox message={error} />}
            {!versions && !error && <Loading text="Loading versions..." />}
            {versions?.length === 0 && <p className="ws-muted">No versions.</p>}
            {versions?.map((v) => (
              <div key={v.id} className="monitor-version">
                <div className="monitor-version-head">
                  <span className={`monitor-vstatus monitor-vstatus-${v.status}`}>{v.status}</span>
                  <strong>{v.version_label || 'Unlabelled edition'}</strong>
                  <span className="ws-muted">
                    published {v.published_at || '—'} · retrieved {when(v.retrieved_at)}
                  </span>
                </div>
                {v.documents.map((d) => {
                  const s = status[d.id]
                  return (
                    <div key={d.id} className="monitor-doc">
                      <span>{d.filename}</span>
                      <span className="ws-muted">{d.processing_status} · {d.chunk_count} chunks · {d.visibility}</span>
                      {s?.error ? (
                        <span className="ws-fail">{s.error}</span>
                      ) : s ? (
                        <span className={s.searchable ? 'ws-pass' : 'ws-fail'}>
                          {s.searchable ? 'Searchable' : 'Not searchable'} · {s.vector_count ?? '?'} vectors indexed
                        </span>
                      ) : (
                        <button type="button" className="ws-btn ws-btn-link" onClick={() => check(d.id)}>
                          Check indexing
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </td>
        </tr>
      )}
    </>
  )
}

function SourcesTab() {
  const [{ loading, data, error }] = useLoad(listSources)
  if (loading) return <Loading text="Loading legal sources..." />
  if (error) return <ErrorBox message={error} />
  return (
    <section className="ws-panel">
      <h2>Source versions and indexing</h2>
      <p className="ws-muted">Open a source to see its editions, documents and whether they are indexed for search.</p>
      {data.length === 0 ? (
        <p className="ws-empty">No legal sources uploaded yet.</p>
      ) : (
        <table className="ws-table">
          <thead>
            <tr><th /><th>Source</th><th>Type</th><th>Trust tier</th><th>Jurisdiction</th></tr>
          </thead>
          <tbody>
            {data.map((s) => <SourceRow key={s.id} source={s} />)}
          </tbody>
        </table>
      )}
    </section>
  )
}

/* ------------------------------------------------------------- evaluation */
const CHECK_LABEL = {
  availability: 'Availability',
  content: 'Content accuracy',
  json: 'Classifier JSON',
  latency: 'Latency (p95)',
}

function EvaluationTab() {
  const loader = useCallback(
    () => Promise.all([listEvaluationReports(), getRuntimeStats(7), getFeedbackSummary()]),
    [],
  )
  const [{ loading, data, error }] = useLoad(loader)
  const [detail, setDetail] = useState(null)
  const [detailError, setDetailError] = useState('')

  async function openReport(name) {
    setDetailError('')
    try {
      setDetail(await getEvaluationReport(name))
    } catch (err) {
      setDetailError(errorMessage(err))
    }
  }

  if (loading) return <Loading text="Loading evaluation results..." />
  if (error) return <ErrorBox message={error} />
  const [reports, runtime, feedback] = data
  const latest = reports[0]

  return (
    <div className="ws-stack">
      <section className="ws-panel">
        <h2>Latest model evaluation</h2>
        {!latest ? (
          <p className="ws-empty">No evaluation reports yet. Run scripts/evaluate_model.py on the server.</p>
        ) : (
          <>
            <p className="ws-muted">
              {latest.model} · {when(latest.created_at)} · {latest.cases_passed}/{latest.cases_total} cases passed ·{' '}
              <span className={latest.passed ? 'ws-pass' : 'ws-fail'}>{latest.passed ? 'PASSED' : 'FAILED'}</span>
            </p>
            <div className="ws-cards">
              <div className="ws-card">
                <span>{CHECK_LABEL.availability}</span>
                <strong className={latest.checks.availability ? 'ws-pass' : 'ws-fail'}>{pct(latest.metrics.availability)}</strong>
                <small>target {pct(latest.criteria.min_availability)}</small>
              </div>
              <div className="ws-card">
                <span>{CHECK_LABEL.content}</span>
                <strong className={latest.checks.content ? 'ws-pass' : 'ws-fail'}>{pct(latest.metrics.content_pass_rate)}</strong>
                <small>target {pct(latest.criteria.min_content_pass_rate)}</small>
              </div>
              <div className="ws-card">
                <span>{CHECK_LABEL.json}</span>
                <strong className={latest.checks.json ? 'ws-pass' : 'ws-fail'}>{pct(latest.metrics.json_pass_rate)}</strong>
                <small>target {pct(latest.criteria.min_json_pass_rate)}</small>
              </div>
              <div className="ws-card">
                <span>{CHECK_LABEL.latency}</span>
                <strong className={latest.checks.latency ? 'ws-pass' : 'ws-fail'}>{secs(latest.metrics.p95_latency_ms)}</strong>
                <small>limit {secs(latest.criteria.max_p95_latency_ms)} · p50 {secs(latest.metrics.p50_latency_ms)}</small>
              </div>
            </div>
          </>
        )}
      </section>

      {reports.length > 0 && (
        <section className="ws-panel">
          <h2>All evaluation runs</h2>
          <table className="ws-table">
            <thead>
              <tr><th>Run</th><th>Model</th><th>Cases</th><th>Content</th><th>p95</th><th>Result</th><th /></tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.name}>
                  <td>{when(r.created_at)}</td>
                  <td>{r.model}</td>
                  <td>{r.cases_passed}/{r.cases_total}</td>
                  <td>{pct(r.metrics.content_pass_rate)}</td>
                  <td>{secs(r.metrics.p95_latency_ms)}</td>
                  <td className={r.passed ? 'ws-pass' : 'ws-fail'}>{r.passed ? 'Pass' : 'Fail'}</td>
                  <td>
                    <button type="button" className="ws-btn ws-btn-link" onClick={() => openReport(r.name)}>
                      Cases
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ErrorBox message={detailError} />
          {detail && (
            <div className="monitor-cases">
              <h3>Cases in run {when(detail.created_at)}</h3>
              <table className="ws-table">
                <thead>
                  <tr><th>Case</th><th>Result</th><th>Time</th><th>Missing concepts / error</th></tr>
                </thead>
                <tbody>
                  {detail.cases.map((c) => (
                    <tr key={c.id}>
                      <td>{c.id}</td>
                      <td className={c.passed ? 'ws-pass' : 'ws-fail'}>{c.passed ? 'Pass' : 'Fail'}</td>
                      <td>{secs(c.duration_ms)}</td>
                      <td className="ws-muted">{c.error || (c.missing || []).join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <section className="ws-panel">
        <h2>Live model usage (last {runtime.days} days)</h2>
        <div className="ws-cards">
          <div className="ws-card"><span>Model calls</span><strong>{runtime.total_runs}</strong></div>
          <div className="ws-card">
            <span>Succeeded</span>
            <strong>{runtime.by_status.succeeded ?? runtime.by_status.completed ?? runtime.by_status.ok ?? 0}</strong>
            <small>{Object.entries(runtime.by_status).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'none'}</small>
          </div>
          <div className="ws-card"><span>Average time</span><strong>{secs(runtime.avg_duration_ms)}</strong></div>
          <div className="ws-card"><span>95th percentile</span><strong>{secs(runtime.p95_duration_ms)}</strong></div>
        </div>
        {Object.keys(runtime.errors_by_code).length > 0 && (
          <p className="ws-muted">Errors: {Object.entries(runtime.errors_by_code).map(([k, v]) => `${k} (${v})`).join(', ')}</p>
        )}
      </section>

      <section className="ws-panel">
        <h2>User feedback on answers</h2>
        <div className="ws-cards">
          <div className="ws-card"><span>Ratings</span><strong>{feedback.total}</strong></div>
          <div className="ws-card">
            <span>Average rating</span>
            <strong>{feedback.average_rating ?? '—'}</strong>
            <small>out of 5</small>
          </div>
          <div className="ws-card">
            <span>Reported issues</span>
            <strong>{Object.values(feedback.by_issue_type).reduce((a, b) => a + b, 0)}</strong>
            <small>{Object.entries(feedback.by_issue_type).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · ') || 'none'}</small>
          </div>
        </div>
        {feedback.recent.length === 0 ? (
          <p className="ws-empty">No feedback yet. Users rate answers with the thumbs buttons in the chat.</p>
        ) : (
          <table className="ws-table">
            <thead><tr><th>When</th><th>Rating</th><th>Issue</th><th>Comment</th></tr></thead>
            <tbody>
              {feedback.recent.map((f, i) => (
                <tr key={i}>
                  <td>{when(f.created_at)}</td>
                  <td>{f.rating}/5</td>
                  <td>{f.issue_type?.replace(/_/g, ' ') || '—'}</td>
                  <td>{f.comment || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

const TABS = [
  ['ingestion', 'Ingestion'],
  ['sources', 'Sources & indexing'],
  ['evaluation', 'Evaluation & feedback'],
]

function AdminMonitoring() {
  const [tab, setTab] = useState('ingestion')
  return (
    <div className="ws-page">
      <div className="ws-heading">
        <h1>Monitoring</h1>
        <p>Document ingestion, source editions and indexing, model evaluation and user feedback.</p>
      </div>
      <div className="ws-tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`ws-tab ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'ingestion' && <IngestionTab />}
      {tab === 'sources' && <SourcesTab />}
      {tab === 'evaluation' && <EvaluationTab />}
    </div>
  )
}

export default AdminMonitoring
