<script setup lang="ts">
import { ref } from 'vue'
import { X, SmilePlus, Sparkles } from 'lucide-vue-next'

const props = defineProps<{
  initialEmojis?: string
  initialIntensity?: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', payload: { emojis: string; intensity: number }): void
  (e: 'remove'): void
}>()

const currentEmojis = ref(props.initialEmojis || '🔥')
const intensityPct = ref(Math.round((props.initialIntensity || 0.85) * 100))

const QUICK_EMOJIS = [
  '🔥', '✨', '🎤', '👑', '🚀', '💖', '💣', '🥂', '💔', '💥', '⚡', '🎸', '🌹', '😈', '👽'
]

function toggleEmoji(em: string) {
  if (currentEmojis.value.includes(em)) {
    // Remove if already included and not sole character
    if (currentEmojis.value.length > 2) {
      currentEmojis.value = currentEmojis.value.replace(em, '').trim()
    }
  } else {
    currentEmojis.value = (currentEmojis.value + em).trim()
  }
}

function onApply() {
  const ems = currentEmojis.value.trim() || '🔥'
  emit('apply', {
    emojis: ems,
    intensity: intensityPct.value / 100,
  })
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-md bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <SmilePlus class="w-5 h-5 text-purple-400" />
          <span>Настройка салюта эмодзи</span>
        </h2>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Body -->
      <div class="p-5 space-y-4 text-xs">
        <div>
          <label class="text-slate-300 font-medium block mb-2">Быстрый выбор эмодзи:</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="em in QUICK_EMOJIS"
              :key="em"
              type="button"
              @click="toggleEmoji(em)"
              :class="[
                'w-10 h-10 text-xl rounded-xl border flex items-center justify-center transition-all',
                currentEmojis.includes(em)
                  ? 'border-purple-500 bg-purple-500/20 shadow-md shadow-purple-950/40 ring-1 ring-purple-400'
                  : 'border-studio-border bg-studio-surface hover:bg-slate-700'
              ]"
            >
              {{ em }}
            </button>
          </div>
        </div>

        <div>
          <label class="text-slate-300 font-medium block mb-1">
            Выбранные эмодзи (можно вводить любые с клавиатуры):
          </label>
          <input
            v-model="currentEmojis"
            type="text"
            placeholder="🔥✨👑"
            class="w-full bg-studio-surface border border-studio-border rounded-lg px-3 py-2 text-base text-white tracking-widest focus:outline-none focus:border-purple-500"
          />
        </div>

        <!-- Intensity Slider -->
        <div class="pt-2 border-t border-studio-border space-y-2">
          <div class="flex justify-between">
            <span class="font-medium text-slate-300">Интенсивность (частота частиц):</span>
            <span class="font-mono text-purple-400 font-semibold">{{ intensityPct }}%</span>
          </div>
          <input
            type="range"
            min="10"
            max="100"
            step="5"
            v-model.number="intensityPct"
            class="w-full bg-slate-700 h-1.5 rounded cursor-pointer"
          />
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-studio-border bg-studio-surface/40 flex items-center justify-between">
        <button
          @click="emit('remove')"
          class="px-3 py-1.5 text-xs font-medium rounded text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
        >
          Удалить с выделения
        </button>

        <div class="flex space-x-2">
          <button
            @click="emit('close')"
            class="px-4 py-2 text-xs font-medium rounded-lg text-slate-300 hover:text-white transition-colors"
          >
            Отмена
          </button>
          <button
            @click="onApply"
            class="px-5 py-2 text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-500 text-white shadow-md transition-colors flex items-center space-x-1.5"
          >
            <Sparkles class="w-3.5 h-3.5" />
            <span>Применить эмодзи</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
