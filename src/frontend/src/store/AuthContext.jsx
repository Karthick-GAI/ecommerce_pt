import { createContext, useContext, useState, useCallback } from 'react'
import { authApi } from '../api/index.js'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('user')) } catch { return null }
  })

  const login = useCallback(async (email, password) => {
    const res = await authApi.login({ email, password })
    const { access_token } = res.data
    localStorage.setItem('token', access_token)
    // Pass token explicitly — don't rely on interceptor picking it up in time
    const profileRes = await authApi.me(access_token)
    const u = profileRes.data
    localStorage.setItem('user', JSON.stringify(u))
    setUser(u)
    return u
  }, [])

  const register = useCallback(async (data) => {
    const res = await authApi.register(data)
    return res.data
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setUser(null)
  }, [])

  return (
    <AuthCtx.Provider value={{ user, login, register, logout, isLoggedIn: !!user }}>
      {children}
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
