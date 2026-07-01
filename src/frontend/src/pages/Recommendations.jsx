import { useState, useEffect, useCallback, useRef } from 'react'
import { recommendationsApi, feedbackApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'
import { productImageUrl } from '../utils/productImage.js'

// ── Strategy display labels ───────────────────────────────────────────────────
const STRATEGY_LABELS = {
  personalized:     'For you',
  cf_item:          'Bought together',
  cf_user:          'Users like you',
  content_purchase: 'Based on purchase',
  category:         'Your category',
  trending:         'Trending',
  trending_views:   'Popular this week',
  new_arrival:      'New arrival',
  deals:            'Top deal',
}

const STRATEGY_COLORS = {
  personalized:     '#4F46E5',
  cf_item:          '#0891B2',
  cf_user:          '#7C3AED',
  content_purchase: '#059669',
  category:         '#D97706',
  trending:         '#DC2626',
  trending_views:   '#B45309',
  new_arrival:      '#059669',
  deals:            '#9333EA',
}

const CAT_COLORS = {
  Electronics:       '#2563EB',
  Clothing:          '#7C3AED',
  Beauty:            '#DB2777',
  Books:             '#D97706',
  'Home & Kitchen':  '#059669',
  'Sports & Fitness':'#0891B2',
  Grocery:           '#65A30D',
  'Toys & Games':    '#F59E0B',
  Automotive:        '#6B7280',
  'Baby Products':   '#EC4899',
  'Pet Supplies':    '#10B981',
  Stationery:        '#8B5CF6',
  Furniture:         '#92400E',
}

const CAT_EMOJI = {
  Electronics: '📱', Clothing: '👕', Beauty: '💄', Books: '📚',
  'Home & Kitchen': '🏠', 'Sports & Fitness': '⚽', Grocery: '🛒',
  'Toys & Games': '🎮', Automotive: '🚗', 'Baby Products': '🍼',
  'Pet Supplies': '🐾', Stationery: '✏️', Furniture: '🛋',
}

const FILTER_STRATEGIES = {
  all:          null,
  personalized: ['personalized', 'cf_user', 'cf_item', 'content_purchase'],
  trending:     ['trending', 'trending_views'],
  deals:        ['deals'],
  new:          ['new_arrival'],
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Recommendations() {
  const { user }                         = useAuth()
  const [customerId, setCustomerId]      = useState('')
  const [draftId, setDraftId]            = useState('')
  const [recs, setRecs]                  = useState([])
  const [loading, setLoading]            = useState(false)
  const [error, setError]                = useState(null)
  const [stats, setStats]                = useState(null)
  const [filter, setFilter]              = useState('all')
  const [feedbackMap, setFeedbackMap]    = useState({})   // productId → type
  const [hiddenIds, setHiddenIds]        = useState(new Set())
  const [toasts, setToasts]              = useState([])
  const toastCounter                     = useRef(0)

  // Pre-fill from logged-in user
  useEffect(() => {
    if (user?.id && !customerId) {
      setCustomerId(user.id)
      setDraftId(user.id)
    }
  }, [user])

  // Load recs + stats whenever customerId changes
  useEffect(() => {
    if (customerId) fetchAll(customerId)
  }, [customerId])

  const fetchAll = useCallback(async (cid) => {
    setLoading(true)
    setError(null)
    try {
      const [recRes, statsRes] = await Promise.allSettled([
        recommendationsApi.forCustomer(cid, { limit: 24 }),
        feedbackApi.stats(cid),
      ])
      if (recRes.status === 'fulfilled') {
        setRecs(recRes.value.data.recommendations || [])
      } else {
        throw new Error(recRes.reason?.message || 'Failed to load recommendations')
      }
      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data)
      }
    } catch (e) {
      setError('Recommendation service unavailable. Make sure port 8006 is running.')
    } finally {
      setLoading(false)
    }
  }, [])

  function handleLoadId(e) {
    e.preventDefault()
    const id = draftId.trim()
    if (!id) return
    setCustomerId(id)
    setFeedbackMap({})
    setHiddenIds(new Set())
    setStats(null)
    setRecs([])
  }

  // ── Toast helpers ─────────────────────────────────────────────────────────
  function toast(message, type = 'success') {
    const id = ++toastCounter.current
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3800)
  }

  // ── Feedback handler ──────────────────────────────────────────────────────
  async function giveFeedback(productId, feedbackType, strategy) {
    if (!customerId || feedbackMap[productId]) return

    // Optimistic update
    setFeedbackMap(m => ({ ...m, [productId]: feedbackType }))
    if (feedbackType === 'not_interested') {
      setHiddenIds(s => { const n = new Set(s); n.add(productId); return n })
    }

    const MSGS = {
      thumbs_up:      'More recommendations like this coming up!',
      thumbs_down:    "We'll reduce similar items in your feed.",
      not_interested: 'Product hidden from your recommendations.',
    }
    toast(MSGS[feedbackType], feedbackType === 'thumbs_down' ? 'warn' : 'ok')

    try {
      await feedbackApi.give({
        customer_id:   customerId,
        product_id:    productId,
        feedback_type: feedbackType,
        rec_strategy:  strategy || null,
      })
      // Refresh stats sidebar without reloading the whole grid
      const statsRes = await feedbackApi.stats(customerId)
      setStats(statsRes.data)
    } catch {
      setFeedbackMap(m => { const n = { ...m }; delete n[productId]; return n })
      toast('Could not save feedback — try again.', 'err')
    }
  }

  async function resetAdaptation() {
    if (!customerId) return
    await feedbackApi.reset(customerId)
    setFeedbackMap({})
    setHiddenIds(new Set())
    setStats(null)
    toast('Taste profile reset. Refreshing…', 'info')
    fetchAll(customerId)
  }

  // ── Derived data ──────────────────────────────────────────────────────────
  const adaptation    = stats?.adaptation || {}
  const catBoosts     = adaptation.category_boosts  || {}
  const brandBoosts   = adaptation.brand_boosts     || {}
  const thumbsUp      = adaptation.total_thumbs_up  || 0
  const thumbsDown    = adaptation.total_thumbs_down || 0
  const blockedCount  = adaptation.blocked_count    || 0
  const hasAdaptation = thumbsUp + thumbsDown > 0

  const allowedStrategies = FILTER_STRATEGIES[filter]
  const visibleRecs = recs.filter(r => {
    if (hiddenIds.has(r.product_id))         return false
    if (!allowedStrategies)                  return true
    if (filter === 'deals')
      return r.strategy === 'deals' || (r.discount_pct && r.discount_pct > 10)
    return allowedStrategies.includes(r.strategy)
  })

  // Sorted category boost entries for sidebar bars
  const boostEntries = Object.entries(catBoosts).sort((a, b) => b[1] - a[1]).slice(0, 8)

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={s.page}>

      {/* Toast layer */}
      <div style={s.toastLayer}>
        {toasts.map(t => (
          <div key={t.id} style={{
            ...s.toast,
            background:  t.type === 'err' ? '#FEF2F2' : t.type === 'warn' ? '#FFFBEB' : t.type === 'info' ? '#EFF6FF' : '#F0FDF4',
            borderColor: t.type === 'err' ? '#FECACA' : t.type === 'warn' ? '#FDE68A' : t.type === 'info' ? '#BFDBFE' : '#A7F3D0',
            color:       t.type === 'err' ? '#B91C1C' : t.type === 'warn' ? '#92400E' : t.type === 'info' ? '#1D4ED8' : '#065F46',
          }}>
            {t.type === 'err' ? '✕' : t.type === 'warn' ? '↓' : t.type === 'info' ? 'ℹ' : '✓'}
            &nbsp;{t.message}
          </div>
        ))}
      </div>

      <div className="container" style={s.wrap}>

        {/* ── Page header ── */}
        <div style={s.header}>
          <div>
            <h1 style={s.title}>Personalized For You</h1>
            <p style={s.subtitle}>Recommendations refine in real-time as you give feedback on each card.</p>
          </div>
          <form onSubmit={handleLoadId} style={s.idForm}>
            <input
              className="input"
              style={s.idInput}
              value={draftId}
              onChange={e => setDraftId(e.target.value)}
              placeholder="Customer ID (e.g. CUST-001)"
            />
            <button type="submit" className="btn btn-primary" style={s.idBtn}>Load</button>
            <button
              type="button"
              className="btn btn-outline"
              style={s.idBtn}
              onClick={() => customerId && fetchAll(customerId)}
              disabled={loading || !customerId}
            >
              {loading ? '⏳' : '↺'} Refresh
            </button>
          </form>
        </div>

        {/* ── No customer ID yet ── */}
        {!customerId ? (
          <div style={s.splash}>
            <div style={s.splashIcon}>🎯</div>
            <h2 style={s.splashTitle}>Enter a Customer ID to start</h2>
            <p style={s.splashDesc}>
              Type any customer ID above. As you give thumbs-up or thumbs-down on cards,
              the engine learns your preferences and re-ranks future recommendations in real time.
            </p>
            <p style={s.splashHint}>
              Try a dataset customer: <code style={s.code}>CUST-001</code>,{' '}
              <code style={s.code}>CUST-042</code>, <code style={s.code}>CUST-100</code>
              &nbsp;— or any string for a fresh cold-start profile.
            </p>
          </div>
        ) : (
          <div style={s.layout}>

            {/* ── Taste profile sidebar ── */}
            <aside style={s.sidebar}>

              {/* Profile card */}
              <div style={s.sideCard}>
                <div style={s.sideLabel}>Taste Profile</div>
                <div style={s.custBadge}>{customerId}</div>

                {!hasAdaptation ? (
                  <p style={s.sideHint}>
                    Give feedback on recommendations below to build your taste profile.
                    The more you rate, the more personalized your feed becomes.
                  </p>
                ) : (
                  <>
                    {/* Thumbs stats */}
                    <div style={s.thumbStats}>
                      <div style={s.thumbChip}>
                        <span style={{ color: '#059669', fontWeight: 700, fontSize: 15 }}>👍</span>
                        <span style={s.thumbNum}>{thumbsUp}</span>
                      </div>
                      <div style={s.thumbChip}>
                        <span style={{ color: '#DC2626', fontWeight: 700, fontSize: 15 }}>👎</span>
                        <span style={s.thumbNum}>{thumbsDown}</span>
                      </div>
                      {blockedCount > 0 && (
                        <div style={s.thumbChip}>
                          <span style={{ color: '#6B7280', fontSize: 13 }}>🚫 {blockedCount}</span>
                        </div>
                      )}
                    </div>

                    {/* Category boost bars */}
                    {boostEntries.length > 0 && (
                      <div style={{ marginTop: 16 }}>
                        <div style={s.sideSubLabel}>Category Adjustments</div>
                        {boostEntries.map(([cat, boost]) => {
                          const pct    = Math.round(Math.abs((boost - 1) / 1.5) * 100)
                          const isPos  = boost >= 1.0
                          const color  = CAT_COLORS[cat] || '#6B7280'
                          return (
                            <div key={cat} style={s.boostRow}>
                              <div style={s.boostLabelWrap}>
                                <div style={{ ...s.catDot, background: color }} />
                                <span style={s.boostCatName}>{cat}</span>
                              </div>
                              <div style={s.barTrack}>
                                <div style={{
                                  ...s.barFill,
                                  width: `${Math.min(100, pct)}%`,
                                  background: isPos ? '#059669' : '#DC2626',
                                }} />
                              </div>
                              <span style={{ ...s.boostPct, color: isPos ? '#059669' : '#DC2626' }}>
                                {boost > 1 ? '+' : ''}{Math.round((boost - 1) * 100)}%
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* Brand boosts (top 4 only) */}
                    {Object.keys(brandBoosts).length > 0 && (
                      <div style={{ marginTop: 14 }}>
                        <div style={s.sideSubLabel}>Brand Signals</div>
                        <div style={s.brandList}>
                          {Object.entries(brandBoosts)
                            .sort((a, b) => Math.abs(b[1] - 1) - Math.abs(a[1] - 1))
                            .slice(0, 4)
                            .map(([brand, boost]) => (
                              <span key={brand} style={{
                                ...s.brandChip,
                                background: boost >= 1 ? '#F0FDF4' : '#FEF2F2',
                                borderColor: boost >= 1 ? '#A7F3D0' : '#FECACA',
                                color: boost >= 1 ? '#065F46' : '#991B1B',
                              }}>
                                {boost >= 1 ? '↑' : '↓'} {brand}
                              </span>
                            ))}
                        </div>
                      </div>
                    )}

                    <button onClick={resetAdaptation} style={s.resetBtn}>
                      ↺ Reset taste profile
                    </button>
                  </>
                )}
              </div>

              {/* How it works */}
              <div style={{ ...s.sideCard, marginTop: 10 }}>
                <div style={s.sideLabel}>How It Works</div>
                <ol style={s.howList}>
                  <li>Browse recommendations on the right</li>
                  <li><strong>👍</strong> boosts that category + brand</li>
                  <li><strong>👎</strong> lowers similar items in your feed</li>
                  <li><strong>✕</strong> hides the product permanently</li>
                  <li>Hit <strong>Refresh</strong> to see your updated picks</li>
                </ol>
              </div>
            </aside>

            {/* ── Recommendation grid ── */}
            <main style={s.main}>

              {/* Filter chips */}
              <div style={s.filterRow}>
                {['all', 'personalized', 'trending', 'deals', 'new'].map(f => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    style={{ ...s.chip, ...(filter === f ? s.chipActive : {}) }}
                  >
                    {{ all: 'All', personalized: 'For You', trending: 'Trending',
                       deals: 'Deals', new: 'New Arrivals' }[f]}
                    {f === 'all' && !loading && (
                      <span style={s.chipCount}>{visibleRecs.length}</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Adaptation notice */}
              {hasAdaptation && (
                <div style={s.adaptedBanner}>
                  ✦ Results adapted to your feedback — {thumbsUp} positive,&nbsp;
                  {thumbsDown} negative signals applied.
                </div>
              )}

              {/* Error */}
              {error && <div style={s.errBanner}>⚠ {error}</div>}

              {/* Loading skeleton */}
              {loading ? (
                <div style={s.grid}>
                  {Array.from({ length: 12 }).map((_, i) => (
                    <div key={i} style={s.skelCard}>
                      <div style={s.skelImg} />
                      <div style={s.skelLine} />
                      <div style={{ ...s.skelLine, width: '60%' }} />
                      <div style={{ ...s.skelLine, width: '40%' }} />
                    </div>
                  ))}
                </div>
              ) : visibleRecs.length === 0 ? (
                <div style={s.empty}>
                  <div style={{ fontSize: 40 }}>📭</div>
                  <p>No recommendations for this filter. Try <strong>All</strong> or give more feedback.</p>
                </div>
              ) : (
                <div style={s.grid}>
                  {visibleRecs.map(rec => {
                    const fb         = feedbackMap[rec.product_id]
                    const catColor   = CAT_COLORS[rec.category] || '#6B7280'
                    const stratLabel = STRATEGY_LABELS[rec.strategy] || rec.strategy
                    const stratColor = STRATEGY_COLORS[rec.strategy] || '#6B7280'
                    const effPrice   = rec.discount_pct
                      ? rec.price * (1 - rec.discount_pct / 100)
                      : null
                    const ratingStars = rec.rating_avg
                      ? '★'.repeat(Math.round(rec.rating_avg)) + '☆'.repeat(5 - Math.round(rec.rating_avg))
                      : null

                    return (
                      <div
                        key={rec.product_id}
                        style={{
                          ...s.card,
                          opacity:     fb === 'thumbs_down' ? 0.45 : 1,
                          borderColor: fb === 'thumbs_up'   ? '#A7F3D0'
                                     : fb === 'thumbs_down' ? '#FECACA'
                                     : '#E5E7EB',
                          boxShadow:   fb === 'thumbs_up'
                            ? '0 0 0 2px #A7F3D0'
                            : '0 1px 3px rgba(0,0,0,.06)',
                        }}
                      >
                        {/* Category colour bar */}
                        <div style={{ ...s.catBar, background: catColor }} />

                        {/* Image area */}
                        <div style={{ ...s.imgArea, background: catColor + '14', overflow: 'hidden' }}>
                          <img
                            src={productImageUrl(rec)}
                            alt={rec.name}
                            style={{
                              width: '100%', height: '100%',
                              objectFit: 'cover',
                              display: 'block',
                            }}
                            loading="lazy"
                            onError={e => {
                              e.currentTarget.style.display = 'none'
                              e.currentTarget.nextSibling.style.display = 'flex'
                            }}
                          />
                          <span style={{
                            display: 'none', fontSize: 34, opacity: 0.65,
                            width: '100%', height: '100%',
                            alignItems: 'center', justifyContent: 'center',
                          }}>
                            {CAT_EMOJI[rec.category] || '📦'}
                          </span>
                          {rec.discount_pct > 0 && (
                            <span style={s.discountPill}>−{rec.discount_pct}%</span>
                          )}
                        </div>

                        {/* Strategy badge */}
                        <div style={s.metaRow}>
                          <span style={{
                            ...s.stratBadge,
                            background:  stratColor + '15',
                            color:       stratColor,
                            borderColor: stratColor + '40',
                          }}>
                            {stratLabel}
                          </span>
                          {rec.health === 'low' && (
                            <span style={s.lowStockBadge}>Low stock</span>
                          )}
                        </div>

                        {/* Product info */}
                        <div style={s.cardName} title={rec.name}>{rec.name}</div>
                        <div style={s.cardBrand}>{rec.brand} · {rec.category}</div>

                        {ratingStars && (
                          <div style={s.ratingRow}>
                            <span style={s.stars}>{ratingStars}</span>
                            <span style={s.ratingVal}>{rec.rating_avg?.toFixed(1)}</span>
                          </div>
                        )}

                        <div style={s.priceRow}>
                          {effPrice ? (
                            <>
                              <span style={s.salePrice}>${effPrice.toFixed(2)}</span>
                              <span style={s.origPrice}>${rec.price?.toFixed(2)}</span>
                            </>
                          ) : (
                            <span style={s.price}>${rec.price?.toFixed(2)}</span>
                          )}
                        </div>

                        {/* Feedback controls */}
                        <div style={s.fbRow}>
                          <button
                            onClick={() => giveFeedback(rec.product_id, 'thumbs_up', rec.strategy)}
                            disabled={!!fb}
                            style={{
                              ...s.fbBtn,
                              ...(fb === 'thumbs_up' ? s.fbBtnUp : {}),
                            }}
                            title="More like this"
                          >👍</button>
                          <button
                            onClick={() => giveFeedback(rec.product_id, 'thumbs_down', rec.strategy)}
                            disabled={!!fb}
                            style={{
                              ...s.fbBtn,
                              ...(fb === 'thumbs_down' ? s.fbBtnDown : {}),
                            }}
                            title="Fewer like this"
                          >👎</button>
                          <button
                            onClick={() => giveFeedback(rec.product_id, 'not_interested', rec.strategy)}
                            disabled={!!fb}
                            style={{ ...s.fbBtn, ...s.fbBtnX, marginLeft: 'auto' }}
                            title="Hide permanently"
                          >✕</button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </main>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = {
  page: {
    minHeight: '100vh',
    background: 'var(--bg, #F8F9FA)',
    paddingBottom: 64,
  },
  wrap: {
    paddingTop: 28,
  },

  // Header
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 20,
    marginBottom: 28,
    flexWrap: 'wrap',
  },
  title: {
    fontSize: '1.7rem',
    fontWeight: 800,
    color: '#0F172A',
    marginBottom: 4,
    letterSpacing: '-0.5px',
  },
  subtitle: {
    color: '#6B7280',
    fontSize: '0.88rem',
  },
  idForm: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  idInput: { width: 240, height: 40, fontSize: '0.85rem' },
  idBtn:   { height: 40, padding: '0 16px', whiteSpace: 'nowrap', flexShrink: 0 },

  // Splash
  splash: {
    textAlign: 'center',
    padding: '80px 24px',
    maxWidth: 540,
    margin: '0 auto',
  },
  splashIcon:  { fontSize: 52, marginBottom: 18 },
  splashTitle: { fontSize: '1.4rem', fontWeight: 800, color: '#0F172A', marginBottom: 12 },
  splashDesc:  { color: '#4B5563', fontSize: '0.9rem', lineHeight: 1.65, marginBottom: 12 },
  splashHint:  { color: '#9CA3AF', fontSize: '0.82rem' },
  code: {
    fontFamily: 'monospace',
    background: '#F3F4F6',
    border: '1px solid #E5E7EB',
    borderRadius: 4,
    padding: '1px 6px',
    fontSize: '0.82rem',
    color: '#374151',
  },

  // Layout
  layout: { display: 'flex', gap: 20, alignItems: 'flex-start' },

  // Sidebar
  sidebar: { width: 236, flexShrink: 0 },
  sideCard: {
    background: '#fff',
    border: '1.5px solid #E5E7EB',
    borderRadius: 12,
    padding: '16px',
  },
  sideLabel: {
    fontSize: '0.7rem',
    fontWeight: 800,
    letterSpacing: '.09em',
    textTransform: 'uppercase',
    color: '#6B7280',
    marginBottom: 10,
  },
  sideSubLabel: {
    fontSize: '0.67rem',
    fontWeight: 700,
    letterSpacing: '.07em',
    textTransform: 'uppercase',
    color: '#9CA3AF',
    marginBottom: 7,
  },
  custBadge: {
    display: 'inline-block',
    background: '#EFF6FF',
    color: '#2563EB',
    border: '1px solid #BFDBFE',
    borderRadius: 6,
    padding: '3px 10px',
    fontSize: '0.78rem',
    fontWeight: 700,
    marginBottom: 12,
    fontFamily: 'monospace',
    maxWidth: '100%',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  sideHint: {
    fontSize: '0.78rem',
    color: '#9CA3AF',
    lineHeight: 1.55,
  },
  thumbStats: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  thumbChip: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    background: '#F9FAFB',
    border: '1px solid #E5E7EB',
    borderRadius: 7,
    padding: '4px 9px',
  },
  thumbNum: { fontSize: '0.82rem', fontWeight: 700, color: '#374151' },

  // Boost bars
  boostRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    marginBottom: 5,
  },
  boostLabelWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    width: 90,
    flexShrink: 0,
    overflow: 'hidden',
  },
  catDot: {
    width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
  },
  boostCatName: {
    fontSize: '0.72rem',
    color: '#374151',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  barTrack: {
    flex: 1,
    height: 6,
    background: '#F3F4F6',
    borderRadius: 3,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 3,
    transition: 'width .35s ease',
    minWidth: 3,
  },
  boostPct: {
    fontSize: '0.68rem',
    fontWeight: 700,
    width: 34,
    textAlign: 'right',
    flexShrink: 0,
    fontVariantNumeric: 'tabular-nums',
  },

  // Brand chips
  brandList: { display: 'flex', flexWrap: 'wrap', gap: 4 },
  brandChip: {
    display: 'inline-block',
    fontSize: '0.7rem',
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: 20,
    border: '1px solid',
  },

  resetBtn: {
    marginTop: 14,
    width: '100%',
    background: 'none',
    border: '1px solid #E5E7EB',
    borderRadius: 7,
    padding: '7px 12px',
    fontSize: '0.78rem',
    color: '#6B7280',
    cursor: 'pointer',
    textAlign: 'center',
  },
  howList: {
    paddingLeft: 18,
    fontSize: '0.78rem',
    color: '#4B5563',
    lineHeight: 1.9,
    margin: 0,
  },

  // Main area
  main: { flex: 1, minWidth: 0 },
  filterRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    marginBottom: 14,
    alignItems: 'center',
  },
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    background: '#F9FAFB',
    border: '1.5px solid #E5E7EB',
    borderRadius: 20,
    padding: '5px 14px',
    fontSize: '0.82rem',
    fontWeight: 500,
    color: '#6B7280',
    cursor: 'pointer',
    transition: 'border-color .12s, color .12s',
  },
  chipActive: {
    background: '#EFF6FF',
    borderColor: '#2563EB',
    color: '#2563EB',
    fontWeight: 700,
  },
  chipCount: {
    background: '#DBEAFE',
    color: '#1D4ED8',
    fontSize: '0.7rem',
    fontWeight: 700,
    borderRadius: 10,
    padding: '1px 6px',
  },
  adaptedBanner: {
    background: '#EFF6FF',
    border: '1px solid #BFDBFE',
    borderRadius: 8,
    padding: '8px 14px',
    fontSize: '0.82rem',
    color: '#1D4ED8',
    marginBottom: 14,
    fontWeight: 500,
  },
  errBanner: {
    background: '#FEF2F2',
    border: '1px solid #FECACA',
    borderRadius: 8,
    padding: '10px 14px',
    fontSize: '0.85rem',
    color: '#B91C1C',
    marginBottom: 14,
  },

  // Grid
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
    gap: 12,
  },

  // Card
  card: {
    background: '#fff',
    border: '1.5px solid #E5E7EB',
    borderRadius: 12,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    transition: 'opacity .2s, border-color .15s, box-shadow .15s',
  },
  catBar:  { height: 3, flexShrink: 0 },
  imgArea: {
    height: 108,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
    flexShrink: 0,
  },
  discountPill: {
    position: 'absolute',
    top: 8, right: 8,
    background: '#DC2626',
    color: '#fff',
    fontSize: '0.65rem',
    fontWeight: 800,
    padding: '2px 6px',
    borderRadius: 4,
    letterSpacing: '.02em',
  },
  metaRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    padding: '7px 9px 3px',
    flexWrap: 'wrap',
  },
  stratBadge: {
    display: 'inline-block',
    fontSize: '0.62rem',
    fontWeight: 700,
    letterSpacing: '.04em',
    padding: '2px 7px',
    borderRadius: 20,
    border: '1px solid',
    whiteSpace: 'nowrap',
  },
  lowStockBadge: {
    display: 'inline-block',
    fontSize: '0.62rem',
    fontWeight: 700,
    padding: '2px 7px',
    borderRadius: 20,
    background: '#FEF3C7',
    color: '#92400E',
    border: '1px solid #FDE68A',
  },
  cardName: {
    padding: '0 9px',
    fontSize: '0.8rem',
    fontWeight: 600,
    color: '#0F172A',
    lineHeight: 1.4,
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    marginBottom: 2,
  },
  cardBrand: {
    padding: '0 9px',
    fontSize: '0.7rem',
    color: '#9CA3AF',
    marginBottom: 4,
  },
  ratingRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '0 9px',
    marginBottom: 3,
  },
  stars:     { fontSize: '0.68rem', color: '#F59E0B', letterSpacing: 0.5 },
  ratingVal: { fontSize: '0.7rem', color: '#6B7280' },
  priceRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
    padding: '0 9px 8px',
    marginTop: 'auto',
    flexWrap: 'wrap',
  },
  price: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#0F172A',
    fontVariantNumeric: 'tabular-nums',
  },
  salePrice: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#DC2626',
    fontVariantNumeric: 'tabular-nums',
  },
  origPrice: {
    fontSize: '0.78rem',
    color: '#9CA3AF',
    textDecoration: 'line-through',
    fontVariantNumeric: 'tabular-nums',
  },

  // Feedback row
  fbRow: {
    display: 'flex',
    gap: 4,
    padding: '6px 7px 8px',
    borderTop: '1px solid #F3F4F6',
  },
  fbBtn: {
    background: '#F9FAFB',
    border: '1px solid #E5E7EB',
    borderRadius: 6,
    width: 32,
    height: 29,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '0.9rem',
    cursor: 'pointer',
    flexShrink: 0,
  },
  fbBtnUp:   { background: '#F0FDF4', borderColor: '#A7F3D0' },
  fbBtnDown: { background: '#FEF2F2', borderColor: '#FECACA' },
  fbBtnX:    { background: '#F9FAFB', color: '#6B7280', fontSize: '0.78rem', fontWeight: 700 },

  // Skeleton
  skelCard: {
    background: '#fff',
    border: '1.5px solid #E5E7EB',
    borderRadius: 12,
    overflow: 'hidden',
    padding: 12,
  },
  skelImg: {
    height: 96,
    background: 'linear-gradient(90deg, #F3F4F6 25%, #E9EAEC 50%, #F3F4F6 75%)',
    backgroundSize: '200% 100%',
    animation: 'shimmer 1.4s infinite',
    borderRadius: 8,
    marginBottom: 10,
  },
  skelLine: {
    height: 11,
    background: '#F3F4F6',
    borderRadius: 4,
    marginBottom: 7,
    width: '80%',
  },

  // Empty
  empty: {
    textAlign: 'center',
    padding: '48px 20px',
    color: '#6B7280',
    fontSize: '0.88rem',
  },

  // Toast
  toastLayer: {
    position: 'fixed',
    bottom: 24, right: 24,
    zIndex: 9999,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    pointerEvents: 'none',
  },
  toast: {
    padding: '9px 16px',
    borderRadius: 8,
    border: '1.5px solid',
    fontSize: '0.83rem',
    fontWeight: 600,
    boxShadow: '0 4px 18px rgba(0,0,0,.1)',
    whiteSpace: 'nowrap',
  },
}
