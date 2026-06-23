import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { productsApi } from '../api/index.js'
import ProductCard from '../components/ProductCard.jsx'

const CATEGORIES = [
  { label: 'Electronics',  icon: '📱', slug: 'Electronics' },
  { label: 'Clothing',     icon: '👕', slug: 'Clothing' },
  { label: 'Books',        icon: '📚', slug: 'Books' },
  { label: 'Home & Living',icon: '🏠', slug: 'Home' },
  { label: 'Sports',       icon: '⚽', slug: 'Sports' },
  { label: 'Beauty',       icon: '💄', slug: 'Beauty' },
  { label: 'Automotive',   icon: '🚗', slug: 'Automotive' },
  { label: 'Toys',         icon: '🧸', slug: 'Toys' },
]

export default function Home() {
  const [featured, setFeatured] = useState([])
  const [newArrivals, setNewArrivals] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    Promise.all([
      productsApi.list({ limit: 8, sort_by: 'rating', order: 'desc' }),
      productsApi.list({ limit: 8, sort_by: 'created_at', order: 'desc' }),
    ]).then(([feat, news]) => {
      setFeatured(feat.data.results || [])
      setNewArrivals(news.data.results || [])
    }).catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      {/* Hero */}
      <section style={styles.hero}>
        <div className="container" style={styles.heroInner}>
          <div style={styles.heroText}>
            <p style={styles.heroEyebrow}>AI-Powered Shopping</p>
            <h1 style={styles.heroHeadline}>
              Discover what you<br />
              <span style={styles.heroAccent}>actually</span> want
            </h1>
            <p style={styles.heroSub}>
              Smart search, personalised picks, and an AI assistant that helps you<br />
              find exactly what you're looking for — in seconds.
            </p>
            <div style={styles.heroCtas}>
              <button className="btn btn-accent btn-lg" onClick={() => navigate('/products')}>
                Shop Now
              </button>
              <button className="btn btn-outline btn-lg" onClick={() => navigate('/products?q=best+sellers')}>
                Best Sellers
              </button>
            </div>
          </div>
          <div style={styles.heroVisual}>
            <div style={styles.heroCard}>
              <div style={{ fontSize: '4rem', marginBottom: 12 }}>🛍</div>
              <div style={{ fontSize: '0.9rem', color: 'var(--muted)' }}>6,525+ products</div>
              <div style={{ fontSize: '0.9rem', color: 'var(--muted)' }}>AI-curated just for you</div>
            </div>
          </div>
        </div>
      </section>

      {/* Categories */}
      <section style={styles.section}>
        <div className="container">
          <h2 style={styles.sectionTitle}>Browse Categories</h2>
          <div style={styles.catGrid}>
            {CATEGORIES.map(cat => (
              <button
                key={cat.slug}
                style={styles.catCard}
                onClick={() => navigate(`/products?category=${encodeURIComponent(cat.slug)}`)}
              >
                <span style={styles.catIcon}>{cat.icon}</span>
                <span style={styles.catLabel}>{cat.label}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Featured */}
      <section style={styles.section}>
        <div className="container">
          <div style={styles.sectionHeader}>
            <h2 style={styles.sectionTitle}>Top Rated Products</h2>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/products?sort_by=rating')}>
              View all →
            </button>
          </div>
          {loading ? (
            <div className="spinner-wrap"><div className="spinner" /></div>
          ) : (
            <div className="product-grid">
              {featured.map(p => <ProductCard key={p.id} product={p} />)}
            </div>
          )}
        </div>
      </section>

      {/* New Arrivals */}
      <section style={{ ...styles.section, background: 'var(--surface)', padding: '40px 0' }}>
        <div className="container">
          <div style={styles.sectionHeader}>
            <h2 style={styles.sectionTitle}>New Arrivals</h2>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/products')}>
              View all →
            </button>
          </div>
          {loading ? (
            <div className="spinner-wrap"><div className="spinner" /></div>
          ) : (
            <div className="product-grid">
              {newArrivals.map(p => <ProductCard key={p.id} product={p} />)}
            </div>
          )}
        </div>
      </section>

      {/* AI Feature banner */}
      <section style={styles.aiSection}>
        <div className="container" style={styles.aiInner}>
          <div style={{ fontSize: '3rem' }}>🤖</div>
          <div>
            <h2 style={{ marginBottom: 8 }}>Meet your AI Shopping Assistant</h2>
            <p style={{ color: 'var(--muted)', maxWidth: 480 }}>
              Ask natural questions like "show me running shoes under ₹3000" or
              "what's a good gift for a 10-year-old?" — the chat widget is always available.
            </p>
          </div>
          <button
            className="btn btn-primary btn-lg"
            style={{ flexShrink: 0 }}
            onClick={() => document.querySelector('[aria-label="Open chat assistant"]')?.click()}
          >
            Try it now →
          </button>
        </div>
      </section>
    </div>
  )
}

const styles = {
  hero: {
    background: 'linear-gradient(135deg, #EEF0FF 0%, #F5F4FF 50%, #FFF4F0 100%)',
    padding: '60px 0',
  },
  heroInner: {
    display: 'flex', alignItems: 'center', gap: 40, flexWrap: 'wrap',
  },
  heroText: { flex: 1, minWidth: 300 },
  heroEyebrow: {
    fontSize: '0.85rem', fontWeight: 700, color: 'var(--primary)',
    textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 12,
  },
  heroHeadline: { fontSize: '3rem', fontWeight: 900, lineHeight: 1.15, marginBottom: 16 },
  heroAccent: {
    background: 'linear-gradient(90deg, var(--primary), var(--accent))',
    WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
  },
  heroSub: { color: 'var(--muted)', lineHeight: 1.7, marginBottom: 28, fontSize: '1rem' },
  heroCtas: { display: 'flex', gap: 12, flexWrap: 'wrap' },
  heroVisual: { flex: 0, display: 'flex', justifyContent: 'center' },
  heroCard: {
    background: '#fff', borderRadius: 20, padding: '32px 40px',
    boxShadow: 'var(--shadow-lg)', textAlign: 'center',
    border: '1px solid var(--border)',
  },
  section: { padding: '48px 0' },
  sectionHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  sectionTitle: { fontSize: '1.4rem', fontWeight: 700 },
  catGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 12,
  },
  catCard: {
    background: 'var(--surface)', border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius-lg)', padding: '20px 12px',
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
    cursor: 'pointer', transition: 'all var(--transition)',
  },
  catIcon: { fontSize: '2rem' },
  catLabel: { fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' },
  aiSection: {
    background: 'linear-gradient(135deg, var(--primary) 0%, #3D33D4 100%)',
    padding: '40px 0',
    color: '#fff',
  },
  aiInner: {
    display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap',
  },
}
