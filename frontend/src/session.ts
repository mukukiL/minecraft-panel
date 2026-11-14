import { shallowRef } from 'vue'

export type Role = 'admin' | 'operator' | 'viewer'
export type User = { id: number; username: string; role: Role; enabled: boolean; scopes: string[] }
type Session = { user: User; csrf_token: string; expires_at: string }

export const session = shallowRef<Session | null>(null)
export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(code) }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (typeof options.body === 'string') headers.set('Content-Type', 'application/json')
  if (session.value && options.method && options.method !== 'GET') {
    headers.set('X-CSRF-Token', session.value.csrf_token)
  }
  const response = await fetch('/api/v1' + path, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') session.value = null
    const error = await response.json().catch(() => ({}))
    throw new ApiError(response.status, error.code ?? 'REQUEST_FAILED')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

const messages: Record<string, string> = {
  FORBIDDEN: '当前角色没有操作权限。',
  LAST_ACTIVE_ADMIN: '至少保留一个启用的管理员。',
  USERNAME_TAKEN: '该用户名已被使用。',
  WEAK_PASSWORD: '请输入至少 12 个字符且与用户名不同的强密码。',
  INVALID_CREDENTIALS: '用户名或密码错误。',
  INVALID_INPUT: '请检查输入格式。',
  UPLOAD_TOO_LARGE: '文件超过上传大小限制。',
  SITE_IMAGE_TOO_LARGE: '请选择 5 MB 以内的图片。',
  INVALID_SITE_IMAGE: '请选择有效的 JPG、PNG 或 WebP 静态图片，尺寸不超过 6000 像素且总像素不超过 1600 万。',
  SITE_UPLOAD_BUSY: '正在处理另一张图片，请稍后再试。',
  INVALID_JAR: '文件不是有效的 JAR 容器。',
  INVALID_JAR_NAME: '文件名须使用字母、数字、点、下划线或短横线，并以 .jar 结尾。',
  MOD_EXISTS: '已有同名文件，请修改文件名。',
  CONTROL_BUSY: '服务器正在执行操作。',
  CONSOLE_UNAVAILABLE: '当前服务器未启用命令控制台。',
  CONSOLE_SEND_FAILED: '命令发送失败，请确认服务器仍在运行。',
  TMUX_PANE_UNVERIFIED: '无法确认 Minecraft 控制台，操作已取消。',
  SERVER_ALREADY_RUNNING: '服务器已经在运行。',
  SERVER_NOT_RUNNING: '服务器当前未运行。',
  SERVER_RUNNING_TIMEOUT: '启动后未在时限内确认运行，请检查日志。',
  SERVER_STOPPED_TIMEOUT: '未在时限内确认停止，请检查日志。',
  UPLOAD_STORAGE_UNAVAILABLE: '无法写入禁用区，请检查服务器配置。',
}
export function explain(error: unknown): string {
  if (error instanceof ApiError) return messages[error.code] ?? `操作失败（${error.code}）。`
  return '连接失败，请检查面板是否在线。'
}

export async function restore() {
  session.value = await api<Session>('/auth/me')
}

export async function login(username: string, password: string) {
  session.value = await api<Session>('/auth/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  })
}

export async function logout() {
  await api('/auth/logout', { method: 'POST' })
  session.value = null
}
