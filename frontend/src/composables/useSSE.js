/**
 * POST 触发的 SSE 流式解析（需求 2 核心交互）。
 * EventSource 不支持 POST/自定义头，故用 fetch + ReadableStream 手动解析 SSE 帧。
 * 事件协议：meta → citation* → (reasoning*) → token* → done | fallback | error
 */
export function useSSE() {
  /**
   * 发起流式问答。
   * @param {{sessionId?: string, query: string}} payload
   * @param {{onEvent: (event: string, data: object) => void}} handlers
   * @param {AbortSignal} [signal] 可中断（停止生成）
   */
  async function streamChat(payload, handlers, signal) {
    const token = localStorage.getItem('token')
    const resp = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ session_id: payload.sessionId ?? null, query: payload.query }),
      signal
    })
    if (!resp.ok) {
      throw new Error(`流式请求失败: ${resp.status}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 帧以空行分隔；最后一段可能不完整，留在 buffer 里
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        let event = 'message'
        let data = ''
        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim()
          else if (line.startsWith('data: ')) data += line.slice(6)
          // 以 ":" 开头的是心跳注释（ping），忽略
        }
        if (data) {
          try {
            handlers.onEvent(event, JSON.parse(data))
          } catch {
            /* 心跳/非 JSON 帧跳过 */
          }
        }
      }
    }
  }

  return { streamChat }
}
