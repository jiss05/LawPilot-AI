
import AssistantChat from '../../components/AssistantChat'

function LawyerDashboard() {
  return (
    <div className="role-dashboard-page">
      <div className="role-dashboard-heading">
        <h1>Lawyer Dashboard</h1>
        <p>
          Research legal authorities, examine relevant judgments, and
          prepare evidence-based legal arguments.
        </p>
      </div>

      <AssistantChat agent="lawyer" />
    </div>
  )
}

export default LawyerDashboard
