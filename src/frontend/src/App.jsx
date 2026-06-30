import { Routes, Route } from 'react-router-dom'
import Header from './components/Header.jsx'
import ChatWidget from './components/ChatWidget.jsx'
import Home from './pages/Home.jsx'
import Products from './pages/Products.jsx'
import ProductDetail from './pages/ProductDetail.jsx'
import Checkout from './pages/Checkout.jsx'
import Orders from './pages/Orders.jsx'
import Auth from './pages/Auth.jsx'
import Inventory from './pages/Inventory.jsx'
import Guardrails from './pages/Guardrails.jsx'

export default function App() {
  return (
    <>
      <Header />
      <main>
        <Routes>
          <Route path="/"                  element={<Home />} />
          <Route path="/products"          element={<Products />} />
          <Route path="/products/:id"      element={<ProductDetail />} />
          <Route path="/checkout"          element={<Checkout />} />
          <Route path="/orders"            element={<Orders />} />
          <Route path="/auth"              element={<Auth />} />
          <Route path="/inventory"         element={<Inventory />} />
          <Route path="/guardrails"        element={<Guardrails />} />
          <Route path="*"                  element={<Home />} />
        </Routes>
      </main>
      <ChatWidget />
    </>
  )
}
