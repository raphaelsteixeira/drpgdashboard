import { useEffect, useState } from 'react'
import { X, FileText, ChevronRight, ArrowLeft, Clock, CheckCircle2, XCircle, AlertCircle, Loader2, Circle, ChevronDown, ChevronUp, PlayCircle } from 'lucide-react'
import axios from 'axios'
import StateBadge from './StateBadge'
import Spinner from './Spinner'

const PLAN_TYPE_LABELS = {
  SWITCHOVER: 'Switchover',
  FAILOVER: 'Failover',
  START_DRILL: 'Start Drill',
  STOP_DRILL: 'Stop Drill',
}

const EXEC_TYPE_COLORS = {
  SWITCHOVER:  'bg-orange-100 text-orange-800',
  FAILOVER:    'bg-red-100 text-red-800',
  START_DRILL: 'bg-blue-100 text-blue-800',
  STOP_DRILL:  'bg-gray-100 text-gray-700',
}

function StepStatusIcon({ status }) {
  const s = (status || '').toUpperCase()
  if (s === 'SUCCEEDED')                    return <CheckCircle2 size={14} className="text-green-500 shrink-0" />
  if (s === 'FAILED')                       return <XCircle      size={14} className="text-red-500 shrink-0" />
  if (s === 'IN_PROGRESS')                  return <Loader2      size={14} className="text-blue-500 animate-spin shrink-0" />
  if (s === 'CANCELED' || s === 'CANCELING') return <AlertCircle size={14} className="text-yellow-500 shrink-0" />
  return <Circle size={14} className="text-gray-300 shrink-0" />
}

function GroupRow({ group }) {
  const [open, setOpen] = useState(true)
  const sec = group.execution_duration_in_sec
  const dur = sec != null ? (sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`) : null

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <StepStatusIcon status={group.status} />
          <span className="font-semibold text-sm text-gray-800">{group.display_name}</span>
          {dur && <span className="text-xs text-gray-400 font-mono">{dur}</span>}
        </div>
        <div className="flex items-center gap-2">
          <StateBadge state={group.status} />
          {open ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
        </div>
      </button>

      {open && group.steps.length > 0 && (
        <div className="divide-y divide-gray-100">
          {group.steps.map(step => {
            const ssec = step.execution_duration_in_sec
            const sdur = ssec != null ? (ssec >= 60 ? `${Math.floor(ssec / 60)}m ${ssec % 60}s` : `${ssec}s`) : null
            return (
              <div key={step.id} className="px-4 py-2.5 flex items-start gap-3 hover:bg-gray-50">
                <StepStatusIcon status={step.status} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm text-gray-800">{step.display_name}</span>
                    {sdur && <span className="text-xs text-gray-400 font-mono">{sdur}</span>}
                  </div>
                  {step.error_message && (
                    <p className="text-xs text-red-600 mt-0.5 font-mono break-words">{step.error_message}</p>
                  )}
                </div>
                <StateBadge state={step.status} />
              </div>
            )
          })}
        </div>
      )}

      {open && group.steps.length === 0 && (
        <div className="px-4 py-2 text-xs text-gray-400 italic">No steps</div>
      )}
    </div>
  )
}

// ── Execution Detail ──────────────────────────────────────────────────────────
function ExecutionDetailView({ execution, region, onBack }) {
  const [detail, setDetail]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    axios
      .get(`/api/executions/${execution.id}`, { params: { region } })
      .then(r => setDetail(r.data))
      .catch(err => setError(err.response?.data?.error || err.message))
      .finally(() => setLoading(false))
  }, [execution.id, region])

  const typeLabel = PLAN_TYPE_LABELS[execution.plan_execution_type] || execution.plan_execution_type || '—'
  const typeColor = EXEC_TYPE_COLORS[execution.plan_execution_type] || 'bg-gray-100 text-gray-700'

  return (
    <>
      <div className="flex items-center justify-between p-6 border-b border-gray-100">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors shrink-0">
            <ArrowLeft size={18} />
          </button>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-gray-900 truncate">{execution.display_name}</h2>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${typeColor}`}>{typeLabel}</span>
              {execution.duration && (
                <span className="text-xs text-gray-500 flex items-center gap-1"><Clock size={11} />{execution.duration}</span>
              )}
              {execution.time_started && (
                <span className="text-xs text-gray-400">{new Date(execution.time_started).toLocaleString()}</span>
              )}
            </div>
          </div>
        </div>
        <StateBadge state={execution.lifecycle_state} />
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Spinner /><p className="text-sm text-gray-500">Loading execution details…</p>
          </div>
        )}
        {error && <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>}
        {!loading && !error && detail && (
          <div className="space-y-3">
            {detail.groups.length === 0 && (
              <p className="text-center text-gray-400 py-8">No execution groups found</p>
            )}
            {detail.groups.map(grp => <GroupRow key={grp.id} group={grp} />)}
          </div>
        )}
      </div>
    </>
  )
}

// ── Executions list ───────────────────────────────────────────────────────────
function ExecutionsView({ plan, onBack, onSelect }) {
  const [executions, setExecutions] = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [running, setRunning]       = useState(false)
  const [runError, setRunError]     = useState(null)
  const [runSuccess, setRunSuccess] = useState(null)

  const loadExecutions = () => {
    setLoading(true)
    setError(null)
    axios
      .get(`/api/drpgs/${plan.drpg_id}/executions`, {
        params: { region: plan.region, plan_id: plan.id },
      })
      .then(r => setExecutions(r.data))
      .catch(err => setError(err.response?.data?.error || err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadExecutions() }, [plan.id, plan.drpg_id, plan.region])

  const canPrecheck = ['SWITCHOVER', 'FAILOVER', 'START_DRILL', 'STOP_DRILL'].includes(plan.type)
  const isPlanActive = (plan.lifecycle_state || '').toUpperCase() === 'ACTIVE'

  async function handlePrecheck() {
    setRunning(true)
    setRunError(null)
    setRunSuccess(null)
    setConfirming(false)
    try {
      const res = await axios.post(`/api/plans/${plan.id}/precheck`, {
        region: plan.region,
        drpg_id: plan.drpg_id,
        plan_type: plan.type,
        display_name: `Precheck – ${plan.display_name}`,
      })
      setRunSuccess(res.data)
      loadExecutions()
    } catch (err) {
      setRunError(err.response?.data?.error || err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <div className="flex items-center justify-between p-6 border-b border-gray-100">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors shrink-0">
            <ArrowLeft size={18} />
          </button>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-gray-900 truncate">{plan.display_name}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {PLAN_TYPE_LABELS[plan.type] || plan.type || '—'} ·{' '}
              <span className={`font-semibold ${plan.source === 'PRIMARY' ? 'text-purple-700' : 'text-blue-700'}`}>
                {plan.source}
              </span>
            </p>
          </div>
        </div>
        {canPrecheck && !confirming && (
          <button
            onClick={() => isPlanActive && !running && setConfirming(true)}
            disabled={!isPlanActive || running}
            title={!isPlanActive ? `Plan must be ACTIVE to run a precheck (current: ${plan.lifecycle_state || 'unknown'})` : 'Run precheck'}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors shrink-0
              ${isPlanActive && !running
                ? 'bg-blue-50 hover:bg-blue-100 text-blue-700 cursor-pointer'
                : 'bg-gray-100 text-gray-400 cursor-not-allowed'}`}
          >
            {running
              ? <Loader2 size={13} className="animate-spin" />
              : <PlayCircle size={13} />}
            Run Precheck
          </button>
        )}
        {confirming && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-gray-600 font-medium">Run precheck?</span>
            <button
              onClick={handlePrecheck}
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-3">
        {runSuccess && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg text-sm">
            <CheckCircle2 size={15} className="text-green-500 shrink-0" />
            <span>Precheck started: <span className="font-semibold">{runSuccess.display_name}</span></span>
          </div>
        )}
        {runError && (
          <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">{runError}</div>
        )}
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Spinner /><p className="text-sm text-gray-500">Loading executions…</p>
          </div>
        )}
        {error && <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>}
        {!loading && !error && executions.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <FileText size={36} className="mx-auto mb-3 opacity-30" />
            <p>No executions found for this plan</p>
          </div>
        )}
        {!loading && executions.length > 0 && (
          <div className="space-y-2">
            {executions.map(exec => {
              const typeLabel = PLAN_TYPE_LABELS[exec.plan_execution_type] || exec.plan_execution_type || '—'
              const typeColor = EXEC_TYPE_COLORS[exec.plan_execution_type] || 'bg-gray-100 text-gray-700'
              return (
                <button
                  key={exec.id}
                  onClick={() => onSelect(exec)}
                  className="w-full text-left flex items-center justify-between p-4 rounded-xl border border-gray-100 hover:border-gray-300 bg-gray-50 hover:bg-white transition-all"
                >
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 text-sm truncate">{exec.display_name}</p>
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${typeColor}`}>{typeLabel}</span>
                      {exec.duration && (
                        <span className="text-xs text-gray-500 flex items-center gap-1"><Clock size={11} />{exec.duration}</span>
                      )}
                      {exec.time_started && (
                        <span className="text-xs text-gray-400">{new Date(exec.time_started).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    <StateBadge state={exec.lifecycle_state} />
                    <ChevronRight size={14} className="text-gray-400" />
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}

// ── Plans list ────────────────────────────────────────────────────────────────
function PlansListView({ drpg, region, onClose, onSelectPlan }) {
  const [plans, setPlans]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    axios
      .get(`/api/drpgs/${drpg.id}/plans`, { params: { region } })
      .then(r => setPlans(r.data))
      .catch(err => setError(err.response?.data?.error || err.message))
      .finally(() => setLoading(false))
  }, [drpg.id, region])

  const primaryPlans = plans.filter(p => p.source === 'PRIMARY')
  const standbyPlans = plans.filter(p => p.source === 'STANDBY')

  function PlanCard({ plan }) {
    return (
      <button
        onClick={() => onSelectPlan(plan)}
        className="w-full text-left flex items-center justify-between p-4 rounded-xl border border-gray-100 hover:border-gray-300 bg-gray-50 hover:bg-white transition-all"
      >
        <div>
          <p className="font-semibold text-gray-900 text-sm">{plan.display_name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Type: <span className="font-medium text-gray-700">{PLAN_TYPE_LABELS[plan.type] || plan.type || '—'}</span>
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            Updated: {plan.time_updated ? new Date(plan.time_updated).toLocaleString() : '—'}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-3">
          <StateBadge state={plan.lifecycle_state} />
          <ChevronRight size={14} className="text-gray-400" />
        </div>
      </button>
    )
  }

  function Section({ title, badge, plans }) {
    if (!plans.length) return null
    return (
      <div>
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full ${badge}`}>{title}</span>
        </div>
        <div className="space-y-2">
          {plans.map(p => <PlanCard key={p.id} plan={p} />)}
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="flex items-center justify-between p-6 border-b border-gray-100">
        <div>
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <FileText className="text-red-600" size={20} />
            DR Plans
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">{drpg.display_name}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors p-1.5 rounded-lg hover:bg-gray-100">
          <X size={20} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading && <div className="flex justify-center py-12"><Spinner /></div>}
        {error && <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>}
        {!loading && !error && plans.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <FileText size={40} className="mx-auto mb-3 opacity-30" />
            <p>No plans found</p>
          </div>
        )}
        {!loading && plans.length > 0 && (
          <div className="space-y-6">
            <Section title="PRIMARY" badge="bg-purple-100 text-purple-800" plans={primaryPlans} />
            <Section title="STANDBY" badge="bg-blue-100 text-blue-800"   plans={standbyPlans} />
          </div>
        )}
      </div>
    </>
  )
}

// ── Root modal ────────────────────────────────────────────────────────────────
export default function PlansModal({ drpg, region, onClose }) {
  const [view, setView]                         = useState('plans')
  const [selectedPlan, setSelectedPlan]         = useState(null)
  const [selectedExecution, setSelectedExecution] = useState(null)

  function handleSelectPlan(plan) {
    setSelectedPlan(plan)
    setView('executions')
  }

  function handleSelectExecution(exec) {
    setSelectedExecution(exec)
    setView('execution-detail')
  }

  function handleBack() {
    if (view === 'execution-detail') {
      setView('executions')
      setSelectedExecution(null)
    } else {
      setView('plans')
      setSelectedPlan(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col">

        {view === 'plans' && (
          <>
            <PlansListView drpg={drpg} region={region} onClose={onClose} onSelectPlan={handleSelectPlan} />
            <div className="p-4 border-t border-gray-100 flex justify-end">
              <button onClick={onClose} className="btn-secondary">Close</button>
            </div>
          </>
        )}

        {view === 'executions' && selectedPlan && (
          <>
            <ExecutionsView plan={selectedPlan} onBack={handleBack} onSelect={handleSelectExecution} />
            <div className="p-4 border-t border-gray-100 flex justify-between">
              <button onClick={handleBack} className="btn-secondary flex items-center gap-1.5">
                <ArrowLeft size={14} /> Back
              </button>
              <button onClick={onClose} className="btn-secondary">Close</button>
            </div>
          </>
        )}

        {view === 'execution-detail' && selectedExecution && (
          <>
            <ExecutionDetailView
              execution={selectedExecution}
              region={selectedPlan.region}
              onBack={handleBack}
            />
            <div className="p-4 border-t border-gray-100 flex justify-between">
              <button onClick={handleBack} className="btn-secondary flex items-center gap-1.5">
                <ArrowLeft size={14} /> Back
              </button>
              <button onClick={onClose} className="btn-secondary">Close</button>
            </div>
          </>
        )}

      </div>
    </div>
  )
}
