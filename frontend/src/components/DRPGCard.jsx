import { useState, useEffect } from 'react'
import { Shield, FileText, Box, ChevronRight, Clock, RotateCcw, MapPin, AlertTriangle } from 'lucide-react'
import axios from 'axios'
import StateBadge from './StateBadge'
import RpoBadge from './RpoBadge'
import PlansModal from './PlansModal'
import MembersModal from './MembersModal'

export default function DRPGCard({ drpg, region, compartmentId }) {
  const [showPlans, setShowPlans] = useState(false)
  const [showMembers, setShowMembers] = useState(false)
  const [rtoInfo, setRtoInfo] = useState(null)
  const [rtoLoading, setRtoLoading] = useState(false)
  const [membersRpo, setMembersRpo] = useState(null)
  const [membersLoading, setMembersLoading] = useState(false)

  // Fetch RTO on mount
  useEffect(() => {
    const fetchRto = async () => {
      try {
        setRtoLoading(true)
        const res = await axios.get(`/api/drpgs/${drpg.id}/rto`, {
          params: { region },
        })
        setRtoInfo(res.data)
      } catch (err) {
        setRtoInfo({ rto: 'Error', last_execution: null })
      } finally {
        setRtoLoading(false)
      }
    }
    fetchRto()
  }, [drpg.id, region])

  // Fetch members RPO on mount
  useEffect(() => {
    const fetchMembersRpo = async () => {
      try {
        setMembersLoading(true)
        const res = await axios.get(`/api/drpgs/${drpg.id}/members`, {
          params: { region, compartment_id: compartmentId },
        })
        const members = res.data
        if (!members || members.length === 0) {
          setMembersRpo({ rpo: 'No members', worst: null })
          return
        }

        // Calculate worst (max) RPO among members; flag any member with Unknown lifecycle state
        let worstSeconds = -1
        let worstRpo = null
        const hasUnknown = members.some(
          m => !m.lifecycle_state || m.lifecycle_state === 'UNKNOWN'
        )
        for (const m of members) {
          if (!m.rpo || m.rpo === 'Unknown' || m.rpo === 'N/A' || m.rpo.includes('No')) continue
          const seconds = parseRpoSeconds(m.rpo)
          if (seconds !== null && seconds > worstSeconds) {
            worstSeconds = seconds
            worstRpo = m.rpo
          }
        }
        setMembersRpo({ rpo: worstRpo || 'Unknown', worst: worstSeconds, hasUnknown })
      } catch {
        setMembersRpo({ rpo: 'Error', worst: null })
      } finally {
        setMembersLoading(false)
      }
    }
    fetchMembersRpo()
  }, [drpg.id, region, compartmentId])

  function parseRpoSeconds(rpoStr) {
    if (!rpoStr) return null
    let total = 0
    const hMatch = rpoStr.match(/(\d+)h/)
    const mMatch = rpoStr.match(/(\d+)m/)
    const sMatch = rpoStr.match(/(\d+)s/)
    if (hMatch) total += parseInt(hMatch[1]) * 3600
    if (mMatch) total += parseInt(mMatch[1]) * 60
    if (sMatch) total += parseInt(sMatch[1])
    return total
  }

  const peerInfo = drpg.peer_region
    ? `Peer: ${drpg.peer_region}`
    : null

  return (
    <>
      <div className="card hover:shadow-md transition-shadow duration-200">
        {/* Card Header */}
        <div className="p-5 border-b border-gray-100">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`rounded-xl p-2.5 shrink-0 ${membersRpo?.hasUnknown ? 'bg-amber-100' : 'bg-red-100'}`}>
                {membersRpo?.hasUnknown
                  ? <AlertTriangle className="text-amber-500" size={22} />
                  : <Shield className="text-red-600" size={22} />
                }
              </div>
              <div className="min-w-0">
                <h3 className="font-bold text-gray-900 text-base truncate">
                  {drpg.display_name}
                </h3>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  <StateBadge state={drpg.lifecycle_state} />
                  <span className="badge bg-purple-100 text-purple-800">
                    PRIMARY
                  </span>
                </div>
              </div>
            </div>
          </div>

          {peerInfo && (
            <div className="flex items-center gap-1.5 mt-3 text-xs text-gray-500">
              <MapPin size={12} />
              {peerInfo}
            </div>
          )}

          <p className="mt-2 text-xs font-mono text-gray-400 break-all">{drpg.id}</p>
        </div>

        {/* Misconfiguration Warning */}
        {!membersLoading && membersRpo?.hasUnknown && (
          <div className="mx-5 mt-3 mb-0 flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
            <AlertTriangle size={14} className="shrink-0 text-amber-500" />
            <span>
              <span className="font-semibold">Misconfiguration detected</span> — one or more members
              have an unknown RPO. Check Members for details.
            </span>
          </div>
        )}

        {/* Metrics Row */}
        <div className="grid grid-cols-2 divide-x divide-gray-100 border-b border-gray-100">
          <div className="p-4">
            <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1.5">
              <RotateCcw size={12} />
              <span className="font-semibold uppercase tracking-wide">Worst RPO</span>
            </div>
            {membersLoading ? (
              <div className="h-5 w-20 bg-gray-100 animate-pulse rounded" />
            ) : (
              <RpoBadge value={membersRpo?.rpo} />
            )}
          </div>
          <div className="p-4">
            <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1.5">
              <Clock size={12} />
              <span className="font-semibold uppercase tracking-wide">Last RTO</span>
            </div>
            {rtoLoading ? (
              <div className="h-5 w-20 bg-gray-100 animate-pulse rounded" />
            ) : (
              <div className="flex flex-col gap-0.5">
                <RpoBadge value={rtoInfo?.rto} />
                {rtoInfo?.standby_region && (
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <MapPin size={10} />
                    {rtoInfo.standby_region}
                  </span>
                )}
                {rtoInfo?.last_execution?.time_started && (
                  <span className="text-xs text-gray-400">
                    {new Date(rtoInfo.last_execution.time_started).toLocaleDateString()}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="p-4 flex gap-2">
          <button
            onClick={() => setShowMembers(true)}
            className="btn-secondary flex-1 flex items-center justify-center gap-2 text-sm"
          >
            <Box size={15} />
            Members
            <ChevronRight size={14} className="text-gray-400" />
          </button>
          <button
            onClick={() => setShowPlans(true)}
            className="btn-secondary flex-1 flex items-center justify-center gap-2 text-sm"
          >
            <FileText size={15} />
            Plans
            <ChevronRight size={14} className="text-gray-400" />
          </button>
        </div>
      </div>

      {showPlans && (
        <PlansModal
          drpg={drpg}
          region={region}
          onClose={() => setShowPlans(false)}
        />
      )}
      {showMembers && (
        <MembersModal
          drpg={drpg}
          region={region}
          compartmentId={compartmentId}
          onClose={() => setShowMembers(false)}
        />
      )}
    </>
  )
}
