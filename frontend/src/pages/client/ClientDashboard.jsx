
import AssistantChat from '../../components/AssistantChat'

function ClientDashboard() {
  return (
    <div className="role-dashboard-page">
      <div className="role-dashboard-heading">
        <h1>Client Dashboard</h1>
        <p>
          Ask legal questions and receive clear, evidence-based legal
          information with relevant legal references.
        </p>
      </div>

      <AssistantChat agent="client" />
    </div>
  )
}

export default ClientDashboard
