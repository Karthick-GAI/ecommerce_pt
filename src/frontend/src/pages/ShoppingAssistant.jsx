import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { assistantApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'

const QUICK_PROMPTS = [
  { label: 'Recommend a laptop',        text: 'Recommend a good laptop for college under ₹60,000' },
  { label: 'Wireless earphones',         text: 'Which wireless earphones are in stock under ₹2,000?' },
  { label: 'Compare smartphones',        text: 'Compare the best smartphones between ₹20,000 and ₹40,000' },
  { label: 'Skincare for dry skin',      text: 'What skincare products do you have for dry skin?' },
  { label: 'Best rated clothing',        text: 'Show me the best rated women\'s dresses' },
  { label: 'Books on finance',           text: 'What finance books are available?' },
]

// ── Simple markdown → React renderer ─────────────────────────────────────────
// Handles: **bold**, *italic*, bullet lists (- item), line breaks

function renderMarkdown(text) {
  if (!text) return null
  const lines = text.split('\n')
  const elements = []
  let listItems = []

  function flushList() {
    if (listItems.length) {
      elements.push(
        <ul key={`ul-${elements.length}`} style={md.ul}>
          {listItems.map((item, i) => <li key={i} style={md.li}>{item}</li>)}
        </ul>
      )
      listItems = []
    }
  }

  function renderInline(str) {
    const parts = []
    const regex = /\*\*(.+?)\*\*|\*(.+?)\*/g
    let last = 0, m
    while ((m = regex.exec(str)) !== null) {
      if (m.index > last) parts.push(str.slice(last, m.index))
      if (m[1] !== undefined) parts.push(<strong key={m.index}>{m[1]}</strong>)
      else if (m[2] !== undefined) parts.push(<em key={m.index}>{m[2]}</em>)
      last = m.index + m[0].length
    }
    if (last < str.length) parts.push(str.slice(last))
    return parts
  }

  lines.forEach((line, i) => {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
      listItems.push(renderInline(trimmed.slice(2)))
    } else {
      flushList()
      if (trimmed === '') {
        elements.push(<br key={`br-${i}`} />)
      } else {
        elements.push(<p key={`p-${i}`} style={md.p}>{renderInline(trimmed)}</p>)
      }
    }
  })
  flushList()
  return elements
}

const md = {
  p:  { margin: '2px 0', lineHeight: 1.6 },
  ul: { margin: '6px 0 6px 16px', padding: 0 },
  li: { margin: '3px 0', lineHeight: 1.55 },
}

// ── Product source card ───────────────────────────────────────────────────────

function SourceCard({ product }) {
  const stars = product.rating_avg
    ? '★'.repeat(Math.round(product.rating_avg)) + '☆'.repeat(5 - Math.round(product.rating_avg))
    : null

  return (
    <div style={s.card}>
      {product.primary_image && (
        <img
          src={product.primary_image}
          alt={product.name}
          style={s.cardImg}
          onError={e => { e.target.style.display = 'none' }}
        />
      )}
      <div style={s.cardBody}>
        <p style={s.cardName}>{product.name}</p>
        <p style={s.cardPrice}>₹{product.effective_price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
        {stars && (
          <p style={s.cardRating}>
            <span style={{ color: '#f59e0b' }}>{stars}</span>
            <span style={{ color: 'var(--muted)', fontSize: '0.72rem', marginLeft: 4 }}>
              ({product.rating_count})
            </span>
          </p>
        )}
        <span style={{ ...s.stockBadge, ...(product.in_stock ? s.inStock : s.outStock) }}>
          {product.in_stock ? 'In Stock' : 'Out of Stock'}
        </span>
      </div>
      <Link to={`/products/${product.id}`} style={s.viewBtn}>View →</Link>
    </div>
  )
}

// ── Parsed filter banner ──────────────────────────────────────────────────────

function FilterBanner({ filters }) {
  if (!filters) return null
  const chips = []
  if (filters.category)  chips.push({ k: 'Category', v: filters.category })
  if (filters.subcategory) chips.push({ k: 'Type', v: filters.subcategory })
  if (filters.brand)     chips.push({ k: 'Brand', v: filters.brand })
  if (filters.max_price) chips.push({ k: 'Max', v: `₹${Number(filters.max_price).toLocaleString('en-IN')}` })
  if (filters.min_price) chips.push({ k: 'Min', v: `₹${Number(filters.min_price).toLocaleString('en-IN')}` })
  if (filters.keywords)  chips.push({ k: 'Keywords', v: filters.keywords })
  if (!chips.length)     return null
  return (
    <div style={s.filterBanner}>
      <span style={{ fontSize: '0.9rem' }}>✨</span>
      <span style={s.filterLabel}>I searched for:</span>
      {chips.map(c => (
        <span key={c.k} style={s.filterChip}>
          <span style={{ opacity: .7 }}>{c.k} </span>
          <strong>{c.v}</strong>
        </span>
      ))}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ShoppingAssistant() {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const sessionRef = useRef(null)
  const bottomRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function send(text) {
    text = (text ?? input).trim()
    if (!text || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setLoading(true)
    try {
      const res = await assistantApi.chat(text, sessionRef.current, user?.id)
      const d = res.data
      sessionRef.current = d.session_id
      setMessages(m => [...m, {
        role:          'bot',
        text:          d.reply,
        sources:       d.sources || [],
        parsedFilters: d.parsed_filters || null,
        fallback:      d.fallback_mode,
      }])
    } catch {
      setMessages(m => [...m, { role: 'bot', text: 'Sorry, the assistant is temporarily unavailable. Please try again.', sources: [], parsedFilters: null, fallback: false }])
    } finally {
      setLoading(false)
    }
  }

  function newChat() {
    sessionRef.current = null
    setMessages([])
    setInput('')
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const showQuickPrompts = messages.length === 0 && !loading

  return (
    <div style={s.page}>
      {/* Page header */}
      <div style={s.pageHeader}>
        <div>
          <h1 style={s.title}>Shopping Assistant</h1>
          <p style={s.subtitle}>Ask me about products, availability, or get personalised recommendations</p>
        </div>
        {messages.length > 0 && (
          <button className="btn btn-outline btn-sm" onClick={newChat}>
            + New Chat
          </button>
        )}
      </div>

      {/* Chat area */}
      <div style={s.chatArea}>
        {showQuickPrompts && (
          <div style={s.welcomeWrap}>
            <div style={s.welcomeIcon}>🛍️</div>
            <h2 style={s.welcomeTitle}>How can I help you today?</h2>
            <p style={s.welcomeSub}>I can find products, check stock, compare options, and give personalised recommendations.</p>
            <div style={s.quickGrid}>
              {QUICK_PROMPTS.map(q => (
                <button key={q.label} style={s.quickBtn} onClick={() => send(q.text)}>
                  {q.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={s.msgWrap}>
            {msg.role === 'user' ? (
              <div style={s.userRow}>
                <div style={s.userBubble}>{msg.text}</div>
              </div>
            ) : (
              <div style={s.botRow}>
                <div style={s.botAvatar}>🤖</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* Fallback warning */}
                  {msg.fallback && (
                    <div style={s.fallbackWarn}>
                      ⚠️ AI service is degraded — response generated by local model
                    </div>
                  )}
                  {/* Parsed filter banner */}
                  <FilterBanner filters={msg.parsedFilters} />
                  {/* Bot reply with markdown */}
                  <div style={s.botBubble}>
                    {renderMarkdown(msg.text)}
                  </div>
                  {/* Source product cards */}
                  {msg.sources?.length > 0 && (
                    <div style={s.sourcesWrap}>
                      <p style={s.sourcesLabel}>Retrieved products:</p>
                      <div style={s.cardsRow}>
                        {msg.sources.map(p => <SourceCard key={p.id} product={p} />)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={s.botRow}>
            <div style={s.botAvatar}>🤖</div>
            <div style={{ ...s.botBubble, padding: '14px 18px' }}>
              <span className="typing"><span /><span /><span /></span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div style={s.inputBar}>
        <div style={s.inputWrap}>
          <textarea
            style={s.textarea}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask about products, availability, comparisons…"
            rows={1}
            disabled={loading}
          />
          <button
            className="btn btn-primary"
            style={s.sendBtn}
            onClick={() => send()}
            disabled={loading || !input.trim()}
          >
            ↑
          </button>
        </div>
        <p style={s.inputHint}>Press Enter to send · Shift+Enter for new line</p>
      </div>

      <style>{`
        .typing { display: inline-flex; gap: 4px; align-items: center; }
        .typing span { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); animation: tbounce .9s infinite; }
        .typing span:nth-child(2) { animation-delay: .2s; }
        .typing span:nth-child(3) { animation-delay: .4s; }
        @keyframes tbounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
      `}</style>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const s = {
  page: {
    display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)',
    maxWidth: 860, margin: '0 auto', padding: '0 16px',
  },
  pageHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    padding: '20px 0 12px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  title:    { fontSize: '1.3rem', fontWeight: 800, margin: 0 },
  subtitle: { fontSize: '0.85rem', color: 'var(--muted)', marginTop: 4 },
  chatArea: {
    flex: 1, overflowY: 'auto', padding: '20px 0',
    display: 'flex', flexDirection: 'column', gap: 16,
  },
  // Welcome screen
  welcomeWrap: {
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    textAlign: 'center', padding: '48px 24px',
  },
  welcomeIcon:  { fontSize: '3rem', marginBottom: 16 },
  welcomeTitle: { fontSize: '1.4rem', fontWeight: 700, margin: '0 0 8px' },
  welcomeSub:   { color: 'var(--muted)', fontSize: '0.9rem', maxWidth: 480, marginBottom: 28 },
  quickGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
    gap: 10, width: '100%', maxWidth: 580,
  },
  quickBtn: {
    padding: '10px 14px', borderRadius: 10, textAlign: 'left',
    background: 'var(--surface)', border: '1.5px solid var(--border)',
    fontSize: '0.83rem', fontWeight: 600, color: 'var(--primary)',
    cursor: 'pointer', transition: 'border-color .15s',
  },
  // Messages
  msgWrap: { display: 'flex', flexDirection: 'column' },
  userRow: { display: 'flex', justifyContent: 'flex-end' },
  userBubble: {
    maxWidth: '72%', background: 'var(--primary)', color: '#fff',
    padding: '10px 16px', borderRadius: '18px 18px 4px 18px',
    fontSize: '0.9rem', lineHeight: 1.55, whiteSpace: 'pre-wrap',
  },
  botRow: { display: 'flex', gap: 12, alignItems: 'flex-start' },
  botAvatar: {
    width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
    background: 'rgba(80,70,229,.1)', display: 'flex',
    alignItems: 'center', justifyContent: 'center', fontSize: '1rem', marginTop: 2,
  },
  botBubble: {
    background: 'var(--ground)', borderRadius: '4px 18px 18px 18px',
    padding: '12px 16px', fontSize: '0.9rem', color: 'var(--text)',
    lineHeight: 1.6,
  },
  fallbackWarn: {
    background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.3)',
    color: '#92400e', borderRadius: 8, padding: '6px 12px',
    fontSize: '0.78rem', marginBottom: 8,
  },
  // Parsed filter banner
  filterBanner: {
    display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6,
    background: 'rgba(80,70,229,.06)', border: '1px solid rgba(80,70,229,.15)',
    borderRadius: 8, padding: '7px 12px', marginBottom: 8,
    fontSize: '0.8rem',
  },
  filterLabel: { fontWeight: 700, color: 'var(--primary)', marginRight: 2 },
  filterChip: {
    background: 'rgba(80,70,229,.1)', borderRadius: 999,
    padding: '1px 9px', color: 'var(--primary)', fontSize: '0.78rem',
  },
  // Source product cards
  sourcesWrap: { marginTop: 10 },
  sourcesLabel: {
    fontSize: '0.75rem', fontWeight: 700, color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 8,
  },
  cardsRow: {
    display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 4,
  },
  card: {
    flexShrink: 0, width: 148, border: '1px solid var(--border)',
    borderRadius: 10, overflow: 'hidden', background: 'var(--surface)',
    display: 'flex', flexDirection: 'column',
  },
  cardImg: {
    width: '100%', height: 96, objectFit: 'cover', display: 'block',
  },
  cardBody: { padding: '8px 10px', flex: 1 },
  cardName: {
    fontSize: '0.78rem', fontWeight: 600, margin: '0 0 4px',
    display: '-webkit-box', WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical', overflow: 'hidden',
  },
  cardPrice: {
    fontSize: '0.85rem', fontWeight: 700, color: 'var(--primary)', margin: '0 0 4px',
  },
  cardRating: { fontSize: '0.75rem', margin: '0 0 6px' },
  stockBadge: {
    fontSize: '0.68rem', fontWeight: 700, padding: '2px 7px',
    borderRadius: 999, display: 'inline-block',
  },
  inStock:  { background: 'rgba(0,179,126,.12)', color: '#059669' },
  outStock: { background: 'rgba(239,68,68,.1)',  color: '#dc2626' },
  viewBtn: {
    display: 'block', textAlign: 'center', padding: '7px',
    borderTop: '1px solid var(--border)', fontSize: '0.78rem',
    fontWeight: 700, color: 'var(--primary)', textDecoration: 'none',
    background: 'rgba(80,70,229,.04)',
  },
  // Input bar
  inputBar: {
    flexShrink: 0, paddingBottom: 16, borderTop: '1px solid var(--border)', paddingTop: 12,
  },
  inputWrap: { display: 'flex', gap: 8, alignItems: 'flex-end' },
  textarea: {
    flex: 1, resize: 'none', padding: '10px 14px',
    borderRadius: 12, border: '1.5px solid var(--border)',
    fontSize: '0.9rem', fontFamily: 'inherit', lineHeight: 1.5,
    background: 'var(--surface)', color: 'var(--text)',
    outline: 'none', minHeight: 42,
  },
  sendBtn: {
    height: 42, width: 42, padding: 0, flexShrink: 0,
    borderRadius: 12, fontSize: '1.1rem',
  },
  inputHint: {
    fontSize: '0.72rem', color: 'var(--muted)', textAlign: 'center', marginTop: 6,
  },
}
