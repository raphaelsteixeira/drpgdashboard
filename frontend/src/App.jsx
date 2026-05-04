import { useState, useEffect } from 'react'
import axios from 'axios'
import { Shield, RefreshCw, AlertCircle, Globe, Layers } from 'lucide-react'
import DRPGCard from './components/DRPGCard'
import Spinner from './components/Spinner'
import PasswordGate from './components/PasswordGate'

const TOKEN_KEY = 'drpg_token'

function setAxiosToken(token) {
  axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
}

export default function App() {
  const [token, setToken] = useState(() => {
    const t = sessionStorage.getItem(TOKEN_KEY)
    if (t) setAxiosToken(t)
    return t
  })

  const handleAuth = (t) => {
    sessionStorage.setItem(TOKEN_KEY, t)
    setAxiosToken(t)
    setToken(t)
  }

  const handleLogout = () => {
    sessionStorage.removeItem(TOKEN_KEY)
    delete axios.defaults.headers.common['Authorization']
    setToken(null)
  }

  // Redirect to password gate on 401 (e.g. backend restarted, token lost)
  useEffect(() => {
    const interceptor = axios.interceptors.response.use(
      (res) => res,
      (err) => {
        if (err.response?.status === 401) handleLogout()
        return Promise.reject(err)
      }
    )
    return () => axios.interceptors.response.eject(interceptor)
  }, [])

  if (!token) return <PasswordGate onAuth={handleAuth} />

  const [regions, setRegions] = useState([])
  const [compartments, setCompartments] = useState([])
  const [selectedRegion, setSelectedRegion] = useState('')
  const [selectedCompartment, setSelectedCompartment] = useState('')
  const [drpgs, setDrpgs] = useState([])

  const [loadingRegions, setLoadingRegions] = useState(true)
  const [loadingCompartments, setLoadingCompartments] = useState(false)
  const [loadingDrpgs, setLoadingDrpgs] = useState(false)

  const [regionError, setRegionError] = useState(null)
  const [compartmentError, setCompartmentError] = useState(null)
  const [drpgError, setDrpgError] = useState(null)

  // Load regions on mount
  useEffect(() => {
    const fetchRegions = async () => {
      try {
        setLoadingRegions(true)
        setRegionError(null)
        const res = await axios.get('/api/regions')
        const sorted = res.data.sort((a, b) => a.name.localeCompare(b.name))
        setRegions(sorted)
      } catch (err) {
        setRegionError(err.response?.data?.error || err.message)
      } finally {
        setLoadingRegions(false)
      }
    }
    fetchRegions()
  }, [])

  // Load compartments when region changes
  useEffect(() => {
    if (!selectedRegion) return
    const fetchCompartments = async () => {
      try {
        setLoadingCompartments(true)
        setCompartmentError(null)
        setSelectedCompartment('')
        setDrpgs([])
        const res = await axios.get('/api/compartments', {
          params: { region: selectedRegion },
        })
        setCompartments(res.data)
      } catch (err) {
        setCompartmentError(err.response?.data?.error || err.message)
      } finally {
        setLoadingCompartments(false)
      }
    }
    fetchCompartments()
  }, [selectedRegion])

  const handleSearch = async () => {
    if (!selectedRegion || !selectedCompartment) return
    try {
      setLoadingDrpgs(true)
      setDrpgError(null)
      setDrpgs([])
      const res = await axios.get('/api/drpgs', {
        params: { region: selectedRegion, compartment_id: selectedCompartment },
      })
      setDrpgs(res.data)
    } catch (err) {
      setDrpgError(err.response?.data?.error || err.message)
    } finally {
      setLoadingDrpgs(false)
    }
  }

  const canSearch = selectedRegion && selectedCompartment && !loadingDrpgs

  return (
    <div className="min-h-screen bg-slate-100">
      {/* Top Bar */}
      <header className="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-3">
          <div className="bg-red-600 p-2 rounded-xl">
            <Shield className="text-white" size={22} />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 leading-tight">
              OCI DR Protection Group Dashboard
            </h1>
            <p className="text-xs text-gray-500">Oracle Cloud Infrastructure · Disaster Recovery</p>
          </div>
        </div>
      </header>

      {/* Filter Bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Globe size={15} className="text-red-600" />
            Select Region &amp; Compartment
          </h2>
          <div className="flex flex-col sm:flex-row gap-3 items-end">
            {/* Region Select */}
            <div className="flex-1">
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                Region
              </label>
              {loadingRegions ? (
                <div className="flex items-center gap-2 h-10 px-3 border border-gray-200 rounded-lg bg-gray-50">
                  <Spinner size="sm" />
                  <span className="text-sm text-gray-400">Loading regions…</span>
                </div>
              ) : regionError ? (
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <AlertCircle size={14} />
                  {regionError}
                </div>
              ) : (
                <select
                  value={selectedRegion}
                  onChange={(e) => setSelectedRegion(e.target.value)}
                  className="w-full h-10 px-3 border border-gray-200 rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"
                >
                  <option value="">— Select region —</option>
                  {regions.map((r) => (
                    <option key={r.name} value={r.name}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Compartment Select */}
            <div className="flex-1">
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                Compartment
              </label>
              {loadingCompartments ? (
                <div className="flex items-center gap-2 h-10 px-3 border border-gray-200 rounded-lg bg-gray-50">
                  <Spinner size="sm" />
                  <span className="text-sm text-gray-400">Loading compartments…</span>
                </div>
              ) : compartmentError ? (
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <AlertCircle size={14} />
                  {compartmentError}
                </div>
              ) : (
                <select
                  value={selectedCompartment}
                  onChange={(e) => setSelectedCompartment(e.target.value)}
                  disabled={!selectedRegion}
                  className="w-full h-10 px-3 border border-gray-200 rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-400"
                >
                  <option value="">— Select compartment —</option>
                  {compartments.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Search Button */}
            <button
              onClick={handleSearch}
              disabled={!canSearch}
              className="btn-primary flex items-center gap-2 whitespace-nowrap h-10 px-5"
            >
              {loadingDrpgs ? (
                <>
                  <Spinner size="sm" />
                  Searching…
                </>
              ) : (
                <>
                  <RefreshCw size={15} />
                  Load DRPGs
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 pb-12">
        {drpgError && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-5 py-4 rounded-xl flex items-start gap-3 mb-6">
            <AlertCircle size={18} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Failed to load DR Protection Groups</p>
              <p className="text-sm mt-0.5">{drpgError}</p>
            </div>
          </div>
        )}

        {!loadingDrpgs && drpgs.length > 0 && (
          <>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <Layers size={15} className="text-red-600" />
                Primary DR Protection Groups
                <span className="ml-1 bg-red-100 text-red-700 text-xs font-bold px-2 py-0.5 rounded-full">
                  {drpgs.length}
                </span>
              </h2>
              <p className="text-xs text-gray-400">
                Region: <span className="font-medium text-gray-600">{selectedRegion}</span>
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
              {drpgs.map((drpg) => (
                <DRPGCard
                  key={drpg.id}
                  drpg={drpg}
                  region={selectedRegion}
                  compartmentId={selectedCompartment}
                />
              ))}
            </div>
          </>
        )}

        {!loadingDrpgs && drpgs.length === 0 && selectedRegion && selectedCompartment && !drpgError && (
          <div className="card p-12 text-center">
            <Shield size={48} className="mx-auto text-gray-200 mb-4" />
            <p className="text-gray-500 font-medium">No primary DR Protection Groups found</p>
            <p className="text-sm text-gray-400 mt-1">
              Try a different region or compartment
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
