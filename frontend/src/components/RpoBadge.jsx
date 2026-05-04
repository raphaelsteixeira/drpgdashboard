/**
 * Colour-coded RPO / RTO badge.
 *
 * Green  : ≤ 5 min
 * Yellow : ≤ 30 min
 * Orange : ≤ 2 h
 * Red    : > 2 h
 * Gray   : Unknown / N/A
 */
function parseSeconds(rpoStr) {
  if (!rpoStr || rpoStr === 'Unknown' || rpoStr === 'N/A') return null
  let total = 0
  const hMatch = rpoStr.match(/(\d+)h/)
  const mMatch = rpoStr.match(/(\d+)m/)
  const sMatch = rpoStr.match(/(\d+)s/)
  if (hMatch) total += parseInt(hMatch[1]) * 3600
  if (mMatch) total += parseInt(mMatch[1]) * 60
  if (sMatch) total += parseInt(sMatch[1])
  return total
}

export default function RpoBadge({ value, label }) {
  const seconds = parseSeconds(value)
  let color = 'bg-gray-100 text-gray-600'

  if (seconds !== null) {
    if (seconds <= 300) color = 'bg-green-100 text-green-800'
    else if (seconds <= 1800) color = 'bg-yellow-100 text-yellow-800'
    else if (seconds <= 7200) color = 'bg-orange-100 text-orange-800'
    else color = 'bg-red-100 text-red-800'
  }

  return (
    <div className="flex flex-col items-start gap-0.5">
      {label && <span className="text-xs text-gray-400">{label}</span>}
      <span className={`badge ${color} font-mono text-xs`}>{value || 'Unknown'}</span>
    </div>
  )
}
