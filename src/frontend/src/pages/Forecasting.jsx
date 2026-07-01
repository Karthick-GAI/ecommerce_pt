import { useState, useEffect, useCallback, useRef } from 'react'
import { forecastApi } from '../api/index.js'
import { useToast } from '../store/ToastContext.jsx'

const RISK = {
  critical: { color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', label: 'Critical' },
  warning:  { color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', label: 'Warning'  },
  low:      { color: '#2563EB', bg: '#EFF6FF', border: '#BFDBFE', label: 'Low'      },
  healthy:  { color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0', label: 'Healthy'  },
}

function RiskBadge({ level }) {
  const m = RISK[level] || RISK.healthy
  return (
    <span style={{
      display: 'inline-block', fontSize: '0.72rem', fontWeight: 700,
      padding: '2px 9px', borderRadius: 20, letterSpacing: '.02em',
      background: m.bg, color: m.color, border: `1px solid ${m.border}`,
    }}>
      {m.label}
    </span>
  )
}

function TrendIcon({ trend }) {
  if (trend === 'up')   return <span style={{ color: '#059669', fontWeight: 700 }}>↑</span>
  if (trend === 'down') return <span style={{ color: '#DC2626', fontWeight: 700 }}>↓</span>
  return <span style={{ color: '#6B7280', fontWeight: 700 }}>→</span>
}

// ── SVG Demand Chart ──────────────────────────────────────────────────────────

function DemandChart({ history, forecast, stockoutDate }) {
  if (!history || !forecast || history.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: 260, color: 'var(--muted)', fontSize: '0.875rem' }}>
        No chart data available
      </div>
    )
  }

  const W = 900, H = 260
  const padL = 55, padR = 20, padT = 25, padB = 45
  const chartW = W - padL - padR
  const chartH = H - padT - padB

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const parseDate = (s) => {
    const d = new Date(s)
    d.setHours(0, 0, 0, 0)
    return d
  }

  const allDates = [
    ...history.map(h => parseDate(h.date)),
    ...forecast.map(f => parseDate(f.date)),
  ]
  const minDate = new Date(Math.min(...allDates.map(d => d.getTime())))
  const maxDate = new Date(Math.max(...allDates.map(d => d.getTime())))

  const totalMs = maxDate.getTime() - minDate.getTime()

  const allUpperBounds = forecast.map(f => f.upper_bound || f.predicted_units || 0)
  const allHistUnits   = history.map(h => h.units_sold || 0)
  const rawMax = Math.max(...allUpperBounds, ...allHistUnits, 1)
  const yMax   = rawMax * 1.15

  const toX = (dateStr) => {
    const t = parseDate(dateStr).getTime() - minDate.getTime()
    return padL + (totalMs > 0 ? (t / totalMs) * chartW : 0)
  }

  const toY = (val) => {
    return padT + chartH - (val / yMax) * chartH
  }

  // Y-axis ticks
  const yTicks = Array.from({ length: 5 }, (_, i) => {
    const val = (yMax / 4) * i
    return { val, y: toY(val) }
  })

  // X-axis labels every 14 days
  const xLabels = []
  const labelStep = 14 * 24 * 60 * 60 * 1000
  let labelTime = minDate.getTime()
  while (labelTime <= maxDate.getTime()) {
    const d = new Date(labelTime)
    const x = padL + ((labelTime - minDate.getTime()) / totalMs) * chartW
    xLabels.push({ x, label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) })
    labelTime += labelStep
  }

  // Build history path
  const histPath = history
    .map((h, i) => {
      const x = toX(h.date)
      const y = toY(h.units_sold || 0)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  // Build forecast path
  const forecastPath = forecast
    .map((f, i) => {
      const x = toX(f.date)
      const y = toY(f.predicted_units || 0)
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  // Build confidence band path
  const upperPoints = forecast.map(f => ({ x: toX(f.date), y: toY(f.upper_bound || f.predicted_units || 0) }))
  const lowerPoints = forecast.map(f => ({ x: toX(f.date), y: toY(f.lower_bound || f.predicted_units || 0) }))

  const bandPath = upperPoints.length > 0
    ? [
        upperPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' '),
        [...lowerPoints].reverse().map(p => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' '),
        'Z',
      ].join(' ')
    : ''

  // Today line X
  const todayMs = today.getTime()
  const todayInRange = todayMs >= minDate.getTime() && todayMs <= maxDate.getTime()
  const todayX = todayInRange
    ? padL + ((todayMs - minDate.getTime()) / totalMs) * chartW
    : null

  // Stockout line X
  let stockoutX = null
  if (stockoutDate) {
    const sdMs = parseDate(stockoutDate).getTime()
    if (sdMs >= minDate.getTime() && sdMs <= maxDate.getTime()) {
      stockoutX = padL + ((sdMs - minDate.getTime()) / totalMs) * chartW
    }
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {/* Horizontal grid lines */}
      {yTicks.map((t, i) => (
        <line key={i}
          x1={padL} y1={t.y.toFixed(1)}
          x2={W - padR} y2={t.y.toFixed(1)}
          stroke="#E5E7EB" strokeWidth="1" />
      ))}

      {/* Y-axis tick labels */}
      {yTicks.map((t, i) => (
        <text key={i}
          x={(padL - 6).toFixed(1)} y={(t.y + 4).toFixed(1)}
          textAnchor="end" fontSize="10" fill="#9CA3AF">
          {Math.round(t.val)}
        </text>
      ))}

      {/* X-axis date labels */}
      {xLabels.map((l, i) => (
        <text key={i}
          x={l.x.toFixed(1)} y={(H - padB + 16).toFixed(1)}
          textAnchor="middle" fontSize="9.5" fill="#9CA3AF">
          {l.label}
        </text>
      ))}

      {/* Confidence band */}
      {bandPath && (
        <path d={bandPath} fill="rgba(124,58,237,0.10)" stroke="none" />
      )}

      {/* Historical line */}
      {histPath && (
        <path d={histPath} stroke="#2563EB" strokeWidth="2" fill="none" />
      )}

      {/* Forecast line */}
      {forecastPath && (
        <path d={forecastPath} stroke="#7C3AED" strokeWidth="2.5" fill="none" strokeDasharray="6,4" />
      )}

      {/* Today vertical line */}
      {todayX !== null && (
        <>
          <line
            x1={todayX.toFixed(1)} y1={padT}
            x2={todayX.toFixed(1)} y2={padT + chartH}
            stroke="#9CA3AF" strokeWidth="1.5" strokeDasharray="4,3" />
          <text x={(todayX + 4).toFixed(1)} y={(padT + 12).toFixed(1)}
            fontSize="9.5" fill="#9CA3AF">Today</text>
        </>
      )}

      {/* Stockout vertical line */}
      {stockoutX !== null && (
        <>
          <line
            x1={stockoutX.toFixed(1)} y1={padT}
            x2={stockoutX.toFixed(1)} y2={padT + chartH}
            stroke="#DC2626" strokeWidth="1.5" strokeDasharray="4,3" />
          <circle cx={stockoutX.toFixed(1)} cy={padT} r="4" fill="#DC2626" />
          <text x={(stockoutX + 5).toFixed(1)} y={(padT + 12).toFixed(1)}
            fontSize="9" fill="#DC2626" fontWeight="700">STOCKOUT</text>
        </>
      )}

      {/* Legend */}
      {(() => {
        const ly = H - 10
        const items = [
          { label: 'Historical', color: '#2563EB', dash: null },
          { label: 'Forecast',   color: '#7C3AED', dash: '6,4' },
          { label: 'Confidence Band', color: 'rgba(124,58,237,0.35)', fill: true },
        ]
        let lx = padL
        return items.map((item, i) => {
          const el = (
            <g key={i} transform={`translate(${lx},${ly})`}>
              {item.fill ? (
                <rect x="0" y="-7" width="20" height="9" fill="rgba(124,58,237,0.18)"
                  stroke="rgba(124,58,237,0.45)" strokeWidth="1" rx="1" />
              ) : (
                <line x1="0" y1="-3" x2="20" y2="-3"
                  stroke={item.color} strokeWidth="2"
                  strokeDasharray={item.dash || undefined} />
              )}
              <text x="24" y="0" fontSize="10" fill="#6B7280">{item.label}</text>
            </g>
          )
          lx += item.label.length * 6.5 + 36
          return el
        })
      })()}
    </svg>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function Forecasting() {
  const toast = useToast()

  // ── tab / filter state ────────────────────────────────────────────────────
  const [tab, setTab]                   = useState('categories')
  const [alertFilter, setAlertFilter]   = useState('all')

  // ── data state ────────────────────────────────────────────────────────────
  const [summary, setSummary]           = useState(null)
  const [categories, setCategories]     = useState([])
  const [alerts, setAlerts]             = useState([])
  const [totalAlerts, setTotalAlerts]   = useState(0)
  const [detail, setDetail]             = useState(null)       // category detail object

  // ── loading flags ─────────────────────────────────────────────────────────
  const [summaryLoading, setSummaryLoading]       = useState(true)
  const [categoriesLoading, setCategoriesLoading] = useState(true)
  const [alertsLoading, setAlertsLoading]         = useState(false)
  const [detailLoading, setDetailLoading]         = useState(false)
  const [training, setTraining]                   = useState(false)

  const pollRef = useRef(null)

  // ── data loaders ──────────────────────────────────────────────────────────
  const loadSummary = useCallback(async () => {
    try {
      const res = await forecastApi.summary()
      setSummary(res.data)
    } catch { /* silent on poll */ }
    finally { setSummaryLoading(false) }
  }, [])

  const loadCategories = useCallback(async () => {
    setCategoriesLoading(true)
    try {
      const res = await forecastApi.categories()
      setCategories(res.data.categories || [])
    } catch { toast('Could not load forecast categories', 'error') }
    finally { setCategoriesLoading(false) }
  }, [])

  const loadAlerts = useCallback(async () => {
    setAlertsLoading(true)
    try {
      const res = await forecastApi.restockAlerts()
      setAlerts(res.data.alerts || [])
      setTotalAlerts(res.data.total || 0)
    } catch { toast('Could not load restock alerts', 'error') }
    finally { setAlertsLoading(false) }
  }, [])

  const loadDetail = useCallback(async (category) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      const res = await forecastApi.category(category)
      setDetail(res.data)
    } catch { toast(`Could not load detail for ${category}`, 'error') }
    finally { setDetailLoading(false) }
  }, [])

  // ── lifecycle + polling ───────────────────────────────────────────────────
  useEffect(() => {
    loadSummary()
    loadCategories()
  }, [])

  useEffect(() => {
    if (tab === 'alerts') loadAlerts()
  }, [tab])

  // 30-second polling
  useEffect(() => {
    pollRef.current = setInterval(() => {
      loadSummary()
      if (tab === 'categories') loadCategories()
    }, 30000)
    return () => clearInterval(pollRef.current)
  }, [tab])

  // ── actions ───────────────────────────────────────────────────────────────
  async function handleTrain() {
    setTraining(true)
    try {
      const res = await forecastApi.train()
      toast(res.data.message || 'Model retrained successfully', 'success')
      loadSummary()
      loadCategories()
    } catch (e) {
      toast(e.response?.data?.detail || 'Training failed', 'error')
    } finally { setTraining(false) }
  }

  async function handleAcknowledge(alertId) {
    try {
      await forecastApi.acknowledge(alertId, { acknowledged_by: 'ops_team' })
      toast('Alert acknowledged', 'success')
      loadAlerts()
    } catch { toast('Could not acknowledge alert', 'error') }
  }

  function openDetail(category) {
    loadDetail(category)
  }

  function closeDetail() {
    setDetail(null)
  }

  // ── filtered alerts ────────────────────────────────────────────────────────
  const filteredAlerts = alertFilter === 'all'
    ? alerts
    : alerts.filter(a => a.severity === alertFilter)

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="page">
      <div className="container">

        {/* Page header */}
        <div style={s.pageHeader}>
          <div>
            <h1 style={{ marginBottom: 4 }}>Demand Forecasting</h1>
            <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>
              AI-powered demand predictions, restock alerts and category-level trend analysis
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {summary?.last_trained_at && (
              <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                Last trained: {new Date(summary.last_trained_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            <button
              className="btn btn-primary btn-sm"
              onClick={handleTrain}
              disabled={training}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {training ? (
                <>
                  <span style={s.spinnerSmall} />
                  Training…
                </>
              ) : 'Retrain Model'}
            </button>
          </div>
        </div>

        {/* Summary cards */}
        {summaryLoading ? (
          <div className="spinner-wrap"><div className="spinner" /></div>
        ) : summary && (
          <div style={s.statsRow}>
            {[
              { label: 'Categories Tracked', value: summary.categories_tracked,  color: '#2563EB' },
              { label: 'At Risk',             value: summary.categories_at_risk,  color: '#D97706' },
              { label: 'Critical Alerts',     value: summary.open_critical,       color: '#DC2626' },
              { label: 'Stockout < 7d',       value: summary.stockout_within_7d,  color: '#DC2626' },
              { label: 'Stockout < 30d',      value: summary.stockout_within_30d, color: '#D97706' },
            ].map(({ label, value, color }) => (
              <div key={label} style={s.statCard}>
                <span style={{ fontSize: '1.75rem', fontWeight: 800, color, display: 'block', fontVariantNumeric: 'tabular-nums' }}>
                  {(value ?? 0).toLocaleString()}
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: 2, display: 'block' }}>
                  {label}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Model metrics strip */}
        {summary?.model_metrics && summary.model_metrics.length > 0 && (
          <div style={s.metricsStrip}>
            <span style={{ fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 700, marginRight: 10 }}>
              RMSE:
            </span>
            {summary.model_metrics.map((m) => (
              <span key={m.category} style={s.metricChip}>
                {m.category}: <strong>{typeof m.rmse === 'number' ? m.rmse.toFixed(2) : m.rmse}</strong>
              </span>
            ))}
          </div>
        )}

        {/* Tabs */}
        <div style={s.tabBar}>
          {[
            ['categories', 'Category Overview', null],
            ['alerts',     'Restock Alerts',     totalAlerts > 0 ? totalAlerts : null],
          ].map(([key, label, badge]) => (
            <button key={key}
              style={{ ...s.tab, ...(tab === key ? s.tabActive : {}) }}
              onClick={() => setTab(key)}>
              {label}
              {badge !== null && badge > 0 && (
                <span style={{ ...s.tabBadge, background: '#DC2626' }}>{badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* ══ CATEGORY OVERVIEW TAB ══════════════════════════════════════════════ */}
        {tab === 'categories' && (
          <div>
            {categoriesLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : categories.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>📊</div>
                <h3>No forecast data yet</h3>
                <p style={{ color: 'var(--muted)', marginTop: 8, fontSize: '0.875rem' }}>
                  Run a model training to generate forecasts
                </p>
                <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={handleTrain} disabled={training}>
                  {training ? 'Training…' : 'Train Model'}
                </button>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Category', 'Current Stock', 'Avg Daily Demand', '30d Forecast', 'Days of Stock', 'Trend', 'Risk Level', 'Action'].map(h => (
                        <th key={h} style={s.th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map(cat => (
                      <tr key={cat.category} style={s.tr}>
                        <td style={{ ...s.td, fontWeight: 600, fontSize: '0.875rem' }}>
                          {cat.category}
                          {cat.has_alert && (
                            <span style={{ marginLeft: 6, color: '#DC2626', fontSize: '0.75rem', fontWeight: 700 }}>!</span>
                          )}
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                          {(cat.current_stock ?? 0).toLocaleString()}
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                          {typeof cat.avg_daily_demand === 'number' ? cat.avg_daily_demand.toFixed(1) : cat.avg_daily_demand}
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                          {(cat.forecast_30d_units ?? 0).toLocaleString()}
                        </td>
                        <td style={{
                          ...s.td, fontVariantNumeric: 'tabular-nums', fontWeight: 700,
                          color: (cat.days_of_stock ?? 999) <= 7 ? '#DC2626'
                               : (cat.days_of_stock ?? 999) <= 30 ? '#D97706' : 'var(--text)',
                        }}>
                          {cat.days_of_stock ?? '—'}
                        </td>
                        <td style={s.td}><TrendIcon trend={cat.trend} /></td>
                        <td style={s.td}><RiskBadge level={cat.risk_level} /></td>
                        <td style={s.td}>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => openDetail(cat.category)}>
                            View Detail
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Detail panel */}
            {(detailLoading || detail) && (
              <div style={s.detailPanel}>
                <div style={s.detailHeader}>
                  <h3 style={{ margin: 0, fontSize: '1.05rem' }}>
                    {detail ? detail.category : 'Loading…'}
                  </h3>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={closeDetail}
                    style={{ marginLeft: 'auto' }}>
                    Close
                  </button>
                </div>

                {detailLoading ? (
                  <div className="spinner-wrap" style={{ minHeight: 120 }}><div className="spinner" /></div>
                ) : detail && (
                  <>
                    {/* Detail meta row */}
                    <div style={s.detailMeta}>
                      <div style={s.detailMetaItem}>
                        <span style={s.metaLabel}>Current Stock</span>
                        <span style={s.metaValue}>{(detail.current_stock ?? 0).toLocaleString()}</span>
                      </div>
                      <div style={s.detailMetaItem}>
                        <span style={s.metaLabel}>Model RMSE</span>
                        <span style={s.metaValue}>
                          {typeof detail.model_rmse === 'number' ? detail.model_rmse.toFixed(3) : detail.model_rmse ?? '—'}
                        </span>
                      </div>
                      <div style={s.detailMetaItem}>
                        <span style={s.metaLabel}>Stockout Date</span>
                        <span style={{
                          ...s.metaValue,
                          color: detail.stockout_date ? '#DC2626' : 'var(--muted)',
                          fontWeight: detail.stockout_date ? 700 : 400,
                        }}>
                          {detail.stockout_date
                            ? new Date(detail.stockout_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                            : 'None projected'}
                        </span>
                      </div>
                    </div>

                    {/* Restock alert box */}
                    {detail.restock_alert && (
                      <div style={{
                        ...s.alertBox,
                        borderColor: detail.restock_alert.severity === 'critical' ? '#FECACA' : '#FDE68A',
                        background:  detail.restock_alert.severity === 'critical' ? '#FEF2F2' : '#FFFBEB',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <RiskBadge level={detail.restock_alert.severity} />
                          <span style={{ fontWeight: 700, fontSize: '0.875rem',
                            color: detail.restock_alert.severity === 'critical' ? '#DC2626' : '#D97706' }}>
                            Restock Required
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: '0.82rem', color: 'var(--muted)' }}>
                          <span>Days until stockout: <strong style={{ color: '#DC2626' }}>
                            {detail.restock_alert.days_until_stockout}
                          </strong></span>
                          <span>Avg daily demand: <strong style={{ color: 'var(--text)' }}>
                            {typeof detail.restock_alert.avg_daily_demand === 'number'
                              ? detail.restock_alert.avg_daily_demand.toFixed(1)
                              : detail.restock_alert.avg_daily_demand}
                          </strong></span>
                          <span>Recommended reorder: <strong style={{ color: '#2563EB' }}>
                            {(detail.restock_alert.recommended_reorder ?? 0).toLocaleString()} units
                          </strong></span>
                        </div>
                      </div>
                    )}

                    {/* SVG Chart */}
                    <div style={{ marginTop: 16, background: 'var(--ground)', borderRadius: 8, padding: '12px 8px 4px' }}>
                      <DemandChart
                        history={detail.history}
                        forecast={detail.forecast}
                        stockoutDate={detail.stockout_date}
                      />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* ══ RESTOCK ALERTS TAB ════════════════════════════════════════════════ */}
        {tab === 'alerts' && (
          <div>
            <div style={s.filterRow}>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>Filter:</span>
              {[['all', 'All'], ['critical', 'Critical'], ['warning', 'Warning']].map(([key, label]) => (
                <button key={key}
                  style={{ ...s.chip, ...(alertFilter === key ? s.chipActive : {}) }}
                  onClick={() => setAlertFilter(key)}>
                  {label}
                  {key !== 'all' && (
                    <span style={{ opacity: .7, fontSize: '0.7rem' }}>
                      &nbsp;{alerts.filter(a => a.severity === key).length}
                    </span>
                  )}
                </button>
              ))}
              <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--muted)' }}>
                {filteredAlerts.length} alert{filteredAlerts.length !== 1 ? 's' : ''}
              </span>
            </div>

            {alertsLoading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : filteredAlerts.length === 0 ? (
              <div className="empty-state" style={{ padding: '48px 0' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>✅</div>
                <h3>No alerts{alertFilter !== 'all' ? ` for ${alertFilter} severity` : ''}</h3>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
                {filteredAlerts.map(alert => {
                  const rm = RISK[alert.severity] || RISK.warning
                  return (
                    <div key={alert.id} style={{
                      background: 'var(--surface)',
                      borderRadius: 'var(--radius)',
                      border: `1px solid ${rm.border}`,
                      borderLeft: `4px solid ${rm.color}`,
                      boxShadow: 'var(--shadow)',
                      padding: '16px 18px',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                        <RiskBadge level={alert.severity} />
                        <span style={{ fontWeight: 700, fontSize: '0.9rem', flex: 1 }}>{alert.category}</span>
                        {alert.status === 'acknowledged' && (
                          <span style={{ fontSize: '0.72rem', color: '#059669', fontWeight: 700 }}>Acknowledged</span>
                        )}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: '0.8rem', marginBottom: 10 }}>
                        <div>
                          <span style={{ color: 'var(--muted)' }}>Current Stock</span>
                          <div style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                            {(alert.current_stock ?? 0).toLocaleString()}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted)' }}>Avg Daily Demand</span>
                          <div style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                            {typeof alert.avg_daily_demand === 'number' ? alert.avg_daily_demand.toFixed(1) : alert.avg_daily_demand ?? '—'}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted)' }}>Days Until Stockout</span>
                          <div style={{ fontWeight: 700, color: '#DC2626', fontVariantNumeric: 'tabular-nums' }}>
                            {alert.days_until_stockout ?? '—'}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted)' }}>30d Forecast Demand</span>
                          <div style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                            {(alert.forecasted_demand_30d ?? 0).toLocaleString()}
                          </div>
                        </div>
                        <div style={{ gridColumn: '1/-1' }}>
                          <span style={{ color: 'var(--muted)' }}>Recommended Reorder Qty</span>
                          <div style={{ fontWeight: 700, color: '#2563EB', fontVariantNumeric: 'tabular-nums' }}>
                            {(alert.recommended_reorder_qty ?? 0).toLocaleString()} units
                          </div>
                        </div>
                      </div>
                      {alert.triggered_at && (
                        <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginBottom: 8 }}>
                          Triggered: {new Date(alert.triggered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                          {alert.acknowledged_by && ` · Ack'd by ${alert.acknowledged_by}`}
                        </div>
                      )}
                      {alert.status !== 'acknowledged' && (
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ width: '100%', marginTop: 4 }}
                          onClick={() => handleAcknowledge(alert.id)}>
                          Acknowledge
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

const s = {
  pageHeader:    { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 },
  statsRow:      { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 },
  statCard:      { background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '16px 20px', textAlign: 'left', boxShadow: 'var(--shadow)', border: '1.5px solid var(--border)' },
  metricsStrip:  { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, padding: '8px 14px', background: 'var(--ground)', borderRadius: 'var(--radius)', marginBottom: 20, fontSize: '0.78rem' },
  metricChip:    { padding: '2px 10px', borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--muted)', fontSize: '0.78rem' },
  tabBar:        { display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 24 },
  tab:           { padding: '10px 20px', border: 'none', background: 'none', fontSize: '0.9rem', fontWeight: 600, color: 'var(--muted)', borderBottom: '2px solid transparent', marginBottom: -2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, transition: 'color .15s, border-color .15s' },
  tabActive:     { color: 'var(--primary)', borderBottomColor: 'var(--primary)' },
  tabBadge:      { color: '#fff', fontSize: '0.68rem', fontWeight: 700, padding: '1px 6px', borderRadius: 10, lineHeight: 1.6 },
  filterRow:     { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 16 },
  chip:          { padding: '5px 14px', borderRadius: 20, border: '1.5px solid var(--border)', background: 'var(--surface)', fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', cursor: 'pointer', transition: 'all .15s' },
  chipActive:    { background: 'var(--primary)', color: '#fff', borderColor: 'var(--primary)' },
  table:         { width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' },
  th:            { textAlign: 'left', padding: '10px 12px', fontSize: '0.72rem', letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 700, background: 'var(--ground)', borderBottom: '2px solid var(--border)' },
  td:            { padding: '12px 12px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle' },
  tr:            { transition: 'background .1s' },
  detailPanel:   { marginTop: 24, background: 'var(--surface)', border: '1.5px solid var(--border)', borderRadius: 'var(--radius)', padding: '20px 24px', boxShadow: 'var(--shadow)' },
  detailHeader:  { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, paddingBottom: 14, borderBottom: '1px solid var(--border)' },
  detailMeta:    { display: 'flex', gap: 32, flexWrap: 'wrap', marginBottom: 14 },
  detailMetaItem:{ display: 'flex', flexDirection: 'column', gap: 2 },
  metaLabel:     { fontSize: '0.72rem', color: 'var(--muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em' },
  metaValue:     { fontSize: '1rem', fontWeight: 600, color: 'var(--text)' },
  alertBox:      { border: '1px solid', borderRadius: 8, padding: '12px 16px', marginBottom: 8 },
  spinnerSmall:  { width: 14, height: 14, borderRadius: '50%', border: '2px solid rgba(255,255,255,.3)', borderTopColor: '#fff', animation: 'spin .7s linear infinite', display: 'inline-block' },
}
