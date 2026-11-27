
import { useEffect, useRef, useState } from 'react'
import {
  Send,
  Plus,
  FileText,
  AlertCircle,
  LoaderCircle,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react'
import {
  getAvailableAgents,
  sendAssistantMessage,
  sendFeedback,
} from '../services/assistant'
import { errorMessage, warningText } from '../services/errors'
import { CitationList, ReliabilityNotice } from './Verification'
import './AssistantChat.css'

const AGENT_TEXT = {
  lawyer: {
    title: 'Lawyer AI Assistant',
    subtitle: 'Research legal authorities and prepare evidence-based arguments.',
  },
  judge_support: {
    title: 'Judge Support Assistant',
    subtitle:
      'Neutral summaries of facts, issues and applicable law. It never recommends an outcome.',
  },
  client: {
    title: 'Legal AI Assistant',
    subtitle: 'Ask legal questions and receive clear, source-supported guidance.',
  },
}

const ISSUE_TYPES = [
  ['incorrect', 'Incorrect'],
  ['unsupported_citation', 'Wrong or missing source'],
  ['incomplete', 'Incomplete'],
  ['not_neutral', 'Not neutral'],
  ['unclear', 'Unclear'],
  ['other', 'Other'],
]

function FeedbackBar({ messageId }) {
  const [state, setState] = useState('idle') // idle | choosing | sending | sent | error
  const [issue, setIssue] = useState('incorrect')

  if (!messageId) return null

  async function send(rating, issueType) {
    setState('sending')
    try {
      await sendFeedback({ messageId, rating, issueType })
      setState('sent')
    } catch {
      setState('error')
    }
  }

  if (state === 'sent') {
    return <p className="assistant-feedback-done">Thanks for your feedback.</p>
  }

  return (
    <div className="assistant-feedback">
      <span>Was this helpful?</span>
      <button
        type="button"
        aria-label="Helpful"
        onClick={() => send(5, null)}
        disabled={state === 'sending'}
      >
        <ThumbsUp size={15} />
      </button>
      <button
        type="button"
        aria-label="Not helpful"
        onClick={() => setState('choosing')}
        disabled={state === 'sending'}
      >
        <ThumbsDown size={15} />
      </button>

      {state === 'choosing' && (
        <>
          <select value={issue} onChange={(event) => setIssue(event.target.value)}>
            {ISSUE_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button type="button" className="assistant-feedback-send" onClick={() => send(2, issue)}>
            Send
          </button>
        </>
      )}

      {state === 'error' && <span className="assistant-feedback-error">Could not send.</span>}
    </div>
  )
}

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
          errorMessage(err, 'Unable to load the available legal assistants.'),
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

  const text = AGENT_TEXT[agent] || AGENT_TEXT.client

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
          reliable: Boolean(response.reliable),
          notice: response.notice,
          invalidReferences: response.verification?.invalid_references || [],
          messageId: response.message_id,
        },
      ])
    } catch (err) {
      setError(errorMessage(err))
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

  return (
    <div className="assistant-chat">
      <div className="assistant-chat-header">
        <div>
          <h2>{text.title}</h2>
          <p>{text.subtitle}</p>
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

            {message.role === 'assistant' && (
              <ReliabilityNotice reliable={message.reliable} notice={message.notice} />
            )}

            <div className="assistant-message-content">
              {message.content}
            </div>

            {message.warnings?.some((w) => warningText(w)) && (
              <div className="assistant-warnings">
                {[...new Set(message.warnings.map(warningText).filter(Boolean))].map(
                  (warning) => (
                    <p key={warning}>{warning}</p>
                  ),
                )}
              </div>
            )}

            {message.role === 'assistant' && (
              <CitationList
                citations={message.citations}
                invalidReferences={message.invalidReferences}
              />
            )}

            {message.role === 'assistant' && <FeedbackBar messageId={message.messageId} />}
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
