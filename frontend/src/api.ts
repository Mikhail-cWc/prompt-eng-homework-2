export function safeMessage(value: unknown): string {
  const message = String(value ?? 'Не удалось выполнить запрос')
  if (/failed to fetch|networkerror|load failed/i.test(message)) return 'Связь с сервером прервана. Переподключаемся…'
  return message
    .replace(/(?:Bearer|Api-Key)\s+[^\s"',}]+/gi, '[скрыто]')
    .replace(/(?:api[_-]?key|authorization|access[_-]?token|iam[_-]?token)(\s*[=:]\s*)[^\s"',}]+/gi, '$1[скрыто]')
    .replace(/(?:AQVN|y0__|t1\.)[a-zA-Z0-9_.-]{10,}/g, '[скрыто]')
    .slice(0, 500)
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : `Ошибка сервера (${response.status})`
    throw Object.assign(new Error(safeMessage(typeof detail === 'string' ? detail : JSON.stringify(detail))), { status: response.status })
  }
  return response.json() as Promise<T>
}
