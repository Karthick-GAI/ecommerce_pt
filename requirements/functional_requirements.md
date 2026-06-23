# Functional Requirements

## 1. User Management (B2C)

### 1.1 Authentication
- FR-AUTH-01: Users can register with email, password, full name, and phone number.
- FR-AUTH-02: Passwords are hashed with bcrypt before storage (plaintext never persisted).
- FR-AUTH-03: Login returns a short-lived JWT access token (15 min) and a refresh token (7 days).
- FR-AUTH-04: Access tokens can be refreshed without re-authentication using the refresh token.
- FR-AUTH-05: Invalid or expired tokens return HTTP 401 with a descriptive error body.

### 1.2 User Profile
- FR-PROFILE-01: Authenticated users can view and update their profile (name, phone, avatar).
- FR-PROFILE-02: Users can add, edit, and delete multiple shipping addresses.
- FR-PROFILE-03: Users can add payment methods (card tokens — no raw PANs stored).

### 1.3 GDPR Compliance
- FR-GDPR-01: Users can export all personal data as machine-readable JSON (Art. 20 portability).
- FR-GDPR-02: Users can request erasure of their personal data (Art. 17 right to erasure).
- FR-GDPR-03: Erasure anonymises PII (email, name) while retaining order rows for legal obligations (Art. 17(3)(b)).
- FR-GDPR-04: Each erasure request returns a unique erasure token as proof of completion.

---

## 2. Product Catalogue

### 2.1 Product Discovery
- FR-CAT-01: Products can be browsed by category, brand, price range, and rating filters.
- FR-CAT-02: Keyword search matches product name, description, and tags.
- FR-CAT-03: Semantic (vector) search accepts natural language queries and returns cosine-ranked results.
- FR-CAT-04: Each product page shows stock availability in real time.

### 2.2 Product Data
- FR-CAT-05: Each product record includes name, description, category, brand, price, images, and specifications.
- FR-CAT-06: Product embeddings (1536-dim via `text-embedding-3-small`) are generated on creation and updated on edit.

---

## 3. Shopping Cart & Checkout

### 3.1 Cart Management
- FR-CART-01: Authenticated users can add, update quantity, and remove items from their cart.
- FR-CART-02: Cart persists across sessions (server-side storage).
- FR-CART-03: Adding an out-of-stock item is rejected with HTTP 409.

### 3.2 Order Placement
- FR-ORDER-01: Placing an order atomically reserves stock and creates an order record.
- FR-ORDER-02: Order placement is idempotent: replaying the same `Idempotency-Key` header returns the original response without creating a duplicate order.
- FR-ORDER-03: Orders transition through states: `pending` → `confirmed` → `shipped` → `delivered` → `cancelled`.

### 3.3 Payment
- FR-PAY-01: Checkout initiates a Razorpay payment session and returns a payment link/order ID.
- FR-PAY-02: Razorpay webhooks confirm payment and advance order state to `confirmed`.
- FR-PAY-03: Payment failures leave the order in `pending` state and release reserved stock after TTL.

---

## 4. Inventory Management

- FR-INV-01: Stock levels are tracked per SKU.
- FR-INV-02: Order placement decrements available stock atomically (no overselling under concurrent load).
- FR-INV-03: Order cancellation restores reserved stock.
- FR-INV-04: Low-stock alerts are generated when quantity falls below a configurable threshold.

---

## 5. Recommendation Engine

- FR-REC-01: Personalised recommendations are generated per user based on purchase and browsing history.
- FR-REC-02: User-based collaborative filtering identifies users with similar taste profiles.
- FR-REC-03: Item-based collaborative filtering recommends products frequently bought together.
- FR-REC-04: Content-based filtering uses product category and attribute similarity.
- FR-REC-05: A hybrid weight model blends CF + content + trending signals; weights adapt to data availability.
- FR-REC-06: Cold-start users (no history) receive trending / category-popular recommendations.

---

## 6. AI Shopping Assistant (RAG)

- FR-RAG-01: Users can ask natural language questions about products (e.g., "waterproof hiking boots under ₹5000").
- FR-RAG-02: Queries are parsed to extract intent, filters, and entities.
- FR-RAG-03: Parsed query is embedded and used for cosine similarity search against the product vector store.
- FR-RAG-04: Top-k retrieved products are passed as context to GPT-4o-mini, which generates a conversational response.
- FR-RAG-05: Guardrails service validates both input query and output response before returning to the user.

---

## 7. Multi-Agent Order Management

- FR-AGENT-01: An Orchestrator agent receives escalated order issues and routes them to specialist agents.
- FR-AGENT-02: Specialist agents handle: payment disputes, delivery tracking, return/refund, and product quality issues.
- FR-AGENT-03: A Root Cause Analysis (RCA) agent produces a structured diagnosis for each case.
- FR-AGENT-04: A Rerouting agent escalates to human support when confidence is below threshold.
- FR-AGENT-05: All agent decisions are logged with reasoning traces for auditability.

---

## 8. Seller Portal (B2B)

### 8.1 Onboarding & KYC
- FR-SELLER-01: Sellers register with business name, email, GST number, and PAN number.
- FR-SELLER-02: New seller accounts start in `pending_verification` status; an admin approves to activate.
- FR-SELLER-03: GST/PAN changes on an active account trigger re-verification.

### 8.2 Product Management
- FR-SELLER-04: Sellers can create, edit, and manage their own product listings.
- FR-SELLER-05: New product listings require admin approval before going live (`pending_review` → `approved`).
- FR-SELLER-06: Editing an already-approved product resets it to `pending_review` to prevent post-approval fraud.
- FR-SELLER-07: Sellers can update stock quantities directly via a dedicated stock endpoint.

### 8.3 Order Fulfilment
- FR-SELLER-08: Sellers can view orders for their products with filters by status and date.
- FR-SELLER-09: Sellers update fulfilment status (`processing` → `shipped` → `delivered`); backward transitions are rejected.
- FR-SELLER-10: A dashboard endpoint returns aggregated sales, revenue, and commission metrics.
- FR-SELLER-11: Platform commission is fixed at 10% of the selling price per order.

---

## 9. Session & Behavioural Tracking

- FR-SESSION-01: Browsing events (product views, searches, category visits) are captured per session.
- FR-SESSION-02: Session data feeds the recommendation engine as behavioural signals.
- FR-SESSION-03: Sessions are keyed by user ID (authenticated) or anonymous session token.

---

## 10. Logistics Integration

- FR-SHIP-01: Confirmed orders are submitted to Shiprocket for fulfilment.
- FR-SHIP-02: Tracking IDs from Shiprocket are stored and surfaced on the order detail endpoint.
- FR-SHIP-03: Delivery status webhooks from Shiprocket advance the order to `delivered`.
