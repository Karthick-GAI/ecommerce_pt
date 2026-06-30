import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { productsApi, recommendationsApi } from '../api/index.js'
import { useCart } from '../store/CartContext.jsx'
import { useToast } from '../store/ToastContext.jsx'
import ProductCard from '../components/ProductCard.jsx'

function normalizeRec(item) {
  const disc = (item.discount_pct || 0) / 100
  return {
    id:              item.product_id,
    name:            item.name,
    brand:           item.brand || '',
    price:           item.price || 0,
    effective_price: item.price * (1 - disc),
    discount_pct:    item.discount_pct || 0,
    rating_avg:      item.rating_avg || 0,
    rating_count:    0,
    in_stock:        (item.stock ?? 1) > 0,
    primary_image:   null,
  }
}

export default function ProductDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { addItem } = useCart()
  const toast = useToast()
  const [product, setProduct] = useState(null)
  const [loading, setLoading] = useState(true)
  const [qty, setQty] = useState(1)
  const [adding, setAdding] = useState(false)
  const [similar, setSimilar] = useState([])
  const [boughtTogether, setBoughtTogether] = useState([])

  useEffect(() => {
    productsApi.get(id).then(r => setProduct(r.data)).catch(() => navigate('/products')).finally(() => setLoading(false))
    // Load recommendation sections in parallel, silently ignore failures
    recommendationsApi.similar(id, { strategy: 'both', limit: 6 })
      .then(r => setSimilar((r.data.similar || []).map(normalizeRec)))
      .catch(() => {})
    recommendationsApi.boughtTogether(id, { limit: 6 })
      .then(r => setBoughtTogether((r.data.bought_together || []).map(normalizeRec)))
      .catch(() => {})
  }, [id])

  async function handleAdd() {
    setAdding(true)
    try {
      await addItem(product, qty)
      toast(`${product.name.slice(0, 30)}… added to cart`, 'success')
    } catch {
      toast('Could not add item — please try again', 'error')
    } finally {
      setAdding(false)
    }
  }

  async function handleBuyNow() {
    await handleAdd()
    navigate('/checkout')
  }

  if (loading) return <div className="spinner-wrap"><div className="spinner" /></div>
  if (!product) return null

  const discount    = product.discount_pct ?? 0
  const finalPrice  = product.effective_price ?? product.price
  const stars       = Math.round(product.rating_avg ?? 0)
  const savings     = product.price - finalPrice

  return (
    <div className="page">
      <div className="container">
        {/* Breadcrumb */}
        <div style={styles.breadcrumb}>
          <button style={styles.crumb} onClick={() => navigate('/')}>Home</button>
          <span style={styles.crumbSep}>/</span>
          <button style={styles.crumb} onClick={() => navigate(`/products?category=${product.category}`)}>
            {product.category}
          </button>
          <span style={styles.crumbSep}>/</span>
          <span style={styles.crumbCurrent}>{product.name}</span>
        </div>

        <div style={styles.grid}>
          {/* Image */}
          <div style={styles.imgSection}>
            <div style={styles.imgWrap}>
              <img
                src={product.primary_image || `https://picsum.photos/seed/${product.id}/600/500`}
                alt={product.name}
                style={styles.img}
              />
              {discount > 0 && (
                <span style={styles.discountBadge}>{Math.round(discount)}% OFF</span>
              )}
            </div>
          </div>

          {/* Info */}
          <div style={styles.infoSection}>
            <div style={styles.brandRow}>
              <span className="badge badge-primary">{product.brand}</span>
              <span className="badge badge-accent">{product.category}</span>
            </div>

            <h1 style={styles.title}>{product.name}</h1>

            {/* Rating */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <div className="stars" style={{ fontSize: '1rem' }}>
                {'★'.repeat(stars)}{'☆'.repeat(5 - stars)}
              </div>
              <span style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
                {product.rating_avg?.toFixed(1)} ({product.rating_count} reviews)
              </span>
            </div>

            {/* Price */}
            <div style={styles.priceSection}>
              <div className="price-block">
                <span style={{ fontSize: '2rem', fontWeight: 800 }}>
                  ₹{Number(finalPrice).toLocaleString('en-IN')}
                </span>
                {discount > 0 && (
                  <>
                    <span className="price-original" style={{ fontSize: '1.1rem' }}>
                      ₹{Number(product.price).toLocaleString('en-IN')}
                    </span>
                    <span className="price-discount" style={{ fontSize: '1rem' }}>
                      Save ₹{Number(savings).toLocaleString('en-IN')}
                    </span>
                  </>
                )}
              </div>
              <p style={{ color: 'var(--muted)', fontSize: '0.85rem', marginTop: 4 }}>
                Inclusive of all taxes
              </p>
            </div>

            {/* Stock status */}
            <div style={{ marginTop: 4 }}>
              {product.in_stock ? (
                <span style={styles.inStock}>✓ In Stock</span>
              ) : (
                <span style={styles.outOfStock}>✕ Out of Stock</span>
              )}
            </div>

            <div className="divider" />

            {/* Description */}
            {product.description && (
              <p style={styles.description}>{product.description}</p>
            )}

            {/* Tags */}
            {product.tags?.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                {product.tags.map(t => (
                  <span key={t} className="badge badge-primary">{t}</span>
                ))}
              </div>
            )}

            <div className="divider" />

            {/* Qty + CTA */}
            <div style={styles.ctaSection}>
              <div style={styles.qtyRow}>
                <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>Qty:</span>
                <button style={styles.qtyBtn} onClick={() => setQty(q => Math.max(1, q - 1))}>−</button>
                <span style={styles.qtyVal}>{qty}</span>
                <button style={styles.qtyBtn} onClick={() => setQty(q => q + 1)}>+</button>
              </div>
              <div style={styles.btnRow}>
                <button
                  className="btn btn-outline btn-lg"
                  style={{ flex: 1 }}
                  onClick={handleAdd}
                  disabled={!product.in_stock || adding}
                >
                  {adding ? '…' : 'Add to Cart'}
                </button>
                <button
                  className="btn btn-accent btn-lg"
                  style={{ flex: 1 }}
                  onClick={handleBuyNow}
                  disabled={!product.in_stock || adding}
                >
                  Buy Now
                </button>
              </div>
            </div>

            {/* Trust signals */}
            <div style={styles.trust}>
              {['🚚 Free delivery on orders ₹500+', '↩ 7-day easy returns', '✓ Secure payments'].map(t => (
                <span key={t} style={styles.trustItem}>{t}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Similar Products */}
      {similar.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 40, marginTop: 8 }}>
          <h2 style={{ marginBottom: 20 }}>Similar Products</h2>
          <div className="product-grid">
            {similar.map(p => <ProductCard key={p.id} product={p} />)}
          </div>
        </div>
      )}

      {/* Bought Together */}
      {boughtTogether.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 40, marginTop: 32 }}>
          <h2 style={{ marginBottom: 4 }}>Frequently Bought Together</h2>
          <p style={{ color: 'var(--muted)', fontSize: '0.875rem', marginBottom: 20 }}>
            Customers who bought this also purchased
          </p>
          <div className="product-grid">
            {boughtTogether.map(p => <ProductCard key={p.id} product={p} />)}
          </div>
        </div>
      )}
    </div>
  )
}

const styles = {
  breadcrumb: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 24, flexWrap: 'wrap' },
  crumb: { background: 'none', border: 'none', color: 'var(--primary)', fontSize: '0.875rem', cursor: 'pointer' },
  crumbSep: { color: 'var(--muted)', fontSize: '0.75rem' },
  crumbCurrent: { color: 'var(--muted)', fontSize: '0.875rem',
    maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  grid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48,
    alignItems: 'flex-start',
  },
  imgSection: {},
  imgWrap: {
    position: 'relative', borderRadius: 'var(--radius-lg)', overflow: 'hidden',
    background: 'var(--ground)', border: '1px solid var(--border)',
  },
  img: { width: '100%', display: 'block', maxHeight: 460, objectFit: 'contain' },
  discountBadge: {
    position: 'absolute', top: 16, left: 16,
    background: 'var(--accent)', color: '#fff',
    borderRadius: 8, padding: '6px 12px', fontSize: '0.875rem', fontWeight: 700,
  },
  infoSection: {},
  brandRow: { display: 'flex', gap: 8, marginBottom: 12 },
  title: { fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.4 },
  priceSection: {
    background: 'linear-gradient(135deg, rgba(80,70,229,.06), rgba(255,120,73,.06))',
    borderRadius: 'var(--radius)', padding: '16px 20px', marginTop: 16,
  },
  inStock: { color: 'var(--success)', fontWeight: 600, fontSize: '0.9rem' },
  outOfStock: { color: 'var(--danger)', fontWeight: 600, fontSize: '0.9rem' },
  description: { color: 'var(--muted)', lineHeight: 1.7, fontSize: '0.925rem' },
  ctaSection: { display: 'flex', flexDirection: 'column', gap: 14 },
  qtyRow: { display: 'flex', alignItems: 'center', gap: 12 },
  qtyBtn: {
    width: 34, height: 34, border: '1.5px solid var(--border)',
    borderRadius: 8, background: 'none', fontWeight: 700, fontSize: '1.1rem',
    cursor: 'pointer',
  },
  qtyVal: { fontSize: '1rem', fontWeight: 700, minWidth: 24, textAlign: 'center' },
  btnRow: { display: 'flex', gap: 12 },
  trust: { display: 'flex', flexDirection: 'column', gap: 6, marginTop: 16 },
  trustItem: { fontSize: '0.825rem', color: 'var(--muted)' },
}
