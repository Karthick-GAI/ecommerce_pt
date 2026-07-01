import { useCart } from '../store/CartContext.jsx'
import { useNavigate } from 'react-router-dom'
import { productImageUrl } from '../utils/productImage.js'

export default function CartDrawer({ open, onClose }) {
  const { items, count, subtotal, updateQty, removeItem, loading } = useCart()
  const navigate = useNavigate()

  function goCheckout() {
    onClose()
    navigate('/checkout')
  }

  return (
    <>
      {open && <div style={styles.overlay} onClick={onClose} />}
      <aside style={{ ...styles.drawer, right: open ? 0 : '-420px' }}>
        <div style={styles.header}>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>
            Cart {count > 0 && <span style={styles.countChip}>{count}</span>}
          </h2>
          <button onClick={onClose} style={styles.closeBtn}>✕</button>
        </div>

        <div style={styles.body}>
          {items.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize: '3rem', marginBottom: 12 }}>🛒</div>
              <h3>Your cart is empty</h3>
              <p style={{ fontSize: '0.9rem' }}>Add products to get started</p>
            </div>
          ) : (
            items.map(item => (
              <div key={item.product_id} style={styles.item}>
                <img
                  src={item.image_url || productImageUrl({ id: item.product_id, category: item.category, subcategory: item.subcategory }, 80, 80)}
                  alt={item.product_name}
                  style={styles.itemImg}
                />
                <div style={styles.itemInfo}>
                  <p style={styles.itemName}>{item.product_name}</p>
                  <p style={styles.itemPrice}>₹{Number(item.unit_price).toLocaleString('en-IN')}</p>
                  <div style={styles.qtyRow}>
                    <button style={styles.qtyBtn} onClick={() => updateQty(item.product_id, item.quantity - 1)}>−</button>
                    <span style={styles.qtyVal}>{item.quantity}</span>
                    <button style={styles.qtyBtn} onClick={() => updateQty(item.product_id, item.quantity + 1)}>+</button>
                    <button style={styles.removeBtn} onClick={() => removeItem(item.product_id)}>Remove</button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {items.length > 0 && (
          <div style={styles.footer}>
            <div style={styles.subtotalRow}>
              <span>Subtotal ({count} items)</span>
              <span style={{ fontWeight: 700 }}>₹{Number(subtotal).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
            </div>
            <button
              className="btn btn-accent btn-full btn-lg"
              onClick={goCheckout}
              disabled={loading}
            >
              Proceed to Checkout →
            </button>
          </div>
        )}
      </aside>
    </>
  )
}

const styles = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,.4)',
    zIndex: 200, backdropFilter: 'blur(2px)',
  },
  drawer: {
    position: 'fixed', top: 0, bottom: 0, width: 400,
    background: 'var(--surface)', zIndex: 201,
    boxShadow: '-8px 0 32px rgba(0,0,0,.12)',
    transition: 'right .3s cubic-bezier(.4,0,.2,1)',
    display: 'flex', flexDirection: 'column',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '16px 20px', borderBottom: '1px solid var(--border)',
  },
  countChip: {
    background: 'var(--primary)', color: '#fff',
    borderRadius: 999, padding: '0 8px', fontSize: '0.75rem',
    marginLeft: 8,
  },
  closeBtn: {
    background: 'none', border: 'none', fontSize: '1.1rem',
    color: 'var(--muted)', padding: 6, lineHeight: 1,
  },
  body: {
    flex: 1, overflowY: 'auto', padding: '12px 20px',
    display: 'flex', flexDirection: 'column', gap: 12,
  },
  item: {
    display: 'flex', gap: 12, padding: '12px 0',
    borderBottom: '1px solid var(--border)',
  },
  itemImg: {
    width: 72, height: 72, objectFit: 'cover',
    borderRadius: 8, flexShrink: 0, background: 'var(--ground)',
  },
  itemInfo: { flex: 1, display: 'flex', flexDirection: 'column', gap: 4 },
  itemName: { fontSize: '0.875rem', fontWeight: 500, lineHeight: 1.4 },
  itemPrice: { fontSize: '0.9rem', fontWeight: 700, color: 'var(--primary)' },
  qtyRow: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 },
  qtyBtn: {
    width: 28, height: 28, border: '1.5px solid var(--border)',
    borderRadius: 6, background: 'none', fontWeight: 700, fontSize: '1rem',
  },
  qtyVal: { fontSize: '0.9rem', fontWeight: 600, minWidth: 20, textAlign: 'center' },
  removeBtn: {
    background: 'none', border: 'none', color: 'var(--danger)',
    fontSize: '0.8rem', cursor: 'pointer', marginLeft: 4,
  },
  footer: {
    padding: '16px 20px', borderTop: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column', gap: 14,
  },
  subtotalRow: {
    display: 'flex', justifyContent: 'space-between',
    fontSize: '1rem',
  },
}
