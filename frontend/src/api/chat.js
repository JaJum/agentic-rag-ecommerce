/**
 * 会话与问答 API：会话 CRUD / 历史 / 反馈 / 导出 / 停止生成
 * （流式问答走 useSSE.js 的 fetch 流，不在 axios 封装内）
 */
import request from './request'

/** 会话列表 */
export function listSessions() {
  return request.get('/sessions')
}

/** 新建会话 */
export function createSession(title) {
  return request.post('/sessions', { title })
}

/** 重命名会话 */
export function renameSession(sessionId, title) {
  return request.patch(`/sessions/${sessionId}`, { title })
}

/** 删除会话（软删） */
export function deleteSession(sessionId) {
  return request.delete(`/sessions/${sessionId}`)
}

/** 历史消息（含引用） */
export function getSessionMessages(sessionId) {
  return request.get(`/sessions/${sessionId}/messages`)
}

/** 点赞/点踩 */
export function feedback(messageId, rating) {
  return request.post(`/chat/messages/${messageId}/feedback`, { rating })
}

/** 导出对话 Markdown */
export function exportSession(sessionId) {
  return request.get(`/chat/sessions/${sessionId}/export`, { params: { format: 'md' } })
}

/** 停止生成 */
export function stopGeneration(sessionId) {
  return request.post('/chat/stop', { session_id: sessionId })
}

/** 查询消息的 Agent 执行轨迹（回放） */
export function getMessageTrace(messageId) {
  return request.get(`/chat/messages/${messageId}/trace`)
}
