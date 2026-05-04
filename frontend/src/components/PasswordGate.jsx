import { useState } from 'react'
import axios from 'axios'
import { Shield, Lock } from 'lucide-react'

export default function PasswordGate({ onAuth }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post('/api/auth', { password })
      onAuth(res.data.token)
    } catch (err) {
      setError(err.response?.data?.error || 'Invalid password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="bg-red-600 p-3 rounded-xl mb-3">
            <Shield className="text-white" size={28} />
          </div>
          <h1 className="text-lg font-bold text-gray-900">OCI DR Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Enter the password to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              autoFocus
              className="w-full h-10 pl-9 pr-3 border border-gray-200 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={!password || loading}
            className="btn-primary h-10"
          >
            {loading ? 'Verifying…' : 'Access Dashboard'}
          </button>
        </form>
      </div>
    </div>
  )
}
