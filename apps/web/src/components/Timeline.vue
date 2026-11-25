<script setup lang="ts">
import { computed } from 'vue'
import { store } from '../store'

const times = computed(() => store.state.frames.map((f, i) => ({ i, time: f.valid_time })))
const current = computed(() => store.state.frames[store.state.frameIndex])
const fmt = (t: string) => t ? t.replace('T', ' ').replace('Z', ' UTC') : '—'
function togglePlay() { store.state.playing = !store.state.playing }
</script>

<template>
  <div class="timeline">
    <div class="tl-controls">
      <button class="play" @click="togglePlay" :title="store.state.playing ? '暂停' : '播放'">
        {{ store.state.playing ? '❚❚' : '▶' }}
      </button>
      <select v-model.number="store.state.speed" class="speed" title="播放倍率">
        <option :value="0.5">0.5×</option><option :value="1">1×</option>
        <option :value="2">2×</option><option :value="4">4×</option>
      </select>
    </div>
    <div class="tl-track">
      <input type="range" min="0" :max="Math.max(0, times.length - 1)" :value="store.state.frameIndex"
             @input="store.setFrame(+($event.target as HTMLInputElement).value)" />
      <div class="tl-labels">
        <span>{{ fmt(times[0]?.time) }}</span>
        <span class="tl-current">{{ fmt(current?.valid_time) }}</span>
        <span>{{ fmt(times[times.length - 1]?.time) }}</span>
      </div>
    </div>
    <div class="tl-meta">
      <span class="tag">全球预报</span>
      <span>{{ store.activeLayer.value?.attribution || '—' }}</span>
      <span v-if="store.state.missingTimes.length" class="gaps" :title="store.state.missingTimes.join('\n')">⚠ {{ store.state.missingTimes.length }} 个缺帧</span>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 18px;
  padding: 12px 18px; border-top: 1px solid var(--line); background: rgba(9, 16, 27, .92);
  backdrop-filter: blur(10px); min-height: 72px;
}
.tl-controls { display: flex; align-items: center; gap: 8px; }
.play {
  width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line);
  background: rgba(255,255,255,.05); color: var(--text); cursor: pointer; font-size: 12px;
}
.play:hover { border-color: var(--accent); color: var(--accent); }
.speed { background: transparent; color: var(--muted); border: 1px solid var(--line); border-radius: 6px; padding: 6px; font-size: 12px; }
.tl-track input { width: 100%; accent-color: var(--accent); cursor: pointer; }
.tl-labels { display: flex; justify-content: space-between; font: 11px ui-monospace, monospace; color: var(--muted); margin-top: 2px; }
.tl-current { color: var(--accent); font-weight: 700; }
.tl-meta { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted); max-width: 220px; }
.tag { padding: 3px 8px; border-radius: 4px; background: rgba(94, 200, 255, .14); color: var(--accent); font-weight: 700; }
.gaps { color: #ffd479; cursor: help; white-space: nowrap; }
</style>
