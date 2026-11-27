import api from './api'

// Matters (a draft always belongs to a matter)
export async function listMatters() {
  return (await api.get('/matters')).data
}

export async function createMatter(matter) {
  return (await api.post('/matters', matter)).data
}

export async function listMatterMembers(matterId) {
  return (await api.get(`/matters/${matterId}/members`)).data
}

export async function addMatterMember(matterId, { email, permission }) {
  return (await api.post(`/matters/${matterId}/members`, { email, permission })).data
}

// Drafts (SCRUM-24)
export async function listDrafts(status) {
  return (await api.get('/drafts/', { params: status ? { status } : {} })).data
}

export async function getDraft(draftId) {
  return (await api.get(`/drafts/${draftId}`)).data
}

export async function generateDraft(payload) {
  return (await api.post('/drafts/generate', payload)).data
}

export async function updateDraft(draftId, { title, content }) {
  return (await api.put(`/drafts/${draftId}`, { title, content })).data
}

export async function listDraftVersions(draftId) {
  return (await api.get(`/drafts/${draftId}/versions`)).data
}

export async function submitDraftForReview(draftId) {
  return (await api.post(`/drafts/${draftId}/review`)).data
}

export async function approveDraft(draftId, notes) {
  return (await api.post(`/drafts/${draftId}/approve`, { notes: notes || null })).data
}

export async function requestDraftChanges(draftId, notes) {
  return (await api.post(`/drafts/${draftId}/request-changes`, { notes: notes || null })).data
}

export async function exportDraft(draftId) {
  const response = await api.post(`/drafts/${draftId}/export`, null, {
    responseType: 'blob',
  })
  const disposition = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  return { blob: response.data, filename: match ? match[1] : 'legal_draft.docx' }
}
