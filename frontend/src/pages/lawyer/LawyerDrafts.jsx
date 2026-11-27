import { useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FilePlus2,
  History,
  LoaderCircle,
  Save,
  Send,
  ShieldCheck,
  Undo2,
  UserPlus,
} from 'lucide-react'
import api from '../../services/api'
import {
  addMatterMember,
  approveDraft,
  createMatter,
  exportDraft,
  generateDraft,
  getDraft,
  listDraftVersions,
  listDrafts,
  listMatterMembers,
  listMatters,
  requestDraftChanges,
  submitDraftForReview,
  updateDraft,
} from '../../services/drafts'
import { errorMessage } from '../../services/errors'
import { CitationList } from '../../components/Verification'
import '../../components/Workspace.css'
import './LawyerDrafts.css'

const STATUS_LABEL = {
  draft: 'Draft',
  reviewed: 'Awaiting approval',
  approved: 'Approved',
  exported: 'Downloaded',
}

function StatusBadge({ status }) {
  return <span className={`ws-status ws-status-${status}`}>{STATUS_LABEL[status] || status}</span>
}

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function LawyerDrafts() {
  const [me, setMe] = useState(null)
  const [matters, setMatters] = useState([])
  const [matterId, setMatterId] = useState('')
  const [members, setMembers] = useState([])
  const [drafts, setDrafts] = useState([])
  const [loadingList, setLoadingList] = useState(true)

  const [draft, setDraft] = useState(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [versions, setVersions] = useState(null)
  const [notes, setNotes] = useState('')

  const [busy, setBusy] = useState('') // which action is running
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  const [showNewMatter, setShowNewMatter] = useState(false)
  const [newMatter, setNewMatter] = useState({ title: '', court: '', matter_reference: '' })
  const [reviewer, setReviewer] = useState({ email: '', permission: 'review' })
  const [generate, setGenerate] = useState({ title: '', document_type: 'Legal Notice', case_facts: '' })

  const selectedMatter = matters.find((m) => m.id === matterId)
  const isOwnerOfMatter = selectedMatter && ['owner', 'admin'].includes(selectedMatter.my_permission)
  const isAuthor = draft && me && draft.owner_user_id === me.id
  const dirty = draft && (title !== draft.title || content !== draft.content)
  const editable = isAuthor && draft && draft.status !== 'exported'

  const visibleDrafts = useMemo(
    () => (matterId ? drafts.filter((d) => d.matter_id === matterId) : drafts),
    [drafts, matterId],
  )
  const awaitingMe = drafts.filter((d) => d.status === 'reviewed' && d.can_approve)

  function run(name, fn) {
    return async (...args) => {
      setBusy(name)
      setError('')
      setInfo('')
      try {
        await fn(...args)
      } catch (err) {
        setError(errorMessage(err))
      } finally {
        setBusy('')
      }
    }
  }

  useEffect(() => {
    let active = true
    Promise.all([api.get('/users/me'), listMatters(), listDrafts()])
      .then(([meResponse, matterList, draftList]) => {
        if (!active) return
        setMe(meResponse.data)
        setMatters(matterList)
        setDrafts(draftList)
        if (matterList.length > 0) setMatterId(matterList[0].id)
      })
      .catch((err) => active && setError(errorMessage(err, 'Could not load your drafts.')))
      .finally(() => active && setLoadingList(false))
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!matterId) return undefined
    let active = true
    listMatterMembers(matterId)
      .then((list) => active && setMembers(list))
      .catch(() => active && setMembers([]))
    return () => {
      active = false
    }
  }, [matterId])

  function showDraft(next) {
    setDraft(next)
    setTitle(next.title)
    setContent(next.content)
    setVersions(null)
    setNotes('')
  }

  function replaceInList(next) {
    setDrafts((list) => {
      const others = list.filter((d) => d.id !== next.id)
      return [next, ...others]
    })
    showDraft(next)
  }

  const openDraft = run('open', async (id) => {
    showDraft(await getDraft(id))
  })

  const onCreateMatter = run('matter', async (event) => {
    event.preventDefault()
    const created = await createMatter({
      title: newMatter.title,
      court: newMatter.court || null,
      matter_reference: newMatter.matter_reference || null,
    })
    setMatters((list) => [created, ...list])
    setMatterId(created.id)
    setNewMatter({ title: '', court: '', matter_reference: '' })
    setShowNewMatter(false)
    setInfo('Matter created.')
  })

  const onAddReviewer = run('reviewer', async (event) => {
    event.preventDefault()
    const added = await addMatterMember(matterId, reviewer)
    setMembers((list) => [...list.filter((m) => m.user_id !== added.user_id), added])
    setReviewer({ email: '', permission: 'review' })
    setInfo(`${added.display_name} can now ${added.permission === 'review' ? 'review and approve' : 'access'} drafts in this matter.`)
  })

  const onGenerate = run('generate', async (event) => {
    event.preventDefault()
    const created = await generateDraft({ matter_id: matterId, ...generate })
    replaceInList(created)
    setGenerate({ title: '', document_type: generate.document_type, case_facts: '' })
    setInfo('Draft generated. Review every fact and citation before submitting it.')
  })

  const onSave = run('save', async () => {
    const saved = await updateDraft(draft.id, { title, content })
    replaceInList(saved)
    setInfo(`Saved as version ${saved.version}.`)
  })

  const onSubmit = run('submit', async () => {
    replaceInList(await submitDraftForReview(draft.id))
    setInfo('Submitted. A reviewer on this matter can now approve it.')
  })

  const onApprove = run('approve', async () => {
    replaceInList(await approveDraft(draft.id, notes))
    setInfo('Draft approved. The author can now download it.')
  })

  const onRequestChanges = run('changes', async () => {
    replaceInList(await requestDraftChanges(draft.id, notes))
    setInfo('Sent back to the author with your notes.')
  })

  const onExport = run('export', async () => {
    const { blob, filename } = await exportDraft(draft.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
    replaceInList(await getDraft(draft.id))
  })

  const onVersions = run('versions', async () => {
    setVersions(versions ? null : await listDraftVersions(draft.id))
  })

  return (
    <div className="ws-page">
      <div className="ws-heading">
        <h1>Legal Drafts</h1>
        <p>
          Generate drafts from case facts and the legal knowledge base. Every AI draft must be
          approved by a second lawyer before it can be downloaded.
        </p>
      </div>

      {error && (
        <div className="ws-alert ws-alert-error" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}
      {info && (
        <div className="ws-alert ws-alert-success">
          <CheckCircle2 size={17} />
          <span>{info}</span>
        </div>
      )}

      <div className="ws-grid">
        {/* ---------------- left column ---------------- */}
        <div className="ws-stack">
          <section className="ws-panel">
            <h2>Matter</h2>
            {loadingList ? (
              <div className="ws-loading">
                <LoaderCircle size={16} className="assistant-spinner" /> Loading matters...
              </div>
            ) : (
              <>
                {matters.length > 0 ? (
                  <div className="ws-field">
                    <select value={matterId} onChange={(e) => setMatterId(e.target.value)}>
                      {matters.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.title}
                          {m.my_permission !== 'owner' ? ` (${m.my_permission})` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <p className="ws-muted">Create a matter to start drafting.</p>
                )}

                {!showNewMatter ? (
                  <button type="button" className="ws-btn ws-btn-secondary" onClick={() => setShowNewMatter(true)}>
                    <FilePlus2 size={15} /> New matter
                  </button>
                ) : (
                  <form onSubmit={onCreateMatter}>
                    <div className="ws-field">
                      <label htmlFor="matter-title">Title</label>
                      <input
                        id="matter-title"
                        required
                        maxLength={300}
                        value={newMatter.title}
                        onChange={(e) => setNewMatter({ ...newMatter, title: e.target.value })}
                        placeholder="Kumar v. Singh"
                      />
                    </div>
                    <div className="ws-row">
                      <div className="ws-field">
                        <label htmlFor="matter-court">Court</label>
                        <input
                          id="matter-court"
                          value={newMatter.court}
                          onChange={(e) => setNewMatter({ ...newMatter, court: e.target.value })}
                        />
                      </div>
                      <div className="ws-field">
                        <label htmlFor="matter-ref">Reference</label>
                        <input
                          id="matter-ref"
                          value={newMatter.matter_reference}
                          onChange={(e) => setNewMatter({ ...newMatter, matter_reference: e.target.value })}
                        />
                      </div>
                    </div>
                    <div className="ws-actions">
                      <button type="submit" className="ws-btn" disabled={busy === 'matter'}>
                        Create
                      </button>
                      <button type="button" className="ws-btn ws-btn-secondary" onClick={() => setShowNewMatter(false)}>
                        Cancel
                      </button>
                    </div>
                  </form>
                )}

                {selectedMatter && (
                  <>
                    <h3>People on this matter</h3>
                    <ul className="drafts-members">
                      {members.map((m) => (
                        <li key={m.user_id}>
                          <span>{m.display_name}</span>
                          <em>{m.permission === 'review' ? 'reviewer' : m.permission}</em>
                        </li>
                      ))}
                    </ul>

                    {isOwnerOfMatter && (
                      <form onSubmit={onAddReviewer}>
                        <div className="ws-field">
                          <label htmlFor="reviewer-email">Add a lawyer by email</label>
                          <input
                            id="reviewer-email"
                            type="email"
                            required
                            value={reviewer.email}
                            onChange={(e) => setReviewer({ ...reviewer, email: e.target.value })}
                            placeholder="colleague@example.com"
                          />
                        </div>
                        <div className="ws-row">
                          <div className="ws-field">
                            <select
                              aria-label="Permission"
                              value={reviewer.permission}
                              onChange={(e) => setReviewer({ ...reviewer, permission: e.target.value })}
                            >
                              <option value="review">Reviewer (can approve)</option>
                              <option value="write">Can draft</option>
                              <option value="read">Read only</option>
                            </select>
                          </div>
                          <button type="submit" className="ws-btn ws-btn-secondary" disabled={busy === 'reviewer'}>
                            <UserPlus size={15} /> Add
                          </button>
                        </div>
                      </form>
                    )}
                  </>
                )}
              </>
            )}
          </section>

          {selectedMatter && ['owner', 'write', 'admin'].includes(selectedMatter.my_permission) && (
            <section className="ws-panel">
              <h2>Generate a draft</h2>
              <form onSubmit={onGenerate}>
                <div className="ws-field">
                  <label htmlFor="draft-title">Title</label>
                  <input
                    id="draft-title"
                    required
                    maxLength={255}
                    value={generate.title}
                    onChange={(e) => setGenerate({ ...generate, title: e.target.value })}
                    placeholder="Legal notice for cheque dishonour"
                  />
                </div>
                <div className="ws-field">
                  <label htmlFor="draft-type">Document type</label>
                  <input
                    id="draft-type"
                    required
                    maxLength={100}
                    value={generate.document_type}
                    onChange={(e) => setGenerate({ ...generate, document_type: e.target.value })}
                  />
                </div>
                <div className="ws-field">
                  <label htmlFor="draft-facts">Case facts</label>
                  <textarea
                    id="draft-facts"
                    required
                    minLength={20}
                    rows={6}
                    value={generate.case_facts}
                    onChange={(e) => setGenerate({ ...generate, case_facts: e.target.value })}
                    placeholder="Parties, dates, amounts and what happened (at least 20 characters)."
                  />
                </div>
                <button type="submit" className="ws-btn ws-btn-gold" disabled={busy === 'generate'}>
                  {busy === 'generate' ? (
                    <>
                      <LoaderCircle size={15} className="assistant-spinner" /> Drafting... this can take a few minutes
                    </>
                  ) : (
                    <>
                      <FilePlus2 size={15} /> Generate draft
                    </>
                  )}
                </button>
              </form>
            </section>
          )}

          <section className="ws-panel">
            <h2>Drafts</h2>
            {awaitingMe.length > 0 && (
              <p className="drafts-awaiting">
                <ShieldCheck size={15} /> {awaitingMe.length} draft(s) awaiting your approval
              </p>
            )}
            {visibleDrafts.length === 0 ? (
              <p className="ws-empty">No drafts in this matter yet.</p>
            ) : (
              <div className="ws-list">
                {visibleDrafts.map((d) => (
                  <button
                    type="button"
                    key={d.id}
                    className={`ws-list-item ${draft?.id === d.id ? 'active' : ''}`}
                    onClick={() => openDraft(d.id)}
                  >
                    <strong>{d.title}</strong>
                    <StatusBadge status={d.status} />
                    <span>
                      v{d.version} · {formatDate(d.updated_at)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* ---------------- right column ---------------- */}
        <section className="ws-panel drafts-editor">
          {!draft ? (
            <div className="ws-empty">
              {busy === 'open' ? 'Opening draft...' : 'Select a draft, or generate a new one.'}
            </div>
          ) : (
            <>
              <div className="drafts-editor-head">
                <div>
                  <StatusBadge status={draft.status} />
                  <span className="ws-muted">
                    {' '}
                    Version {draft.version} · {isAuthor ? 'You wrote this draft' : 'Written by another lawyer'}
                  </span>
                </div>
                <button type="button" className="ws-btn ws-btn-link" onClick={onVersions}>
                  <History size={15} /> {versions ? 'Hide history' : 'Version history'}
                </button>
              </div>

              {draft.requires_human_review && (
                <div className="ws-alert ws-alert-warning">
                  <AlertCircle size={17} />
                  <span>
                    AI-generated draft. It must be checked by you and approved by a second lawyer
                    before it can be used or downloaded.
                  </span>
                </div>
              )}

              {draft.review_notes && (
                <div className="ws-alert ws-alert-info">
                  <span>
                    <strong>Reviewer notes:</strong> {draft.review_notes}
                  </span>
                </div>
              )}

              {versions && (
                <div className="drafts-versions">
                  {versions.map((v) => (
                    <div key={v.id} className="drafts-version">
                      <strong>Version {v.version}</strong>
                      <span>{formatDate(v.created_at)}</span>
                      <button
                        type="button"
                        className="ws-btn ws-btn-link"
                        disabled={!editable}
                        onClick={() => {
                          setTitle(v.title)
                          setContent(v.content)
                        }}
                      >
                        Load into editor
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="ws-field">
                <label htmlFor="edit-title">Title</label>
                <input
                  id="edit-title"
                  value={title}
                  maxLength={255}
                  readOnly={!editable}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
              <div className="ws-field">
                <label htmlFor="edit-content">Draft</label>
                <textarea
                  id="edit-content"
                  className="drafts-textarea"
                  value={content}
                  readOnly={!editable}
                  onChange={(e) => setContent(e.target.value)}
                />
              </div>

              {!draft.citations_verified && draft.status !== 'exported' && (
                <div className="ws-alert ws-alert-error">
                  <AlertCircle size={17} />
                  <span>
                    Some citations are not verified against the stored legal sources. Fix them
                    before submitting: a draft with failed citations cannot be approved.
                  </span>
                </div>
              )}

              <div className="ws-actions">
                {editable && (
                  <button
                    type="button"
                    className="ws-btn"
                    onClick={onSave}
                    disabled={!dirty || busy === 'save' || !title.trim() || !content.trim()}
                  >
                    <Save size={15} /> Save new version
                  </button>
                )}
                {isAuthor && draft.status === 'draft' && (
                  <button
                    type="button"
                    className="ws-btn ws-btn-gold"
                    onClick={onSubmit}
                    disabled={dirty || busy === 'submit'}
                    title={dirty ? 'Save your changes first' : ''}
                  >
                    <Send size={15} /> Submit for approval
                  </button>
                )}
                {isAuthor && ['approved', 'exported'].includes(draft.status) && (
                  <button type="button" className="ws-btn" onClick={onExport} disabled={busy === 'export'}>
                    <Download size={15} /> Download Word file
                  </button>
                )}
              </div>

              {draft.can_approve && draft.status === 'reviewed' && (
                <div className="drafts-review">
                  <h3>Your review</h3>
                  <div className="ws-field">
                    <label htmlFor="review-notes">Notes for the author (optional)</label>
                    <textarea
                      id="review-notes"
                      rows={3}
                      maxLength={4000}
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                    />
                  </div>
                  <div className="ws-actions">
                    <button type="button" className="ws-btn ws-btn-gold" onClick={onApprove} disabled={busy === 'approve'}>
                      <ShieldCheck size={15} /> Approve
                    </button>
                    <button type="button" className="ws-btn ws-btn-danger" onClick={onRequestChanges} disabled={busy === 'changes'}>
                      <Undo2 size={15} /> Send back
                    </button>
                  </div>
                </div>
              )}

              {draft.status === 'reviewed' && isAuthor && (
                <p className="ws-muted">Waiting for a reviewer on this matter to approve it.</p>
              )}

              <CitationList
                citations={draft.citations}
                invalidReferences={draft.invalid_references}
                title="Sources cited in this draft"
              />
            </>
          )}
        </section>
      </div>
    </div>
  )
}

export default LawyerDrafts
