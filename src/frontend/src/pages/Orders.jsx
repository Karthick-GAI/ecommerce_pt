import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ordersApi, shippingApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'
import { useToast } from '../store/ToastContext.jsx'

const CANCELLABLE = ['pending', 'confirmed', 'processing']

const STATUS_COLORS = {
  pending:          { bg: 'rgba(245,158,11,.12)',  text: '#B45309' },
  confirmed:        { bg: 'rgba(80,70,229,.12)',   text: '#4338ca' },
  processing:       { bg: 'rgba(80,70,229,.12)',   text: '#4338ca' },
  shipped:          { bg: 'rgba(0,179,126,.12)',   text: '#059669' },
  out_for_delivery: { bg: 'rgba(0,179,126,.12)',   text: '#059669' },
  delivered:        { bg: 'rgba(0,179,126,.18)',   text: '#047857' },
  cancelled:        { bg: 'rgba(239,68,68,.12)',   text: '#dc2626' },
  refunded:         { bg: 'rgba(239,68,68,.12)',   text: '#dc2626' },
  payment_failed:   { bg: 'rgba(239,68,68,.12)',   text: '#dc2626' },
}

const STATUS_ICON = {
  pending: '⏳', confirmed: '✅', processing: '⚙️',
  shipped: '🚚', out_for_delivery: '📍', delivered: '📦',
  cancelled: '✕', refunded: '↩', payment_failed: '✕',
}

const REFUND_COLORS = {
  pending:   { bg: 'rgba(245,158,11,.12)', text: '#B45309' },
  approved:  { bg: 'rgba(80,70,229,.12)',  text: '#4338ca' },
  completed: { bg: 'rgba(0,179,126,.12)',  text: '#059669' },
  rejected:  { bg: 'rgba(239,68,68,.12)', text: '#dc2626' },
}

function Badge({ label, colorMap, value }) {
  const c = colorMap[value] || { bg: 'var(--ground)', text: 'var(--muted)' }
  return (
    <span style={{
      background: c.bg, color: c.text,
      padding: '3px 10px', borderRadius: 999,
      fontSize: '0.78rem', fontWeight: 700, textTransform: 'capitalize',
    }}>
      {label}
    </span>
  )
}

export default function Orders() {
  const { user, isLoggedIn } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()

  const [orders, setOrders]           = useState([])
  const [loading, setLoading]         = useState(true)
  const [selected, setSelected]       = useState(null)
  const [detail, setDetail]           = useState(null)   // full order detail
  const [refund, setRefund]           = useState(null)
  const [notifications, setNotifications] = useState([])
  const [tab, setTab]                 = useState('timeline') // timeline | notifications
  const [cancelling, setCancelling]   = useState(false)
  const [approving, setApproving]     = useState(false)
  const [shipment, setShipment]       = useState(null)
  const [tracking, setTracking]       = useState(null)
  const [shipLoading, setShipLoading] = useState(false)

  const loadOrders = useCallback(async () => {
    if (!user) return
    try {
      const r = await ordersApi.byCustomer(user.id)
      setOrders(r.data.orders || [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [user])

  useEffect(() => {
    if (!isLoggedIn) { navigate('/auth', { state: { from: '/orders' } }); return }
    loadOrders()
  }, [isLoggedIn, loadOrders])

  async function openOrder(order) {
    const oid = order.order_id || order.id
    setSelected(order)
    setDetail(null)
    setRefund(null)
    setNotifications([])
    setShipment(null)
    setTracking(null)
    setTab('timeline')

    try {
      const r = await ordersApi.get(oid)
      setDetail(r.data)
    } catch { setDetail(order) }

    // Load refund if exists
    try {
      const r = await ordersApi.getRefund(oid)
      setRefund(r.data)
    } catch { /* no refund yet */ }
  }

  async function loadNotifications() {
    if (!user) return
    try {
      const r = await ordersApi.notifications(user.id)
      const oid = selected?.order_id || selected?.id
      setNotifications((r.data.notifications || []).filter(n => n.order_id === oid))
    } catch { /* ignore */ }
  }

  async function loadShipping() {
    if (shipment) return  // already loaded
    const oid = selected?.order_id || selected?.id
    if (!oid) return
    setShipLoading(true)
    try {
      const r = await shippingApi.byCheckout(oid)
      setShipment(r.data)
      const tr = await shippingApi.track(r.data.id)
      setTracking(tr.data)
    } catch { /* no shipment for this order yet */ }
    finally { setShipLoading(false) }
  }

  async function handleCancel() {
    const oid = selected?.order_id || selected?.id
    if (!oid) return
    if (!window.confirm('Cancel this order? This cannot be undone.')) return
    setCancelling(true)
    try {
      const r = await ordersApi.cancel(oid, 'Customer requested cancellation')
      toast(r.data.refund_initiated
        ? `Order cancelled. Refund of ₹${r.data.refund_amount} initiated.`
        : 'Order cancelled successfully.', 'success')
      await loadOrders()
      // Refresh the selected order
      const updated = await ordersApi.get(oid)
      setDetail(updated.data)
      setSelected(prev => ({ ...prev, status: 'cancelled' }))
      // Load refund
      try { const rf = await ordersApi.getRefund(oid); setRefund(rf.data) } catch { /* none */ }
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not cancel order.', 'error')
    } finally {
      setCancelling(false)
    }
  }

  async function handleApproveRefund() {
    if (!refund?.refund_id) return
    setApproving(true)
    try {
      await ordersApi.approveRefund(refund.refund_id)
      toast('Refund approved and processed!', 'success')
      // Reload refund status
      const oid = selected?.order_id || selected?.id
      const rf = await ordersApi.getRefund(oid)
      setRefund(rf.data)
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not approve refund.', 'error')
    } finally {
      setApproving(false)
    }
  }

  const currentStatus = detail?.status || selected?.status
  const canCancel = CANCELLABLE.includes(currentStatus)

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
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/')}>
              Start Shopping
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: selected ? '360px 1fr' : '1fr', gap: 24, alignItems: 'flex-start' }}>

            {/* Order list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {orders.map(order => {
                const oid = order.order_id || order.id
                const isActive = (selected?.order_id || selected?.id) === oid
                return (
                  <div
                    key={oid}
                    className="card"
                    style={{ padding: '16px 20px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 8,
                      border: isActive ? '2px solid var(--primary)' : undefined,
                      boxShadow: isActive ? '0 0 0 4px rgba(80,70,229,.08)' : undefined }}
                    onClick={() => openOrder(order)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <p style={{ fontWeight: 700, fontSize: '0.9rem' }}>#{oid?.slice(0, 8)?.toUpperCase()}</p>
                        <p style={{ fontSize: '0.78rem', color: 'var(--muted)', marginTop: 2 }}>
                          {new Date(order.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </p>
                      </div>
                      <Badge label={`${STATUS_ICON[order.status] || '•'} ${order.status}`} colorMap={STATUS_COLORS} value={order.status} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 8, borderTop: '1px solid var(--border)' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>{order.item_count} item{order.item_count !== 1 ? 's' : ''}</span>
                      <span style={{ fontWeight: 700 }}>₹{Number(order.total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Detail panel */}
            {selected && (
              <div className="card" style={{ padding: '24px 28px' }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                  <div>
                    <h3 style={{ marginBottom: 6 }}>#{(selected.order_id || selected.id)?.slice(0, 8)?.toUpperCase()}</h3>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <Badge label={`${STATUS_ICON[currentStatus] || '•'} ${currentStatus}`} colorMap={STATUS_COLORS} value={currentStatus} />
                      {detail?.payment_status && (
                        <Badge label={`💳 ${detail.payment_status}`} colorMap={{ success: { bg: 'rgba(0,179,126,.12)', text: '#059669' }, failed: { bg: 'rgba(239,68,68,.12)', text: '#dc2626' } }} value={detail.payment_status} />
                      )}
                    </div>
                  </div>
                  <button style={{ background: 'none', border: 'none', fontSize: '1rem', color: 'var(--muted)', cursor: 'pointer', padding: 4 }}
                    onClick={() => { setSelected(null); setDetail(null); setRefund(null) }}>✕</button>
                </div>

                {/* Cancel button */}
                {canCancel && (
                  <button
                    className="btn btn-lg"
                    style={{ width: '100%', marginBottom: 16, background: 'rgba(239,68,68,.08)', color: '#dc2626', border: '1.5px solid rgba(239,68,68,.3)', fontWeight: 700 }}
                    onClick={handleCancel}
                    disabled={cancelling}
                  >
                    {cancelling ? 'Cancelling…' : '✕ Cancel Order'}
                  </button>
                )}

                {/* Refund panel */}
                {refund && (
                  <div style={{ marginBottom: 16, padding: '14px 16px', borderRadius: 10, border: '1.5px solid var(--border)', background: 'var(--ground)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>↩ Refund</span>
                      <Badge label={refund.status} colorMap={REFUND_COLORS} value={refund.status} />
                    </div>
                    <p style={{ fontSize: '0.85rem', color: 'var(--muted)', marginBottom: 4 }}>
                      Amount: <strong>₹{Number(refund.amount).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</strong>
                    </p>
                    {refund.refund_txn_id && (
                      <p style={{ fontSize: '0.8rem', color: 'var(--muted)', fontFamily: 'monospace' }}>
                        TXN: {refund.refund_txn_id}
                      </p>
                    )}
                    {refund.rejection_reason && (
                      <p style={{ fontSize: '0.8rem', color: '#dc2626', marginTop: 4 }}>
                        Rejected: {refund.rejection_reason}
                      </p>
                    )}
                    {refund.status === 'pending' && (
                      <button
                        className="btn btn-sm"
                        style={{ marginTop: 10, background: 'rgba(0,179,126,.1)', color: '#059669', border: '1.5px solid rgba(0,179,126,.3)', fontWeight: 700, width: '100%' }}
                        onClick={handleApproveRefund}
                        disabled={approving}
                      >
                        {approving ? 'Processing…' : '✓ Approve Refund (Admin)'}
                      </button>
                    )}
                  </div>
                )}

                {/* Tabs */}
                <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)', paddingBottom: 0, flexWrap: 'wrap' }}>
                  {['timeline', 'items', 'shipping', 'notifications'].map(t => (
                    <button key={t} style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      padding: '6px 12px', fontSize: '0.8rem', fontWeight: tab === t ? 700 : 500,
                      color: tab === t ? 'var(--primary)' : 'var(--muted)',
                      borderBottom: tab === t ? '2px solid var(--primary)' : '2px solid transparent',
                      marginBottom: -1, textTransform: 'capitalize',
                    }}
                      onClick={() => {
                        setTab(t)
                        if (t === 'notifications') loadNotifications()
                        if (t === 'shipping') loadShipping()
                      }}
                    >
                      {t === 'timeline' ? '📍 Timeline' : t === 'items' ? '📦 Items' : t === 'shipping' ? '🚚 Shipping' : '🔔 Notifications'}
                    </button>
                  ))}
                </div>

                {/* Timeline tab */}
                {tab === 'timeline' && (
                  <div>
                    {(detail?.timeline || []).length === 0 ? (
                      <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>No status changes yet.</p>
                    ) : (
                      [...(detail?.timeline || [])].reverse().map((ev, i) => (
                        <div key={i} style={{ display: 'flex', gap: 12, paddingBottom: 14, borderLeft: '2px solid var(--border)', marginLeft: 8, paddingLeft: 14, position: 'relative' }}>
                          <div style={{ width: 10, height: 10, borderRadius: '50%', background: i === 0 ? 'var(--success)' : 'var(--border)', position: 'absolute', left: -6, top: 4, border: '2px solid var(--surface)' }} />
                          <div>
                            <p style={{ fontWeight: 700, fontSize: '0.85rem' }}>
                              {STATUS_ICON[ev.to_status]} {ev.to_status?.replace(/_/g, ' ')}
                            </p>
                            {ev.reason && <p style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>{ev.reason}</p>}
                            {ev.tracking_number && <p style={{ fontSize: '0.78rem', color: 'var(--primary)', fontFamily: 'monospace' }}>📦 {ev.tracking_number}</p>}
                            {ev.estimated_delivery && <p style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>ETA: {ev.estimated_delivery}</p>}
                            <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 2 }}>
                              {new Date(ev.created_at || ev.timestamp).toLocaleString('en-IN')}
                            </p>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* Items tab */}
                {tab === 'items' && (
                  <div>
                    {(detail?.items || selected?.items || []).map((item, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                        <img src={`https://picsum.photos/seed/${item.product_id}/56/56`} alt={item.product_name}
                          style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: 8, flexShrink: 0 }} />
                        <div style={{ flex: 1 }}>
                          <p style={{ fontWeight: 600, fontSize: '0.875rem' }}>{item.product_name}</p>
                          <p style={{ color: 'var(--muted)', fontSize: '0.8rem' }}>Qty: {item.quantity} × ₹{Number(item.unit_price).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
                        </div>
                        <p style={{ fontWeight: 700, fontSize: '0.9rem' }}>₹{Number(item.total_price ?? item.unit_price * item.quantity).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
                      </div>
                    ))}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: '1rem', paddingTop: 12 }}>
                      <span>Total</span>
                      <span>₹{Number(detail?.total || selected?.total || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                    </div>
                  </div>
                )}

                {/* Shipping tab */}
                {tab === 'shipping' && (
                  <div>
                    {shipLoading && <div className="spinner-wrap" style={{ minHeight: 80 }}><div className="spinner" /></div>}
                    {!shipLoading && !shipment && (
                      <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>
                        No shipment record linked to this order yet.
                      </p>
                    )}
                    {!shipLoading && shipment && (
                      <div>
                        {/* Shipment header */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
                          <div>
                            <p style={{ fontWeight: 700, fontSize: '0.9rem' }}>{shipment.courier_name}</p>
                            <p style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--primary)', marginTop: 2 }}>
                              AWB: {shipment.awb_number}
                            </p>
                          </div>
                          <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '3px 9px', borderRadius: 99,
                            background: shipment.status === 'delivered' ? 'rgba(5,150,105,.12)' : 'rgba(80,70,229,.1)',
                            color: shipment.status === 'delivered' ? '#059669' : 'var(--primary)',
                            textTransform: 'capitalize' }}>
                            {shipment.status?.replace(/_/g, ' ')}
                          </span>
                        </div>
                        {shipment.estimated_delivery && (
                          <p style={{ fontSize: '0.78rem', color: 'var(--muted)', marginBottom: 14 }}>
                            Estimated delivery: <strong>{new Date(shipment.estimated_delivery).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</strong>
                          </p>
                        )}
                        {/* Tracking timeline */}
                        {(tracking?.events || []).map((ev, i) => (
                          <div key={i} style={{ display: 'flex', gap: 10, paddingBottom: 12,
                            borderLeft: i < tracking.events.length - 1 ? '2px solid var(--border)' : 'none',
                            marginLeft: 6, paddingLeft: 12, position: 'relative' }}>
                            <div style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                              background: i === 0 ? 'var(--success)' : 'var(--border)',
                              border: '2px solid var(--surface)',
                              position: 'absolute', left: -6, top: 4 }} />
                            <div>
                              <p style={{ fontWeight: 700, fontSize: '0.82rem' }}>{ev.status}</p>
                              {ev.description && ev.description !== ev.status && (
                                <p style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>{ev.description}</p>
                              )}
                              <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 1 }}>
                                {ev.location && `${ev.location} · `}
                                {ev.timestamp ? new Date(ev.timestamp).toLocaleString('en-IN') : ''}
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Notifications tab */}
                {tab === 'notifications' && (
                  <div>
                    {notifications.length === 0 ? (
                      <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>No notifications for this order.</p>
                    ) : (
                      notifications.map((n, i) => (
                        <div key={i} style={{ padding: '10px 12px', marginBottom: 8, borderRadius: 8, background: n.is_read ? 'var(--ground)' : 'rgba(80,70,229,.06)', border: '1px solid var(--border)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                            <p style={{ fontWeight: 700, fontSize: '0.85rem' }}>{n.title}</p>
                            <span style={{ fontSize: '0.7rem', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{n.channel}</span>
                          </div>
                          <p style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 3 }}>{n.message}</p>
                          <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 4 }}>{new Date(n.sent_at).toLocaleString('en-IN')}</p>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
