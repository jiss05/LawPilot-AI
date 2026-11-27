import api from './api'

/** Build a neutral, source-referenced case brief (SCRUM-25). */
export async function buildCaseBrief(payload) {
  return (await api.post('/judge-support/case-brief', payload)).data
}
