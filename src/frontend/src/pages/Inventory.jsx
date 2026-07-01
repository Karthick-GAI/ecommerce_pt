import { useState, useEffect, useRef, useCallback } from 'react'
import { inventoryApi, alertsApi, alertRulesApi } from '../api/index.js'
import { useToast } from '../store/ToastContext.jsx'

const HEALTH_META = {
  out_of_stock: { label: 'Out of Stock', color: '#7C3AED', bg: '#F5F3FF', border: '#DDD6FE' },
  critical:     { label: 'Critical',     color: '#DC2626', bg: '#FEF2F2', border: '#FECACA' },
  low:          { label: 'Low Stock',    color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  healthy:      { label: 'Healthy',      color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0' },
}

const SEVERITY_META = {
  critical: { color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', label: 'Critical' },
  warning:  { color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', label: 'Warning'  },
  info:     { color: '#2563EB', bg: '#EFF6FF', border: '#BFDBFE', label: 'Info'     },
}

const CHANGE_TYPE_ICON = {
  restock:    '📦',
  adjustment: '✏️',
  damage:     '💥',
  return:     '↩',
  audit:      '🔍',
  sale:       '🛒',
}

function HealthBadge({ health }) {
  const m = HEALTH_META[health] || HEALTH_META.healthy
  return (
    <span style={{ display: 'inline-block', fontSize: '0.72rem', fontWeight: 700,
      padding: '2px 9px', borderRadius: 20, letterSpacing: '.02em',
      background: m.bg, color: m.color, border: `1px solid ${m.border}` }}>
      {m.label}
    </span>
  )
}

function SeverityBadge({ severity }) {
  const m = SEVERITY_META[severity] || SEVERITY_META.warning
  return (
    <span style={{ display: 'inline-block', fontSize: '0.72rem', fontWeight: 700,
      padding: '2px 9px', borderRadius: 20, letterSpacing: '.02em',
      background: m.bg, color: m.color, border: `1px solid ${m.border}` }}>
      {m.label}
    </span>
  )
}

function RuleTypeBadge({ type }) {
  const meta = {
    global:   { bg: '#F0F9FF', color: '#0369A1', border: '#BAE6FD', label: 'Global'   },
    category: { bg: '#F5F3FF', color: '#7C3AED', border: '#DDD6FE', label: 'Category' },
    product:  { bg: '#FFF7ED', color: '#C2410C', border: '#FED7AA', label: 'Product'  },
  }[type] || { bg: '#F3F4F6', color: '#6B7280', border: '#E5E7EB', label: type }
  return (
    <span style={{ display: 'inline-block', fontSize: '0.68rem', fontWeight: 700,
      padding: '2px 8px', borderRadius: 20, letterSpacing: '.04em',
      background: meta.bg, color: meta.color, border: `1px solid ${meta.border}` }}>
      {meta.label}
    </span>
  )
}

export default function Inventory() {
  const toast = useToast()

  // ── tab / filter state ──────────────────────────────────────────────────────
  const [tab, setTab]                         = useState('stock')
  const [healthFilter, setHealthFilter]       = useState('')
  const [alertStatusFilter, setAlertStatusFilter] = useState('open')

  // ── data state ──────────────────────────────────────────────────────────────
  const [products, setProducts]       = useState([])
  const [totalProducts, setTotalProducts] = useState(0)
  const [alerts, setAlerts]           = useState([])
  const [totalAlerts, setTotalAlerts] = useState(0)
  const [dashboard, setDashboard]     = useState(null)
  const [rules, setRules]             = useState([])

  // ── loading flags ────────────────────────────────────────────────────────────
  const [productsLoading, setProductsLoading] = useState(true)
  const [alertsLoading, setAlertsLoading]     = useState(false)
  const [rulesLoading, setRulesLoading]       = useState(false)

  // ── SSE ─────────────────────────────────────────────────────────────────────
  const [sseConnected, setSseConnected] = useState(false)
  const [lastUpdated, setLastUpdated]   = useState(null)
  const esRef = useRef(null)

  // ── stock modal (restock / adjust) ──────────────────────────────────────────
  const [modal, setModal]       = useState(null)
  const [form, setForm]         = useState({})
  const [submitting, setSubmitting] = useState(false)

  // ── alert-rules modal ───────────────────────────────────────────────────────
  const [ruleModal, setRuleModal]         = useState(null) // null | { mode:'create'|'edit', rule? }
  const [ruleForm, setRuleForm]           = useState({})
  const [ruleSubmitting, setRuleSubmitting] = useState(false)

  // ── movement history modal ───────────────────────────────────────────────────
  const [historyModal, setHistoryModal]     = useState(null) // null | { product, movements }
  const [historyLoading, setHistoryLoading] = useState(false)

  // ── data loaders ─────────────────────────────────────────────────────────────
  const loadDashboard = useCallback(async () => {
    try {
      const res = await inventoryApi.dashboard()
      setDashboard(res.data)
      setLastUpdated(new Date())
    } catch { /* silent */ }
  }, [])

  const loadProducts = useCallback(async (health) => {
    setProductsLoading(true)
    try {
      const params = { limit: 25 }
      if (health) params.health = health
      const res = await inventoryApi.list(params)
      setProducts(res.data.results || [])
      setTotalProducts(res.data.total || 0)
    } catch { toast('Could not load inventory', 'error') }
    finally { setProductsLoading(false) }
  }, [])

  const loadAlerts = useCallback(async (status) => {
    setAlertsLoading(true)
    try {
      const res = await alertsApi.list({ status, limit: 30 })
      setAlerts(res.data.alerts || [])
      setTotalAlerts(res.data.total || 0)
    } catch { toast('Could not load alerts', 'error') }
    finally { setAlertsLoading(false) }
  }, [])

  const loadRules = useCallback(async () => {
    setRulesLoading(true)
    try {
      const res = await alertRulesApi.list()
      setRules(res.data.rules || [])
    } catch { toast('Could not load alert rules', 'error') }
    finally { setRulesLoading(false) }
  }, [])

  // ── lifecycle ────────────────────────────────────────────────────────────────
  useEffect(() => {
    loadDashboard()
    loadProducts('')
  }, [])

  useEffect(() => {
    if (tab === 'alerts') loadAlerts(alertStatusFilter)
  }, [tab, alertStatusFilter])

  useEffect(() => {
    if (tab === 'rules') loadRules()
  }, [tab])

  // SSE real-time connection
  useEffect(() => {
    const es = new EventSource('http://localhost:8005/inventory/stream')
    esRef.current = es
    es.onopen  = () => setSseConnected(true)
    es.onerror = () => setSseConnected(false)
    es.addEventListener('inventory_change', () => {
      loadDashboard()
      loadProducts(healthFilter)
    })
    es.addEventListener('low_stock_alert', () => {
      loadDashboard()
      if (tab === 'alerts') loadAlerts(alertStatusFilter)
    })
    return () => es.close()
  }, [healthFilter, tab, alertStatusFilter])

  function setHealthFilterAndLoad(h) {
    setHealthFilter(h)
    loadProducts(h)
  }

  // ── stock actions ─────────────────────────────────────────────────────────────
  function openModal(type, product) {
    setModal({ type, product })
    setForm(type === 'adjust' ? { change_type: 'adjustment' } : {})
  }
  function closeModal() { setModal(null); setForm({}) }

  async function handleRestock() {
    const qty = Number(form.quantity)
    if (!qty || qty <= 0) { toast('Enter a valid quantity', 'error'); return }
    setSubmitting(true)
    try {
      await inventoryApi.restock(modal.product.product_id, {
        quantity: qty,
        reference_id: form.reference_id || undefined,
        notes: form.notes || undefined,
        changed_by: 'ops_team',
      })
      toast(`Restocked ${modal.product.name} +${qty} units`, 'success')
      closeModal()
      loadDashboard()
      loadProducts(healthFilter)
    } catch (e) { toast(e.response?.data?.detail || 'Restock failed', 'error') }
    finally { setSubmitting(false) }
  }

  async function handleAdjust() {
    const qc = Number(form.quantity_change)
    if (!qc || qc === 0) { toast('Enter a non-zero quantity change', 'error'); return }
    if (!form.reason) { toast('Reason is required', 'error'); return }
    setSubmitting(true)
    try {
      await inventoryApi.adjust(modal.product.product_id, {
        quantity_change: qc,
        change_type: form.change_type || 'adjustment',
        reason: form.reason,
        changed_by: 'ops_team',
      })
      toast(`Adjusted ${modal.product.name} by ${qc > 0 ? '+' : ''}${qc} units`, 'success')
      closeModal()
      loadDashboard()
      loadProducts(healthFilter)
    } catch (e) { toast(e.response?.data?.detail || 'Adjustment failed', 'error') }
    finally { setSubmitting(false) }
  }

  // ── alert actions ─────────────────────────────────────────────────────────────
  async function acknowledgeAlert(alertId) {
    try {
      await alertsApi.acknowledge(alertId, { acknowledged_by: 'ops_team' })
      toast('Alert acknowledged', 'success')
      loadAlerts(alertStatusFilter)
      loadDashboard()
    } catch { toast('Could not acknowledge', 'error') }
  }

  async function resolveAlert(alertId) {
    try {
      await alertsApi.resolve(alertId)
      toast('Alert resolved', 'success')
      loadAlerts(alertStatusFilter)
      loadDashboard()
    } catch { toast('Could not resolve', 'error') }
  }

  async function bulkAcknowledge() {
    try {
      await alertsApi.bulkAcknowledge({ acknowledged_by: 'ops_team' })
      toast('All open alerts acknowledged', 'success')
      loadAlerts(alertStatusFilter)
      loadDashboard()
    } catch { toast('Bulk acknowledge failed', 'error') }
  }

  // ── alert rule actions ────────────────────────────────────────────────────────
  function openCreateRule() {
    setRuleForm({ rule_type: 'category', target_id: '', threshold_value: '', alert_severity: 'warning' })
    setRuleModal({ mode: 'create' })
  }

  function openEditRule(rule) {
    setRuleForm({
      rule_type:       rule.rule_type,
      target_id:       rule.target_id,
      label:           rule.label,
      threshold_value: rule.threshold_value,
      alert_severity:  rule.alert_severity,
      is_active:       rule.is_active,
    })
    setRuleModal({ mode: 'edit', rule })
  }

  async function handleSaveRule() {
    const { rule_type, target_id, threshold_value, alert_severity } = ruleForm
    if (!target_id?.trim()) { toast('Target ID is required', 'error'); return }
    if (threshold_value === '' || threshold_value === null) { toast('Threshold is required', 'error'); return }
    setRuleSubmitting(true)
    try {
      if (ruleModal.mode === 'create') {
        await alertRulesApi.create({
          rule_type,
          target_id: target_id.trim(),
          label: ruleForm.label?.trim() || undefined,
          threshold_value: Number(threshold_value),
          alert_severity,
        })
        toast('Alert rule created', 'success')
      } else {
        await alertRulesApi.update(ruleModal.rule.rule_id, {
          label:           ruleForm.label?.trim() || undefined,
          threshold_value: Number(threshold_value),
          alert_severity,
          is_active:       ruleForm.is_active,
        })
        toast('Alert rule updated', 'success')
      }
      setRuleModal(null)
      loadRules()
    } catch (e) {
      const detail = e.response?.data?.detail
      toast(typeof detail === 'string' ? detail : 'Could not save rule', 'error')
    } finally { setRuleSubmitting(false) }
  }

  async function handleToggleRule(rule) {
    try {
      await alertRulesApi.update(rule.rule_id, { is_active: !rule.is_active })
      toast(rule.is_active ? 'Rule disabled' : 'Rule enabled', 'success')
      loadRules()
    } catch { toast('Could not update rule', 'error') }
  }

  // ── movement history ──────────────────────────────────────────────────────────
  async function openHistory(product) {
    setHistoryModal({ product, movements: [] })
    setHistoryLoading(true)
    try {
      const res = await inventoryApi.movements(product.product_id)
      setHistoryModal({ product, movements: res.data.movements || [] })
    } catch { toast('Could not load movement history', 'error') }
    finally { setHistoryLoading(false) }
  }

  // ── derived values ────────────────────────────────────────────────────────────
  const summary     = dashboard?.summary || {}
  const openCritical = dashboard?.alerts?.open_critical ?? 0
  const openWarning  = dashboard?.alerts?.open_warning ?? 0

  const ruleTypeTargetHint = {
    global:   '"*" — applies to all products',
    category: 'Exact category name, e.g. "Electronics"',
    product:  'Product UUID',
  }

  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <div className="page">
      <div className="container">

        {/* Page header */}
        <div style={s.pageHeader}>
          <div>
            <h1 style={{ marginBottom: 4 }}>Inventory Operations</h1>
            <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>
              Real-time stock levels, low-stock alerts and alert-rule management
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {lastUpdated && (
              <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                Updated {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem',
              color: sseConnected ? 'var(--success, #059669)' : 'var(--muted)', fontWeight: 600 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: sseConnected ? '#059669' : '#9CA3AF',
                ...(sseConnected ? { animation: 'pulse 2s infinite' } : {}),
              }} />
              {sseConnected ? 'Live' : 'Connecting…'}
            </div>
          </div>
        </div>

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }`}</style>

        {/* Stats bar */}
        {dashboard && (
          <div style={s.statsRow}>
            {[
              { key: 'out_of_stock', label: 'Out of Stock', value: summary.out_of_stock, color: '#7C3AED' },
              { key: 'critical',     label: 'Critical',     value: summary.critical,     color: '#DC2626' },
              { key: 'low',         label: 'Low Stock',    value: summary.low,          color: '#D97706' },
              { key: 'healthy',     label: 'Healthy',      value: summary.healthy,      color: '#16A34A' },
            ].map(({ key, label, value, color }) => (
              <button key={key}
                style={{ ...s.statCard, border: healthFilter === key && tab === 'stock' ? `2px solid ${color}` : '2px solid var(--border)', cursor: 'pointer' }}
                onClick={() => { setTab('stock'); setHealthFilterAndLoad(healthFilter === key ? '' : key) }}>
                <span style={{ fontSize: '1.75rem', fontWeight: 800, color, display: 'block', fontVariantNumeric: 'tabular-nums' }}>
                  {(value ?? 0).toLocaleString()}
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 2, display: 'block' }}>{label}</span>
              </button>
            ))}
            <button
              style={{ ...s.statCard, border: tab === 'alerts' ? '2px solid #DC2626' : '2px solid var(--border)', cursor: 'pointer' }}
              onClick={() => setTab('alerts')}>
              <span style={{ fontSize: '1.75rem', fontWeight: 800, color: '#DC2626', display: 'block', fontVariantNumeric: 'tabular-nums' }}>
                {(openCritical + openWarning).toLocaleString()}
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 2, display: 'block' }}>Open Alerts</span>
            </button>
          </div>
        )}

        {/* Tabs */}
        <div style={s.tabBar}>
          {[
            ['stock',  'Stock Levels',  null],
            ['alerts', 'Alert Queue',   openCritical + openWarning > 0 ? openCritical + openWarning : null],
            ['rules',  'Alert Rules',   rules.filter(r => r.is_active).length || null],
          ].map(([key, label, badge]) => (
            <button key={key}
              style={{ ...s.tab, ...(tab === key ? s.tabActive : {}) }}
              onClick={() => setTab(key)}>
              {label}
              {badge !== null && badge > 0 && (
                <span style={{ ...s.tabBadge, background: key === 'alerts' ? '#DC2626' : '#7C3AED' }}>{badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* ══ STOCK TAB ══════════════════════════════════════════════════════════ */}
        {tab === 'stock' && (
          <div>
            <div style={s.filterRow}>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>Filter:</span>
              {[['', 'All'], ['out_of_stock', 'Out of Stock'], ['critical', 'Critical'], ['low', 'Low Stock'], ['healthy', 'Healthy']].map(([key, label]) => (
                <button key={key}
                  style={{ ...s.chip, ...(healthFilter === key ? s.chipActive : {}) }}
                  onClick={() => setHealthFilterAndLoad(key)}>
                  {label}
                  {key && dashboard && (
                    <span style={{ opacity: .7, fontSize: '0.7rem' }}>&nbsp;{(summary[key] ?? 0).toLocaleString()}</span>
                  )}
                </button>
              ))}
              <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--muted)' }}>
                Showing {products.length} of {totalProducts.toLocaleString()}
              </span>
            </div>

            {productsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : products.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📦</div>
                <h3>No products found</h3>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Product', 'Category', 'Brand', 'Stock', 'Status', 'Actions'].map(h => (
                        <th key={h} style={s.th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {products.map(p => (
                      <tr key={p.product_id} style={s.tr}>
                        <td style={{ ...s.td, maxWidth: 260 }}>
                          <span style={{ fontWeight: 600, fontSize: '0.875rem', display: 'block',
                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {p.name}
                          </span>
                        </td>
                        <td style={{ ...s.td, color: 'var(--muted)', fontSize: '0.8rem' }}>{p.category}</td>
                        <td style={{ ...s.td, color: 'var(--muted)', fontSize: '0.8rem' }}>{p.brand}</td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 700,
                          color: p.health === 'healthy' ? 'var(--text)' : HEALTH_META[p.health]?.color }}>
                          {p.stock}
                        </td>
                        <td style={s.td}><HealthBadge health={p.health} /></td>
                        <td style={s.td}>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button className="btn btn-primary btn-sm" onClick={() => openModal('restock', p)}>Restock</button>
                            <button className="btn btn-ghost btn-sm" onClick={() => openModal('adjust', p)}>Adjust</button>
                            <button className="btn btn-ghost btn-sm" onClick={() => openHistory(p)} title="Movement history">History</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ══ ALERTS TAB ════════════════════════════════════════════════════════ */}
        {tab === 'alerts' && (
          <div>
            <div style={s.filterRow}>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>Status:</span>
              {[['open', 'Open'], ['acknowledged', 'Acknowledged'], ['resolved', 'Resolved']].map(([key, label]) => (
                <button key={key}
                  style={{ ...s.chip, ...(alertStatusFilter === key ? s.chipActive : {}) }}
                  onClick={() => setAlertStatusFilter(key)}>
                  {label}
                </button>
              ))}
              {alertStatusFilter === 'open' && (openCritical + openWarning) > 0 && (
                <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={bulkAcknowledge}>
                  Acknowledge All ({openCritical + openWarning})
                </button>
              )}
              {alertStatusFilter !== 'open' && (
                <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--muted)' }}>{totalAlerts} alerts</span>
              )}
            </div>

            {alertsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : alerts.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>{alertStatusFilter === 'open' ? '✅' : '📋'}</div>
                <h3>{alertStatusFilter === 'open' ? 'No open alerts' : 'No alerts found'}</h3>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {alerts.map(a => (
                  <div key={a.alert_id} style={{ ...s.alertRow, borderLeft: `3px solid ${a.severity === 'critical' ? '#DC2626' : '#D97706'}` }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                        <SeverityBadge severity={a.severity} />
                        <span style={{ fontWeight: 600, fontSize: '0.875rem',
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 300 }}>
                          {a.product_name}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 16, fontSize: '0.775rem', color: 'var(--muted)' }}>
                        <span>{a.category} · {a.brand}</span>
                        <span style={{ fontVariantNumeric: 'tabular-nums' }}>Stock: <strong style={{ color: 'var(--text)' }}>{a.current_stock}</strong></span>
                        <span>Threshold: ≤{a.threshold}</span>
                        <span>{new Date(a.created_at).toLocaleDateString()}</span>
                      </div>
                      {a.acknowledged_by && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 2 }}>Ack'd by {a.acknowledged_by}</div>
                      )}
                    </div>
                    {a.status === 'open' && (
                      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => acknowledgeAlert(a.alert_id)}>Acknowledge</button>
                        <button className="btn btn-outline btn-sm" onClick={() => resolveAlert(a.alert_id)}>Resolve</button>
                      </div>
                    )}
                    {a.status === 'acknowledged' && (
                      <button className="btn btn-outline btn-sm" onClick={() => resolveAlert(a.alert_id)}>Resolve</button>
                    )}
                    {a.status === 'resolved' && (
                      <span style={{ fontSize: '0.75rem', color: '#059669', fontWeight: 600 }}>✓ Resolved</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ══ ALERT RULES TAB ═══════════════════════════════════════════════════ */}
        {tab === 'rules' && (
          <div>
            <div style={s.filterRow}>
              <p style={{ color: 'var(--muted)', fontSize: '0.82rem', flex: 1 }}>
                Rules define when low-stock alerts fire. Each rule targets a specific product, category, or all products globally.
              </p>
              <button className="btn btn-primary btn-sm" onClick={openCreateRule}>+ New Rule</button>
            </div>

            {rulesLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : rules.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>⚙️</div>
                <h3>No alert rules yet</h3>
                <p style={{ color: 'var(--muted)', marginTop: 8, fontSize: '0.875rem' }}>Create a rule to start receiving low-stock alerts</p>
                <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={openCreateRule}>+ New Rule</button>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Type', 'Label / Target', 'Threshold', 'Severity', 'Status', 'Actions'].map(h => (
                        <th key={h} style={s.th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map(rule => (
                      <tr key={rule.rule_id} style={{ ...s.tr, opacity: rule.is_active ? 1 : 0.5 }}>
                        <td style={s.td}><RuleTypeBadge type={rule.rule_type} /></td>
                        <td style={{ ...s.td, maxWidth: 280 }}>
                          <p style={{ fontWeight: 600, fontSize: '0.875rem', margin: 0 }}>{rule.label}</p>
                          <p style={{ color: 'var(--muted)', fontSize: '0.75rem', margin: '2px 0 0', fontFamily: 'monospace' }}>
                            {rule.target_id}
                          </p>
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>
                          ≤ {rule.threshold_value}
                        </td>
                        <td style={s.td}><SeverityBadge severity={rule.alert_severity} /></td>
                        <td style={s.td}>
                          <button
                            onClick={() => handleToggleRule(rule)}
                            style={{
                              display: 'inline-flex', alignItems: 'center', gap: 6,
                              background: 'none', border: 'none', cursor: 'pointer',
                              fontSize: '0.78rem', fontWeight: 700,
                              color: rule.is_active ? '#059669' : '#9CA3AF',
                            }}>
                            <span style={{
                              width: 32, height: 18, borderRadius: 9, display: 'inline-block',
                              background: rule.is_active ? '#059669' : '#D1D5DB',
                              position: 'relative', transition: 'background .2s',
                            }}>
                              <span style={{
                                position: 'absolute', top: 2, borderRadius: '50%',
                                width: 14, height: 14, background: '#fff',
                                left: rule.is_active ? 16 : 2, transition: 'left .2s',
                              }} />
                            </span>
                            {rule.is_active ? 'Active' : 'Disabled'}
                          </button>
                        </td>
                        <td style={s.td}>
                          <button className="btn btn-ghost btn-sm" onClick={() => openEditRule(rule)}>Edit</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══ RESTOCK / ADJUST MODAL ════════════════════════════════════════════════ */}
      {modal && (
        <div style={s.overlay} onClick={closeModal}>
          <div style={s.modalBox} onClick={e => e.stopPropagation()}>
            <div style={s.modalHeader}>
              <div>
                <h2 style={{ fontSize: '1.1rem', marginBottom: 2 }}>
                  {modal.type === 'restock' ? 'Restock Product' : 'Adjust Stock'}
                </h2>
                <p style={{ color: 'var(--muted)', fontSize: '0.8rem' }}>{modal.product.name}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <HealthBadge health={modal.product.health} />
                <div style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 4 }}>
                  Current stock: <strong>{modal.product.stock}</strong>
                </div>
              </div>
            </div>

            {modal.type === 'restock' ? (
              <div style={s.formGrid}>
                <div className="form-group">
                  <label>Quantity to Add *</label>
                  <input className="input" type="number" min="1" placeholder="e.g. 50"
                    value={form.quantity || ''} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label>Purchase Order / Reference</label>
                  <input className="input" placeholder="e.g. PO-2026-001"
                    value={form.reference_id || ''} onChange={e => setForm(f => ({ ...f, reference_id: e.target.value }))} />
                </div>
                <div className="form-group" style={{ gridColumn: '1/-1' }}>
                  <label>Notes</label>
                  <input className="input" placeholder="Optional notes"
                    value={form.notes || ''} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
                </div>
              </div>
            ) : (
              <div style={s.formGrid}>
                <div className="form-group">
                  <label>Quantity Change *</label>
                  <input className="input" type="number" placeholder="Negative to reduce, e.g. -5"
                    value={form.quantity_change || ''} onChange={e => setForm(f => ({ ...f, quantity_change: e.target.value }))} />
                  {form.quantity_change && (
                    <p style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 4 }}>
                      New stock: <strong>{modal.product.stock + Number(form.quantity_change)}</strong>
                    </p>
                  )}
                </div>
                <div className="form-group">
                  <label>Change Type *</label>
                  <select className="input" value={form.change_type || 'adjustment'}
                    onChange={e => setForm(f => ({ ...f, change_type: e.target.value }))}>
                    <option value="adjustment">Adjustment</option>
                    <option value="damage">Damage</option>
                    <option value="return">Return</option>
                    <option value="audit">Audit</option>
                  </select>
                </div>
                <div className="form-group" style={{ gridColumn: '1/-1' }}>
                  <label>Reason *</label>
                  <input className="input" placeholder="Why is this adjustment being made?"
                    value={form.reason || ''} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} />
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button className="btn btn-ghost" onClick={closeModal}>Cancel</button>
              <button className="btn btn-primary" disabled={submitting}
                onClick={modal.type === 'restock' ? handleRestock : handleAdjust}>
                {submitting ? 'Saving…' : modal.type === 'restock' ? 'Restock' : 'Apply Adjustment'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ══ ALERT RULE CREATE / EDIT MODAL ═══════════════════════════════════════ */}
      {ruleModal && (
        <div style={s.overlay} onClick={() => setRuleModal(null)}>
          <div style={s.modalBox} onClick={e => e.stopPropagation()}>
            <h2 style={{ fontSize: '1.1rem', marginBottom: 4 }}>
              {ruleModal.mode === 'create' ? '+ New Alert Rule' : 'Edit Alert Rule'}
            </h2>
            <p style={{ color: 'var(--muted)', fontSize: '0.8rem', marginBottom: 20 }}>
              Alert fires when a product's stock falls at or below the threshold.
            </p>

            <div style={s.formGrid}>
              {ruleModal.mode === 'create' && (
                <div className="form-group">
                  <label>Rule Type *</label>
                  <select className="input" value={ruleForm.rule_type || 'category'}
                    onChange={e => setRuleForm(f => ({ ...f, rule_type: e.target.value, target_id: e.target.value === 'global' ? '*' : '' }))}>
                    <option value="global">Global — all products</option>
                    <option value="category">Category</option>
                    <option value="product">Specific product</option>
                  </select>
                </div>
              )}

              {ruleModal.mode === 'create' && (
                <div className="form-group">
                  <label>Target ID *</label>
                  <input className="input"
                    placeholder={ruleTypeTargetHint[ruleForm.rule_type || 'category']}
                    value={ruleForm.target_id || ''}
                    readOnly={ruleForm.rule_type === 'global'}
                    onChange={e => setRuleForm(f => ({ ...f, target_id: e.target.value }))} />
                  <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 4 }}>
                    {ruleTypeTargetHint[ruleForm.rule_type || 'category']}
                  </p>
                </div>
              )}

              <div className="form-group">
                <label>Threshold (stock ≤ N fires alert) *</label>
                <input className="input" type="number" min="0" placeholder="e.g. 10"
                  value={ruleForm.threshold_value ?? ''}
                  onChange={e => setRuleForm(f => ({ ...f, threshold_value: e.target.value }))} />
              </div>

              <div className="form-group">
                <label>Severity *</label>
                <select className="input" value={ruleForm.alert_severity || 'warning'}
                  onChange={e => setRuleForm(f => ({ ...f, alert_severity: e.target.value }))}>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                  <option value="info">Info</option>
                </select>
              </div>

              <div className="form-group" style={{ gridColumn: '1/-1' }}>
                <label>Label (optional)</label>
                <input className="input" placeholder="Human-readable name for this rule"
                  value={ruleForm.label || ''}
                  onChange={e => setRuleForm(f => ({ ...f, label: e.target.value }))} />
              </div>

              {ruleModal.mode === 'edit' && (
                <div className="form-group" style={{ gridColumn: '1/-1' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                    <input type="checkbox" checked={ruleForm.is_active ?? true}
                      onChange={e => setRuleForm(f => ({ ...f, is_active: e.target.checked }))} />
                    <span>Rule is active</span>
                  </label>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button className="btn btn-ghost" onClick={() => setRuleModal(null)}>Cancel</button>
              <button className="btn btn-primary" disabled={ruleSubmitting} onClick={handleSaveRule}>
                {ruleSubmitting ? 'Saving…' : ruleModal.mode === 'create' ? 'Create Rule' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ══ MOVEMENT HISTORY MODAL ════════════════════════════════════════════════ */}
      {historyModal && (
        <div style={s.overlay} onClick={() => setHistoryModal(null)}>
          <div style={{ ...s.modalBox, maxWidth: 620 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h2 style={{ fontSize: '1.05rem', marginBottom: 2 }}>Movement History</h2>
                <p style={{ color: 'var(--muted)', fontSize: '0.8rem' }}>{historyModal.product.name}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <HealthBadge health={historyModal.product.health} />
                <p style={{ fontSize: '0.78rem', color: 'var(--muted)', marginTop: 4 }}>
                  Current: <strong>{historyModal.product.stock}</strong>
                </p>
              </div>
            </div>

            {historyLoading ? (
              <div className="spinner-wrap" style={{ minHeight: 100 }}><div className="spinner" /></div>
            ) : historyModal.movements.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--muted)' }}>
                <p style={{ fontSize: '2rem' }}>📋</p>
                <p style={{ marginTop: 8 }}>No movement history yet</p>
              </div>
            ) : (
              <div style={{ maxHeight: 380, overflowY: 'auto' }}>
                <table style={{ ...s.table, fontSize: '0.82rem' }}>
                  <thead>
                    <tr>
                      {['Type', 'Change', 'Stock After', 'By / Reference', 'Date'].map(h => (
                        <th key={h} style={{ ...s.th, padding: '8px 10px' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {historyModal.movements.map((m, i) => (
                      <tr key={i} style={s.tr}>
                        <td style={{ ...s.td, padding: '9px 10px' }}>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600 }}>
                            {CHANGE_TYPE_ICON[m.change_type] || '•'}
                            <span style={{ textTransform: 'capitalize' }}>{m.change_type}</span>
                          </span>
                          {m.notes && <p style={{ fontSize: '0.73rem', color: 'var(--muted)', margin: '2px 0 0' }}>{m.notes}</p>}
                        </td>
                        <td style={{ ...s.td, padding: '9px 10px', fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                          color: m.quantity_change > 0 ? '#059669' : m.quantity_change < 0 ? '#DC2626' : 'var(--muted)' }}>
                          {m.quantity_change > 0 ? '+' : ''}{m.quantity_change}
                        </td>
                        <td style={{ ...s.td, padding: '9px 10px', fontVariantNumeric: 'tabular-nums' }}>
                          {m.quantity_after}
                        </td>
                        <td style={{ ...s.td, padding: '9px 10px', color: 'var(--muted)', fontSize: '0.78rem' }}>
                          <div>{m.changed_by}</div>
                          {m.reference_id && <div style={{ fontFamily: 'monospace' }}>{m.reference_id}</div>}
                        </td>
                        <td style={{ ...s.td, padding: '9px 10px', color: 'var(--muted)', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                          {new Date(m.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
              <button className="btn btn-ghost" onClick={() => setHistoryModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const s = {
  pageHeader: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 },
  statsRow:   { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 24 },
  statCard:   { background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '16px 20px', textAlign: 'left', boxShadow: 'var(--shadow)', transition: 'border-color .15s', width: '100%' },
  tabBar:     { display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 24 },
  tab:        { padding: '10px 20px', border: 'none', background: 'none', fontSize: '0.9rem', fontWeight: 600, color: 'var(--muted)', borderBottom: '2px solid transparent', marginBottom: -2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, transition: 'color .15s, border-color .15s' },
  tabActive:  { color: 'var(--primary)', borderBottomColor: 'var(--primary)' },
  tabBadge:   { color: '#fff', fontSize: '0.68rem', fontWeight: 700, padding: '1px 6px', borderRadius: 10, lineHeight: 1.6 },
  filterRow:  { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 16 },
  chip:       { padding: '5px 14px', borderRadius: 20, border: '1.5px solid var(--border)', background: 'var(--surface)', fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', cursor: 'pointer', transition: 'all .15s' },
  chipActive: { background: 'var(--primary)', color: '#fff', borderColor: 'var(--primary)' },
  table:      { width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' },
  th:         { textAlign: 'left', padding: '10px 12px', fontSize: '0.72rem', letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 700, background: 'var(--ground)', borderBottom: '2px solid var(--border)' },
  td:         { padding: '12px 12px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle' },
  tr:         { transition: 'background .1s' },
  alertRow:   { display: 'flex', alignItems: 'center', gap: 16, padding: '14px 16px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', borderLeft: '3px solid transparent' },
  overlay:    { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 },
  modalBox:   { background: 'var(--surface)', borderRadius: 'var(--radius-lg)', padding: '28px 32px', width: '100%', maxWidth: 520, boxShadow: 'var(--shadow-lg)' },
  modalHeader:{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, gap: 12 },
  formGrid:   { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 },
}
