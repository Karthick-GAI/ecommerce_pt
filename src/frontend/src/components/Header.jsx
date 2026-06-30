import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/AuthContext.jsx'
import { useCart } from '../store/CartContext.jsx'
import CartDrawer from './CartDrawer.jsx'

export default function Header() {
  const { user, logout } = useAuth()
  const { count } = useCart()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [cartOpen, setCartOpen] = useState(false)

  function handleSearch(e) {
    e.preventDefault()
    if (query.trim()) navigate(`/products?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <>
      <header style={styles.header}>
        <div className="container" style={styles.inner}>
          {/* Logo */}
          <Link to="/" style={styles.logo}>
            <span style={styles.logoIcon}>🛍</span>
            <span style={styles.logoText}>ShopAI</span>
          </Link>

          {/* Search */}
          <form onSubmit={handleSearch} style={styles.searchForm}>
            <input
              className="input"
              style={styles.searchInput}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search products, brands, categories…"
            />
            <button type="submit" className="btn btn-primary" style={styles.searchBtn}>
              🔍
            </button>
          </form>

          {/* Actions */}
          <nav style={styles.nav}>
            <Link to="/products" style={styles.navLink}>Browse</Link>
            <Link to="/inventory" style={styles.navLink}>Ops</Link>
            <Link to="/guardrails" style={styles.navLink}>Security</Link>

            {user ? (
              <>
                <Link to="/orders" style={styles.navLink}>My Orders</Link>
                <div style={styles.userMenu}>
                  <span style={styles.userName}>{user.first_name || user.email?.split('@')[0]}</span>
                  <button onClick={logout} style={styles.logoutBtn}>Sign out</button>
                </div>
              </>
            ) : (
              <Link to="/auth" className="btn btn-outline btn-sm">Sign in</Link>
            )}

            <button
              onClick={() => setCartOpen(true)}
              style={styles.cartBtn}
              aria-label="Open cart"
            >
              🛒
              {count > 0 && <span style={styles.cartBadge}>{count}</span>}
            </button>
          </nav>
        </div>
      </header>

      <CartDrawer open={cartOpen} onClose={() => setCartOpen(false)} />
    </>
  )
}

const styles = {
  header: {
    position: 'sticky', top: 0, zIndex: 100,
    background: 'rgba(255,255,255,.95)', backdropFilter: 'blur(8px)',
    borderBottom: '1px solid var(--border)',
    boxShadow: '0 2px 8px rgba(80,70,229,.06)',
  },
  inner: {
    display: 'flex', alignItems: 'center', gap: 16, height: 64,
  },
  logo: {
    display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
  },
  logoIcon: { fontSize: '1.5rem' },
  logoText: {
    fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)',
    letterSpacing: '-0.5px',
  },
  searchForm: {
    flex: 1, display: 'flex', gap: 8, maxWidth: 560,
  },
  searchInput: {
    flex: 1, height: 40, fontSize: '0.9rem',
  },
  searchBtn: {
    height: 40, padding: '0 16px', flexShrink: 0,
  },
  nav: {
    display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
  },
  navLink: {
    padding: '6px 12px', borderRadius: 'var(--radius)',
    fontSize: '0.9rem', fontWeight: 500, color: 'var(--muted)',
    transition: 'color var(--transition)',
  },
  userMenu: {
    display: 'flex', alignItems: 'center', gap: 8,
  },
  userName: {
    fontSize: '0.875rem', fontWeight: 600, color: 'var(--text)',
  },
  logoutBtn: {
    background: 'none', border: 'none', color: 'var(--muted)',
    fontSize: '0.8rem', padding: '4px 8px', borderRadius: 6,
    cursor: 'pointer',
  },
  cartBtn: {
    position: 'relative', background: 'none', border: 'none',
    fontSize: '1.4rem', padding: '4px 8px', lineHeight: 1,
  },
  cartBadge: {
    position: 'absolute', top: -2, right: -2,
    background: 'var(--accent)', color: '#fff',
    borderRadius: '999px', fontSize: '0.65rem', fontWeight: 700,
    minWidth: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '0 4px',
  },
}
