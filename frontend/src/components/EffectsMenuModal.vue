<script setup lang="ts">
import { ref } from 'vue'
import {
  X,
  Zap,
  Siren,
  Sparkles,
  Flame,
  Rainbow,
  Layers,
} from 'lucide-vue-next'

const props = defineProps<{
  initialEffect?: string
  initialIntensity?: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', payload: { effect: string; intensity: number }): void
  (e: 'remove'): void
}>()

const selectedEffect = ref(props.initialEffect || 'sparkles_pulse')
const intensityPct = ref(Math.round((props.initialIntensity || 0.85) * 100))

const FX_PRESETS = [
  {
    id: 'sparkles_pulse',
    name: 'Припев (Неон + Блестки)',
    desc: 'Пульсация рамки в такт битам и парящие золотые искры',
    icon: Zap,
    color: 'from-purple-500 to-indigo-600',
    badge: '#8b5cf6',
  },
  {
    id: 'police_strobe',
    name: 'Полицейская мигалка',
    desc: 'Красно-синий стробоскоп с бегущими точками вокруг рамки',
    icon: Siren,
    color: 'from-red-600 via-white to-blue-600',
    badge: '#ef4444',
  },
  {
    id: 'green_neon',
    name: 'Зеленый неон (Acid Lime)',
    desc: 'Кислотно-зеленый и изумрудный неоновый ореол вокруг экрана',
    icon: Flame,
    color: 'from-emerald-400 to-lime-500',
    badge: '#10b981',
  },
  {
    id: 'sparkles',
    name: 'Золотые блестки',
    desc: 'Нежные парящие золотые частицы боке без мерцания рамки',
    icon: Sparkles,
    color: 'from-amber-400 to-yellow-500',
    badge: '#f59e0b',
  },
  {
    id: 'climax',
    name: 'Климакс (Максимум)',
    desc: 'Двойная мощность неоновой рамки и плотный поток искр',
    icon: Layers,
    color: 'from-pink-500 to-rose-600',
    badge: '#ec4899',
  },
  {
    id: 'neon_rainbow',
    name: 'Неоновая радуга',
    desc: 'Иридесцентные спектральные переливы по периметру',
    icon: Rainbow,
    color: 'from-sky-400 via-purple-400 to-pink-500',
    badge: '#06b6d4',
  },
]

function onApply() {
  emit('apply', {
    effect: selectedEffect.value,
    intensity: intensityPct.value / 100,
  })
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-xl bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden max-h-[90vh]">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <span>Меню визуальных эффектов сцены</span>
        </h2>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Presets Grid -->
      <div class="p-5 overflow-y-auto space-y-4">
        <div class="text-xs text-studio-muted">
          Выберите эффект для выделенного интервала на таймлайне:
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div
            v-for="p in FX_PRESETS"
            :key="p.id"
            @click="selectedEffect = p.id"
            :class="[
              'p-3.5 rounded-xl border text-left cursor-pointer transition-all flex flex-col justify-between space-y-2',
              selectedEffect === p.id
                ? 'border-sky-500 bg-sky-600/15 shadow-md shadow-sky-950/40 ring-1 ring-sky-500'
                : 'border-studio-border bg-studio-surface/50 hover:bg-studio-surface hover:border-slate-600'
            ]"
          >
            <div class="flex items-center space-x-2.5">
              <div :class="['w-8 h-8 rounded-lg flex items-center justify-center bg-gradient-to-br text-white shadow-sm', p.color]">
                <component :is="p.icon" class="w-4 h-4" />
              </div>
              <span class="text-xs font-semibold text-white">{{ p.name }}</span>
            </div>
            <p class="text-[11px] text-slate-400 leading-snug">
              {{ p.desc }}
            </p>
          </div>
        </div>

        <!-- Intensity Slider -->
        <div class="pt-3 border-t border-studio-border space-y-2">
          <div class="flex justify-between text-xs">
            <span class="font-medium text-slate-300">Интенсивность свечения и частиц:</span>
            <span class="font-mono text-sky-400 font-semibold">{{ intensityPct }}%</span>
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
          Удалить эффект с выделения
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
            class="px-5 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow-md transition-colors"
          >
            Применить эффект
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
