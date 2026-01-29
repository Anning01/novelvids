import axios from 'axios'
import type { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios'

// API base URL (without /api/v1 prefix)
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/**
 * Get full URL for media files (images, videos, etc.)
 * Converts relative paths like /media/... to full URLs
 */
export function getMediaUrl(relativePath: string | null | undefined): string | undefined {
  if (!relativePath) return undefined
  // If already a full URL (http/https or data:), return as-is
  if (relativePath.startsWith('http') || relativePath.startsWith('data:')) {
    return relativePath
  }
  // Otherwise prepend the API base URL
  return `${API_BASE_URL}${relativePath}`
}

const api: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

// 标记，防止多次同时刷新令牌
let isRefreshing = false
let failedQueue: Array<{
  resolve: (value?: unknown) => void
  reject: (reason?: unknown) => void
}> = []

const processQueue = (error: Error | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve()
    }
  })
  failedQueue = []
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // 如果错误码不是 401 或请求已重试过，立即拒绝
    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error)
    }

    // Extract backend error message if available
    if (error.response?.data) {
      const data = error.response.data as any
      if (data.message) {
        error.message = data.message
      }
      if (data.code) {
        // @ts-ignore
        error.code = data.code
      }
    }

    // 如果失败的请求是刷新端点，不重试
    if (originalRequest.url?.includes('/auth/refresh')) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      // 使用路由导航而不是 window.location 以获得更好的用户体验
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    // 如果正在刷新中，将此请求加入队列
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({ resolve, reject })
      })
        .then(() => {
          return api(originalRequest)
        })
        .catch((err) => {
          return Promise.reject(err)
        })
    }

    originalRequest._retry = true
    isRefreshing = true

    const refreshToken = localStorage.getItem('refresh_token')

    if (!refreshToken) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    try {
      // 尝试刷新令牌
      const response = await api.post('/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefreshToken } = response.data

      // 更新本地存储中的令牌
      localStorage.setItem('access_token', access_token)
      if (newRefreshToken) {
        localStorage.setItem('refresh_token', newRefreshToken)
      }

      // 更新原始请求的授权头
      originalRequest.headers.Authorization = `Bearer ${access_token}`

      // 处理队列中的请求
      processQueue()

      // 重试原始请求
      return api(originalRequest)
    } catch (refreshError) {
      // 刷新失败，清除令牌并跳转到登录页
      processQueue(refreshError as Error)
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  }
)

export default api
