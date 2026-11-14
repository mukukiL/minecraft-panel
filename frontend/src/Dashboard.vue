<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, explain } from './session'
import { Copy, Maximize2, Minimize2, Play, RefreshCw, RotateCcw, Send, Server, Square, Terminal, Upload } from '@lucide/vue'
import { branding } from './branding'

type Action = 'start' | 'stop' | 'restart'
type Status = { state: string; adapter: string; controls: Action[]; upload_available: boolean; console_available: boolean }
const status = ref<Status>()
const lines = ref<string[]>([])
const refreshing = ref(false)
const expandedLogs = ref(false)
const copyMessage = ref('')
const command = ref('')
const sending = ref(false)
const commandMessage = ref('')
const error = ref('')
const uploadMessage = ref('')
const pending = ref<Action>()
const busy = ref(false)
const uploading = ref(false)
const file = ref<File>()
const selectedFile = ref<HTMLInputElement>()
const names: Record<Action, string> = { start: '启动', stop: '停止', restart: '重启' }
const actionIcons = { start: Play, stop: Square, restart: RotateCcw }
const states: Record<string, string> = {
  running: '运行中', stopped: '已停止', starting: '启动中', unknown: '未知',
  port_conflict: '端口冲突', session_present: '会话存在', session_absent: '未发现会话',
}

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const [server, log] = await Promise.all([
      api<Status>('/server/status'), api<{lines: string[]}>('/console/logs?limit=100'),
    ])
    status.value = server
    lines.value = log.lines
  } catch (err) { error.value = explain(err) }
  finally { refreshing.value = false }
}
let interval: ReturnType<typeof setInterval>
onMounted(() => { void refresh(); interval = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(interval))

async function copyLogs() {
  copyMessage.value = ''
  try {
    await navigator.clipboard.writeText(lines.value.join('\n'))
    copyMessage.value = '日志已复制'
  } catch {
    copyMessage.value = '复制失败，请选中文字后手动复制。'
  }
}

async function sendCommand() {
  const value = command.value.trim()
  if (!value || sending.value) return
  sending.value = true
  commandMessage.value = ''
  try {
    await api('/console/command', { method: 'POST', body: JSON.stringify({ command: value }) })
    command.value = ''
    commandMessage.value = '命令已发送，输出见日志。'
    await refresh()
  } catch (err) {
    commandMessage.value = explain(err)
  } finally {
    sending.value = false
  }
}

async function perform(action: Action) {
  pending.value = undefined
  busy.value = true
  error.value = ''
  try {
    await api('/server/' + action, {
      method: 'POST',
      body: action === 'start' ? undefined : JSON.stringify({ confirm: action.toUpperCase() }),
    })
  } catch (err) { error.value = explain(err) }
  finally { busy.value = false; await refresh() }
}
async function upload() {
  if (!file.value) return
  uploading.value = true
  uploadMessage.value = ''
  error.value = ''
  try {
    const result = await api<{ filename: string; location: string }>('/mods/upload/' + encodeURIComponent(file.value.name), {
      method: 'PUT', headers: { 'Content-Type': 'application/java-archive' }, body: file.value,
    })
    uploadMessage.value = result.location === 'simulated'
      ? `模拟校验通过 · ${result.filename}` : `已保存到禁用区 · ${result.filename}`
    file.value = undefined
    if (selectedFile.value) selectedFile.value.value = ''
  } catch (err) { error.value = explain(err) }
  finally { uploading.value = false }
}
</script>

<template>
  <main class="shell">
    <div class="heading dashboard-heading">
      <div>
        <h1>服务器仪表盘</h1>
        <button class="secondary refresh-button" :disabled="refreshing" @click="refresh">
          <RefreshCw :size="16" :class="{ spinning: refreshing }" aria-hidden="true" />
          {{ refreshing ? '刷新中' : '刷新' }}
        </button>
      </div>
      <img v-if="branding.portrait" class="dashboard-portrait" :src="branding.portrait" alt="" width="128" height="128">
      <Server v-else :size="56" aria-hidden="true" />
    </div>
    <p v-if="error" class="notice" role="alert">{{ error }}</p>
    <section class="card server-card" aria-labelledby="server-heading">
      <div>
        <h2 id="server-heading"><Server :size="18" /> 服务器状态</h2>
        <p class="state" role="status"><span class="state-dot" :class="{ running: status?.state === 'running' }" aria-hidden="true"></span>{{ status ? (states[status.state] ?? status.state) : '读取中…' }}</p>
        <p class="muted">{{ status?.adapter === 'mock' ? '模拟服务器' : status?.adapter }}</p>
      </div>
      <div class="actions">
        <button v-for="action in status?.controls" :key="action" :class="{ secondary: action !== 'start' }" :disabled="busy || !!pending"
          @click="action === 'start' ? perform(action) : (pending = action)">
          <component :is="actionIcons[action]" :size="16" /> {{ names[action] }}
        </button>
      </div>
      <Transition name="reveal">
        <div v-if="pending" class="confirm" role="group" :aria-label="'确认' + names[pending]">
          <span>确认{{ names[pending] }}服务器？</span>
          <button class="secondary" @click="pending = undefined">取消</button>
          <button @click="perform(pending)">确认{{ names[pending] }}</button>
        </div>
      </Transition>
    </section>
    <section class="card">
      <div class="card-heading">
        <h2 id="console-heading"><Terminal :size="18" /> 服务器控制台</h2>
        <div class="actions">
          <button class="secondary" :disabled="!lines.length" @click="copyLogs"><Copy :size="16" /> 复制日志</button>
          <button class="secondary" aria-controls="server-log" :aria-expanded="expandedLogs" @click="expandedLogs = !expandedLogs">
            <component :is="expandedLogs ? Minimize2 : Maximize2" :size="16" />
            {{ expandedLogs ? '缩小' : '放大' }}
          </button>
        </div>
      </div>
      <pre id="server-log" class="console" :class="{ expanded: expandedLogs }" tabindex="0" aria-labelledby="console-heading">{{ lines.length ? lines.join('\n') : '暂无日志' }}</pre>
      <p v-if="copyMessage" class="feedback" role="status">{{ copyMessage }}</p>
      <form v-if="status?.console_available" class="command-form" @submit.prevent="sendCommand">
        <label for="game-command">Minecraft 命令</label>
        <div class="command-input">
          <input id="game-command" v-model="command" placeholder="list" maxlength="2048" autocomplete="off"
            :disabled="status.state !== 'running' || sending">
          <button :disabled="!command.trim() || status.state !== 'running' || sending">
            <Send :size="16" /> {{ sending ? '发送中' : '发送' }}
          </button>
        </div>
        <p v-if="commandMessage" class="feedback" role="status">{{ commandMessage }}</p>
      </form>
    </section>
    <section v-if="status?.upload_available" class="card">
      <h2><Upload :size="18" /> 上传 Mod</h2>
      <p class="muted">上传的 .jar 文件进入禁用区。</p>
      <form class="actions" @submit.prevent="upload">
        <input ref="selectedFile" type="file" accept=".jar" aria-label="选择 Mod 文件" @change="file = ($event.target as HTMLInputElement).files?.[0]">
        <button :disabled="!file || uploading">{{ uploading ? '正在上传…' : '上传' }}</button>
      </form>
      <p v-if="uploadMessage" role="status">{{ uploadMessage }}</p>
    </section>
  </main>
</template>
