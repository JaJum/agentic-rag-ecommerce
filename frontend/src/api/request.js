/**
 * Axios 实例：统一挂 token、401 跳登录、错误提示。
 * baseURL 走 Vite 代理 /api → FastAPI。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 60000
})

// 请求拦截：自动携带 JWT
request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：401 清 token 跳登录；其余抛统一错误
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    } else if (error.response?.status === 403) {
      ElMessage.error('无权访问该功能（仅管理员）')
    }
    return Promise.reject(error.response?.data ?? error)
  }
)

export default request
