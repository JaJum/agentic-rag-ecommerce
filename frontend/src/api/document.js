/**
 * 知识库管理 API（仅 admin）：
 * 上传（多文件）/ 列表 / 分块预览 / 重建索引 / 删除
 */
import request from './request'

/** 上传文档（multipart 多文件），doc_type: auto/param/faq/prose */
export function uploadDocuments(files, docType = 'auto') {
  const formData = new FormData()
  for (const f of files) {
    formData.append('files', f.raw ?? f)
  }
  formData.append('doc_type', docType)
  return request.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 文档列表（按上传时间倒序） */
export function listDocuments() {
  return request.get('/documents')
}

/** 分块预览（分页） */
export function getDocumentChunks(docId, page = 1, size = 10) {
  return request.get(`/documents/${docId}/chunks`, { params: { page, size } })
}

/** 重建索引（重跑入库链路） */
export function reindexDocument(docId) {
  return request.post(`/documents/${docId}/reindex`)
}

/** 删除文档 */
export function deleteDocument(docId) {
  return request.delete(`/documents/${docId}`)
}
