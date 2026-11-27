import { useState } from 'react'
import AssistantChat from '../../components/AssistantChat'
import CaseBrief from './CaseBrief'
import '../../components/Workspace.css'

function JudgeDashboard() {
  const [tab, setTab] = useState('brief')

  return (
    <div className="ws-page">
      <div className="ws-heading">
        <h1>Judge Support Workspace</h1>
        <p>
          Organise case facts, chronology, issues and each party&apos;s arguments with their
          sources. LawPilot never decides a case or recommends an outcome.
        </p>
      </div>

      <div className="ws-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'brief'} className={`ws-tab ${tab === 'brief' ? 'active' : ''}`} onClick={() => setTab('brief')}>
          Case brief
        </button>
        <button type="button" role="tab" aria-selected={tab === 'chat'} className={`ws-tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>
          Assistant
        </button>
      </div>

      {tab === 'brief' ? <CaseBrief /> : <AssistantChat agent="judge_support" />}
    </div>
  )
}

export default JudgeDashboard
