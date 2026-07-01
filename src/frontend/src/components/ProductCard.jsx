import { useNavigate } from 'react-router-dom'
import { useCart } from '../store/CartContext.jsx'
import { useToast } from '../store/ToastContext.jsx'
import { productImageUrl } from '../utils/productImage.js'

export default function ProductCard({ product }) {
  const { addItem } = useCart()
  const toast = useToast()
  const navigate = useNavigate()

  const discount = product.discount_pct ?? 0
  const finalPrice = product.effective_price ?? product.price
  const stars = Math.round(product.rating_avg ?? 0)

  async function handleAdd(e) {
    e.stopPropagation()
    await addItem(product, 1)
    toast(`${product.name.slice(0, 30)}… added to cart`, 'success')
  }

  return (
    <div
      className="card"
      style={styles.card}
      onClick={() => navigate(`/products/${product.id}`)}
    >
      <div style={styles.imgWrap}>
        <img
          src={productImageUrl(product)}
          alt={product.name}
          style={styles.img}
          loading="lazy"
        />
        {discount > 0 && (
          <span style={styles.discountBadge}>{Math.round(discount)}% OFF</span>
        )}
        {!product.in_stock && (
          <span style={styles.outBadge}>Out of Stock</span>
        )}
      </div>

      <div style={styles.body}>
        <p style={styles.brand}>{product.brand}</p>
        <p style={styles.name}>{product.name}</p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
          <div className="stars">{'★'.repeat(stars)}{'☆'.repeat(5 - stars)}</div>
          {product.rating_count > 0 && (
            <span style={styles.ratingCount}>({product.rating_count})</span>
          )}
        </div>

        <div className="price-block" style={{ marginTop: 8 }}>
          <span className="price-final">₹{Number(finalPrice).toLocaleString('en-IN')}</span>
          {discount > 0 && (
            <span className="price-original">₹{Number(product.price).toLocaleString('en-IN')}</span>
          )}
        </div>
      </div>

      <div style={styles.footer}>
        <button
          className="btn btn-primary btn-full"
          style={{ fontSize: '0.85rem', padding: '8px' }}
          onClick={handleAdd}
          disabled={!product.in_stock}
        >
          {product.in_stock ? '+ Add to Cart' : 'Out of Stock'}
        </button>
      </div>
    </div>
  )
}

const styles = {
  card: { cursor: 'pointer', display: 'flex', flexDirection: 'column' },
  imgWrap: {
    position: 'relative', background: 'var(--ground)',
    paddingBottom: '75%', overflow: 'hidden',
  },
  img: {
    position: 'absolute', inset: 0, width: '100%', height: '100%',
    objectFit: 'cover', transition: 'transform .3s',
  },
  discountBadge: {
    position: 'absolute', top: 10, left: 10,
    background: 'var(--accent)', color: '#fff',
    borderRadius: 6, padding: '3px 8px', fontSize: '0.75rem', fontWeight: 700,
  },
  outBadge: {
    position: 'absolute', top: 10, right: 10,
    background: 'rgba(0,0,0,.6)', color: '#fff',
    borderRadius: 6, padding: '3px 8px', fontSize: '0.75rem',
  },
  body: { padding: '12px 14px', flex: 1 },
  brand: { fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.5px' },
  name: { fontSize: '0.9rem', fontWeight: 600, lineHeight: 1.4, marginTop: 2,
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' },
  ratingCount: { fontSize: '0.75rem', color: 'var(--muted)' },
  footer: { padding: '0 14px 14px' },
}
