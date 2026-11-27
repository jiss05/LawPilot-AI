import { useState } from 'react'
import { AlertCircle, FileSearch, LoaderCircle, Plus, Scale, Trash2 } from 'lucide-react'
import { buildCaseBrief } from '../../services/judgeSupport'
import { errorMessage, warningText } from '../../services/errors'
import { CitationList, ReliabilityNotice } from '../../components/Verification'
import '../../components/Workspace.css'
import './CaseBrief.css'

const emptyFact = () => ({ text: '', source_ref: '', date: '', disputed: false })
const emptyArgument = () => ({ text: '', source_ref: '' })

const EXAMPLE = {
  case_title: 'A. Kumar v. B. Singh',
  case_number: 'CC 12/2024',
  court: 'Judicial Magistrate First Class, Kochi',
  question: '',
  facts: [
    { text: 'The accused issued cheque no. 4471 for Rs 2,00,000 to the complainant.', source_ref: 'Exhibit P-1', date: '2024-03-12', disputed: false },
    { text: 'The cheque was returned unpaid for insufficient funds.', source_ref: 'Exhibit P-2, bank memo', date: '2024-04-01', disputed: false },
    { text: 'The complainant sent a statutory demand notice.', source_ref: 'Exhibit P-3', date: '2024-04-20', disputed: false },
    { text: 'The demand notice was received by the accused.', source_ref: 'Exhibit P-4, postal receipt', date: '', disputed: true },
  ],
  parties: [
    {
      name: 'A. Kumar',
      role: 'Complainant',
      arguments: [
        { text: 'All ingredients of Section 138 of the Negotiable Instruments Act are made out.', source_ref: 'Complaint, para 7' },
      ],
    },
    {
      name: 'B. Singh',
      role: 'Accused',
      arguments: [
        { text: 'No demand notice was received, so the offence is not complete.', source_ref: 'Reply, para 3' },
      ],
    },
  ],
}

const EMPTY = {
  case_title: '',
  case_number: '',
  court: '',
  question: '',
  facts: [emptyFact()],
  parties: [
    { name: '', role: 'Petitioner', arguments: [emptyArgument()] },
    { name: '', role: 'Respondent', arguments: [emptyArgument()] },
  ],
}

function CaseBrief() {
  const [form, setForm] = useState(EMPTY)
  const [brief, setBrief] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const setFact = (i, patch) => set({ facts: form.facts.map((f, j) => (j === i ? { ...f, ...patch } : f)) })
  const setParty = (i, patch) => set({ parties: form.parties.map((p, j) => (j === i ? { ...p, ...patch } : p)) })
  const setArgument = (pi, ai, patch) =>
    setParty(pi, {
      arguments: form.parties[pi].arguments.map((a, j) => (j === ai ? { ...a, ...patch } : a)),
    })

  async function onSubmit(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const payload = {
        case_title: form.case_title,
        case_number: form.case_number || null,
        court: form.court || null,
        question: form.question || null,
        facts: form.facts
          .filter((f) => f.text.trim())
          .map((f) => ({ ...f, date: f.date || null })),
        parties: form.parties.map((p) => ({
          ...p,
          arguments: p.arguments
            .filter((a) => a.text.trim())
            .map((a) => ({ ...a, source_ref: a.source_ref || null })),
        })),
      }
      setBrief(await buildCaseBrief(payload))
    } catch (err) {
      setError(errorMessage(err, 'The case brief could not be prepared.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ws-stack">
      <form className="ws-panel" onSubmit={onSubmit}>
        <div className="brief-form-head">
          <h2>Case details</h2>
          <button type="button" className="ws-btn ws-btn-link" onClick={() => setForm(EXAMPLE)}>
            Load example case
          </button>
        </div>

        <div className="ws-row">
          <div className="ws-field">
            <label htmlFor="case-title">Case title</label>
            <input id="case-title" required maxLength={300} value={form.case_title} onChange={(e) => set({ case_title: e.target.value })} />
          </div>
          <div className="ws-field">
            <label htmlFor="case-number">Case number</label>
            <input id="case-number" maxLength={100} value={form.case_number} onChange={(e) => set({ case_number: e.target.value })} />
          </div>
          <div className="ws-field">
            <label htmlFor="case-court">Court</label>
            <input id="case-court" maxLength={200} value={form.court} onChange={(e) => set({ court: e.target.value })} />
          </div>
        </div>

        <h3>Facts</h3>
        <p className="ws-muted">Every fact needs its source (exhibit, page, paragraph or witness).</p>
        {form.facts.map((fact, i) => (
          <div className="brief-fact-row" key={i}>
            <input aria-label={`Fact ${i + 1}`} placeholder="What happened" value={fact.text} onChange={(e) => setFact(i, { text: e.target.value })} />
            <input aria-label={`Source of fact ${i + 1}`} placeholder="Source, e.g. Exhibit P-2" required={Boolean(fact.text)} value={fact.source_ref} onChange={(e) => setFact(i, { source_ref: e.target.value })} />
            <input aria-label={`Date of fact ${i + 1}`} placeholder="Date" value={fact.date} onChange={(e) => setFact(i, { date: e.target.value })} />
            <label className="brief-check">
              <input type="checkbox" checked={fact.disputed} onChange={(e) => setFact(i, { disputed: e.target.checked })} />
              Disputed
            </label>
            <button type="button" className="brief-icon" aria-label="Remove fact" disabled={form.facts.length === 1} onClick={() => set({ facts: form.facts.filter((_, j) => j !== i) })}>
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        <button type="button" className="ws-btn ws-btn-secondary" onClick={() => set({ facts: [...form.facts, emptyFact()] })}>
          <Plus size={15} /> Add fact
        </button>

        <h3>Parties and their arguments</h3>
        <div className="brief-parties">
          {form.parties.map((party, pi) => (
            <div className="brief-party" key={pi}>
              <div className="ws-row">
                <div className="ws-field">
                  <label htmlFor={`party-${pi}-name`}>Name</label>
                  <input id={`party-${pi}-name`} required value={party.name} onChange={(e) => setParty(pi, { name: e.target.value })} />
                </div>
                <div className="ws-field">
                  <label htmlFor={`party-${pi}-role`}>Role</label>
                  <input id={`party-${pi}-role`} required value={party.role} onChange={(e) => setParty(pi, { role: e.target.value })} />
                </div>
              </div>
              {party.arguments.map((arg, ai) => (
                <div className="brief-arg-row" key={ai}>
                  <textarea rows={2} aria-label={`Argument ${ai + 1} of ${party.name || 'party'}`} placeholder="Argument" required={ai === 0} value={arg.text} onChange={(e) => setArgument(pi, ai, { text: e.target.value })} />
                  <input aria-label="Argument source" placeholder="Source (optional)" value={arg.source_ref} onChange={(e) => setArgument(pi, ai, { source_ref: e.target.value })} />
                </div>
              ))}
              <button type="button" className="ws-btn ws-btn-link" onClick={() => setParty(pi, { arguments: [...party.arguments, emptyArgument()] })}>
                <Plus size={14} /> Add argument
              </button>
            </div>
          ))}
        </div>

        <div className="ws-field brief-question">
          <label htmlFor="case-question">Specific question for the brief (optional)</label>
          <input id="case-question" maxLength={2000} value={form.question} onChange={(e) => set({ question: e.target.value })} />
        </div>

        <button type="submit" className="ws-btn ws-btn-gold" disabled={loading}>
          {loading ? (
            <>
              <LoaderCircle size={15} className="assistant-spinner" /> Preparing brief... this can take a few minutes
            </>
          ) : (
            <>
              <FileSearch size={15} /> Prepare neutral brief
            </>
          )}
        </button>
      </form>

      {error && (
        <div className="ws-alert ws-alert-error" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}

      {brief && <BriefResult brief={brief} />}
    </div>
  )
}

function BriefResult({ brief }) {
  const factsById = Object.fromEntries(brief.facts.map((f) => [f.id, f]))
  const warnings = [...new Set(brief.warnings.map(warningText).filter(Boolean))]

  return (
    <section className="ws-panel brief-result">
      <div className="brief-title">
        <Scale size={20} />
        <div>
          <h2>{brief.case_title}</h2>
          <p className="ws-muted">{[brief.case_number, brief.court].filter(Boolean).join(' · ')}</p>
        </div>
      </div>

      <ReliabilityNotice reliable={brief.reliable} notice={brief.notice} />
      {warnings.map((w) => (
        <p key={w} className="ws-muted">{w}</p>
      ))}

      <h3>Neutral summary</h3>
      <p className="brief-summary">{brief.neutral_summary}</p>
      {brief.neutrality?.removed_statements > 0 && (
        <p className="ws-muted">
          The neutrality check removed {brief.neutrality.removed_statements} statement(s) that suggested an outcome.
        </p>
      )}

      <h3>Chronology</h3>
      {brief.chronology.length === 0 ? (
        <p className="ws-muted">No dated facts.</p>
      ) : (
        <table className="ws-table">
          <thead>
            <tr><th>Date</th><th>Fact</th><th>Source</th></tr>
          </thead>
          <tbody>
            {brief.chronology.map((c) => (
              <tr key={c.fact_id}>
                <td className="brief-nowrap">{c.date_iso}</td>
                <td>
                  <span className="brief-id">{c.fact_id}</span> {c.text}
                  {c.disputed && <span className="brief-disputed">disputed</span>}
                </td>
                <td>{c.source_ref}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {brief.undated_fact_ids.length > 0 && (
        <p className="ws-muted">
          Undated: {brief.undated_fact_ids.map((id) => `${id} (${factsById[id]?.source_ref})`).join(', ')}
        </p>
      )}

      <h3>Issues for determination</h3>
      {brief.disputed_issues.length === 0 ? (
        <p className="ws-muted">No disputed issues were identified.</p>
      ) : (
        <ol className="brief-issues">
          {brief.disputed_issues.map((issue) => (
            <li key={issue.id}>
              <strong>{issue.issue}</strong>
              {issue.fact_ids.length > 0 && (
                <span className="ws-muted">
                  {' '}Facts {issue.fact_ids.join(', ')} · {issue.source_refs.join('; ')}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}

      <h3>Arguments of each party</h3>
      <div className="brief-parties">
        {brief.party_arguments.map((p) => (
          <div className="brief-party" key={p.party}>
            <h4>
              {p.party} <span className="ws-muted">({p.role})</span>
            </h4>
            <ul>
              {p.arguments.map((a) => (
                <li key={a.id}>
                  {a.text}
                  {a.source_ref && <span className="ws-muted"> — {a.source_ref}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <CitationList citations={brief.legal_sources} title="Applicable law (from the knowledge base)" />

      <p className="brief-disclaimer">{brief.disclaimer}</p>
    </section>
  )
}

export default CaseBrief
