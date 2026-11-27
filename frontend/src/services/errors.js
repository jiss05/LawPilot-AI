/**
 * Turn an API error into a short message a user can act on (SCRUM-27).
 * Never shows raw server output.
 */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const detail = err?.response?.data?.detail

  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join(', ') || fallback
  }
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message
  }
  if (!err?.response) {
    return 'The LawPilot server could not be reached. Check your connection and try again.'
  }
  return fallback
}

const WARNING_TEXT = {
  retrieval_unavailable: 'The legal knowledge base could not be searched.',
  model_unavailable: 'The AI model was unavailable.',
  model_timeout: 'The AI model took too long to respond.',
  model_bad_response: 'The AI model returned an unusable response.',
  citation_verification_failed: 'Some citations could not be verified.',
  unsupported_provisions: 'The answer names law that is not in the retrieved sources.',
  conflicting_sources: 'The retrieved sources conflict with each other.',
  conversation_not_saved: 'This conversation could not be saved.',
  audit_not_saved: 'This action could not be recorded in the audit log.',
}

export function warningText(code) {
  if (WARNING_TEXT[code]) return WARNING_TEXT[code]
  if (code?.startsWith('handoff_to_')) return 'Another assistant was not available for this request.'
  return null
}
