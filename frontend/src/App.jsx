import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { getToken } from './api'
import Navbar from './components/Navbar'
import LiveAlerts from './components/LiveAlerts'
import Login from './pages/Login'
import Register from './pages/Register'
import GarminSetup from './pages/GarminSetup'
import Dashboard from './pages/Dashboard'
import Insights from './pages/Insights'
import Chat from './pages/Chat'
import Health from './pages/Health'

function PrivateRoute({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />
}

function AppLayout({ children }) {
  return (
    <div className="layout">
      <Navbar />
      <LiveAlerts />
      <main className="main">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/setup" element={<PrivateRoute><AppLayout><GarminSetup /></AppLayout></PrivateRoute>} />
        <Route path="/" element={<PrivateRoute><AppLayout><Dashboard /></AppLayout></PrivateRoute>} />
        <Route path="/insights" element={<PrivateRoute><AppLayout><Insights /></AppLayout></PrivateRoute>} />
        <Route path="/chat" element={<PrivateRoute><AppLayout><Chat /></AppLayout></PrivateRoute>} />
        <Route path="/health" element={<PrivateRoute><AppLayout><Health /></AppLayout></PrivateRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
