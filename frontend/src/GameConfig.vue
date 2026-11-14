<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FileSliders, History, RefreshCw, Save } from '@lucide/vue'
import { ApiError, api, explain } from './session'

type Field = {
  key: string; label: string; value: string; kind: 'text' | 'number' | 'select' | 'boolean'
  choices?: Record<string, string>; min?: number; max?: number; max_length?: number
}
type Config = {
  revision: string
  fields: Field[]
  restore: { key: string; before: string; after: string }[]
  restart_required?: boolean
}
const config = ref<Config>()
const draft = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
const notice = ref('')
const review = ref<'save' | 'restore'>()
const changes = computed(() => (config.value?.fields ?? []).filter(field => draft.value[field.key] !== field.value))
const labels = computed(() => Object.fromEntries((config.value?.fields ?? []).map(field => [field.key, field.label])))
const preview = computed(() => review.value === 'restore'
  ? (config.value?.restore ?? []).map(item => ({ key: item.key, from: item.after, to: item.before }))
  : changes.value.map(field => ({ key: field.key, from: field.value, to: draft.value[field.key] })))

function loadDraft(snapshot: Config) {
  config.value = snapshot
  draft.value = Object.fromEntries(snapshot.fields.map(field => [field.key, field.value]))
}

async function load() {
  if (busy.value) return
  busy.value = true
  error.value = notice.value = ''
  review.value = undefined
  try {
    loadDraft(await api<Config>('/server/config'))
  } catch (err) {
    error.value = explain(err)
  } finally {
    busy.value = false
  }
}

function reload() {
  if (!changes.value.length || window.confirm('重新读取会丢弃尚未保存的修改。继续吗？')) void load()
}

async function save() {
  if (!config.value || !review.value || busy.value) return
  busy.value = true
  error.value = notice.value = ''
  const restoring = review.value === 'restore'
  const body = { revision: config.value.revision }
  try {
    const snapshot = await api<Config>(restoring ? '/server/config/restore' : '/server/config', {
      method: restoring ? 'POST' : 'PATCH',
      body: JSON.stringify(restoring ? body : {
        ...body,
        changes: Object.fromEntries(changes.value.map(field => [field.key, draft.value[field.key]])),
      }),
    })
    loadDraft(snapshot)
    review.value = undefined
    notice.value = snapshot.restart_required ? '文件已保存，游戏服将在下次启动时读取。' : '文件内容没有变化。'
  } catch (err) {
    error.value = explain(err)
    if (err instanceof ApiError && err.code === 'CONFIG_STALE') review.value = undefined
  } finally {
    busy.value = false
  }
}

function display(key: string, value: string) {
  const field = config.value?.fields.find(item => item.key === key)
  if (field?.kind === 'boolean') return value === 'true' ? '启用' : value === 'false' ? '关闭' : value
  return field?.choices?.[value] ?? (value || '（空）')
}

onMounted(load)
</script>

<template>
  <main class="shell">
    <div class="heading dashboard-heading">
      <div>
        <h1>游戏配置</h1>
        <p class="settings-subtitle">编辑 server.properties 中的常用选项。</p>
      </div>
      <FileSliders :size="48" aria-hidden="true" />
    </div>
    <p v-if="error" class="notice" role="alert">{{ error }}</p>
    <p v-if="notice" class="card settings-feedback" role="status">
      {{ notice }} <RouterLink class="text-link" to="/manage">打开服务器管理</RouterLink>
    </p>
    <section class="card">
      <div class="card-heading">
        <h2>服务器属性</h2>
        <button class="secondary" :disabled="busy" @click="reload"><RefreshCw :size="16" /> 重新读取</button>
      </div>
      <p v-if="!config && busy" role="status">正在读取配置…</p>
      <form v-if="config?.fields.length" @submit.prevent="review = 'save'">
        <div class="metric-grid game-config-grid">
          <label v-for="field in config.fields" :key="field.key" :class="{ 'full-width': field.kind === 'text' }">
            <span>{{ field.label }} <small class="field-key">{{ field.key }}</small></span>
            <select v-if="field.kind === 'boolean' || field.kind === 'select'" v-model="draft[field.key]" :disabled="busy">
              <template v-if="field.kind === 'boolean'">
                <option v-if="!['true', 'false'].includes(field.value)" :value="field.value">{{ field.value || '（空）' }}</option>
                <option value="true">启用</option>
                <option value="false">关闭</option>
              </template>
              <template v-else>
                <option v-if="!Object.hasOwn(field.choices ?? {}, field.value)" :value="field.value">{{ field.value || '（空）' }}</option>
                <option v-for="(label, value) in field.choices" :key="value" :value="value">{{ label }}</option>
              </template>
            </select>
            <input v-else v-model="draft[field.key]" :maxlength="field.max_length ?? 4"
              :inputmode="field.kind === 'number' ? 'numeric' : 'text'"
              :pattern="field.kind === 'number' && draft[field.key] !== field.value ? '[0-9]{1,4}' : undefined"
              :required="field.kind === 'number' && draft[field.key] !== field.value" :disabled="busy">
            <small v-if="field.kind === 'number'" class="field-key">{{ field.min }}–{{ field.max }}</small>
          </label>
        </div>
        <div class="actions config-actions">
          <button :disabled="!changes.length || busy"><Save :size="16" /> 查看改动<span v-if="changes.length">（{{ changes.length }}）</span></button>
          <button type="button" class="secondary" :disabled="!config.restore.length || busy"
            @click="review = 'restore'"><History :size="16" /> 恢复上次修改</button>
        </div>
      </form>
      <p v-else-if="config" class="muted">当前文件中没有可编辑的常用属性。</p>
    </section>
    <Transition name="reveal">
      <section v-if="review" class="card" aria-labelledby="config-review">
        <h2 id="config-review">{{ review === 'restore' ? '确认恢复' : '确认保存' }}</h2>
        <div class="table-scroll">
          <table class="config-diff">
            <thead><tr><th>属性</th><th>当前值</th><th>保存后</th></tr></thead>
            <tbody>
              <tr v-for="item in preview" :key="item.key">
                <td>{{ labels[item.key] ?? item.key }}</td>
                <td>{{ display(item.key, item.from) }}</td>
                <td>{{ display(item.key, item.to) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted">修改将在下次启动时生效。可在服务器管理页选择重启时间。</p>
        <div class="actions">
          <button :disabled="busy || !preview.length" @click="save"><Save :size="16" /> {{ review === 'restore' ? '确认恢复' : '确认保存' }}</button>
          <button class="secondary" :disabled="busy" @click="review = undefined">取消</button>
        </div>
      </section>
    </Transition>
  </main>
</template>
