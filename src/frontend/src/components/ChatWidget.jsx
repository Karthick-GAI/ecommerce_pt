import { useState, useRef, useEffect } from 'react'
import { agentChatApi } from '../api/index.js'
import { useAuth } from '../store/AuthContext.jsx'
import { useNavigate } from 'react-router-dom'

const BOT_INTRO = "Hi! I'm your AI assistant powered by tool-calling. I can look up your orders, check live stock, and recommend products. Try asking me anything."

const QUICK_PROMPTS = [
  { label: 'My orders',        text: 'Show me my recent orders' },
  { label: 'Best deals',       text: 'What are the best deals right now?' },
  { label: 'Trending now',     text: 'What products are trending this month?' },
  { label: 'Recommend for me', text: 'Recommend some products for me' },
]

const TOOL_LABELS = {
  lookup_order:          'Order lookup',
  get_customer_orders:   'Order history',
  get_order_tracking:    'Order tracking',
  search_products:       'Product search',
  check_product_stock:   'Stock check',
  get_category_summary:  'Inventory summary',
  get_recommendations:   'Personalised recs',
  get_similar_products:  'Similar products',
  get_trending_products: 'Trending products',
  get_deals:             'Best deals',
}

export default function ChatWidget() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen]       = useState(false)
  const [messages, setMessages] = useState([{ role: 'bot', text: BOT_INTRO, tools: [] }])
  const [input, setInput]     = useState('')
  const [loading, setLoading] = useState(false)
  const sessionRef            = useRef(null)
  const bottomRef             = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(text) {
    text = (text ?? input).trim()
    if (!text || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setLoading(true)

    try {
      const res = await agentChatApi.chat(text, sessionRef.current, user?.id)
      sessionRef.current = res.data.session_id || sessionRef.current

      setMessages(m => [...m, {
        role:  'bot',
        text:  res.data.response || 'Sorry, I could not process that.',
        tools: res.data.tools_used || [],
      }])
    } catch {
      setMessages(m => [...m, {
        role: 'bot',
        text: 'Sorry, the assistant is temporarily unavailable.',
        tools: [],
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
      <button onClick={() => setOpen(o => !o)} style={s.fab} aria-label="Open chat assistant">
        {open ? '✕' : '💬'}
      </button>

      {open && (
        <div style={s.panel}>
          {/* Header */}
          <div style={s.header}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: '1.5rem' }}>🤖</div>
              <div>
                <div style={s.botName}>ShopAI Agent</div>
                <div style={s.botStatus}>● Tool-calling enabled</div>
              </div>
            </div>
            <button onClick={() => setOpen(false)} style={s.closeBtn}>✕</button>
          </div>

          {/* Messages */}
          <div style={s.messages}>
            {messages.map((msg, i) => (
              <div key={i}>
                <div style={{ ...s.bubble, ...(msg.role === 'user' ? s.userBubble : s.botBubble) }}>
                  {msg.text}
                </div>
                {msg.tools?.length > 0 && (
                  <div style={s.toolRow}>
                    {msg.tools.map(t => (
                      <span key={t} style={s.toolChip}>
                        ⚡ {TOOL_LABELS[t] || t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* Quick prompts — show only before first user message */}
            {messages.length === 1 && !loading && (
              <div style={s.quickRow}>
                {QUICK_PROMPTS.map(q => (
                  <button key={q.label} style={s.quickBtn} onClick={() => send(q.text)}>
                    {q.label}
                  </button>
                ))}
              </div>
            )}

            {loading && (
              <div style={{ ...s.bubble, ...s.botBubble }}>
                <span className="typing"><span /><span /><span /></span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={s.inputRow}>
            <input
              className="input"
              style={s.chatInput}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about orders, stock, or products…"
              disabled={loading}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '0 16px', height: 40, flexShrink: 0 }}
              onClick={() => send()}
              disabled={loading || !input.trim()}
            >
              ↑
            </button>
          </div>
        </div>
      )}

      <style>{`
        .typing { display: inline-flex; gap: 4px; align-items: center; }
        .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: bounce .9s infinite; }
        .typing span:nth-child(2) { animation-delay: .2s; }
        .typing span:nth-child(3) { animation-delay: .4s; }
        @keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
      `}</style>
    </>
  )
}

const s = {
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
    width: 380, height: 540,
    background: 'var(--surface)', borderRadius: 'var(--radius-lg)',
    boxShadow: 'var(--shadow-lg)', border: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '14px 16px', background: 'var(--primary)', color: '#fff',
  },
  botName:   { fontWeight: 700, fontSize: '0.95rem' },
  botStatus: { fontSize: '0.72rem', opacity: .8 },
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
    borderRadius: 14, fontSize: '0.875rem', lineHeight: 1.55,
    whiteSpace: 'pre-wrap',
  },
  botBubble: {
    background: 'var(--ground)', color: 'var(--text)',
    borderBottomLeftRadius: 4, alignSelf: 'flex-start',
  },
  userBubble: {
    background: 'var(--primary)', color: '#fff',
    borderBottomRightRadius: 4, alignSelf: 'flex-end',
  },
  toolRow: {
    display: 'flex', flexWrap: 'wrap', gap: 4,
    marginTop: 4, marginBottom: 2, paddingLeft: 2,
  },
  toolChip: {
    fontSize: '0.68rem', fontWeight: 600,
    padding: '2px 7px', borderRadius: 10,
    background: '#EEF0FF', color: 'var(--primary)',
    border: '1px solid #D0D3FF',
  },
  quickRow: {
    display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4,
  },
  quickBtn: {
    padding: '5px 11px', borderRadius: 16,
    background: 'var(--surface)', border: '1.5px solid var(--border)',
    fontSize: '0.78rem', fontWeight: 600, color: 'var(--primary)',
    cursor: 'pointer', transition: 'all .15s',
  },
  inputRow: {
    display: 'flex', gap: 8, padding: '12px 14px',
    borderTop: '1px solid var(--border)',
  },
  chatInput: { height: 40, fontSize: '0.875rem' },
}
