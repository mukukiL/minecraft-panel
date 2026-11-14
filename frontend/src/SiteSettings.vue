<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Image, ImagePlus, Palette, Save, Trash2 } from '@lucide/vue'
import { applyBranding, branding, loadBranding, type SiteBranding } from './branding'
import { api, explain } from './session'

type Slot = 'portrait' | 'background'
const slots = [
  { key: 'portrait', label: '头图' },
  { key: 'background', label: '背景图' },
] as const
const initialTitle = ref(branding.value.title)
const title = ref(initialTitle.value)
const files = reactive<Partial<Record<Slot, File>>>({})
const inputKeys = reactive({ portrait: 0, background: 0 })
const loading = ref(true)
const loaded = ref(false)
const saving = ref(false)
const message = ref('')
const error = ref('')

async function reload() {
  loading.value = true
  error.value = ''
  try {
    await loadBranding()
    initialTitle.value = title.value = branding.value.title
    loaded.value = true
  } catch (err) {
    error.value = explain(err)
  } finally {
    loading.value = false
  }
}
onMounted(reload)

async function save(path: string, options: RequestInit, success: string) {
  if (saving.value || !loaded.value) return false
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    applyBranding(await api<SiteBranding>(path, options))
    message.value = success
    return true
  } catch (err) {
    error.value = explain(err)
    return false
  } finally {
    saving.value = false
  }
}

async function saveTitle() {
  if (!title.value.trim()) return
  if (await save('/site', { method: 'PATCH', body: JSON.stringify({ title: title.value.trim() }) }, '标题已保存。')) {
    initialTitle.value = title.value = branding.value.title
  }
}

async function uploadImage(slot: Slot, label: string) {
  const file = files[slot]
  if (!file) return
  if (file.size > 5 * 1024 ** 2) {
    message.value = ''
    error.value = '请选择 5 MB 以内的图片。'
    return
  }
  if (await save('/site/images/' + slot, {
    method: 'PUT',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  }, label + '已更新。')) {
    delete files[slot]
    inputKeys[slot]++
  }
}
</script>

<template>
  <main class="shell">
    <div class="heading dashboard-heading">
      <div>
        <h1>站点设置</h1>
        <p class="settings-subtitle">标题和图片保存后会显示在访客首页。</p>
      </div>
      <Palette :size="48" aria-hidden="true" />
    </div>
    <p v-if="error" class="notice" role="alert">{{ error }}</p>
    <button v-if="!loaded && !loading" class="secondary" @click="reload">重新加载</button>
    <p v-else-if="loading" class="card" role="status">正在加载站点设置…</p>
    <template v-else>
      <form class="card settings-title" @submit.prevent="saveTitle">
        <h2><Palette :size="18" /> 站点标题</h2>
        <div class="command-input">
          <label class="settings-title-field">网页标题
            <input v-model="title" maxlength="64" required :disabled="saving">
          </label>
          <button :disabled="saving || !title.trim() || title.trim() === initialTitle">
            <Save :size="16" /> 保存标题
          </button>
        </div>
      </form>
      <div class="metric-grid">
        <section v-for="slot in slots" :key="slot.key" class="card">
          <h2><Image :size="18" /> {{ slot.label }}</h2>
          <div class="site-image-preview" :class="slot.key">
            <img v-if="branding[slot.key]" :src="branding[slot.key] ?? undefined" :alt="slot.label + '预览'">
            <span v-else>使用默认样式</span>
          </div>
          <label class="site-image-file">{{ '选择' + slot.label }}
            <input :key="inputKeys[slot.key]" type="file" accept="image/jpeg,image/png,image/webp"
              :disabled="saving" @change="files[slot.key] = ($event.target as HTMLInputElement).files?.[0]">
          </label>
          <div class="actions">
            <button :disabled="saving || !files[slot.key]" @click="uploadImage(slot.key, slot.label)">
              <ImagePlus :size="16" /> 上传{{ slot.label }}
            </button>
            <button v-if="branding[slot.key]" class="secondary" :disabled="saving"
              @click="save('/site/images/' + slot.key, { method: 'DELETE' }, slot.label + '已移除。')">
              <Trash2 :size="16" /> 移除{{ slot.label }}
            </button>
          </div>
        </section>
      </div>
      <p class="card settings-feedback" role="status" v-if="message || saving">{{ saving ? '正在保存…' : message }}</p>
    </template>
  </main>
</template>
