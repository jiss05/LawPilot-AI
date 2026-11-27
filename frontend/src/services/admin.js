import api from './api'

// Ingestion monitoring (SCRUM-18 APIs, shown on the SCRUM-29 dashboard)
export async function getIngestionSummary() {
  return (await api.get('/admin/ingestion-jobs/summary')).data
}

export async function listIngestionJobs({ status, limit = 25 } = {}) {
  return (await api.get('/admin/ingestion-jobs', { params: { status: status || undefined, limit } })).data
}

export async function reprocessDocument(documentId) {
  return (await api.post('/admin/ingestion-jobs', { document_id: documentId })).data
}

export async function listSources() {
  return (await api.get('/knowledge-sources')).data
}

export async function listSourceVersions(sourceId) {
  return (await api.get(`/knowledge-sources/${sourceId}/versions`)).data
}

export async function getDocumentStatus(documentId) {
  return (await api.get(`/admin/documents/${documentId}/status`)).data
}

// Evaluation and feedback (SCRUM-29)
export async function listEvaluationReports() {
  return (await api.get('/admin/evaluation/reports')).data
}

export async function getEvaluationReport(name) {
  return (await api.get(`/admin/evaluation/reports/${encodeURIComponent(name)}`)).data
}

export async function getRuntimeStats(days = 7) {
  return (await api.get('/admin/evaluation/runtime', { params: { days } })).data
}

export async function getFeedbackSummary() {
  return (await api.get('/admin/feedback/summary')).data
}
