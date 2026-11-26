
import { useEffect, useRef, useState } from 'react'
import { Send, Plus, FileText, AlertCircle, LoaderCircle } from 'lucide-react'
import {
  getAvailableAgents,
  sendAssistantMessage,
} from '../services/assistant'
import './AssistantChat.css'

function AssistantChat({ agent }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [agentReady, setAgentReady] = useState(false)
  const [agentError, setAgentError] = useState('')
  const [useKnowledgeBase, setUseKnowledgeBase] = useState(true)

  const messagesEndRef = useRef(null)

  useEffect(() => {
    let active = true

    async function loadAgents() {
      try {
        const response = await getAvailableAgents()
        const agents = response?.agents || []
        const permitted = agents.some(
          (item) => item.name?.toLowerCase() === agent.toLowerCase(),
        )

        if (!active) return

        if (permitted) {
          setAgentReady(true)
          setAgentError('')
        } else {
          setAgentError(
            `The ${agent} assistant is not available for this account.`,
          )
        }
      } catch (err) {
        if (!active) return
        setAgentError(
          err.response?.data?.detail ||
            'Unable to load the available legal assistants.',
        )
      }
    }

    loadAgents()

    return () => {
      active = false
    }
  }, [agent])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  function getErrorMessage(err) {
    const detail = err.response?.data?.detail

    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((item) => item.msg).join(', ')
    }

    return 'Something went wrong. Please try again.'
  }

  async function handleSubmit(event) {
    event.preventDefault()

    const message = input.trim()

    if (!message || loading || !agentReady) return

    setError('')
    setInput('')
    setMessages((previous) => [
      ...previous,
      { role: 'user', content: message },
    ])
    setLoading(true)

    try {
      const response = await sendAssistantMessage({
        message,
        agent,
        conversationId,
        useKnowledgeBase,
      })

      if (response.conversation_id) {
        setConversationId(response.conversation_id)
      }

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: response.answer || 'No answer was returned.',
          citations: response.citations || [],
          warnings: response.warnings || [],
          status: response.status,
        },
      ])
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function handleNewChat() {
    if (loading) return

    setMessages([])
    setConversationId(null)
    setInput('')
    setError('')
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

  return (
    <div className="assistant-chat">
      <div className="assistant-chat-header">
        <div>
          <h2>
            {agent === 'lawyer'
              ? 'Lawyer AI Assistant'
              : 'Legal AI Assistant'}
          </h2>
          <p>
            {agent === 'lawyer'
              ? 'Research legal authorities and prepare evidence-based arguments.'
              : 'Ask legal questions and receive clear, source-supported guidance.'}
          </p>
        </div>

        <button
          type="button"
          className="assistant-new-chat"
          onClick={handleNewChat}
          disabled={loading}
        >
          <Plus size={17} />
          New Chat
        </button>
      </div>

      <div className="assistant-chat-toolbar">
        <label className="assistant-knowledge-toggle">
          <input
            type="checkbox"
            checked={useKnowledgeBase}
            onChange={(event) => setUseKnowledgeBase(event.target.checked)}
            disabled={loading}
          />
          Search legal knowledge base
        </label>
      </div>

      <div className="assistant-messages">
        {messages.length === 0 && (
          <div className="assistant-empty-state">
            <FileText size={38} />
            <h3>How can I help you today?</h3>
            <p>
              Enter your legal question below. The assistant can use the
              available legal knowledge base to support its response with
              relevant citations.
            </p>
          </div>
        )}

        {messages.map((message, index) => (
          <div
            className={`assistant-message assistant-message-${message.role}`}
            key={`${message.role}-${index}`}
          >
            <div className="assistant-message-label">
              {message.role === 'user' ? 'You' : 'LawPilot AI'}
            </div>

            <div className="assistant-message-content">
              {message.content}
            </div>

            {message.warnings?.length > 0 && (
              <div className="assistant-warnings">
                {message.warnings.map((warning, warningIndex) => (
                  <p key={warningIndex}>{warning}</p>
                ))}
              </div>
            )}

            {message.citations?.length > 0 && (
              <div className="assistant-citations">
                <h4>
                  <FileText size={16} />
                  Legal Sources
                </h4>

                {message.citations.map((citation, citationIndex) => (
                  <div
                    className="assistant-citation"
                    key={citation.chunk_id || citation.ref || citationIndex}
                  >
                    <strong>
                      {citation.source_title || 'Legal source'}
                    </strong>

                    {citation.citation && (
                      <p>{citation.citation}</p>
                    )}

                    {isValidExternalUrl(citation.url) && (
                      <a
                        href={citation.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        View source
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="assistant-loading">
            <LoaderCircle size={18} className="assistant-spinner" />
            <span>LawPilot AI is preparing your response...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {(error || agentError) && (
        <div className="assistant-error">
          <AlertCircle size={17} />
          <span>{error || agentError}</span>
        </div>
      )}

      <form className="assistant-input-area" onSubmit={handleSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type your legal question here..."
          rows={3}
          maxLength={4000}
          disabled={!agentReady || loading}
        />

        <div className="assistant-input-footer">
          <span>{input.length}/4000 characters</span>

          <button
            type="submit"
            disabled={!agentReady || loading || !input.trim()}
          >
            <Send size={17} />
            Send
          </button>
        </div>
      </form>

      <p className="assistant-disclaimer">
        LawPilot AI provides legal information and research assistance.
        Its responses should be reviewed and verified before being relied upon.
      </p>
    </div>
  )
}

export default AssistantChat
