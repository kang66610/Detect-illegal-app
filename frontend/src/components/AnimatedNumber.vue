<template><span class="animated-number">{{ display }}</span></template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { interpolateInteger } from '../utils/uiMotion'

const props = defineProps({ value: { type: Number, required: true } })
const display = ref(0)
let frame = null

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}
function animate(nextValue) {
  cancelAnimationFrame(frame)
  const startValue = display.value
  const target = Number(nextValue) || 0
  if (prefersReducedMotion() || startValue === target) {
    display.value = target
    return
  }
  const startedAt = performance.now()
  const duration = 440
  const tick = (now) => {
    const progress = Math.min(1, (now - startedAt) / duration)
    // Ease-out keeps the last few increments calm instead of mechanical.
    display.value = interpolateInteger(startValue, target, 1 - Math.pow(1 - progress, 3))
    if (progress < 1) frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)
}

onMounted(() => animate(props.value))
watch(() => props.value, animate)
onBeforeUnmount(() => cancelAnimationFrame(frame))
</script>

<style scoped>
.animated-number { display: inline-block; font-variant-numeric: tabular-nums; }
</style>
