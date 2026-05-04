const STATE_COLORS = {
  // Lifecycle states
  ACTIVE: 'bg-green-100 text-green-800',
  AVAILABLE: 'bg-green-100 text-green-800',
  SUCCEEDED: 'bg-green-100 text-green-800',
  RUNNING: 'bg-blue-100 text-blue-800',
  UPDATING: 'bg-blue-100 text-blue-800',
  PROVISIONING: 'bg-blue-100 text-blue-800',
  ACCEPTED: 'bg-blue-100 text-blue-800',
  IN_PROGRESS: 'bg-blue-100 text-blue-800',
  WARNING: 'bg-yellow-100 text-yellow-800',
  NEEDS_ATTENTION: 'bg-yellow-100 text-yellow-800',
  FAILED: 'bg-red-100 text-red-800',
  DELETED: 'bg-gray-100 text-gray-600',
  CANCELED: 'bg-gray-100 text-gray-600',
  DELETING: 'bg-orange-100 text-orange-800',
}

export default function StateBadge({ state }) {
  const color = STATE_COLORS[state?.toUpperCase()] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`badge ${color}`}>
      {state || 'Unknown'}
    </span>
  )
}
