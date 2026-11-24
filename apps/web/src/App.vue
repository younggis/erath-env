<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { store } from './store'
import GlobeView from './components/GlobeView.vue'
import LayerPanel from './components/LayerPanel.vue'
import Timeline from './components/Timeline.vue'
import DetailPanel from './components/DetailPanel.vue'
import LocationBar from './components/LocationBar.vue'

const clock = ref('')
let timer = 0

function navForecast() {
  const l = store.state.layers.find(x => x.kind === 'forecast')
  if (l) store.selectLayer(l.layer_id)
}

onMounted(() => {
  store.init()
  const tick = () => { clock.value = new Date().toISOString().slice(11, 19) + ' UTC' }
  tick(); timer = window.setInterval(tick, 1000)
})
const error = computed(() => store.state.apiError)
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">◉</div>
        <div><b>地球环境模拟器</b><span>EARTH ENVIRONMENT SIMULATOR</span></div>
      </div>
      <nav class="nav">
        <button @click="navForecast">看预报</button>
      </nav>
      <div class="top-right">
        <span class="clock">{{ clock }}</span>
        <span class="live" :class="store.state.mode">{{ store.state.mode === 'fixture' ? '● 演示' : '● 在线' }}</span>
      </div>
    </header>

    <div v-if="error" class="error-bar">⚠ {{ error }} <button @click="store.init()">重试</button></div>

    <main class="layout">
      <LayerPanel class="left" />
      <section class="stage">
        <LocationBar />
        <div class="stage-body"><GlobeView /></div>
        <Timeline />
      </section>
      <aside class="right">
        <DetailPanel />
      </aside>
    </main>

    <footer class="footer">
      <span>{{ store.state.status }}</span>
      <span>EPSG:4326 · WGS84 · API v1 · {{ store.activeLayer.value?.attribution || '—' }}</span>
    </footer>
  </div>
</template>

<style scoped>
.app { height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--text); }
.topbar {
  height: 62px; display: flex; align-items: center; padding: 0 20px; gap: 28px;
  border-bottom: 1px solid var(--line); background: rgba(8, 14, 24, .95);
}
.brand { display: flex; align-items: center; gap: 10px; }
.brand-mark { font-size: 24px; color: var(--accent); text-shadow: 0 0 18px rgba(94,200,255,.6); }
.brand div:last-child { display: flex; flex-direction: column; }
.brand b { font-size: 14px; letter-spacing: .04em; }
.brand span { font: 9px ui-monospace, monospace; color: var(--muted); letter-spacing: .14em; }
.nav { display: flex; gap: 6px; }
.nav button { padding: 8px 16px; border-radius: 7px; border: 1px solid transparent; background: transparent; color: var(--muted); font-size: 12.5px; cursor: pointer; transition: .18s; }
.nav button:hover { color: var(--text); background: rgba(255,255,255,.05); }
.nav button.active { color: var(--accent); background: rgba(94,200,255,.1); border-color: rgba(94,200,255,.3); }
.top-right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
.clock { font: 11px ui-monospace, monospace; color: var(--muted); }
.live { font-size: 11px; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--line); }
.live.fixture { color: #ffd479; border-color: rgba(255,212,121,.35); }
.live.live { color: #6ef0b4; border-color: rgba(110,240,180,.35); }
.error-bar { padding: 8px 18px; background: rgba(220,70,70,.15); border-bottom: 1px solid rgba(220,70,70,.4); color: #ffb3b3; font-size: 12px; }
.error-bar button { margin-left: 12px; background: transparent; border: 1px solid #ffb3b3; color: #ffb3b3; border-radius: 5px; cursor: pointer; }
.layout { flex: 1; display: grid; grid-template-columns: 248px 1fr 330px; min-height: 0; }
.left, .right { border-right: 1px solid var(--line); background: rgba(10, 17, 28, .72); min-height: 0; }
.right { border-right: 0; border-left: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; }
.stage { display: flex; flex-direction: column; min-width: 0; min-height: 0; position: relative; }
.stage-body { flex: 1; min-height: 0; }
.footer { height: 30px; padding: 0 18px; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--line); font: 10px ui-monospace, monospace; color: var(--muted); }
@media (max-width: 1100px) { .layout { grid-template-columns: 200px 1fr 280px; } }
</style>
