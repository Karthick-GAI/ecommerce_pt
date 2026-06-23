import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ordersApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'

const STATUS_COLORS = {
  pending:    { bg: 'rgba(245,158,11,.1)',  text: '#B45309' },
  confirmed:  { bg: 'rgba(80,70,229,.1)',   text: 'var(--primary)' },
  processing: { bg: 'rgba(80,70,229,.1)',   text: 'var(--primary)' },
  shipped:    { bg: 'rgba(0,179,126,.1)',   text: 'var(--success)' },
  delivered:  { bg: 'rgba(0,179,126,.15)',  text: 'var(--success)' },
  cancelled:  { bg: 'rgba(239,68,68,.1)',   text: 'var(--danger)' },
  refunded:   { bg: 'rgba(239,68,68,.1)',   text: 'var(--danger)' },
}

const STATUS_ICON = {
  pending: '⏳', confirmed: '✅', processing: '⚙️',
  shipped: '🚚', delivered: '📦', cancelled: '❌', refunded: '↩',
}

function StatusBadge({ status }) {
  const c = STATUS_COLORS[status] || { bg: 'var(--ground)', text: 'var(--muted)' }
  return (
    <span style={{
      background: c.bg, color: c.text,
      padding: '4px 12px', borderRadius: 999,
      fontSize: '0.8rem', fontWeight: 700,
      textTransform: 'capitalize',
    }}>
      {STATUS_ICON[status] || '•'} {status}
    </span>
  )
}

export default function Orders() {
  const { user, isLoggedIn } = useAuth()
  const navigate = useNavigate()
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [timeline, setTimeline] = useState([])
  const [tlLoading, setTlLoading] = useState(false)

  useEffect(() => {
    if (!isLoggedIn) { navigate('/auth', { state: { from: '/orders' } }); return }
    ordersApi.byCustomer(user.id, { limit: 20 })
      .then(r => setOrders(r.data.orders || r.data.results || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [isLoggedIn, user])

  async function openOrder(order) {
    setSelected(order)
    setTimeline([])
    setTlLoading(true)
    try {
      const r = await ordersApi.timeline(order.order_id || order.id)
      setTimeline(r.data.timeline || r.data || [])
    } catch {}
    finally { setTlLoading(false) }
  }

  if (!isLoggedIn) return null

  return (
    <div className="page">
      <div className="container">
        <h1 style={{ marginBottom: 24 }}>My Orders</h1>

        {loading ? (
          <div className="spinner-wrap"><div className="spinner" /></div>
        ) : orders.length === 0 ? (
          <div className="empty-state">
            <div style={{ fontSize: '3rem', marginBottom: 12 }}>📦</div>
            <h3>No orders yet</h3>
            <p>Your orders will appear here</p>
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/')}>
              Start Shopping
            </button>
          </div>
        ) : (
          <div style={styles.layout}>
            {/* Order list */}
            <div style={styles.list}>
              {orders.map(order => {
                const oid = order.order_id || order.id
                const isActive = selected?.order_id === oid || selected?.id === oid
                return (
                  <div
                    key={oid}
                    className="card"
                    style={{ ...styles.orderCard, ...(isActive ? styles.orderCardActive : {}) }}
                    onClick={() => openOrder(order)}
                  >
                    <div style={styles.orderHeader}>
                      <div>
                        <p style={styles.orderId}>Order #{oid?.slice(0, 8)?.toUpperCase()}</p>
                        <p style={styles.orderDate}>{new Date(order.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</p>
                      </div>
                      <StatusBadge status={order.status} />
                    </div>

                    {order.items?.slice(0, 2).map((item, i) => (
                      <div key={i} style={styles.orderItem}>
                        <img
                          src={item.image_url || `https://picsum.photos/seed/${item.product_id}/48/48`}
                          alt={item.product_name}
                          style={styles.orderItemImg}
                        />
                        <div>
                          <p style={{ fontSize: '0.875rem', fontWeight: 500 }}>{item.product_name}</p>
                          <p style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Qty: {item.quantity}</p>
                        </div>
                      </div>
                    ))}
                    {order.items?.length > 2 && (
                      <p style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 4 }}>
                        +{order.items.length - 2} more items
                      </p>
                    )}

                    <div style={styles.orderFooter}>
                      <span style={{ fontWeight: 700 }}>
                        ₹{Number(order.total || order.total_amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                      </span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--primary)', fontWeight: 600 }}>
                        View Details →
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Detail panel */}
            {selected && (
              <div style={styles.detail}>
                <div className="card" style={{ padding: '24px 28px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
                    <div>
                      <h3>Order #{(selected.order_id || selected.id)?.slice(0, 8)?.toUpperCase()}</h3>
                      <StatusBadge status={selected.status} />
                    </div>
                    <button style={styles.closeDetail} onClick={() => setSelected(null)}>✕</button>
                  </div>

                  {/* Timeline */}
                  {tlLoading ? (
                    <div className="spinner-wrap" style={{ minHeight: 80 }}><div className="spinner" /></div>
                  ) : timeline.length > 0 ? (
                    <div style={styles.timeline}>
                      <h4 style={{ marginBottom: 12, fontSize: '0.875rem', textTransform: 'uppercase', color: 'var(--muted)', letterSpacing: '.5px' }}>
                        Tracking
                      </h4>
                      {timeline.map((ev, i) => (
                        <div key={i} style={styles.tlEvent}>
                          <div style={{ ...styles.tlDot, background: i === 0 ? 'var(--success)' : 'var(--border)' }} />
                          <div>
                            <p style={{ fontWeight: 600, fontSize: '0.875rem' }}>{ev.status || ev.event}</p>
                            <p style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>{ev.description || ev.note}</p>
                            <p style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                              {ev.timestamp && new Date(ev.timestamp).toLocaleString('en-IN')}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <div className="divider" />

                  {/* Items */}
                  <h4 style={{ marginBottom: 12, fontSize: '0.875rem', textTransform: 'uppercase', color: 'var(--muted)', letterSpacing: '.5px' }}>
                    Items
                  </h4>
                  {selected.items?.map((item, i) => (
                    <div key={i} style={styles.detailItem}>
                      <img
                        src={item.image_url || `https://picsum.photos/seed/${item.product_id}/56/56`}
                        alt={item.product_name}
                        style={styles.detailImg}
                      />
                      <div style={{ flex: 1 }}>
                        <p style={{ fontWeight: 500, fontSize: '0.875rem' }}>{item.product_name}</p>
                        <p style={{ color: 'var(--muted)', fontSize: '0.8rem' }}>Qty: {item.quantity}</p>
                      </div>
                      <p style={{ fontWeight: 700, fontSize: '0.9rem' }}>
                        ₹{Number(item.unit_price * item.quantity).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                      </p>
                    </div>
                  ))}

                  <div className="divider" />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: '1rem' }}>
                    <span>Total</span>
                    <span>₹{Number(selected.total || selected.total_amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  layout: { display: 'grid', gridTemplateColumns: selected => selected ? '1fr 1fr' : '1fr', gap: 24 },
  list: { display: 'flex', flexDirection: 'column', gap: 16 },
  orderCard: { padding: '16px 20px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 10 },
  orderCardActive: { border: '2px solid var(--primary)', boxShadow: '0 0 0 4px rgba(80,70,229,.08)' },
  orderHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' },
  orderId: { fontWeight: 700, fontSize: '0.925rem' },
  orderDate: { fontSize: '0.8rem', color: 'var(--muted)', marginTop: 2 },
  orderItem: { display: 'flex', alignItems: 'center', gap: 10 },
  orderItemImg: { width: 44, height: 44, objectFit: 'cover', borderRadius: 6, flexShrink: 0 },
  orderFooter: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 8, borderTop: '1px solid var(--border)' },
  detail: {},
  closeDetail: {
    background: 'none', border: 'none', fontSize: '1rem',
    color: 'var(--muted)', cursor: 'pointer', padding: 4,
  },
  timeline: { marginBottom: 16 },
  tlEvent: {
    display: 'flex', gap: 12, paddingBottom: 14,
    borderLeft: '2px solid var(--border)', marginLeft: 8, paddingLeft: 14, position: 'relative',
  },
  tlDot: {
    width: 12, height: 12, borderRadius: '50%',
    position: 'absolute', left: -7, top: 4, flexShrink: 0,
    border: '2px solid var(--surface)',
  },
  detailItem: {
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '8px 0', borderBottom: '1px solid var(--border)',
  },
  detailImg: { width: 52, height: 52, objectFit: 'cover', borderRadius: 6, flexShrink: 0 },
}
