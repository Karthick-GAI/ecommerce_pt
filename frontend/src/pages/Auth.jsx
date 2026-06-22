import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/AuthContext.jsx'
import { useToast } from '../store/ToastContext.jsx'

export default function Auth() {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ email: '', password: '', first_name: '', last_name: '', phone: '' })
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const { login, register } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/'

  function setField(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setErrors({})
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(form.email, form.password)
        toast('Welcome back!', 'success')
        navigate(from, { replace: true })
      } else {
        await register({ ...form })
        toast('Account created! Please sign in.', 'success')
        setMode('login')
      }
    } catch (err) {
      const msg = err.response?.data?.detail || 'Something went wrong'
      if (typeof msg === 'string') {
        setErrors({ general: msg })
      } else {
        const mapped = {}
        msg.forEach?.((e) => { mapped[e.loc?.[1] || 'general'] = e.msg })
        setErrors(mapped)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card} className="card">
        <div style={styles.logoWrap}>
          <span style={{ fontSize: '2rem' }}>🛍</span>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)' }}>ShopAI</h1>
        </div>

        <div style={styles.tabRow}>
          <button
            style={{ ...styles.tab, ...(mode === 'login' ? styles.tabActive : {}) }}
            onClick={() => setMode('login')}
          >
            Sign In
          </button>
          <button
            style={{ ...styles.tab, ...(mode === 'register' ? styles.tabActive : {}) }}
            onClick={() => setMode('register')}
          >
            Create Account
          </button>
        </div>

        <form onSubmit={handleSubmit} style={styles.form}>
          {errors.general && (
            <div style={styles.errorBox}>{errors.general}</div>
          )}

          {mode === 'register' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="form-group">
                <label>First Name</label>
                <input className="input" value={form.first_name}
                  onChange={e => setField('first_name', e.target.value)} required />
              </div>
              <div className="form-group">
                <label>Last Name</label>
                <input className="input" value={form.last_name}
                  onChange={e => setField('last_name', e.target.value)} required />
              </div>
            </div>
          )}

          <div className="form-group">
            <label>Email</label>
            <input className="input" type="email" value={form.email}
              onChange={e => setField('email', e.target.value)} required
              autoComplete="email" />
            {errors.email && <span className="form-error">{errors.email}</span>}
          </div>

          <div className="form-group">
            <label>Password</label>
            <input className="input" type="password" value={form.password}
              onChange={e => setField('password', e.target.value)} required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              minLength={8} />
            {errors.password && <span className="form-error">{errors.password}</span>}
          </div>

          {mode === 'register' && (
            <div className="form-group">
              <label>Phone (optional)</label>
              <input className="input" type="tel" value={form.phone}
                onChange={e => setField('phone', e.target.value)}
                placeholder="+91 98765 43210" />
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-full btn-lg"
            disabled={loading}
            style={{ marginTop: 4 }}
          >
            {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>

        {mode === 'login' && (
          <p style={styles.hint}>
            Don't have an account?{' '}
            <button style={styles.switchLink} onClick={() => setMode('register')}>Create one</button>
          </p>
        )}

        {/* Demo hint */}
        <div style={styles.demoBox}>
          <p style={{ fontSize: '0.8rem', color: 'var(--muted)', textAlign: 'center' }}>
            Demo: register a new account to get started
          </p>
        </div>
      </div>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '40px 20px',
  },
  card: {
    width: '100%', maxWidth: 460, padding: '36px 40px',
  },
  logoWrap: {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 28,
  },
  tabRow: {
    display: 'flex', background: 'var(--ground)', borderRadius: 10, padding: 4, marginBottom: 24,
  },
  tab: {
    flex: 1, padding: '8px 16px', border: 'none', background: 'none',
    borderRadius: 8, fontSize: '0.9rem', fontWeight: 500, cursor: 'pointer',
    color: 'var(--muted)',
  },
  tabActive: {
    background: 'var(--surface)', color: 'var(--primary)', fontWeight: 700,
    boxShadow: '0 2px 8px rgba(0,0,0,.08)',
  },
  form: { display: 'flex', flexDirection: 'column', gap: 16 },
  errorBox: {
    background: 'rgba(239,68,68,.1)', color: 'var(--danger)',
    borderRadius: 8, padding: '10px 14px', fontSize: '0.875rem',
  },
  hint: { textAlign: 'center', fontSize: '0.875rem', color: 'var(--muted)', marginTop: 16 },
  switchLink: {
    background: 'none', border: 'none', color: 'var(--primary)', fontWeight: 600, cursor: 'pointer',
  },
  demoBox: {
    background: 'var(--ground)', borderRadius: 8, padding: '10px 14px', marginTop: 16,
  },
}
