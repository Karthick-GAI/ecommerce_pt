import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { profileApi, addressApi, paymentMethodApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'
import { useToast } from '../store/ToastContext.jsx'

const TABS = ['Personal Info', 'Address Book', 'Payment Methods']

const INDIAN_STATES = [
  'Andhra Pradesh','Arunachal Pradesh','Assam','Bihar','Chhattisgarh','Goa','Gujarat',
  'Haryana','Himachal Pradesh','Jharkhand','Karnataka','Kerala','Madhya Pradesh',
  'Maharashtra','Manipur','Meghalaya','Mizoram','Nagaland','Odisha','Punjab',
  'Rajasthan','Sikkim','Tamil Nadu','Telangana','Tripura','Uttar Pradesh',
  'Uttarakhand','West Bengal','Delhi','Jammu & Kashmir','Ladakh','Puducherry',
]

const WALLET_PROVIDERS = ['Paytm', 'PhonePe', 'GPay', 'Amazon Pay', 'MobiKwik']
const CARD_BRANDS      = ['Visa', 'Mastercard', 'RuPay', 'Amex']

// ── tiny helpers ─────────────────────────────────────────────────────────────

function Field({ label, error, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={s.label}>{label}</label>
      {children}
      {error && <p style={s.fieldError}>{error}</p>}
    </div>
  )
}

function SectionCard({ title, children }) {
  return (
    <div style={s.card}>
      {title && <h3 style={s.cardTitle}>{title}</h3>}
      {children}
    </div>
  )
}

// ── Personal Info tab ─────────────────────────────────────────────────────────

function PersonalInfo({ user, onUpdated }) {
  const toast = useToast()
  const [form, setForm]     = useState({ first_name: '', last_name: '', phone: '' })
  const [pwForm, setPwForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [saving, setSaving] = useState(false)
  const [savingPw, setSavingPw] = useState(false)
  const [errors, setErrors] = useState({})
  const [pwErrors, setPwErrors] = useState({})

  useEffect(() => {
    if (user) setForm({ first_name: user.first_name || '', last_name: user.last_name || '', phone: user.phone || '' })
  }, [user])

  async function saveProfile(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const res = await profileApi.update({
        first_name: form.first_name || undefined,
        last_name:  form.last_name  || undefined,
        phone:      form.phone      || undefined,
      })
      onUpdated(res.data)
      toast('Profile updated', 'success')
    } catch (err) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        const map = {}
        detail.forEach(d => { map[d.loc?.at(-1)] = d.msg })
        setErrors(map)
      } else {
        toast(detail || 'Failed to update profile', 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  async function changePassword(e) {
    e.preventDefault()
    setPwErrors({})
    if (pwForm.new_password !== pwForm.confirm) {
      setPwErrors({ confirm: 'Passwords do not match' })
      return
    }
    setSavingPw(true)
    try {
      await profileApi.changePassword({
        current_password: pwForm.current_password,
        new_password:     pwForm.new_password,
      })
      toast('Password changed', 'success')
      setPwForm({ current_password: '', new_password: '', confirm: '' })
    } catch (err) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        const map = {}
        detail.forEach(d => { map[d.loc?.at(-1)] = d.msg })
        setPwErrors(map)
      } else {
        toast(detail || 'Failed to change password', 'error')
      }
    } finally {
      setSavingPw(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      {/* profile form */}
      <SectionCard title="Account Details">
        <form onSubmit={saveProfile}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="First Name" error={errors.first_name}>
              <input className="input" value={form.first_name}
                onChange={e => setForm(f => ({ ...f, first_name: e.target.value }))} />
            </Field>
            <Field label="Last Name" error={errors.last_name}>
              <input className="input" value={form.last_name}
                onChange={e => setForm(f => ({ ...f, last_name: e.target.value }))} />
            </Field>
          </div>
          <Field label="Email">
            <input className="input" value={user?.email || ''} disabled style={{ opacity: .6 }} />
          </Field>
          <Field label="Phone" error={errors.phone}>
            <input className="input" value={form.phone} placeholder="10-digit mobile"
              onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />
          </Field>
          <button type="submit" className="btn btn-primary" disabled={saving} style={{ marginTop: 4 }}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </form>
      </SectionCard>

      {/* password form */}
      <SectionCard title="Change Password">
        <form onSubmit={changePassword}>
          <Field label="Current Password" error={pwErrors.current_password}>
            <input type="password" className="input" value={pwForm.current_password}
              onChange={e => setPwForm(f => ({ ...f, current_password: e.target.value }))} />
          </Field>
          <Field label="New Password" error={pwErrors.new_password}>
            <input type="password" className="input" value={pwForm.new_password}
              placeholder="Min 8 chars, 1 uppercase, 1 digit"
              onChange={e => setPwForm(f => ({ ...f, new_password: e.target.value }))} />
          </Field>
          <Field label="Confirm New Password" error={pwErrors.confirm}>
            <input type="password" className="input" value={pwForm.confirm}
              onChange={e => setPwForm(f => ({ ...f, confirm: e.target.value }))} />
          </Field>
          <button type="submit" className="btn btn-primary" disabled={savingPw} style={{ marginTop: 4 }}>
            {savingPw ? 'Saving…' : 'Change Password'}
          </button>
        </form>
      </SectionCard>
    </div>
  )
}

// ── Address Book tab ──────────────────────────────────────────────────────────

const EMPTY_ADDR = {
  label: '', full_name: '', phone: '', alternate_phone: '',
  line1: '', line2: '', landmark: '', city: '', state: '', pincode: '',
}

function AddressBook() {
  const toast = useToast()
  const [addresses, setAddresses] = useState([])
  const [loading, setLoading]     = useState(true)
  const [showForm, setShowForm]   = useState(false)
  const [editing, setEditing]     = useState(null)   // address id being edited
  const [form, setForm]           = useState(EMPTY_ADDR)
  const [saving, setSaving]       = useState(false)
  const [errors, setErrors]       = useState({})

  async function load() {
    try {
      const res = await addressApi.list()
      setAddresses(res.data)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  function openAdd() { setForm(EMPTY_ADDR); setEditing(null); setErrors({}); setShowForm(true) }
  function openEdit(addr) {
    setForm({ ...addr, alternate_phone: addr.alternate_phone || '', line2: addr.line2 || '', landmark: addr.landmark || '' })
    setEditing(addr.id); setErrors({}); setShowForm(true)
  }
  function cancel() { setShowForm(false); setEditing(null) }

  async function submit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    const payload = {
      label: form.label, full_name: form.full_name, phone: form.phone,
      alternate_phone: form.alternate_phone || undefined,
      line1: form.line1, line2: form.line2 || undefined,
      landmark: form.landmark || undefined,
      city: form.city, state: form.state, pincode: form.pincode,
    }
    try {
      if (editing) {
        const res = await addressApi.update(editing, payload)
        setAddresses(a => a.map(x => x.id === editing ? res.data : x))
        toast('Address updated', 'success')
      } else {
        const res = await addressApi.create(payload)
        setAddresses(a => [...a, res.data])
        toast('Address added', 'success')
      }
      cancel()
    } catch (err) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        const map = {}
        detail.forEach(d => { map[d.loc?.at(-1)] = d.msg })
        setErrors(map)
      } else {
        toast(detail || 'Failed to save address', 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  async function remove(id) {
    if (!confirm('Delete this address?')) return
    try {
      await addressApi.remove(id)
      setAddresses(a => a.filter(x => x.id !== id))
      toast('Address deleted', 'success')
    } catch {
      toast('Failed to delete address', 'error')
    }
  }

  async function setDefault(id) {
    try {
      await addressApi.setDefault(id)
      setAddresses(a => a.map(x => ({ ...x, is_default: x.id === id })))
      toast('Default address updated', 'success')
    } catch {
      toast('Failed to update default', 'error')
    }
  }

  if (loading) return <p style={{ color: 'var(--muted)' }}>Loading addresses…</p>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h3 style={s.sectionTitle}>Saved Addresses ({addresses.length})</h3>
        {!showForm && (
          <button className="btn btn-primary btn-sm" onClick={openAdd}>+ Add Address</button>
        )}
      </div>

      {showForm && (
        <SectionCard title={editing ? 'Edit Address' : 'New Address'}>
          <form onSubmit={submit}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Label (e.g. Home, Office)" error={errors.label}>
                <input className="input" value={form.label} placeholder="Home"
                  onChange={e => setForm(f => ({ ...f, label: e.target.value }))} />
              </Field>
              <Field label="Recipient Name" error={errors.full_name}>
                <input className="input" value={form.full_name}
                  onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} />
              </Field>
              <Field label="Phone" error={errors.phone}>
                <input className="input" value={form.phone} placeholder="10-digit mobile"
                  onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />
              </Field>
              <Field label="Alternate Phone (optional)" error={errors.alternate_phone}>
                <input className="input" value={form.alternate_phone}
                  onChange={e => setForm(f => ({ ...f, alternate_phone: e.target.value }))} />
              </Field>
              <Field label="Address Line 1" error={errors.line1}>
                <input className="input" value={form.line1}
                  onChange={e => setForm(f => ({ ...f, line1: e.target.value }))} />
              </Field>
              <Field label="Address Line 2 (optional)">
                <input className="input" value={form.line2}
                  onChange={e => setForm(f => ({ ...f, line2: e.target.value }))} />
              </Field>
              <Field label="Landmark (optional)">
                <input className="input" value={form.landmark} placeholder="Near Big Bazaar"
                  onChange={e => setForm(f => ({ ...f, landmark: e.target.value }))} />
              </Field>
              <Field label="City" error={errors.city}>
                <input className="input" value={form.city}
                  onChange={e => setForm(f => ({ ...f, city: e.target.value }))} />
              </Field>
              <Field label="State" error={errors.state}>
                <select className="input" value={form.state}
                  onChange={e => setForm(f => ({ ...f, state: e.target.value }))}>
                  <option value="">Select state</option>
                  {INDIAN_STATES.map(st => <option key={st} value={st}>{st}</option>)}
                </select>
              </Field>
              <Field label="Pincode" error={errors.pincode}>
                <input className="input" value={form.pincode} placeholder="6 digits"
                  maxLength={6}
                  onChange={e => setForm(f => ({ ...f, pincode: e.target.value }))} />
              </Field>
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving…' : (editing ? 'Update Address' : 'Add Address')}
              </button>
              <button type="button" className="btn btn-outline" onClick={cancel}>Cancel</button>
            </div>
          </form>
        </SectionCard>
      )}

      {addresses.length === 0 && !showForm && (
        <div style={s.empty}>No saved addresses yet.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, marginTop: 16 }}>
        {addresses.map(addr => (
          <div key={addr.id} style={{ ...s.card, position: 'relative', padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <span style={s.addrLabel}>{addr.label}</span>
                {addr.is_default && <span style={s.defaultBadge}>Default</span>}
              </div>
            </div>
            <p style={s.addrLine}>{addr.full_name}</p>
            <p style={s.addrLine}>{addr.line1}{addr.line2 ? `, ${addr.line2}` : ''}</p>
            {addr.landmark && <p style={s.addrLine}>{addr.landmark}</p>}
            <p style={s.addrLine}>{addr.city}, {addr.state} — {addr.pincode}</p>
            <p style={s.addrLine}>📞 {addr.phone}{addr.alternate_phone ? ` / ${addr.alternate_phone}` : ''}</p>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button className="btn btn-outline btn-sm" onClick={() => openEdit(addr)}>Edit</button>
              {!addr.is_default && (
                <button className="btn btn-outline btn-sm" onClick={() => setDefault(addr.id)}>Set Default</button>
              )}
              <button className="btn btn-sm" style={s.deleteBtn} onClick={() => remove(addr.id)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Payment Methods tab ───────────────────────────────────────────────────────

const EMPTY_PM = { type: 'card', label: '', card_last4: '', card_brand: 'Visa', card_holder: '', card_expiry: '', upi_id: '', wallet_provider: 'Paytm', wallet_phone: '' }

function PaymentMethods() {
  const toast = useToast()
  const [methods, setMethods] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]       = useState(EMPTY_PM)
  const [saving, setSaving]   = useState(false)
  const [errors, setErrors]   = useState({})

  async function load() {
    try {
      const res = await paymentMethodApi.list()
      setMethods(res.data)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  function openAdd() { setForm(EMPTY_PM); setErrors({}); setShowForm(true) }

  async function submit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    let payload = { type: form.type, label: form.label || undefined }
    if (form.type === 'card') {
      payload = { ...payload, card_last4: form.card_last4, card_brand: form.card_brand, card_holder: form.card_holder, card_expiry: form.card_expiry }
    } else if (form.type === 'upi') {
      payload = { ...payload, upi_id: form.upi_id }
    } else {
      payload = { ...payload, wallet_provider: form.wallet_provider, wallet_phone: form.wallet_phone }
    }
    try {
      const res = await paymentMethodApi.create(payload)
      setMethods(m => [...m, res.data])
      toast('Payment method added', 'success')
      setShowForm(false)
    } catch (err) {
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        const map = {}
        detail.forEach(d => { map[d.loc?.at(-1)] = d.msg })
        setErrors(map)
      } else {
        toast(detail || 'Failed to add payment method', 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  async function remove(id) {
    if (!confirm('Remove this payment method?')) return
    try {
      await paymentMethodApi.remove(id)
      setMethods(m => m.filter(x => x.id !== id))
      toast('Payment method removed', 'success')
    } catch {
      toast('Failed to remove payment method', 'error')
    }
  }

  async function setDefault(id) {
    try {
      await paymentMethodApi.setDefault(id)
      setMethods(m => m.map(x => ({ ...x, is_default: x.id === id })))
      toast('Default payment method updated', 'success')
    } catch {
      toast('Failed to update default', 'error')
    }
  }

  function pmIcon(type) { return type === 'card' ? '💳' : type === 'upi' ? '📲' : '👛' }

  function pmSummary(m) {
    if (m.type === 'card')   return `${m.card_brand} •••• ${m.card_last4} — ${m.card_holder} (exp ${m.card_expiry})`
    if (m.type === 'upi')    return m.upi_id
    return `${m.wallet_provider} — ${m.wallet_phone}`
  }

  if (loading) return <p style={{ color: 'var(--muted)' }}>Loading payment methods…</p>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h3 style={s.sectionTitle}>Saved Payment Methods ({methods.length})</h3>
        {!showForm && (
          <button className="btn btn-primary btn-sm" onClick={openAdd}>+ Add Method</button>
        )}
      </div>

      {showForm && (
        <SectionCard title="Add Payment Method">
          <form onSubmit={submit}>
            <Field label="Type">
              <div style={{ display: 'flex', gap: 8 }}>
                {['card','upi','wallet'].map(t => (
                  <button key={t} type="button"
                    className={`btn btn-sm ${form.type === t ? 'btn-primary' : 'btn-outline'}`}
                    onClick={() => setForm(f => ({ ...f, type: t }))}>
                    {pmIcon(t)} {t.toUpperCase()}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Label (optional)">
              <input className="input" value={form.label} placeholder="e.g. My HDFC card"
                onChange={e => setForm(f => ({ ...f, label: e.target.value }))} />
            </Field>

            {form.type === 'card' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Card Brand" error={errors.card_brand}>
                  <select className="input" value={form.card_brand}
                    onChange={e => setForm(f => ({ ...f, card_brand: e.target.value }))}>
                    {CARD_BRANDS.map(b => <option key={b}>{b}</option>)}
                  </select>
                </Field>
                <Field label="Last 4 Digits" error={errors.card_last4}>
                  <input className="input" value={form.card_last4} placeholder="1234" maxLength={4}
                    onChange={e => setForm(f => ({ ...f, card_last4: e.target.value }))} />
                </Field>
                <Field label="Cardholder Name" error={errors.card_holder}>
                  <input className="input" value={form.card_holder}
                    onChange={e => setForm(f => ({ ...f, card_holder: e.target.value }))} />
                </Field>
                <Field label="Expiry (MM/YYYY)" error={errors.card_expiry}>
                  <input className="input" value={form.card_expiry} placeholder="09/2028"
                    onChange={e => setForm(f => ({ ...f, card_expiry: e.target.value }))} />
                </Field>
              </div>
            )}

            {form.type === 'upi' && (
              <Field label="UPI ID" error={errors.upi_id}>
                <input className="input" value={form.upi_id} placeholder="name@paytm"
                  onChange={e => setForm(f => ({ ...f, upi_id: e.target.value }))} />
              </Field>
            )}

            {form.type === 'wallet' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Wallet Provider" error={errors.wallet_provider}>
                  <select className="input" value={form.wallet_provider}
                    onChange={e => setForm(f => ({ ...f, wallet_provider: e.target.value }))}>
                    {WALLET_PROVIDERS.map(p => <option key={p}>{p}</option>)}
                  </select>
                </Field>
                <Field label="Registered Phone" error={errors.wallet_phone}>
                  <input className="input" value={form.wallet_phone} placeholder="10-digit mobile"
                    onChange={e => setForm(f => ({ ...f, wallet_phone: e.target.value }))} />
                </Field>
              </div>
            )}

            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving…' : 'Add Method'}
              </button>
              <button type="button" className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </SectionCard>
      )}

      {methods.length === 0 && !showForm && (
        <div style={s.empty}>No saved payment methods yet.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, marginTop: 16 }}>
        {methods.map(m => (
          <div key={m.id} style={{ ...s.card, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span style={{ fontSize: '1.5rem' }}>{pmIcon(m.type)}</span>
              {m.is_default && <span style={s.defaultBadge}>Default</span>}
            </div>
            {m.label && <p style={{ fontWeight: 600, margin: '8px 0 4px' }}>{m.label}</p>}
            <p style={{ ...s.addrLine, fontFamily: 'monospace', marginTop: m.label ? 0 : 8 }}>{pmSummary(m)}</p>
            <p style={{ ...s.addrLine, textTransform: 'capitalize', color: 'var(--muted)', fontSize: '0.8rem' }}>{m.type}</p>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              {!m.is_default && (
                <button className="btn btn-outline btn-sm" onClick={() => setDefault(m.id)}>Set Default</button>
              )}
              <button className="btn btn-sm" style={s.deleteBtn} onClick={() => remove(m.id)}>Remove</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main Profile page ─────────────────────────────────────────────────────────

export default function Profile() {
  const { user, isLoggedIn, setUser } = useAuth()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState(0)

  useEffect(() => {
    if (!isLoggedIn) navigate('/auth')
  }, [isLoggedIn])

  if (!isLoggedIn || !user) return null

  return (
    <div className="container" style={{ padding: '32px 16px', maxWidth: 1100 }}>
      {/* page header */}
      <div style={s.pageHeader}>
        <div style={s.avatar}>{(user.first_name?.[0] || user.email?.[0] || '?').toUpperCase()}</div>
        <div>
          <h1 style={s.pageTitle}>{user.first_name} {user.last_name}</h1>
          <p style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>{user.email}</p>
        </div>
      </div>

      {/* tabs */}
      <div style={s.tabBar}>
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setActiveTab(i)}
            style={{ ...s.tab, ...(activeTab === i ? s.tabActive : {}) }}>
            {t}
          </button>
        ))}
      </div>

      {/* tab content */}
      <div style={{ marginTop: 24 }}>
        {activeTab === 0 && <PersonalInfo user={user} onUpdated={setUser} />}
        {activeTab === 1 && <AddressBook />}
        {activeTab === 2 && <PaymentMethods />}
      </div>
    </div>
  )
}

// ── styles ────────────────────────────────────────────────────────────────────

const s = {
  pageHeader: {
    display: 'flex', alignItems: 'center', gap: 16, marginBottom: 32,
  },
  avatar: {
    width: 64, height: 64, borderRadius: '50%',
    background: 'var(--primary)', color: '#fff',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '1.5rem', fontWeight: 700, flexShrink: 0,
  },
  pageTitle: {
    fontSize: '1.5rem', fontWeight: 700, margin: 0,
  },
  tabBar: {
    display: 'flex', gap: 4, borderBottom: '2px solid var(--border)', paddingBottom: 0,
  },
  tab: {
    padding: '10px 20px', background: 'none', border: 'none',
    fontSize: '0.9rem', fontWeight: 500, color: 'var(--muted)',
    cursor: 'pointer', borderBottom: '2px solid transparent', marginBottom: -2,
    transition: 'color .15s',
  },
  tabActive: {
    color: 'var(--primary)', borderBottomColor: 'var(--primary)', fontWeight: 700,
  },
  card: {
    background: 'var(--surface)', borderRadius: 'var(--radius)',
    border: '1px solid var(--border)', padding: 20, marginBottom: 16,
  },
  cardTitle: {
    fontSize: '1rem', fontWeight: 700, marginBottom: 16, marginTop: 0,
  },
  label: {
    display: 'block', fontSize: '0.8rem', fontWeight: 600,
    color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.3px',
  },
  fieldError: {
    color: 'var(--danger, #ef4444)', fontSize: '0.78rem', marginTop: 4,
  },
  sectionTitle: {
    fontSize: '1.05rem', fontWeight: 700, margin: 0,
  },
  addrLabel: {
    fontWeight: 700, fontSize: '0.95rem',
  },
  addrLine: {
    margin: '4px 0', fontSize: '0.88rem', color: 'var(--text)',
  },
  defaultBadge: {
    background: 'rgba(0,179,126,.12)', color: '#059669',
    padding: '2px 10px', borderRadius: 999, fontSize: '0.72rem', fontWeight: 700,
    marginLeft: 8,
  },
  deleteBtn: {
    background: 'rgba(239,68,68,.08)', color: '#dc2626',
    border: '1px solid rgba(239,68,68,.2)', borderRadius: 6,
  },
  empty: {
    textAlign: 'center', padding: '40px 0', color: 'var(--muted)', fontSize: '0.95rem',
  },
}
