<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Activity, Clock3, Cpu, MemoryStick, Radio, Server, WifiOff } from '@lucide/vue'
import { api } from './session'
import MetricChart from './MetricChart.vue'
import { customBranding, portrait } from './branding'

type Sample = { time: number; cpu: number | null; memory: number | null }
type Snapshot = { state: string; samples: Sample[] }
const snapshot = ref<Snapshot>()
const disconnected = ref(false)
const range = ref(5)
const metrics = [
  { key: 'cpu', label: 'CPU 使用率', icon: Cpu },
  { key: 'memory', label: '内存使用率', icon: MemoryStick },
] as const
const states: Record<string, string> = {
  running: '运行中', stopped: '已停止', starting: '启动中', unknown: '状态未知',
  port_conflict: '端口冲突', session_present: '会话存在', session_absent: '未发现会话',
}
const online = computed(() => !disconnected.value && snapshot.value?.state === 'running')
const stateText = computed(() => {
  if (disconnected.value) return '连接中断'
  if (!snapshot.value) return '正在连接'
  return states[snapshot.value.state] ?? '状态未知'
})
const lastUpdate = computed(() => snapshot.value?.samples.at(-1)?.time)
const samples = computed(() => {
  const latest = lastUpdate.value ?? 0
  return snapshot.value?.samples.filter(sample => sample.time >= latest - range.value * 60) ?? []
})
let active = false
let timer: ReturnType<typeof setTimeout>
async function refresh() {
  try {
    snapshot.value = await api<Snapshot>('/public/monitor', { signal: AbortSignal.timeout(4000) })
    disconnected.value = false
  } catch {
    disconnected.value = true
  } finally {
    if (active) timer = setTimeout(refresh, 5000)
  }
}
onMounted(() => { active = true; void refresh() })
onUnmounted(() => { active = false; clearTimeout(timer) })
</script>

<template>
  <main class="shell monitor-page">
    <section class="monitor-hero" aria-labelledby="monitor-title">
      <div class="hero-content">
        <div class="hero-icon"><Server :size="23" /></div>
        <h1 id="monitor-title">Minecraft 服务器</h1>
        <div class="hero-meta">
          <span class="status-pill" :class="{ online }" role="status">
            <span class="state-dot" :class="{ running: online }" aria-hidden="true"></span>
            {{ stateText }}
          </span>
          <span class="sample-time" v-if="lastUpdate && !disconnected">
            <Clock3 :size="15" /> 更新于 {{ new Date(lastUpdate * 1000).toLocaleTimeString() }}
          </span>
        </div>
      </div>
      <div class="hero-art">
        <img v-if="customBranding" :src="portrait" alt="" width="216" height="216" fetchpriority="high">
        <Activity v-else :size="104" :stroke-width="1" aria-hidden="true" />
      </div>
    </section>
    <section aria-labelledby="metrics-title" class="monitor-metrics">
      <div class="metrics-heading">
        <h2 id="metrics-title"><Activity :size="21" /> 主机性能</h2>
        <div class="range-picker" role="group" aria-label="图表时间范围">
          <button v-for="minutes in [1, 5, 10]" :key="minutes" type="button" :aria-pressed="range === minutes"
            @click="range = minutes">{{ minutes }} 分钟</button>
        </div>
      </div>
      <p v-if="disconnected" class="notice" role="status"><WifiOff :size="16" /> 暂时无法获取新采样，正在重连。</p>
      <div class="metric-grid">
        <article v-for="metric in metrics" :key="metric.key" class="card metric-card" :class="metric.key">
          <h3><span class="metric-icon"><component :is="metric.icon" :size="20" /></span>{{ metric.label }}</h3>
          <MetricChart :label="metric.label" :points="samples.map(sample => ({ time: sample.time, value: sample[metric.key] }))" />
        </article>
      </div>
      <p class="sampling-note"><Radio :size="15" /> 每 5 秒采样一次</p>
    </section>
  </main>
</template>
