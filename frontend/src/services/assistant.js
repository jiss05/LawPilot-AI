
import api from './api'

/**
 * Get the agents available to the authenticated user.
 */
export async function getAvailableAgents() {
  const response = await api.get('/assistant/agents')
  return response.data
}

/**
 * Send a message to the selected legal assistant.
 *
 * conversationId is null for a new conversation.
 * The backend returns a conversation_id for follow-up messages.
 */
export async function sendAssistantMessage({
  message,
  agent,
  conversationId = null,
  useKnowledgeBase = true,
}) {
  const response = await api.post('/assistant/chat', {
    message,
    agent,
    conversation_id: conversationId,
    use_knowledge_base: useKnowledgeBase,
  })

  return response.data
}

/** Rate an assistant answer (SCRUM-29). rating 1-5. */
export async function sendFeedback({ messageId, rating, issueType = null, comment = null }) {
  const response = await api.post('/assistant/feedback', {
    message_id: messageId,
    rating,
    issue_type: issueType,
    comment,
  })
  return response.data
}
