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
const invApi      = make('http://localhost:8005')
const recApi      = make('http://localhost:8006')

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
  register: (data) => userApi.post('/auth/register', data),
  login:    (data) => userApi.post('/auth/login', data),
  me: (token) => userApi.get('/users/me', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  }),
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
  createCart: () => checkoutApi.post('/cart', {}),
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
  get:    (id)          => orderApi.get(`/orders/${id}`),
  timeline: (id)        => orderApi.get(`/orders/${id}/timeline`),
  cancel: (id, reason)  => orderApi.post(`/orders/${id}/cancel`, { reason, cancelled_by: 'customer' }),
  getRefund: (id)       => orderApi.get(`/orders/${id}/refund`),
  approveRefund: (refundId) => orderApi.post(`/refunds/${refundId}/approve`, {}),
  notifications: (customerId) =>
    orderApi.get(`/notifications/customer/${customerId}`),
  markRead: (customerId) =>
    orderApi.put(`/notifications/customer/${customerId}/read-all`),
}

// ── Recommendations ───────────────────────────────────────────────────────────

export const recommendationsApi = {
  homepage:     (customerId)         => recApi.get(`/recommendations/homepage/${customerId}`),
  forCustomer:  (customerId, params) => recApi.get(`/recommendations/for/${customerId}`, { params }),
  similar:      (productId, params)  => recApi.get(`/recommendations/similar/${productId}`, { params }),
  boughtTogether:(productId, params) => recApi.get(`/recommendations/bought-together/${productId}`, { params }),
  trending:     (params)             => recApi.get('/recommendations/trending', { params }),
  deals:        (params)             => recApi.get('/recommendations/deals', { params }),
  newArrivals:  (params)             => recApi.get('/recommendations/new-arrivals', { params }),
}

// ── Inventory (ops) ───────────────────────────────────────────────────────────

export const inventoryApi = {
  dashboard: ()           => invApi.get('/inventory/dashboard'),
  list: (params = {})     => invApi.get('/inventory', { params }),
  get:  (productId)       => invApi.get(`/inventory/${productId}`),
  restock: (productId, data) => invApi.post(`/inventory/${productId}/restock`, data),
  adjust:  (productId, data) => invApi.post(`/inventory/${productId}/adjust`, data),
  movements: (productId)  => invApi.get(`/inventory/${productId}/movements`),
}

export const alertsApi = {
  list: (params = {})       => invApi.get('/alerts', { params }),
  acknowledge: (alertId, data) => invApi.post(`/alerts/${alertId}/acknowledge`, data),
  resolve:     (alertId)    => invApi.post(`/alerts/${alertId}/resolve`, {}),
  bulkAcknowledge: (data)   => invApi.post('/alerts/bulk-acknowledge', data),
}

// ── Payment & Shipping (port 8009) ───────────────────────────────────────────

const payShipApi = make('http://localhost:8009')

export const shippingApi = {
  rates:      (data)    => payShipApi.post('/shipping/rates', data),
  byCheckout: (orderId) => payShipApi.get(`/shipping/shipments/by-checkout/${orderId}`),
  track:      (id)      => payShipApi.get(`/shipping/shipments/${id}/track`),
}

export const payShipAnalyticsApi = {
  overview: () => payShipApi.get('/analytics/overview'),
}

// ── Guardrails (port 8010) ────────────────────────────────────────────────────

const guardrailsApiClient = make('http://localhost:8010')

export const guardrailsValidationApi = {
  text:    (data) => guardrailsApiClient.post('/validate/text', data),
  search:  (data) => guardrailsApiClient.post('/validate/search', data),
  contact: (data) => guardrailsApiClient.post('/validate/contact', data),
  amount:  (data) => guardrailsApiClient.post('/validate/amount', data),
}

export const guardrailsRulesApi = {
  list:   ()         => guardrailsApiClient.get('/rules'),
  toggle: (id)       => guardrailsApiClient.post(`/rules/${id}/toggle`),
  update: (id, data) => guardrailsApiClient.patch(`/rules/${id}`, data),
}

export const guardrailsAnomalyApi = {
  scan:         (type = 'full') => guardrailsApiClient.post(`/anomaly/scan?scan_type=${type}`),
  alerts:       (params = {})   => guardrailsApiClient.get('/anomaly/alerts', { params }),
  acknowledge:  (id)            => guardrailsApiClient.post(`/anomaly/alerts/${id}/acknowledge`),
  resolve:      (id, data)      => guardrailsApiClient.post(`/anomaly/alerts/${id}/resolve`, data),
  falsePositive:(id, data)      => guardrailsApiClient.post(`/anomaly/alerts/${id}/false-positive`, data),
}

export const guardrailsAnalyticsApi = {
  overview: () => guardrailsApiClient.get('/analytics/overview'),
}

// ── Shopping Assistant ────────────────────────────────────────────────────────

export const assistantApi = {
  chat: (message, sessionId) =>
    chatApi.post('/chat', { message, session_id: sessionId }),
  history: (sessionId) => chatApi.get(`/chat/${sessionId}/history`),
}

// ── AI Agent ─────────────────────────────────────────────────────────────────

export const agentChatApi = {
  chat: (message, sessionId, customerId) =>
    agentApi.post('/agent/chat', {
      message,
      session_id:  sessionId  || undefined,
      customer_id: customerId || undefined,
    }),
}
