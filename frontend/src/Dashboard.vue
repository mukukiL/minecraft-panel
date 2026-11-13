<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, explain } from './session'

type Action = 'start' | 'stop' | 'restart'
type Status = { state: string; adapter: string; controls: Action[]; upload_available: boolean }
const status = ref<Status>()
const lines = ref<string[]>([])
const error = ref('')
const uploadMessage = ref('')
const pending = ref<Action>()
const busy = ref(false)
const uploading = ref(false)
const file = ref<File>()
const selectedFile = ref<HTMLInputElement>()
const names: Record<Action, string> = { start: '启动', stop: '停止', restart: '重启' }
const states: Record<string, string> = {
  running: '运行中', stopped: '已停止', starting: '启动中', unknown: '未知',
  port_conflict: '端口冲突', session_present: '会话存在', session_absent: '未发现会话',
}

async function refresh() {
  try {
    const [server, log] = await Promise.all([
      api<Status>('/server/status'), api<{lines: string[]}>('/console/logs?limit=100'),
    ])
    status.value = server
    lines.value = log.lines
  } catch (err) { error.value = explain(err) }
}
let interval: ReturnType<typeof setInterval>
onMounted(() => { void refresh(); interval = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(interval))

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
    <div class="heading"><h1>服务器仪表盘</h1><button class="secondary" @click="refresh">刷新</button></div>
    <p v-if="error" class="notice" role="alert">{{ error }}</p>
    <section class="card server-card" aria-labelledby="server-heading">
      <div>
        <h2 id="server-heading">服务器状态</h2>
        <p class="state"><span :class="{ running: status?.state === 'running' }" aria-hidden="true"></span>{{ status ? (states[status.state] ?? status.state) : '读取中…' }}</p>
        <p class="muted">{{ status?.adapter === 'mock' ? '模拟服务器' : status?.adapter }}</p>
      </div>
      <div class="actions">
        <button v-for="action in status?.controls" :key="action" :class="{ secondary: action !== 'start' }" :disabled="busy || !!pending"
          @click="action === 'start' ? perform(action) : (pending = action)">{{ names[action] }}</button>
      </div>
      <div v-if="pending" class="confirm">
        <span>确认{{ names[pending] }}服务器？</span>
        <button class="secondary" @click="pending = undefined">取消</button>
        <button @click="perform(pending)">确认{{ names[pending] }}</button>
      </div>
    </section>
    <section class="card">
      <h2>服务器日志</h2>
      <pre class="console">{{ lines.length ? lines.join('\n') : '暂无日志' }}</pre>
    </section>
    <section v-if="status?.upload_available" class="card">
      <h2>上传 Mod</h2>
      <p class="muted">上传的 .jar 文件进入禁用区。</p>
      <form class="actions" @submit.prevent="upload">
        <input ref="selectedFile" type="file" accept=".jar" aria-label="选择 Mod 文件" @change="file = ($event.target as HTMLInputElement).files?.[0]">
        <button :disabled="!file || uploading">{{ uploading ? '正在上传…' : '上传' }}</button>
      </form>
      <p v-if="uploadMessage" role="status">{{ uploadMessage }}</p>
    </section>
  </main>
</template>
