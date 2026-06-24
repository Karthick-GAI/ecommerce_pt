import axios from 'axios'

// ── Base clients ──────────────────────────────────────────────────────────────

const make = (baseURL) => axios.create({ baseURL, timeout: 10000 })

const userApi     = make('http://localhost:8000')
const productApi  = make('http://localhost:8001')
const chatApi     = make('http://localhost:8002')
const checkoutApi = make('http://localhost:8003')
const orderApi    = make('http://localhost:8004')
const sessionApi  = make('http://localhost:8008')
const agentApi    = make('http://localhost:8007')

// Attach JWT when present
const withAuth = (api) => {
  api.interceptors.request.use(cfg => {
    const token = localStorage.getItem('token')
    if (token) cfg.headers.Authorization = `Bearer ${token}`
    return cfg
  })
  return api
}
withAuth(userApi)
withAuth(checkoutApi)
withAuth(orderApi)
withAuth(sessionApi)

// ── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  register: (data) => userApi.post('/register', data),
  login:    (data) => userApi.post('/login', data),
  me:       (id)   => userApi.get(`/users/${id}`),
}

// ── Products ──────────────────────────────────────────────────────────────────

export const productsApi = {
  list: (params = {}) => productApi.get('/products', { params }),
  get:  (id)           => productApi.get(`/products/${id}`),
  search: (query, params = {}) =>
    productApi.get('/search/keyword', { params: { q: query, ...params } }),
  categories: () => productApi.get('/categories'),
  featured: () => productApi.get('/products', { params: { limit: 8, sort_by: 'rating', order: 'desc' } }),
}

// ── Session & Cart ────────────────────────────────────────────────────────────

export const sessionsApi = {
  create:  (customerId) => sessionApi.post('/sessions', { customer_id: customerId || null }),
  get:     (id)         => sessionApi.get(`/sessions/${id}`),
  getCart: (id)         => sessionApi.get(`/sessions/${id}/cart`),
  addItem: (sessionId, item) =>
    sessionApi.post(`/sessions/${sessionId}/cart/items`, item),
  updateItem: (sessionId, productId, qty) =>
    sessionApi.put(`/sessions/${sessionId}/cart/items/${productId}`, { quantity: qty }),
  removeItem: (sessionId, productId) =>
    sessionApi.delete(`/sessions/${sessionId}/cart/items/${productId}`),
  clearCart: (id) => sessionApi.delete(`/sessions/${id}/cart`),
  end: (id) => sessionApi.post(`/sessions/${id}/end`),
}

// ── Checkout ──────────────────────────────────────────────────────────────────

export const checkoutsApi = {
  createCart: () => checkoutApi.post('/cart'),
  addItem: (cartId, item) => checkoutApi.post(`/cart/${cartId}/items`, item),
  updateItem: (cartId, productId, qty) =>
    checkoutApi.put(`/cart/${cartId}/items/${productId}`, { quantity: qty }),
  removeItem: (cartId, productId) =>
    checkoutApi.delete(`/cart/${cartId}/items/${productId}`),
  place: (data) => checkoutApi.post('/checkout', data),
  pay: (orderId, data) => checkoutApi.post(`/checkout/${orderId}/pay`, data),
  status: (orderId) => checkoutApi.get(`/checkout/${orderId}/status`),
}

// ── Orders ────────────────────────────────────────────────────────────────────

export const ordersApi = {
  byCustomer: (customerId, params = {}) =>
    orderApi.get(`/orders/customer/${customerId}`, { params }),
  get: (id)        => orderApi.get(`/orders/${id}`),
  timeline: (id)   => orderApi.get(`/orders/${id}/timeline`),
  cancel: (id, reason) => orderApi.post(`/orders/${id}/cancel`, { reason }),
  notifications: (customerId) =>
    orderApi.get(`/notifications/customer/${customerId}`),
  markRead: (customerId) =>
    orderApi.put(`/notifications/customer/${customerId}/read-all`),
}

// ── Shopping Assistant ────────────────────────────────────────────────────────

export const assistantApi = {
  chat: (message, sessionId) =>
    chatApi.post('/chat', { message, session_id: sessionId }),
  history: (sessionId) => chatApi.get(`/chat/${sessionId}/history`),
}

// ── AI Agent ─────────────────────────────────────────────────────────────────

export const agentChatApi = {
  chat: (message, sessionId) =>
    agentApi.post('/agent/chat', { message, session_id: sessionId }),
}
