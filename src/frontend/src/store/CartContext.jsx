import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { sessionsApi } from '../api/index.js'
import { useAuth } from './AuthContext.jsx'

const CartCtx = createContext(null)

export function CartProvider({ children }) {
  const { user } = useAuth()
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('sessionId'))
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const initRef = useRef(false)

  // Load or create session on mount / user change
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    initSession()
  }, [user])

  async function initSession() {
    let sid = localStorage.getItem('sessionId')
    if (sid) {
      try {
        // Validate that the session is still active (not expired/completed)
        const sessionRes = await sessionsApi.get(sid)
        if (sessionRes.data.status === 'active') {
          const cartRes = await sessionsApi.getCart(sid)
          const active = (cartRes.data.items || []).filter(i => !i.saved_for_later)
          setItems(active)
          setSessionId(sid)
          return
        }
      } catch { /* session not found or network error — fall through to create */ }
      localStorage.removeItem('sessionId')
      sid = null
    }
    try {
      const res = await sessionsApi.create(user?.id)
      sid = res.data.session_id
      localStorage.setItem('sessionId', sid)
      setSessionId(sid)
      setItems([])
    } catch (e) {
      console.warn('Could not create session:', e.message)
    }
  }

  const refreshCart = useCallback(async () => {
    const sid = localStorage.getItem('sessionId')
    if (!sid) return
    try {
      const res = await sessionsApi.getCart(sid)
      setItems((res.data.items || []).filter(i => !i.saved_for_later))
    } catch {}
  }, [])

  const addItem = useCallback(async (product, qty = 1) => {
    const sid = localStorage.getItem('sessionId')
    if (!sid) return
    setLoading(true)
    try {
      await sessionsApi.addItem(sid, {
        product_id:   product.id,
        product_name: product.name,
        unit_price:   product.effective_price ?? product.price,
        quantity:     qty,
        image_url:    product.primary_image,
      })
      await refreshCart()
    } finally {
      setLoading(false)
    }
  }, [refreshCart])

  const updateQty = useCallback(async (productId, qty) => {
    const sid = localStorage.getItem('sessionId')
    if (!sid) return
    if (qty <= 0) return removeItem(productId)
    try {
      await sessionsApi.updateItem(sid, productId, qty)
      await refreshCart()
    } catch {}
  }, [refreshCart])

  const removeItem = useCallback(async (productId) => {
    const sid = localStorage.getItem('sessionId')
    if (!sid) return
    try {
      await sessionsApi.removeItem(sid, productId)
      await refreshCart()
    } catch {}
  }, [refreshCart])

  const clearCart = useCallback(async () => {
    const sid = localStorage.getItem('sessionId')
    if (!sid) return
    try {
      await sessionsApi.clearCart(sid)
      setItems([])
    } catch {}
  }, [])

  const count   = items.reduce((s, i) => s + (i.quantity || 1), 0)
  const subtotal = items.reduce((s, i) => s + (i.line_total ?? i.unit_price * i.quantity), 0)

  return (
    <CartCtx.Provider value={{
      items, count, subtotal, loading, sessionId,
      addItem, updateQty, removeItem, clearCart, refreshCart,
    }}>
      {children}
    </CartCtx.Provider>
  )
}

export const useCart = () => useContext(CartCtx)
