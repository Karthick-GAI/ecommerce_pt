import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCart } from '../store/CartContext.jsx'
import { useAuth } from '../store/AuthContext.jsx'
import { useToast } from '../store/ToastContext.jsx'
import { checkoutsApi } from '../api/index.js'

const STEPS = ['Delivery', 'Review', 'Payment']

export default function Checkout() {
  const { items, subtotal, count, clearCart, sessionId } = useCart()
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [orderId, setOrderId] = useState(null)

  const [address, setAddress] = useState({
    name: user ? `${user.first_name || ''} ${user.last_name || ''}`.trim() : '',
    phone: user?.phone || '',
    email: user?.email || '',
    line1: '', city: '', state: '', pincode: '',
  })

  const shipping = subtotal > 500 ? 0 : 50
  const gst = Math.round(subtotal * 0.18)
  const total = subtotal + shipping + gst

  function setField(k, v) { setAddress(a => ({ ...a, [k]: v })) }

  async function placeOrder() {
    setLoading(true)
    try {
      // Build checkout payload
      const cartItems = items.map(i => ({
        product_id: i.product_id,
        product_name: i.product_name,
        quantity: i.quantity,
        unit_price: i.unit_price,
      }))

      const res = await checkoutsApi.place({
        customer_id: user?.id || 'guest',
        session_id: sessionId,
        items: cartItems,
        shipping_name: address.name,
        shipping_phone: address.phone,
        shipping_email: address.email,
        shipping_address: address.line1,
        shipping_city: address.city,
        shipping_state: address.state,
        shipping_pincode: address.pincode,
        payment_method: 'razorpay',
        subtotal,
        shipping_charge: shipping,
        tax: gst,
        total,
      })

      setOrderId(res.data.order_id || res.data.id)
      await clearCart()
      setStep(3)
      toast('Order placed successfully!', 'success')
    } catch (err) {
      const detail = err.response?.data?.detail
      toast(typeof detail === 'string' ? detail : 'Could not place order. Please retry.', 'error')
    } finally {
      setLoading(false)
    }
  }

  // Order success screen
  if (step === 3) {
    return (
      <div style={styles.successPage}>
        <div style={styles.successCard} className="card">
          <div style={{ fontSize: '4rem' }}>🎉</div>
          <h1 style={{ marginTop: 16 }}>Order Placed!</h1>
          <p style={{ color: 'var(--muted)', marginTop: 8 }}>
            Your order {orderId && <strong>#{orderId.slice(0, 8)}</strong>} has been confirmed.
          </p>
          <p style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
            You'll receive a confirmation soon.
          </p>
          <div style={{ display: 'flex', gap: 12, marginTop: 28 }}>
            <button className="btn btn-primary btn-lg" onClick={() => navigate('/orders')}>
              Track Order
            </button>
            <button className="btn btn-outline btn-lg" onClick={() => navigate('/')}>
              Continue Shopping
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div style={styles.successPage}>
        <div className="empty-state">
          <div style={{ fontSize: '3rem', marginBottom: 12 }}>🛒</div>
          <h3>Your cart is empty</h3>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/products')}>
            Browse Products
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="container">
        <h1 style={{ marginBottom: 24 }}>Checkout</h1>

        {/* Step indicator */}
        <div style={styles.stepRow}>
          {STEPS.map((s, i) => (
            <div key={s} style={styles.stepItem}>
              <div style={{
                ...styles.stepDot,
                background: i <= step ? 'var(--primary)' : 'var(--border)',
                color: i <= step ? '#fff' : 'var(--muted)',
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ ...styles.stepLabel, color: i === step ? 'var(--primary)' : 'var(--muted)' }}>
                {s}
              </span>
              {i < STEPS.length - 1 && <div style={styles.stepLine} />}
            </div>
          ))}
        </div>

        <div style={styles.layout}>
          {/* Left: steps */}
          <div style={styles.main}>
            {/* Step 0: Delivery */}
            {step === 0 && (
              <div className="card" style={styles.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Delivery Details</h2>
                <div style={styles.formGrid}>
                  <div className="form-group" style={{ gridColumn: '1/-1' }}>
                    <label>Full Name</label>
                    <input className="input" value={address.name} onChange={e => setField('name', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label>Phone</label>
                    <input className="input" type="tel" value={address.phone} onChange={e => setField('phone', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label>Email</label>
                    <input className="input" type="email" value={address.email} onChange={e => setField('email', e.target.value)} required />
                  </div>
                  <div className="form-group" style={{ gridColumn: '1/-1' }}>
                    <label>Address</label>
                    <input className="input" value={address.line1} onChange={e => setField('line1', e.target.value)} placeholder="House no, street, area" required />
                  </div>
                  <div className="form-group">
                    <label>City</label>
                    <input className="input" value={address.city} onChange={e => setField('city', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label>State</label>
                    <input className="input" value={address.state} onChange={e => setField('state', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label>Pincode</label>
                    <input className="input" value={address.pincode} onChange={e => setField('pincode', e.target.value)}
                      pattern="[0-9]{6}" maxLength={6} required />
                  </div>
                </div>
                <button
                  className="btn btn-primary btn-lg"
                  style={{ marginTop: 20 }}
                  onClick={() => setStep(1)}
                  disabled={!address.name || !address.phone || !address.line1 || !address.pincode}
                >
                  Continue to Review →
                </button>
              </div>
            )}

            {/* Step 1: Review */}
            {step === 1 && (
              <div className="card" style={styles.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Review Order</h2>
                {items.map(item => (
                  <div key={item.product_id} style={styles.reviewItem}>
                    <img
                      src={item.image_url || `https://picsum.photos/seed/${item.product_id}/72/72`}
                      alt={item.product_name}
                      style={styles.reviewImg}
                    />
                    <div style={{ flex: 1 }}>
                      <p style={{ fontWeight: 600 }}>{item.product_name}</p>
                      <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>Qty: {item.quantity}</p>
                    </div>
                    <p style={{ fontWeight: 700 }}>₹{Number(item.line_total ?? item.unit_price * item.quantity).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
                  </div>
                ))}
                <div style={styles.addressBox}>
                  <strong>Delivering to:</strong>
                  <p style={{ color: 'var(--muted)', fontSize: '0.875rem', marginTop: 4 }}>
                    {address.name}, {address.phone}<br />
                    {address.line1}, {address.city}, {address.state} — {address.pincode}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                  <button className="btn btn-ghost" onClick={() => setStep(0)}>← Back</button>
                  <button className="btn btn-primary btn-lg" style={{ flex: 1 }} onClick={() => setStep(2)}>
                    Continue to Payment →
                  </button>
                </div>
              </div>
            )}

            {/* Step 2: Payment */}
            {step === 2 && (
              <div className="card" style={styles.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Payment</h2>
                <div style={styles.payOption}>
                  <div style={styles.payOptionInner}>
                    <input type="radio" id="razorpay" defaultChecked />
                    <label htmlFor="razorpay" style={{ cursor: 'pointer' }}>
                      <strong>Razorpay</strong>
                      <span style={{ color: 'var(--muted)', fontSize: '0.85rem', marginLeft: 8 }}>
                        Cards, UPI, Net Banking, Wallets
                      </span>
                    </label>
                  </div>
                  <div style={styles.payIcons}>💳 UPI 🏦</div>
                </div>
                <div style={styles.safeNotice}>
                  🔒 Your payment is secured with 256-bit SSL encryption
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                  <button className="btn btn-ghost" onClick={() => setStep(1)}>← Back</button>
                  <button
                    className="btn btn-accent btn-lg"
                    style={{ flex: 1 }}
                    onClick={placeOrder}
                    disabled={loading}
                  >
                    {loading ? 'Processing…' : `Pay ₹${Number(total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Right: order summary */}
          <div style={styles.summary}>
            <div className="card" style={{ padding: '20px 24px' }}>
              <h3 style={{ marginBottom: 16 }}>Order Summary</h3>
              <div style={styles.summaryRow}>
                <span>Items ({count})</span>
                <span>₹{Number(subtotal).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              </div>
              <div style={styles.summaryRow}>
                <span>Delivery</span>
                <span style={{ color: shipping === 0 ? 'var(--success)' : undefined }}>
                  {shipping === 0 ? 'FREE' : `₹${shipping}`}
                </span>
              </div>
              <div style={styles.summaryRow}>
                <span>GST (18%)</span>
                <span>₹{Number(gst).toLocaleString('en-IN')}</span>
              </div>
              <div className="divider" />
              <div style={{ ...styles.summaryRow, fontWeight: 700, fontSize: '1.05rem' }}>
                <span>Total</span>
                <span>₹{Number(total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              </div>
              {subtotal < 500 && (
                <p style={{ color: 'var(--success)', fontSize: '0.8rem', marginTop: 8 }}>
                  Add ₹{(500 - subtotal).toFixed(0)} more for free delivery!
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  successPage: {
    minHeight: '70vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40,
  },
  successCard: { padding: '48px 56px', textAlign: 'center', maxWidth: 480 },
  stepRow: {
    display: 'flex', alignItems: 'center', marginBottom: 32, gap: 0,
  },
  stepItem: { display: 'flex', alignItems: 'center', gap: 8, flex: 1 },
  stepDot: {
    width: 32, height: 32, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: 700, fontSize: '0.875rem', flexShrink: 0,
    transition: 'background .3s',
  },
  stepLabel: { fontSize: '0.875rem', fontWeight: 600, whiteSpace: 'nowrap' },
  stepLine: { flex: 1, height: 2, background: 'var(--border)', marginLeft: 8 },
  layout: { display: 'grid', gridTemplateColumns: '1fr 340px', gap: 24, alignItems: 'flex-start' },
  main: {},
  stepCard: { padding: '28px 32px' },
  formGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
  reviewItem: {
    display: 'flex', alignItems: 'center', gap: 14,
    padding: '12px 0', borderBottom: '1px solid var(--border)',
  },
  reviewImg: { width: 64, height: 64, objectFit: 'cover', borderRadius: 8, flexShrink: 0 },
  addressBox: {
    background: 'var(--ground)', borderRadius: 10, padding: '14px 16px', marginTop: 16,
  },
  payOption: {
    border: '2px solid var(--primary)', borderRadius: 10, padding: '14px 16px',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    background: 'rgba(80,70,229,.04)',
  },
  payOptionInner: { display: 'flex', alignItems: 'center', gap: 10 },
  payIcons: { fontSize: '1.2rem' },
  safeNotice: {
    color: 'var(--muted)', fontSize: '0.825rem', marginTop: 12,
    display: 'flex', alignItems: 'center', gap: 6,
  },
  summary: { position: 'sticky', top: 80 },
  summaryRow: {
    display: 'flex', justifyContent: 'space-between',
    fontSize: '0.9rem', marginBottom: 10,
  },
}
