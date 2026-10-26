<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePlayerStore } from '@/stores/player'
import {
  Play,
  Pause,
  Repeat,
  Volume2,
  VolumeX,
  Mic2,
  SkipBack,
} from 'lucide-vue-next'

const projectStore = useProjectStore()
const playerStore = usePlayerStore()

const videoRef = ref<HTMLVideoElement | null>(null)
const audioRef = ref<HTMLAudioElement | null>(null)
const isMuted = ref(false)

const videoUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/video?t=${Date.now()}`
})

const vocalsUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/vocals`
})

const coverUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/cover?t=${projectStore.coverTimestamp}`
})

function formatTime(sec: number): string {
  if (!sec || isNaN(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${cs.toString().padStart(2, '0')}`
}

function handleTimeUpdate() {
  if (videoRef.value) {
    playerStore.onTimeUpdate(videoRef.value.currentTime)
  }
}

function handleVideoEnded() {
  playerStore.pause()
}

function toggleMute() {
  isMuted.value = !isMuted.value
  playerStore.setMasterVolume(isMuted.value ? 0 : 1.0)
}

function onMasterVolumeChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value) / 100
  isMuted.value = val === 0
  playerStore.setMasterVolume(val)
}

function onVocalMultiplierChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value) / 100
  playerStore.setLiveVocalMultiplier(val)
}

function jumpToSelectionStart() {
  if (playerStore.selStart !== null) {
    playerStore.seek(playerStore.selStart)
  } else {
    playerStore.seek(0)
  }
}

// Global hotkeys (Space for play/pause)
function handleKeyDown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
    return
  }
  if (e.code === 'Space') {
    e.preventDefault()
    playerStore.togglePlay()
  }
}

watch(
  [() => videoRef.value, () => audioRef.value],
  ([v, a]) => {
    playerStore.bindMedia(v, a)
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="flex-1 flex flex-col bg-studio-bg overflow-hidden min-h-0 border-r border-studio-border">
    <!-- Video Stage / Canvas Area -->
    <div class="flex-1 flex items-center justify-center p-3 relative overflow-hidden bg-black/60">
      <div v-if="projectStore.hasProject" class="relative max-h-full max-w-full aspect-video flex items-center justify-center rounded-lg overflow-hidden shadow-2xl border border-studio-border/60 bg-black">
        <video
          ref="videoRef"
          :src="videoUrl"
          :poster="coverUrl"
          @timeupdate="handleTimeUpdate"
          @ended="handleVideoEnded"
          class="w-full h-full object-contain"
          playsinline
        ></video>

        <!-- Hidden dry vocal track synced with video -->
        <audio
          ref="audioRef"
          :src="vocalsUrl"
          preload="auto"
        ></audio>
      </div>

      <div v-else class="text-center text-studio-muted">
        <Mic2 class="w-16 h-16 mx-auto mb-3 opacity-30 animate-pulse text-sky-400" />
        <p class="text-sm font-medium">Нет открытого проекта</p>
        <p class="text-xs text-slate-500 mt-1">Выберите трек из списка сверху или создайте новый</p>
      </div>
    </div>

    <!-- Transport & Mixer Bar -->
    <div class="h-14 bg-studio-panel border-t border-studio-border px-4 flex items-center justify-between shrink-0 select-none">
      <!-- Left: Playback controls -->
      <div class="flex items-center space-x-3">
        <button
          @click="playerStore.togglePlay()"
          :disabled="!projectStore.hasProject"
          class="w-9 h-9 rounded-full flex items-center justify-center bg-sky-600 hover:bg-sky-500 text-white shadow transition-all disabled:opacity-40"
        >
          <Pause v-if="playerStore.isPlaying" class="w-4 h-4 fill-current" />
          <Play v-else class="w-4 h-4 fill-current ml-0.5" />
        </button>

        <button
          @click="jumpToSelectionStart"
          :disabled="!projectStore.hasProject"
          title="В начало выделения"
          class="p-2 rounded text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 transition-colors"
        >
          <SkipBack class="w-4 h-4" />
        </button>

        <button
          @click="playerStore.toggleLoop()"
          :class="[
            'p-2 rounded text-xs flex items-center space-x-1 border transition-colors',
            playerStore.isLooping
              ? 'bg-sky-600/30 border-sky-500 text-sky-300'
              : 'border-studio-border text-studio-muted hover:text-white hover:bg-studio-surface'
          ]"
          title="Зациклить воспроизведение выделения"
        >
          <Repeat class="w-4 h-4" />
        </button>

        <!-- Timecode Display -->
        <div class="font-mono text-sm tracking-wider text-slate-200 bg-studio-surface px-2.5 py-1 rounded border border-studio-border/70">
          <span class="text-sky-400 font-semibold">{{ formatTime(playerStore.currentTime) }}</span>
          <span class="text-studio-muted mx-1">/</span>
          <span class="text-slate-400">{{ formatTime(projectStore.duration) }}</span>
        </div>
      </div>

      <!-- Right: Audio Mix Controls -->
      <div class="flex items-center space-x-6">
        <!-- Live Vocal Multiplier (Practice Lead Vocals) -->
        <div class="flex items-center space-x-2" title="Подмешивание оригинального голоса в динамики для разучивания (0% = чистый минус)">
          <Mic2 class="w-4 h-4 text-emerald-400 shrink-0" />
          <span class="text-xs text-slate-300 whitespace-nowrap">Лид-вокал:</span>
          <input
            type="range"
            min="0"
            max="150"
            step="5"
            :value="playerStore.liveVocalMultiplier * 100"
            @input="onVocalMultiplierChange"
            class="w-24 h-1.5 bg-slate-700 rounded-lg cursor-pointer"
          />
          <span class="text-xs font-mono text-emerald-400 w-9 text-right">
            {{ Math.round(playerStore.liveVocalMultiplier * 100) }}%
          </span>
        </div>

        <div class="h-4 w-px bg-studio-border"></div>

        <!-- Master Volume -->
        <div class="flex items-center space-x-2">
          <button @click="toggleMute" class="text-slate-400 hover:text-white transition-colors">
            <VolumeX v-if="isMuted || playerStore.masterVolume === 0" class="w-4 h-4 text-red-400" />
            <Volume2 v-else class="w-4 h-4 text-slate-300" />
          </button>
          <input
            type="range"
            min="0"
            max="100"
            :value="playerStore.masterVolume * 100"
            @input="onMasterVolumeChange"
            class="w-20 h-1.5 bg-slate-700 rounded-lg cursor-pointer"
          />
        </div>
      </div>
    </div>
  </div>
</template>
