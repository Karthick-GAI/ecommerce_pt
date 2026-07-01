import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ordersApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'

const EVENT_ICON = {
  order_placed:          '🛍',
  order_confirmed:       '✅',
  order_processing:      '⚙️',
  order_shipped:         '🚚',
  order_out_for_delivery:'📍',
  order_delivered:       '📦',
  order_cancelled:       '✕',
  refund_initiated:      '↩',
  refund_completed:      '💚',
  refund_rejected:       '❌',
}

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function NotificationBell() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const panelRef = useRef(null)

  const fetchNotifications = useCallback(async () => {
    if (!user?.id) return
    try {
      const r = await ordersApi.notifications(user.id)
      const all = r.data.notifications || []
      // Deduplicate: show only one push notification per order+event combo
      const seen = new Set()
      const deduped = all.filter(n => {
        if (n.channel !== 'push') return false
        const key = `${n.order_id}:${n.event}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      setNotifications(deduped.slice(0, 20))
      setUnreadCount(deduped.filter(n => !n.is_read).length)
    } catch { /* ignore auth errors */ }
  }, [user?.id])

  useEffect(() => {
    fetchNotifications()
    const interval = setInterval(fetchNotifications, 60000)
    return () => clearInterval(interval)
  }, [fetchNotifications])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handler(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  async function handleOpen() {
    setOpen(o => !o)
  }

  async function markAllRead() {
    if (!user?.id) return
    try {
      await ordersApi.markRead(user.id)
      setNotifications(n => n.map(x => ({ ...x, is_read: true })))
      setUnreadCount(0)
    } catch {}
  }

  async function handleNotificationClick(n) {
    if (!n.is_read) {
      try {
        await ordersApi.markNotificationRead(n.id)
        setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, is_read: true } : x))
        setUnreadCount(c => Math.max(0, c - 1))
      } catch {}
    }
    setOpen(false)
    navigate('/orders')
  }

  if (!user) return null

  return (
    <div style={{ position: 'relative' }} ref={panelRef}>
      <button
        onClick={handleOpen}
        style={s.bellBtn}
        aria-label="Notifications"
        title="Notifications"
      >
        🔔
        {unreadCount > 0 && (
          <span style={s.badge}>{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      {open && (
        <div style={s.panel}>
          <div style={s.panelHeader}>
            <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>Notifications</span>
            {unreadCount > 0 && (
              <button style={s.markAllBtn} onClick={markAllRead}>
                Mark all read
              </button>
            )}
          </div>

          <div style={s.list}>
            {notifications.length === 0 ? (
              <div style={s.empty}>
                <p style={{ fontSize: '2rem', margin: '0 0 8px' }}>🔕</p>
                <p style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>No notifications yet</p>
              </div>
            ) : (
              notifications.map(n => (
                <button key={n.id} style={{ ...s.item, background: n.is_read ? 'transparent' : 'rgba(80,70,229,.05)' }}
                  onClick={() => handleNotificationClick(n)}>
                  <span style={{ fontSize: '1.1rem', flexShrink: 0 }}>{EVENT_ICON[n.event] || '📋'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={s.itemTitle}>{n.title}</p>
                    <p style={s.itemMsg}>{n.message}</p>
                    <p style={s.itemTime}>{timeAgo(n.sent_at)}</p>
                  </div>
                  {!n.is_read && <span style={s.dot} />}
                </button>
              ))
            )}
          </div>

          {notifications.length > 0 && (
            <button style={s.viewAll} onClick={() => { setOpen(false); navigate('/orders') }}>
              View all orders →
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const s = {
  bellBtn: {
    position: 'relative', background: 'none', border: 'none',
    fontSize: '1.3rem', padding: '4px 8px', lineHeight: 1, cursor: 'pointer',
  },
  badge: {
    position: 'absolute', top: -2, right: -2,
    background: '#ef4444', color: '#fff',
    borderRadius: 999, fontSize: '0.6rem', fontWeight: 800,
    minWidth: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '0 3px',
  },
  panel: {
    position: 'absolute', right: 0, top: 'calc(100% + 8px)',
    width: 340, maxHeight: 460,
    background: 'var(--surface)', borderRadius: 12,
    boxShadow: '0 8px 32px rgba(0,0,0,.14)', border: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column', zIndex: 300,
    overflow: 'hidden',
  },
  panelHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 16px', borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  markAllBtn: {
    background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--primary)', fontSize: '0.78rem', fontWeight: 600,
  },
  list: { flex: 1, overflowY: 'auto' },
  empty: { padding: '32px 16px', textAlign: 'center' },
  item: {
    display: 'flex', alignItems: 'flex-start', gap: 10,
    padding: '10px 16px', width: '100%', textAlign: 'left',
    border: 'none', cursor: 'pointer', borderBottom: '1px solid var(--border)',
    transition: 'background .12s',
  },
  itemTitle: { fontWeight: 600, fontSize: '0.82rem', marginBottom: 2 },
  itemMsg: { color: 'var(--muted)', fontSize: '0.77rem', lineHeight: 1.4,
    overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' },
  itemTime: { color: 'var(--muted)', fontSize: '0.7rem', marginTop: 3 },
  dot: {
    width: 8, height: 8, borderRadius: '50%',
    background: 'var(--primary)', flexShrink: 0, marginTop: 6,
  },
  viewAll: {
    display: 'block', width: '100%', padding: '10px 16px',
    textAlign: 'center', background: 'var(--ground)', border: 'none',
    borderTop: '1px solid var(--border)', cursor: 'pointer',
    color: 'var(--primary)', fontSize: '0.82rem', fontWeight: 600,
    flexShrink: 0,
  },
}
