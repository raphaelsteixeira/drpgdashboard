import { useEffect, useState } from 'react'
import { X, Server, Database, HardDrive, FolderOpen, Container, Box } from 'lucide-react'
import axios from 'axios'
import StateBadge from './StateBadge'
import RpoBadge from './RpoBadge'
import Spinner from './Spinner'

const MEMBER_TYPE_ICONS = {
  COMPUTE_INSTANCE: Server,
  COMPUTE_INSTANCE_MOVABLE: Server,
  COMPUTE_INSTANCE_NON_MOVABLE: Server,
  VOLUME_GROUP: HardDrive,
  DATABASE: Database,
  AUTONOMOUS_DATABASE: Database,
  AUTONOMOUS_CONTAINER_DATABASE: Database,
  MYSQL_DB_SYSTEM: Database,
  FILE_SYSTEM: FolderOpen,
  OKE_CLUSTER: Container,
  LOAD_BALANCER: Box,
  NETWORK_LOAD_BALANCER: Box,
  OBJECT_STORAGE_BUCKET: Box,
  INTEGRATION_INSTANCE: Box,
}

const MEMBER_TYPE_LABELS = {
  COMPUTE_INSTANCE: 'Compute Instance',
  COMPUTE_INSTANCE_MOVABLE: 'Compute Instance (Movable)',
  COMPUTE_INSTANCE_NON_MOVABLE: 'Compute Instance (Non-Movable)',
  VOLUME_GROUP: 'Volume Group',
  DATABASE: 'Database',
  AUTONOMOUS_DATABASE: 'Autonomous Database',
  AUTONOMOUS_CONTAINER_DATABASE: 'Autonomous Container DB',
  MYSQL_DB_SYSTEM: 'MySQL DB System',
  FILE_SYSTEM: 'File System',
  OKE_CLUSTER: 'OKE Cluster',
  LOAD_BALANCER: 'Load Balancer',
  NETWORK_LOAD_BALANCER: 'Network Load Balancer',
  OBJECT_STORAGE_BUCKET: 'Object Storage Bucket',
  INTEGRATION_INSTANCE: 'Integration Instance',
}

export default function MembersModal({ drpg, region, compartmentId, onClose }) {
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchMembers = async () => {
      try {
        setLoading(true)
        const res = await axios.get(`/api/drpgs/${drpg.id}/members`, {
          params: { region, compartment_id: compartmentId },
        })
        setMembers(res.data)
      } catch (err) {
        setError(err.response?.data?.error || err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchMembers()
  }, [drpg.id, region, compartmentId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-[77rem] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <Box className="text-red-600" size={20} />
              Members
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">{drpg.display_name}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors p-1.5 rounded-lg hover:bg-gray-100"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Spinner />
              <p className="text-sm text-gray-500">Fetching members and calculating RPO…</p>
            </div>
          )}
          {error && (
            <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}
          {!loading && !error && members.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              <Box size={40} className="mx-auto mb-3 opacity-30" />
              <p>No members found</p>
            </div>
          )}
          {!loading && members.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wide">Type</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wide">State</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wide">RPO</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wide">Last Sync</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((m, idx) => {
                    const Icon = MEMBER_TYPE_ICONS[m.member_type] || Box
                    return (
                      <tr
                        key={m.member_id || idx}
                        className="border-b border-gray-50 hover:bg-gray-50 transition-colors"
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <Icon size={15} className="text-gray-400 shrink-0" />
                            <span className="text-gray-700 font-medium whitespace-nowrap">
                              {MEMBER_TYPE_LABELS[m.member_type] || m.member_type}
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <div>
                            <span className="text-gray-800 font-medium text-sm">
                              {m.display_name && m.display_name !== m.member_id
                                ? m.display_name
                                : m.member_id || '—'}
                            </span>
                            {m.display_name && m.display_name !== m.member_id && (
                              <p className="text-xs text-gray-400 font-mono truncate max-w-sm">
                                {m.member_id}
                              </p>
                            )}
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          {m.lifecycle_state
                            ? <StateBadge state={m.lifecycle_state} />
                            : <span className="text-gray-400 text-xs">—</span>}
                        </td>
                        <td className="py-3 px-4">
                          <RpoBadge value={m.rpo} />
                        </td>
                        <td className="py-3 px-4 text-xs text-gray-500 whitespace-nowrap">
                          {m.last_sync
                            ? new Date(m.last_sync).toLocaleString()
                            : m.apply_lag_raw
                              ? <span className="text-orange-600 font-mono">{m.apply_lag_raw}</span>
                              : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-gray-100 flex justify-end">
          <button onClick={onClose} className="btn-secondary">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
