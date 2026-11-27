import { AlertTriangle, CheckCircle2, CircleHelp, MinusCircle, XCircle } from 'lucide-react'
import './Verification.css'

const STATUS = {
  verified: { label: 'Verified', icon: CheckCircle2, className: 'verified' },
  failed: { label: 'Not verified', icon: XCircle, className: 'failed' },
  not_cited: { label: 'Not used in text', icon: MinusCircle, className: 'not-cited' },
  unverified: { label: 'Unverified', icon: CircleHelp, className: 'unverified' },
}

function isValidExternalUrl(value) {
  if (!value) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

/** Badge for one citation's verification status (SCRUM-26). Unknown = unverified. */
export function VerificationBadge({ status }) {
  const info = STATUS[status] || STATUS.unverified
  const Icon = info.icon
  return (
    <span className={`verification-badge verification-${info.className}`}>
      <Icon size={13} />
      {info.label}
    </span>
  )
}

/** Citations with their verification status; failed ones say why. */
export function CitationList({ citations = [], title = 'Legal Sources', invalidReferences = [] }) {
  if (!citations.length && !invalidReferences.length) return null

  return (
    <div className="citation-list">
      <h4>{title}</h4>

      {citations.map((citation, index) => (
        <div
          className={`citation-item citation-${citation.verification_status || 'unverified'}`}
          key={citation.chunk_id || citation.ref || index}
        >
          <div className="citation-item-head">
            <strong>
              {citation.ref ? `[${citation.ref}] ` : ''}
              {citation.source_title || 'Legal source'}
            </strong>
            <VerificationBadge status={citation.verification_status} />
          </div>

          {citation.citation && <p className="citation-locator">{citation.citation}</p>}

          {citation.verification_status === 'failed' &&
            citation.verification_details?.length > 0 && (
              <ul className="citation-issues">
                {citation.verification_details.map((detail, i) => (
                  <li key={i}>{detail}</li>
                ))}
              </ul>
            )}

          {isValidExternalUrl(citation.url) && (
            <a href={citation.url} target="_blank" rel="noreferrer">
              View source
            </a>
          )}
        </div>
      ))}

      {invalidReferences.length > 0 && (
        <div className="citation-item citation-failed">
          <div className="citation-item-head">
            <strong>
              References with no source: {invalidReferences.map((n) => `[${n}]`).join(' ')}
            </strong>
            <VerificationBadge status="failed" />
          </div>
          <p className="citation-locator">
            The text refers to source numbers that do not exist. Remove or correct them.
          </p>
        </div>
      )}
    </div>
  )
}

/** Shown whenever a result must not be relied on as-is (SCRUM-27). */
export function ReliabilityNotice({ reliable, notice }) {
  if (reliable || !notice) return null
  return (
    <div className="reliability-notice" role="alert">
      <AlertTriangle size={17} />
      <span>{notice}</span>
    </div>
  )
}
