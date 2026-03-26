/**
 * API 调用封装
 * 
 * 统一管理所有后端 API 请求
 */
import axios from 'axios'

// 创建 axios 实例
const api = axios.create({
  baseURL: '/api',
  timeout: 120000, // 采集和分析可能需要较长时间
  headers: {
    'Content-Type': 'application/json',
  },
})

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// ============================================
// 配置管理 API
// ============================================

/**
 * 检查配置是否存在
 */
export const checkConfig = () => api.get('/config/check')

/**
 * 获取当前配置
 */
export const getConfig = () => api.get('/config')

/**
 * 保存配置
 */
export const saveConfig = (config) => api.put('/config', config)

/**
 * 上传 .env 文件
 */
export const uploadEnvFile = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/config/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
}

// ============================================
// Mock 数据 API
// ============================================

/**
 * 上传 Mock 数据文件
 */
export const uploadMockData = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/mock/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
}

/**
 * 获取 Mock 数据示例
 */
export const getMockSample = () => api.get('/mock/sample')

/**
 * 获取完整 Mock 数据模板
 */
export const getMockTemplate = () => api.get('/mock/template')

// ============================================
// 数据采集 API
// ============================================

/**
 * 获取可用采集器列表
 */
export const getCollectors = () => api.get('/collect/collectors')

/**
 * 采集单个采集器（应由前端串行调用）
 * @param {string} collector - 采集器名称
 */
export const runOneCollection = (collector) =>
  api.post('/collect/one', { collectors: [collector] })

// ============================================
// 评估分析 API
// ============================================

/**
 * 获取所有分析器列表
 */
export const getAnalyzers = () => api.get('/analyze/analyzers')

/**
 * 获取数据就绪状态
 * @param {string[]} keys - 分析器 key 列表，不传则获取全部
 */
export const getDataStatus = (keys = null) => {
  const params = keys ? { keys: keys.join(',') } : {}
  return api.get('/analyze/data-status', { params })
}

/**
 * 执行评估分析
 * @param {string[]} keys - 分析器 key 列表，空数组表示全部
 */
export const runAnalysis = (keys = []) => 
  api.post('/analyze', { keys })

// ============================================
// 健康检查 API
// ============================================

/**
 * 健康检查
 */
export const healthCheck = () => api.get('/health')

export default api
