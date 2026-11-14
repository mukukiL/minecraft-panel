<script setup lang="ts">
import { computed, ref, useId } from 'vue'

const props = defineProps<{
  points: { time: number; value: number | null }[]
  label: string
}>()
const chartId = useId()
const width = 400
const height = 128
const hovered = ref<number>()
const dots = computed(() => {
  const first = props.points[0]?.time ?? 0
  const last = props.points.at(-1)?.time ?? first
  return props.points.flatMap((point, index) => {
    if (point.value === null) return []
    return [{
      ...point,
      value: point.value,
      x: last === first ? width : (point.time - first) / (last - first) * width,
      y: height - point.value / 100 * (height - 10) - 5,
      breakBefore: index > 0 && props.points[index - 1]?.value === null,
    }]
  })
})
const line = computed(() => dots.value.map((point, index) =>
  `${index === 0 || point.breakBefore ? 'M' : 'L'}${point.x},${point.y}`).join(' '))
const area = computed(() => {
  if (dots.value.length < 2 || dots.value.some(point => point.breakBefore)) return ''
  return `${line.value} L${dots.value.at(-1)?.x},${height} L${dots.value[0].x},${height} Z`
})
const selected = computed(() => {
  if (hovered.value === undefined) return dots.value.at(-1)
  const x = hovered.value
  return dots.value.reduce<typeof dots.value[number] | undefined>((closest, point) =>
    !closest || Math.abs(point.x - x) < Math.abs(closest.x - x) ? point : closest, undefined)
})

function inspect(event: PointerEvent) {
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect()
  hovered.value = (event.clientX - bounds.left) / bounds.width * width
}
</script>

<template>
  <div class="metric-value">{{ selected ? selected.value.toFixed(1) : '—' }}<small v-if="selected">%</small></div>
  <div class="plot">
    <svg :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none"
      role="img" :aria-label="label + '趋势'" @pointermove="inspect" @pointerleave="hovered = undefined">
      <defs>
        <linearGradient :id="chartId" x1="0" x2="0" y1="0" y2="1">
          <stop stop-color="currentColor" stop-opacity=".24" />
          <stop offset="100%" stop-color="currentColor" stop-opacity=".02" />
        </linearGradient>
      </defs>
      <path d="M0,5H400 M0,64H400 M0,123H400" class="plot-grid" />
      <path v-if="area" :d="area" :fill="`url(#${chartId})`" />
      <path :d="line" fill="none" stroke="currentColor" stroke-width="2.5" vector-effect="non-scaling-stroke" />
      <line v-if="selected && hovered !== undefined" :x1="selected.x" :x2="selected.x" y1="0" :y2="height"
        stroke="currentColor" stroke-dasharray="4 4" opacity=".45" />
      <circle v-if="selected" :cx="selected.x" :cy="selected.y" r="4" fill="currentColor" />
    </svg>
    <div class="plot-scale" aria-hidden="true"><span>100%</span><span>50%</span><span>0%</span></div>
  </div>
  <div class="plot-caption">
    {{ !selected ? '等待采样' : hovered === undefined ? '最新采样' : new Date(selected.time * 1000).toLocaleTimeString() }}
  </div>
</template>
