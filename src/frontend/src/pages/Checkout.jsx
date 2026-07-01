import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCart } from '../store/CartContext.jsx'
import { useAuth } from '../store/AuthContext.jsx'
import { useToast } from '../store/ToastContext.jsx'
import { checkoutsApi, shippingApi, addressApi, paymentMethodApi, interactionsApi } from '../api/index.js'

const STEPS = ['Delivery', 'Review', 'Payment']

const WALLETS = [
  { value: 'paytm',     label: 'Paytm' },
  { value: 'phonepe',   label: 'PhonePe' },
  { value: 'googlepay', label: 'Google Pay' },
  { value: 'amazonpay', label: 'Amazon Pay' },
  { value: 'mobikwik',  label: 'MobiKwik' },
]

const INDIAN_STATES = [
  'Andhra Pradesh','Arunachal Pradesh','Assam','Bihar','Chhattisgarh','Goa','Gujarat',
  'Haryana','Himachal Pradesh','Jharkhand','Karnataka','Kerala','Madhya Pradesh',
  'Maharashtra','Manipur','Meghalaya','Mizoram','Nagaland','Odisha','Punjab',
  'Rajasthan','Sikkim','Tamil Nadu','Telangana','Tripura','Uttar Pradesh',
  'Uttarakhand','West Bengal','Delhi','Jammu & Kashmir','Ladakh','Puducherry',
]

// ── card number formatter ─────────────────────────────────────────────────────
function fmtCard(v) {
  return v.replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim()
}

export default function Checkout() {
  const { items, subtotal, count, clearCart } = useCart()
  const { user } = useAuth()
  const toast    = useToast()
  const navigate = useNavigate()

  const [step, setStep]     = useState(0)
  const [loading, setLoading] = useState(false)
  const [orderId, setOrderId] = useState(null)
  const [paymentResult, setPaymentResult] = useState(null)

  // ── Delivery ────────────────────────────────────────────────────────────────
  const [address, setAddress] = useState({
    name:    user ? `${user.first_name || ''} ${user.last_name || ''}`.trim() : '',
    phone:   user?.phone || '',
    line1:   '', city: '', state: '', pincode: '',
  })
  const [savedAddresses, setSavedAddresses] = useState([])
  const [selectedAddrId, setSelectedAddrId] = useState(null)

  // ── Shipping rates ───────────────────────────────────────────────────────────
  const [rates, setRates]                   = useState([])
  const [ratesLoading, setRatesLoading]     = useState(false)
  const [selectedCourier, setSelectedCourier] = useState(null)

  // ── Coupon ──────────────────────────────────────────────────────────────────
  const [coupon, setCoupon]       = useState('')
  const [couponApplied, setCouponApplied] = useState('')

  // ── Payment ─────────────────────────────────────────────────────────────────
  const [payMethod, setPayMethod] = useState('card')
  const [savedMethods, setSavedMethods] = useState([])
  const [selectedSavedMethod, setSelectedSavedMethod] = useState(null)

  const [cardForm, setCardForm] = useState({
    number: '', holder: '', expiry: '', cvv: '',
  })
  const [upiId, setUpiId]       = useState('')
  const [walletType, setWalletType]   = useState('paytm')
  const [walletMobile, setWalletMobile] = useState('')

  // ── Load saved addresses + payment methods if logged in ─────────────────────
  useEffect(() => {
    if (!user) return
    addressApi.list().then(r => setSavedAddresses(r.data || [])).catch(() => {})
    paymentMethodApi.list().then(r => setSavedMethods(r.data || [])).catch(() => {})
  }, [user])

  // ── Shipping rate fetch on pincode change ────────────────────────────────────
  useEffect(() => {
    if (address.pincode.length !== 6) { setRates([]); setSelectedCourier(null); return }
    setRatesLoading(true)
    shippingApi.rates({ origin_pincode: '400069', destination_pincode: address.pincode, weight_kg: 1.0, cod: false })
      .then(r => setRates(r.data.rates || []))
      .catch(() => setRates([]))
      .finally(() => setRatesLoading(false))
  }, [address.pincode])

  // ── Price calculations ───────────────────────────────────────────────────────
  const shippingCharge = selectedCourier
    ? Math.round(selectedCourier.rate_amount)
    : subtotal > 500 ? 0 : 50
  const gst   = Math.round(subtotal * 0.18)
  const total = subtotal + shippingCharge + gst

  function setField(k, v) { setAddress(a => ({ ...a, [k]: v })) }

  function useSavedAddress(addr) {
    setSelectedAddrId(addr.id)
    setAddress({
      name:   addr.full_name,
      phone:  addr.phone,
      line1:  addr.line2 ? `${addr.line1}, ${addr.line2}` : addr.line1,
      city:   addr.city,
      state:  addr.state,
      pincode: addr.pincode,
    })
  }

  function selectSavedPayment(m) {
    setSelectedSavedMethod(m)
    if (m.type === 'card') {
      setPayMethod('card')
      setCardForm({ number: `**** **** **** ${m.card_last4}`, holder: m.card_holder, expiry: m.card_expiry?.replace('/', '/'), cvv: '' })
    } else if (m.type === 'upi') {
      setPayMethod('upi')
      setUpiId(m.upi_id)
    } else if (m.type === 'wallet') {
      setPayMethod('wallet')
      setWalletType(m.wallet_provider?.toLowerCase().replace(/\s/g, '') || 'paytm')
      setWalletMobile(m.wallet_phone || '')
    }
  }

  // ── Place order ──────────────────────────────────────────────────────────────
  async function placeOrder() {
    // Basic payment field validation before API call
    if (payMethod === 'card') {
      const raw = cardForm.number.replace(/\s/g, '')
      if (!selectedSavedMethod && raw.length < 16) { toast('Enter a valid 16-digit card number', 'error'); return }
      if (!cardForm.holder.trim()) { toast('Enter cardholder name', 'error'); return }
      if (!cardForm.expiry.trim()) { toast('Enter card expiry', 'error'); return }
      if (!/^\d{3,4}$/.test(cardForm.cvv)) { toast('Enter a valid CVV (3-4 digits)', 'error'); return }
    } else if (payMethod === 'upi') {
      if (!/^[a-zA-Z0-9._-]+@[a-zA-Z]{3,}$/.test(upiId)) { toast('Enter a valid UPI ID (e.g. name@paytm)', 'error'); return }
    } else if (payMethod === 'wallet') {
      if (!/^[6-9]\d{9}$/.test(walletMobile)) { toast('Enter a valid 10-digit mobile number', 'error'); return }
    }

    setLoading(true)
    try {
      // 1. Create checkout cart
      const cartRes = await checkoutsApi.createCart()
      const cartId  = cartRes.data.cart_id

      // 2. Transfer session items → checkout cart
      for (const item of items) {
        await checkoutsApi.addItem(cartId, { product_id: item.product_id, quantity: item.quantity })
      }

      // 3. Initiate checkout → pending order
      const orderRes = await checkoutsApi.place({
        cart_id:     cartId,
        customer_id: user?.id || null,
        coupon_code: couponApplied || undefined,
        shipping: {
          name:         address.name,
          phone:        address.phone,
          address_line: address.line1,
          city:         address.city,
          state:        address.state,
          pincode:      address.pincode,
        },
      })
      const oid = orderRes.data.order_id

      // 4. Build payment payload from selected method
      let payPayload = { method: payMethod }
      if (payMethod === 'card') {
        // If using a saved card (masked), send test-valid card; in real app this would use tokenisation
        const rawNumber = cardForm.number.replace(/\s/g, '').replace(/\*/g, '')
        payPayload = {
          ...payPayload,
          card_number:  rawNumber.length === 16 ? rawNumber : '4242424242424242',
          card_holder:  cardForm.holder,
          expiry_month: cardForm.expiry.split('/')[0]?.trim(),
          expiry_year:  cardForm.expiry.split('/')[1]?.trim(),
          cvv:          cardForm.cvv,
        }
      } else if (payMethod === 'upi') {
        payPayload = { ...payPayload, upi_id: upiId }
      } else if (payMethod === 'wallet') {
        payPayload = { ...payPayload, wallet_type: walletType, wallet_mobile: walletMobile }
      }

      // 5. Process payment
      const payRes = await checkoutsApi.pay(oid, payPayload)

      if (payRes.data.payment_status !== 'success') {
        throw new Error(payRes.data.message || 'Payment failed')
      }

      setOrderId(oid)
      setPaymentResult(payRes.data)

      // Log purchase interactions for each cart item (feeds recommendation engine)
      if (user?.id) {
        items.forEach(item => {
          interactionsApi.log({
            customer_id: user.id,
            product_id: item.product_id || item.id,
            interaction_type: 'purchase',
            source: 'direct',
          }).catch(() => {})
        })
      }

      await clearCart()
      setStep(3)
      toast('Order placed successfully!', 'success')
    } catch (err) {
      const detail = err.response?.data?.detail
      toast(typeof detail === 'string' ? detail : (err.message || 'Could not place order. Please retry.'), 'error')
    } finally {
      setLoading(false)
    }
  }

  // ── Success screen ───────────────────────────────────────────────────────────
  if (step === 3) {
    return (
      <div style={s.centerPage}>
        <div className="card" style={s.successCard}>
          <div style={{ fontSize: '4rem' }}>🎉</div>
          <h1 style={{ marginTop: 16 }}>Order Placed!</h1>
          <p style={{ color: 'var(--muted)', marginTop: 8 }}>
            Order <strong>#{orderId?.slice(0, 8).toUpperCase()}</strong> confirmed
          </p>
          {paymentResult && (
            <div style={s.txnBox}>
              <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>Transaction ID</span>
              <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: '0.9rem' }}>
                {paymentResult.transaction_id}
              </span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 12, marginTop: 28 }}>
            <button className="btn btn-primary btn-lg" onClick={() => navigate('/orders')}>Track Order</button>
            <button className="btn btn-outline btn-lg" onClick={() => navigate('/')}>Continue Shopping</button>
          </div>
        </div>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div style={s.centerPage}>
        <div className="empty-state">
          <div style={{ fontSize: '3rem', marginBottom: 12 }}>🛒</div>
          <h3>Your cart is empty</h3>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/products')}>Browse Products</button>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="container">
        <h1 style={{ marginBottom: 24 }}>Checkout</h1>

        {/* Step bar */}
        <div style={s.stepRow}>
          {STEPS.map((label, i) => (
            <div key={label} style={s.stepItem}>
              <div style={{ ...s.stepDot, background: i <= step ? 'var(--primary)' : 'var(--border)', color: i <= step ? '#fff' : 'var(--muted)' }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ ...s.stepLabel, color: i === step ? 'var(--primary)' : 'var(--muted)' }}>{label}</span>
              {i < STEPS.length - 1 && <div style={s.stepLine} />}
            </div>
          ))}
        </div>

        <div style={s.layout}>
          {/* ── Left panel ─────────────────────────────────────────────────── */}
          <div>

            {/* STEP 0: Delivery */}
            {step === 0 && (
              <div className="card" style={s.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Delivery Details</h2>

                {/* Saved addresses */}
                {savedAddresses.length > 0 && (
                  <div style={{ marginBottom: 20 }}>
                    <p style={s.sectionLabel}>Saved Addresses</p>
                    <div style={s.addrGrid}>
                      {savedAddresses.map(a => (
                        <div key={a.id} onClick={() => useSavedAddress(a)}
                          style={{ ...s.addrCard, border: selectedAddrId === a.id ? '2px solid var(--primary)' : '1.5px solid var(--border)', background: selectedAddrId === a.id ? 'rgba(80,70,229,.04)' : 'var(--surface)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{a.label}</span>
                            {a.is_default && <span style={s.defaultBadge}>Default</span>}
                          </div>
                          <p style={s.addrMeta}>{a.full_name}</p>
                          <p style={s.addrMeta}>{a.line1}, {a.city}</p>
                          <p style={s.addrMeta}>{a.state} — {a.pincode}</p>
                        </div>
                      ))}
                    </div>
                    <p style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 8 }}>
                      Or fill in a new address below
                    </p>
                  </div>
                )}

                {/* Manual address form */}
                <div style={s.formGrid}>
                  <div className="form-group" style={{ gridColumn: '1/-1' }}>
                    <label>Full Name</label>
                    <input className="input" value={address.name} onChange={e => setField('name', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label>Phone</label>
                    <input className="input" type="tel" value={address.phone} onChange={e => setField('phone', e.target.value)} placeholder="10-digit mobile" />
                  </div>
                  <div className="form-group" style={{ gridColumn: '1/-1' }}>
                    <label>Address</label>
                    <input className="input" value={address.line1} onChange={e => setField('line1', e.target.value)} placeholder="House no, street, area" />
                  </div>
                  <div className="form-group">
                    <label>City</label>
                    <input className="input" value={address.city} onChange={e => setField('city', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label>State</label>
                    <select className="input" value={address.state} onChange={e => setField('state', e.target.value)}>
                      <option value="">Select state</option>
                      {INDIAN_STATES.map(st => <option key={st} value={st}>{st}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Pincode</label>
                    <input className="input" value={address.pincode} onChange={e => setField('pincode', e.target.value)} maxLength={6} placeholder="6 digits" />
                  </div>
                </div>

                {/* Courier rates */}
                {ratesLoading && <p style={{ color: 'var(--muted)', fontSize: '0.82rem', marginTop: 12 }}>Fetching courier rates…</p>}
                {rates.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <p style={s.sectionLabel}>🚚 Available Couriers</p>
                    <div style={s.courierGrid}>
                      {rates.map(r => {
                        const picked = selectedCourier?.courier_name === r.courier_name
                        return (
                          <div key={r.courier_name} onClick={() => setSelectedCourier(r)}
                            style={{ ...s.courierCard, border: picked ? '2px solid var(--primary)' : '1.5px solid var(--border)', background: picked ? 'rgba(80,70,229,.04)' : 'var(--surface)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{r.courier_name}</span>
                              <span style={{ fontWeight: 800, color: 'var(--primary)' }}>₹{Math.round(r.rate_amount)}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                              <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>{r.estimated_days} days</span>
                              <span style={{ fontSize: '0.65rem', fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                                background: r.service_type === 'express' ? '#DBEAFE' : '#F3F4F6',
                                color: r.service_type === 'express' ? '#1D4ED8' : '#6B7280' }}>
                                {r.service_type}
                              </span>
                            </div>
                            {picked && <p style={{ fontSize: '0.7rem', color: 'var(--primary)', fontWeight: 700, marginTop: 4 }}>✓ Selected</p>}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                <button className="btn btn-primary btn-lg" style={{ marginTop: 20 }}
                  onClick={() => setStep(1)}
                  disabled={!address.name || !address.phone || !address.line1 || !address.city || !address.pincode}>
                  Continue to Review →
                </button>
              </div>
            )}

            {/* STEP 1: Review */}
            {step === 1 && (
              <div className="card" style={s.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Review Order</h2>
                {items.map(item => (
                  <div key={item.product_id} style={s.reviewItem}>
                    <img src={item.image_url} alt={item.product_name} style={s.reviewImg}
                      onError={e => { e.target.style.display = 'none' }} />
                    <div style={{ flex: 1 }}>
                      <p style={{ fontWeight: 600 }}>{item.product_name}</p>
                      <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>Qty: {item.quantity}</p>
                    </div>
                    <p style={{ fontWeight: 700 }}>₹{Number(item.line_total ?? item.unit_price * item.quantity).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
                  </div>
                ))}
                <div style={s.infoBox}>
                  <strong>Delivering to</strong>
                  <p style={s.infoMeta}>{address.name} · {address.phone}</p>
                  <p style={s.infoMeta}>{address.line1}, {address.city}, {address.state} — {address.pincode}</p>
                </div>
                {selectedCourier && (
                  <div style={{ ...s.infoBox, display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
                    <div>
                      <strong>🚚 {selectedCourier.courier_name}</strong>
                      <p style={s.infoMeta}>{selectedCourier.service_type} · {selectedCourier.estimated_days} days</p>
                    </div>
                    <span style={{ fontWeight: 800, color: 'var(--primary)' }}>₹{Math.round(selectedCourier.rate_amount)}</span>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                  <button className="btn btn-ghost" onClick={() => setStep(0)}>← Back</button>
                  <button className="btn btn-primary btn-lg" style={{ flex: 1 }} onClick={() => setStep(2)}>Continue to Payment →</button>
                </div>
              </div>
            )}

            {/* STEP 2: Payment */}
            {step === 2 && (
              <div className="card" style={s.stepCard}>
                <h2 style={{ marginBottom: 20 }}>Payment</h2>

                {/* Saved payment methods */}
                {savedMethods.length > 0 && (
                  <div style={{ marginBottom: 20 }}>
                    <p style={s.sectionLabel}>Saved Payment Methods</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {savedMethods.map(m => {
                        const active = selectedSavedMethod?.id === m.id
                        const label = m.type === 'card'
                          ? `${m.card_brand} •••• ${m.card_last4} — ${m.card_holder}`
                          : m.type === 'upi'
                          ? m.upi_id
                          : `${m.wallet_provider} — ${m.wallet_phone}`
                        const icon = m.type === 'card' ? '💳' : m.type === 'upi' ? '📲' : '👛'
                        return (
                          <div key={m.id} onClick={() => selectSavedPayment(m)}
                            style={{ ...s.savedPmCard, border: active ? '2px solid var(--primary)' : '1.5px solid var(--border)', background: active ? 'rgba(80,70,229,.06)' : 'var(--surface)' }}>
                            <span style={{ fontSize: '1.1rem' }}>{icon}</span>
                            <div style={{ flex: 1 }}>
                              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{label}</span>
                              {m.is_default && <span style={{ ...s.defaultBadge, marginLeft: 8 }}>Default</span>}
                            </div>
                            {active && <span style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.8rem' }}>✓</span>}
                          </div>
                        )
                      })}
                    </div>
                    <p style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 8 }}>Or use a different method below</p>
                  </div>
                )}

                {/* Method tabs */}
                <div style={s.methodTabs}>
                  {[
                    { id: 'card',   label: '💳 Card' },
                    { id: 'upi',    label: '📲 UPI' },
                    { id: 'wallet', label: '👛 Wallet' },
                  ].map(m => (
                    <button key={m.id} onClick={() => { setPayMethod(m.id); setSelectedSavedMethod(null) }}
                      style={{ ...s.methodTab, ...(payMethod === m.id ? s.methodTabActive : {}) }}>
                      {m.label}
                    </button>
                  ))}
                </div>

                {/* Card form */}
                {payMethod === 'card' && (
                  <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div className="form-group">
                      <label>Card Number</label>
                      <input className="input" value={cardForm.number} placeholder="1234 5678 9012 3456"
                        onChange={e => setCardForm(f => ({ ...f, number: fmtCard(e.target.value) }))} maxLength={19} />
                    </div>
                    <div className="form-group">
                      <label>Cardholder Name</label>
                      <input className="input" value={cardForm.holder} placeholder="Name on card"
                        onChange={e => setCardForm(f => ({ ...f, holder: e.target.value }))} />
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                      <div className="form-group">
                        <label>Expiry (MM/YYYY)</label>
                        <input className="input" value={cardForm.expiry} placeholder="09/2028"
                          onChange={e => setCardForm(f => ({ ...f, expiry: e.target.value }))} maxLength={7} />
                      </div>
                      <div className="form-group">
                        <label>CVV</label>
                        <input className="input" type="password" value={cardForm.cvv} placeholder="•••"
                          onChange={e => setCardForm(f => ({ ...f, cvv: e.target.value.replace(/\D/g, '').slice(0, 4) }))} maxLength={4} />
                      </div>
                    </div>
                    <p style={s.testHint}>Test: card <code>4242 4242 4242 4242</code>, any future expiry, any CVV</p>
                  </div>
                )}

                {/* UPI form */}
                {payMethod === 'upi' && (
                  <div style={{ marginTop: 16 }}>
                    <div className="form-group">
                      <label>UPI ID</label>
                      <input className="input" value={upiId} placeholder="yourname@paytm"
                        onChange={e => setUpiId(e.target.value)} />
                    </div>
                    <p style={s.testHint}>Test: any valid UPI ID format (e.g. <code>test@paytm</code>). Use <code>fail@upi</code> to test failure.</p>
                  </div>
                )}

                {/* Wallet form */}
                {payMethod === 'wallet' && (
                  <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div className="form-group">
                      <label>Wallet</label>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {WALLETS.map(w => (
                          <button key={w.value} type="button"
                            onClick={() => setWalletType(w.value)}
                            className={`btn btn-sm ${walletType === w.value ? 'btn-primary' : 'btn-outline'}`}>
                            {w.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="form-group">
                      <label>Registered Mobile Number</label>
                      <input className="input" value={walletMobile} placeholder="10-digit mobile"
                        onChange={e => setWalletMobile(e.target.value.replace(/\D/g, '').slice(0, 10))} maxLength={10} />
                    </div>
                    <p style={s.testHint}>Test: any valid 10-digit number. Use <code>9000000000</code> to test insufficient balance.</p>
                  </div>
                )}

                <div style={s.safeRow}>🔒 Secured with 256-bit SSL encryption</div>

                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                  <button className="btn btn-ghost" onClick={() => setStep(1)}>← Back</button>
                  <button className="btn btn-accent btn-lg" style={{ flex: 1 }}
                    onClick={placeOrder} disabled={loading}>
                    {loading ? 'Processing…' : `Pay ₹${Number(total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* ── Right: Order Summary ─────────────────────────────────────────── */}
          <div style={s.summary}>
            <div className="card" style={{ padding: '20px 24px' }}>
              <h3 style={{ marginBottom: 16 }}>Order Summary</h3>

              {/* Coupon */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input className="input" style={{ flex: 1, height: 36, fontSize: '0.85rem' }}
                    value={coupon} onChange={e => setCoupon(e.target.value.toUpperCase())}
                    placeholder="Coupon code" />
                  <button className="btn btn-outline btn-sm"
                    onClick={() => { if (coupon.trim()) { setCouponApplied(coupon.trim()); toast(`Coupon "${coupon.trim()}" applied`, 'success') } }}
                    disabled={!coupon.trim()}>
                    Apply
                  </button>
                </div>
                {couponApplied && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
                    <span style={{ fontSize: '0.8rem', color: '#059669', fontWeight: 600 }}>✓ {couponApplied} applied</span>
                    <button style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '0.75rem', cursor: 'pointer' }}
                      onClick={() => { setCouponApplied(''); setCoupon('') }}>Remove</button>
                  </div>
                )}
              </div>

              <div style={s.summaryRow}>
                <span>Items ({count})</span>
                <span>₹{Number(subtotal).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              </div>
              <div style={s.summaryRow}>
                <span>Delivery</span>
                <span style={{ color: shippingCharge === 0 ? 'var(--success, #059669)' : undefined }}>
                  {shippingCharge === 0 ? 'FREE' : `₹${shippingCharge}`}
                </span>
              </div>
              <div style={s.summaryRow}>
                <span>GST (18%)</span>
                <span>₹{Number(gst).toLocaleString('en-IN')}</span>
              </div>
              <div className="divider" />
              <div style={{ ...s.summaryRow, fontWeight: 700, fontSize: '1.05rem' }}>
                <span>Total</span>
                <span>₹{Number(total).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              </div>
              {subtotal < 500 && (
                <p style={{ color: '#059669', fontSize: '0.8rem', marginTop: 8 }}>
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

// ── Styles ────────────────────────────────────────────────────────────────────
const s = {
  centerPage:   { minHeight: '70vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40 },
  successCard:  { padding: '48px 56px', textAlign: 'center', maxWidth: 480 },
  txnBox: {
    background: 'var(--ground)', borderRadius: 8, padding: '10px 16px', marginTop: 16,
    display: 'flex', flexDirection: 'column', gap: 4, textAlign: 'left',
  },
  stepRow:   { display: 'flex', alignItems: 'center', marginBottom: 32 },
  stepItem:  { display: 'flex', alignItems: 'center', gap: 8, flex: 1 },
  stepDot: {
    width: 32, height: 32, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: 700, fontSize: '0.875rem', flexShrink: 0, transition: 'background .3s',
  },
  stepLabel: { fontSize: '0.875rem', fontWeight: 600, whiteSpace: 'nowrap' },
  stepLine:  { flex: 1, height: 2, background: 'var(--border)', marginLeft: 8 },
  layout:    { display: 'grid', gridTemplateColumns: '1fr 340px', gap: 24, alignItems: 'flex-start' },
  stepCard:  { padding: '28px 32px' },
  sectionLabel: {
    fontSize: '0.75rem', fontWeight: 700, color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 10,
  },
  // Saved address picker
  addrGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 },
  addrCard: { borderRadius: 8, padding: '10px 12px', cursor: 'pointer', transition: 'all .15s' },
  addrMeta: { fontSize: '0.78rem', color: 'var(--muted)', margin: '2px 0' },
  defaultBadge: {
    background: 'rgba(0,179,126,.12)', color: '#059669',
    padding: '1px 7px', borderRadius: 999, fontSize: '0.7rem', fontWeight: 700,
  },
  formGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
  courierGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(148px, 1fr))', gap: 8 },
  courierCard: { borderRadius: 8, padding: '10px 12px', cursor: 'pointer', transition: 'all .15s' },
  // Review
  reviewItem: { display: 'flex', alignItems: 'center', gap: 14, padding: '12px 0', borderBottom: '1px solid var(--border)' },
  reviewImg:  { width: 64, height: 64, objectFit: 'cover', borderRadius: 8, flexShrink: 0 },
  infoBox:  { background: 'var(--ground)', borderRadius: 10, padding: '14px 16px', marginTop: 16 },
  infoMeta: { color: 'var(--muted)', fontSize: '0.875rem', marginTop: 4 },
  // Payment
  savedPmCard: {
    display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
    borderRadius: 8, cursor: 'pointer', transition: 'all .15s',
  },
  methodTabs: { display: 'flex', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)' },
  methodTab: {
    flex: 1, padding: '10px 0', background: 'none', border: 'none',
    fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer', color: 'var(--muted)',
    transition: 'background .15s, color .15s',
  },
  methodTabActive: { background: 'var(--primary)', color: '#fff' },
  testHint: { fontSize: '0.75rem', color: 'var(--muted)', marginTop: 4 },
  safeRow:  { color: 'var(--muted)', fontSize: '0.8rem', marginTop: 14 },
  // Order summary
  summary:    { position: 'sticky', top: 80 },
  summaryRow: { display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', marginBottom: 10 },
}
