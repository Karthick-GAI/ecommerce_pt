import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { productsApi } from '../api/index.js'
import ProductCard from '../components/ProductCard.jsx'

const SORT_OPTIONS = [
  { value: 'rating',       label: 'Top Rated' },
  { value: 'price_asc',    label: 'Price: Low to High' },
  { value: 'price_desc',   label: 'Price: High to Low' },
  { value: 'created_at',   label: 'Newest First' },
  { value: 'discount',     label: 'Best Discount' },
]

const CATEGORIES = [
  'Electronics', 'Clothing', 'Books', 'Home & Kitchen', 'Sports & Fitness',
  'Beauty', 'Baby Products', 'Stationery', 'Toys & Games',
]

function ParsedFilterBanner({ filters }) {
  if (!filters) return null
  const chips = []
  if (filters.category)    chips.push({ label: 'Category', value: filters.category })
  if (filters.subcategory) chips.push({ label: 'Type',     value: filters.subcategory })
  if (filters.brand)       chips.push({ label: 'Brand',    value: filters.brand })
  if (filters.max_price)   chips.push({ label: 'Max price', value: `₹${filters.max_price.toLocaleString()}` })
  if (filters.min_price)   chips.push({ label: 'Min price', value: `₹${filters.min_price.toLocaleString()}` })
  if (filters.keywords && filters.keywords !== filters.query)
    chips.push({ label: 'Keywords', value: filters.keywords })
  if (chips.length === 0)  return null

  return (
    <div style={styles.filterBanner}>
      <span style={styles.filterBannerIcon}>✨</span>
      <span style={styles.filterBannerLabel}>AI understood:</span>
      {chips.map(c => (
        <span key={c.label} style={styles.filterChip}>
          <span style={styles.filterChipKey}>{c.label}</span>
          <span style={styles.filterChipVal}>{c.value}</span>
        </span>
      ))}
    </div>
  )
}

export default function Products() {
  const [params, setParams] = useSearchParams()
  const [products, setProducts]       = useState([])
  const [total, setTotal]             = useState(0)
  const [loading, setLoading]         = useState(true)
  const [page, setPage]               = useState(1)
  const [parsedFilters, setParsedFilters] = useState(null)
  const [searchMode, setSearchMode]   = useState('smart') // 'smart' | 'keyword'

  const q        = params.get('q') || ''
  const category = params.get('category') || ''
  const sortBy   = params.get('sort_by') || 'rating'
  const minPrice = params.get('min_price') || ''
  const maxPrice = params.get('max_price') || ''

  const load = useCallback(async (pg = 1) => {
    setLoading(true)
    setParsedFilters(null)
    try {
      const apiParams = { page: pg, limit: 24 }
      if (category) apiParams.category = category
      if (minPrice) apiParams.min_price = minPrice
      if (maxPrice) apiParams.max_price = maxPrice

      let res
      if (!q) {
        apiParams.sort_by = sortBy
        res = await productsApi.list(apiParams)
      } else if (searchMode === 'smart') {
        res = await productsApi.semanticSearch(q, { page: pg, limit: 24 })
        if (res.data.parsed_filters) setParsedFilters(res.data.parsed_filters)
      } else {
        apiParams.q = q
        apiParams.sort_by = sortBy
        res = await productsApi.search(q, apiParams)
      }

      const data = res.data
      setProducts(data.results || data.products || [])
      setTotal(data.total || 0)
      setPage(pg)
    } catch {
      setProducts([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [q, category, sortBy, minPrice, maxPrice, searchMode])

  useEffect(() => { load(1) }, [load])

  function setFilter(key, val) {
    const next = new URLSearchParams(params)
    if (val) next.set(key, val)
    else next.delete(key)
    next.delete('page')
    setParams(next)
  }

  const totalPages = Math.ceil(total / 24)

  return (
    <div className="page">
      <div className="container">
        {/* Header row */}
        <div style={styles.topRow}>
          <div>
            <h1 style={{ fontSize: '1.4rem' }}>
              {q ? `Results for "${q}"` : category || 'All Products'}
            </h1>
            {!loading && <p style={{ color: 'var(--muted)', fontSize: '0.875rem', marginTop: 4 }}>{total.toLocaleString()} products</p>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Search mode toggle — only shown when there's a query */}
            {q && (
              <div style={styles.modeToggle}>
                <button
                  style={{ ...styles.modeBtn, ...(searchMode === 'smart' ? styles.modeBtnActive : {}) }}
                  onClick={() => setSearchMode('smart')}
                  title="Natural language search — AI understands intent and finds semantically similar products"
                >
                  ✨ Smart Search
                </button>
                <button
                  style={{ ...styles.modeBtn, ...(searchMode === 'keyword' ? styles.modeBtnActive : {}) }}
                  onClick={() => setSearchMode('keyword')}
                  title="Exact keyword match across name, brand, description"
                >
                  🔤 Keyword
                </button>
              </div>
            )}
            {searchMode === 'keyword' && (
              <select
                className="input"
                style={{ width: 'auto', height: 40 }}
                value={sortBy}
                onChange={e => setFilter('sort_by', e.target.value)}
              >
                {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            )}
          </div>
        </div>

        {/* AI parsed-filter banner */}
        {searchMode === 'smart' && <ParsedFilterBanner filters={parsedFilters} />}

        <div style={styles.layout}>
          {/* Sidebar filters */}
          <aside style={styles.sidebar}>
            <div style={styles.filterBlock}>
              <h3 style={styles.filterTitle}>Category</h3>
              <div style={styles.filterList}>
                <button
                  style={{ ...styles.filterItem, ...(category === '' ? styles.filterItemActive : {}) }}
                  onClick={() => setFilter('category', '')}
                >
                  All
                </button>
                {CATEGORIES.map(c => (
                  <button
                    key={c}
                    style={{ ...styles.filterItem, ...(category === c ? styles.filterItemActive : {}) }}
                    onClick={() => setFilter('category', c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            <div style={styles.filterBlock}>
              <h3 style={styles.filterTitle}>Price Range (₹)</h3>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  className="input"
                  placeholder="Min"
                  type="number"
                  value={minPrice}
                  onChange={e => setFilter('min_price', e.target.value)}
                  style={{ flex: 1 }}
                />
                <input
                  className="input"
                  placeholder="Max"
                  type="number"
                  value={maxPrice}
                  onChange={e => setFilter('max_price', e.target.value)}
                  style={{ flex: 1 }}
                />
              </div>
            </div>

            {(q || category || minPrice || maxPrice) && (
              <button
                className="btn btn-ghost btn-full"
                onClick={() => setParams({})}
              >
                Clear Filters
              </button>
            )}
          </aside>

          {/* Product grid */}
          <div style={{ flex: 1 }}>
            {loading ? (
              <div className="spinner-wrap"><div className="spinner" /></div>
            ) : products.length === 0 ? (
              <div className="empty-state">
                <div style={{ fontSize: '3rem', marginBottom: 12 }}>🔍</div>
                <h3>No products found</h3>
                <p>Try adjusting your filters or search term</p>
              </div>
            ) : (
              <>
                <div className="product-grid">
                  {products.map(p => <ProductCard key={p.id} product={p} />)}
                </div>

                {totalPages > 1 && (
                  <div style={styles.pagination}>
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={page === 1}
                      onClick={() => load(page - 1)}
                    >
                      ← Prev
                    </button>
                    <span style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
                      Page {page} of {totalPages}
                    </span>
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={page === totalPages}
                      onClick={() => load(page + 1)}
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  topRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: 24, flexWrap: 'wrap', gap: 12,
  },
  layout: { display: 'flex', gap: 24, alignItems: 'flex-start' },
  sidebar: {
    width: 220, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 24,
    position: 'sticky', top: 80,
  },
  filterBlock: { display: 'flex', flexDirection: 'column', gap: 10 },
  filterTitle: { fontSize: '0.875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.5px', color: 'var(--muted)' },
  filterList: { display: 'flex', flexDirection: 'column', gap: 4 },
  filterItem: {
    background: 'none', border: 'none', textAlign: 'left',
    padding: '6px 10px', borderRadius: 6, fontSize: '0.875rem',
    cursor: 'pointer', color: 'var(--text)',
  },
  filterItemActive: {
    background: 'rgba(80,70,229,.1)', color: 'var(--primary)', fontWeight: 600,
  },
  pagination: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    gap: 16, marginTop: 32, paddingTop: 24, borderTop: '1px solid var(--border)',
  },
  modeToggle: {
    display: 'flex', borderRadius: 8, overflow: 'hidden',
    border: '1px solid var(--border)',
  },
  modeBtn: {
    padding: '8px 14px', background: 'none', border: 'none',
    fontSize: '0.82rem', fontWeight: 500, cursor: 'pointer',
    color: 'var(--muted)', whiteSpace: 'nowrap',
    transition: 'background .15s, color .15s',
  },
  modeBtnActive: {
    background: 'var(--primary)', color: '#fff', fontWeight: 700,
  },
  filterBanner: {
    display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8,
    background: 'rgba(80,70,229,.06)', border: '1px solid rgba(80,70,229,.18)',
    borderRadius: 10, padding: '10px 16px', marginBottom: 20,
    fontSize: '0.85rem',
  },
  filterBannerIcon: { fontSize: '1rem' },
  filterBannerLabel: { fontWeight: 700, color: 'var(--primary)', marginRight: 4 },
  filterChip: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    background: 'rgba(80,70,229,.12)', borderRadius: 999,
    padding: '2px 10px', fontSize: '0.8rem',
  },
  filterChipKey: { color: 'var(--muted)', fontWeight: 500 },
  filterChipVal: { color: 'var(--primary)', fontWeight: 700 },
}
