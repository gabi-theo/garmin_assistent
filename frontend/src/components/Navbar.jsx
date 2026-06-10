import { NavLink, useNavigate } from 'react-router-dom'
import { logout } from '../api'

export default function Navbar() {
  const navigate = useNavigate()

  async function handleLogout() {
    try { await logout() } catch {}
    navigate('/login')
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">⚡ Health Analytics</div>
      <nav>
        <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          📊 Dashboard
        </NavLink>
        <NavLink to="/insights" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          🧠 Insights
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          💬 Chat
        </NavLink>
        <NavLink to="/health" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          🩺 Health
        </NavLink>
        <NavLink to="/setup" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          ⌚ Garmin Setup
        </NavLink>
      </nav>
      <button className="nav-logout" onClick={handleLogout}>↩ Logout</button>
    </aside>
  )
}
