import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { recommendationsApi, interactionsApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'
import ProductCard from '../components/ProductCard.jsx'

const CATEGORIES = [
  { label: 'Electronics',   icon: '📱', slug: 'Electronics' },
  { label: 'Clothing',      icon: '👕', slug: 'Clothing' },
  { label: 'Books',         icon: '📚', slug: 'Books' },
  { label: 'Home & Living', icon: '🏠', slug: 'Home' },
  { label: 'Sports',        icon: '⚽', slug: 'Sports' },
  { label: 'Beauty',        icon: '💄', slug: 'Beauty' },
  { label: 'Automotive',    icon: '🚗', slug: 'Automotive' },
  { label: 'Toys',          icon: '🧸', slug: 'Toys' },
]

// Converts recommendation engine item → ProductCard prop shape
function normalize(item) {
  const disc = (item.discount_pct || 0) / 100
  return {
    id:             item.product_id,
    name:           item.name,
    brand:          item.brand || '',
    category:       item.category || '',
    subcategory:    item.subcategory || '',
    price:          item.price || 0,
    effective_price: item.price * (1 - disc),
    discount_pct:   item.discount_pct || 0,
    rating_avg:     item.rating_avg || 0,
    rating_count:   0,
    in_stock:       (item.stock ?? 1) > 0,
  }
}

function RecSection({ title, badge, items, viewAllPath, onProductClick }) {
  const navigate = useNavigate()
  if (!items || items.length === 0) return null
  return (
    <section style={s.section}>
      <div className="container">
        <div style={s.sectionHeader}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h2 style={s.sectionTitle}>{title}</h2>
            {badge && <span style={s.badge}>{badge}</span>}
          </div>
          {viewAllPath && (
            <button className="btn btn-ghost btn-sm" onClick={() => navigate(viewAllPath)}>
              View all →
            </button>
          )}
        </div>
        <div className="product-grid">
          {items.map(p => (
            <div key={p.id} onClick={() => onProductClick?.(p.id)}>
              <ProductCard product={p} />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [sections, setSections] = useState([])   // [{title, badge, items}]
  const [loading, setLoading]   = useState(true)

  function handleProductClick(productId) {
    if (user?.id) {
      interactionsApi.log({
        customer_id: user.id,
        product_id: productId,
        interaction_type: 'click',
        source: 'homepage',
      }).catch(() => {})
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    async function load() {
      // If user is logged in, attempt personalised homepage feed first
      if (user?.id) {
        try {
          const res = await recommendationsApi.homepage(user.id)
          const personalSections = (res.data.sections || [])
            .filter(sec => (sec.products || []).length > 0)
            .map(sec => ({
              title: sec.title,
              badge: 'For You',
              items: (sec.products || []).slice(0, 8).map(normalize),
            }))
          if (!cancelled && personalSections.length > 0) {
            setSections(personalSections)
            setLoading(false)
            return
          }
        } catch { /* fall through to global */ }
      }

      // Global discovery — works for everyone
      try {
        const [trendRes, dealRes, arrivalRes, topViewedRes] = await Promise.all([
          recommendationsApi.trending({ days: 30, limit: 8 }),
          recommendationsApi.deals({ limit: 8 }),
          recommendationsApi.newArrivals({ limit: 8 }),
          recommendationsApi.topViewed({ days: 7, limit: 8 }),
        ])
        if (cancelled) return
        setSections([
          {
            title: 'Trending Now',
            badge: 'Hot',
            items: (trendRes.data.trending || []).map(normalize),
            viewAllPath: '/products',
          },
          {
            title: 'Most Viewed',
            badge: 'Popular',
            items: (topViewedRes.data.top_viewed || []).map(normalize),
            viewAllPath: '/products',
          },
          {
            title: 'Top Deals',
            badge: 'Sale',
            items: (dealRes.data.deals || []).map(normalize),
            viewAllPath: '/products',
          },
          {
            title: 'New Arrivals',
            badge: null,
            items: (arrivalRes.data.products || []).map(normalize),
            viewAllPath: '/products',
          },
        ])
      } catch {
        setSections([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [user?.id])

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
              Smart search, personalised picks, and an AI assistant that helps you
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

      {/* Recommendation sections */}
      {loading ? (
        <div className="spinner-wrap"><div className="spinner" /></div>
      ) : (
        sections.map((sec, i) => (
          <div key={i} style={i % 2 === 1 ? { background: 'var(--surface)' } : {}}>
            <RecSection
              title={sec.title}
              badge={sec.badge}
              items={sec.items}
              viewAllPath={sec.viewAllPath}
              onProductClick={handleProductClick}
            />
          </div>
        ))
      )}

      {/* AI banner */}
      <section style={styles.aiSection}>
        <div className="container" style={styles.aiInner}>
          <div style={{ fontSize: '3rem' }}>🤖</div>
          <div>
            <h2 style={{ marginBottom: 8 }}>Meet your AI Shopping Assistant</h2>
            <p style={{ color: 'rgba(255,255,255,.75)', maxWidth: 480 }}>
              Ask natural questions like "show me running shoes under ₹3000" or
              "what's a good gift for a 10-year-old?" — the chat widget is always available.
            </p>
          </div>
          <button
            className="btn btn-primary btn-lg"
            style={{ flexShrink: 0, background: '#fff', color: 'var(--primary)' }}
            onClick={() => document.querySelector('[aria-label="Open chat assistant"]')?.click()}
          >
            Try it now →
          </button>
        </div>
      </section>
    </div>
  )
}

const s = {
  section: { padding: '48px 0' },
  sectionHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  sectionTitle: { fontSize: '1.4rem', fontWeight: 700 },
  badge: {
    fontSize: '0.7rem', fontWeight: 800, padding: '3px 9px',
    borderRadius: 20, background: 'var(--accent)', color: '#fff',
    letterSpacing: '.04em', textTransform: 'uppercase',
  },
}

const styles = {
  hero: {
    background: 'linear-gradient(135deg, #EEF0FF 0%, #F5F4FF 50%, #FFF4F0 100%)',
    padding: '60px 0',
  },
  heroInner: { display: 'flex', alignItems: 'center', gap: 40, flexWrap: 'wrap' },
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
    boxShadow: 'var(--shadow-lg)', textAlign: 'center', border: '1px solid var(--border)',
  },
  section: { padding: '48px 0' },
  sectionTitle: { fontSize: '1.4rem', fontWeight: 700, marginBottom: 20 },
  catGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 },
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
    padding: '40px 0', color: '#fff',
  },
  aiInner: { display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' },
}
