import React, { createContext, useContext, useState, useEffect } from 'react'
import { api } from '../services/api'

interface User {
  id: number
  email: string
  name: string | null
  is_admin: boolean
}

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  loading: boolean
  login: (provider: 'google' | 'microsoft') => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`
      fetchUser()
    } else {
      setLoading(false)
    }
  }, [token])

  const fetchUser = async () => {
    try {
      const response = await api.get('admin/auth/me')
      setUser(response.data)
    } catch (error) {
      localStorage.removeItem('token')
      setToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  const login = (provider: 'google' | 'microsoft') => {
    const base = (import.meta.env.VITE_API_URL ?? '').toString().trim()
    const origin = base ? base.replace(/\/+$/, '') : (typeof window !== 'undefined' ? window.location.origin : '')
    window.location.href = `${origin}/api/admin/auth/login/${provider}`
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    delete api.defaults.headers.common['Authorization']
  }

  // Handle OAuth callback - check if we're coming from OAuth redirect
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search)
    const code = urlParams.get('code')
    
    // If we have a code, the backend should handle it and redirect with token
    // For now, we'll check localStorage after redirect
    if (code) {
      // The backend OAuth callback should set the token in response
      // This is a simplified version - in production, handle the full OAuth flow
      window.history.replaceState({}, document.title, window.location.pathname)
    }
    
    // Check for token in URL hash (alternative OAuth flow)
    const hash = window.location.hash
    if (hash) {
      const params = new URLSearchParams(hash.substring(1))
      const accessToken = params.get('access_token')
      if (accessToken) {
        localStorage.setItem('token', accessToken)
        setToken(accessToken)
        window.history.replaceState({}, document.title, window.location.pathname)
      }
    }
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user && !!token,
        loading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

