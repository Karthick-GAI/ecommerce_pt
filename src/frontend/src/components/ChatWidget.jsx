import { useState, useRef, useEffect } from 'react'
import { assistantApi } from '../api/index.js'
import { useCart } from '../store/CartContext.jsx'
import { useToast } from '../store/ToastContext.jsx'
import { useNavigate } from 'react-router-dom'

const BOT_INTRO = "Hi! I'm your AI shopping assistant. Ask me anything — find products, compare options, or get recommendations."

export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([{ role: 'bot', text: BOT_INTRO }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const chatSessionRef = useRef(null)
  const { sessionId } = useCart()
  const toast = useToast()
  const navigate = useNavigate()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setLoading(true)

    try {
      const res = await assistantApi.chat(text, chatSessionRef.current)
      chatSessionRef.current = res.data.session_id || chatSessionRef.current

      const reply    = res.data.reply || res.data.response || res.data.message || 'Sorry, I could not process that.'
      const products = res.data.products || res.data.results || res.data.sources || []

      console.log('[ShopAI] response:', { reply, sources: products.length, session: chatSessionRef.current })
      setMessages(m => [...m,
        { role: 'bot', text: reply, products }
      ])
    } catch (err) {
      console.error('[ShopAI] chat error:', err?.response?.status, err?.response?.data || err?.message)
      setMessages(m => [...m, {
        role: 'bot', text: 'Sorry, the assistant is temporarily unavailable.',
      }])
    } finally {
      setLoading(false)
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen(o => !o)}
        style={styles.fab}
        aria-label="Open chat assistant"
      >
        {open ? '✕' : '💬'}
      </button>

      {/* Chat panel */}
      {open && (
        <div style={styles.panel}>
          <div style={styles.panelHeader}>
            <div style={styles.headerLeft}>
              <div style={styles.avatar}>🤖</div>
              <div>
                <div style={styles.botName}>ShopAI Assistant</div>
                <div style={styles.botStatus}>● Online</div>
              </div>
            </div>
            <button onClick={() => setOpen(false)} style={styles.closeBtn}>✕</button>
          </div>

          <div style={styles.messages}>
            {messages.map((msg, i) => (
              <div key={i}>
                <div style={{ ...styles.bubble, ...(msg.role === 'user' ? styles.userBubble : styles.botBubble) }}>
                  {msg.text}
                </div>
                {msg.products?.length > 0 && (
                  <div style={styles.productPills}>
                    {msg.products.slice(0, 4).map(p => (
                      <div
                        key={p.id}
                        style={styles.productPill}
                        onClick={() => navigate(`/products/${p.id}`)}
                      >
                        <img
                          src={p.primary_image || `https://picsum.photos/seed/${p.id}/60/60`}
                          alt={p.name}
                          style={styles.pillImg}
                        />
                        <div>
                          <div style={styles.pillName}>{p.name?.slice(0, 40)}</div>
                          <div style={styles.pillPrice}>₹{Number(p.effective_price ?? p.price).toLocaleString('en-IN')}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div style={styles.botBubble}>
                <span style={styles.typing}><span /><span /><span /></span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div style={styles.inputRow}>
            <input
              className="input"
              style={styles.chatInput}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask me anything…"
              disabled={loading}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '0 16px', height: 40, flexShrink: 0 }}
              onClick={send}
              disabled={loading || !input.trim()}
            >
              ↑
            </button>
          </div>
        </div>
      )}

      <style>{`
        .typing { display: inline-flex; gap: 4px; align-items: center; }
        .typing span {
          width: 7px; height: 7px; border-radius: 50%;
          background: var(--muted); animation: bounce .9s infinite;
        }
        .typing span:nth-child(2) { animation-delay: .2s; }
        .typing span:nth-child(3) { animation-delay: .4s; }
        @keyframes bounce {
          0%,100% { transform: translateY(0); }
          50% { transform: translateY(-5px); }
        }
      `}</style>
    </>
  )
}

const styles = {
  fab: {
    position: 'fixed', bottom: 28, right: 28, zIndex: 300,
    width: 56, height: 56, borderRadius: '50%',
    background: 'var(--primary)', color: '#fff',
    border: 'none', fontSize: '1.4rem',
    boxShadow: '0 4px 20px rgba(80,70,229,.4)',
    transition: 'all .2s',
  },
  panel: {
    position: 'fixed', bottom: 96, right: 28, zIndex: 300,
    width: 380, height: 520,
    background: 'var(--surface)', borderRadius: 'var(--radius-lg)',
    boxShadow: 'var(--shadow-lg)',
    border: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column',
    overflow: 'hidden',
  },
  panelHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '14px 16px', background: 'var(--primary)',
    color: '#fff',
  },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 10 },
  avatar: { fontSize: '1.5rem' },
  botName: { fontWeight: 700, fontSize: '0.95rem' },
  botStatus: { fontSize: '0.75rem', opacity: .8 },
  closeBtn: {
    background: 'rgba(255,255,255,.2)', border: 'none', color: '#fff',
    borderRadius: 6, padding: '4px 8px', cursor: 'pointer', fontSize: '0.85rem',
  },
  messages: {
    flex: 1, overflowY: 'auto', padding: '14px 16px',
    display: 'flex', flexDirection: 'column', gap: 8,
  },
  bubble: {
    maxWidth: '82%', padding: '10px 14px',
    borderRadius: 14, fontSize: '0.875rem', lineHeight: 1.5,
  },
  botBubble: {
    background: 'var(--ground)', color: 'var(--text)',
    borderBottomLeftRadius: 4, alignSelf: 'flex-start',
  },
  userBubble: {
    background: 'var(--primary)', color: '#fff',
    borderBottomRightRadius: 4, alignSelf: 'flex-end',
  },
  productPills: {
    display: 'flex', flexDirection: 'column', gap: 6,
    marginTop: 6, maxWidth: '85%',
  },
  productPill: {
    display: 'flex', alignItems: 'center', gap: 10,
    background: 'var(--ground)', borderRadius: 10,
    padding: '8px 10px', cursor: 'pointer',
    border: '1px solid var(--border)',
  },
  pillImg: { width: 44, height: 44, objectFit: 'cover', borderRadius: 6, flexShrink: 0 },
  pillName: { fontSize: '0.78rem', fontWeight: 500, lineHeight: 1.3 },
  pillPrice: { fontSize: '0.8rem', fontWeight: 700, color: 'var(--primary)', marginTop: 2 },
  inputRow: {
    display: 'flex', gap: 8, padding: '12px 14px',
    borderTop: '1px solid var(--border)',
  },
  chatInput: { height: 40, fontSize: '0.875rem' },
}
