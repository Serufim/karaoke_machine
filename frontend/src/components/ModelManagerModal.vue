<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useModelsStore } from '@/stores/models'
import {
  X,
  Cpu,
  HardDrive,
  Download,
  Trash2,
  CheckCircle,
  AlertTriangle,
  Search,
  Sparkles,
  Zap,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const modelsStore = useModelsStore()

const activeTab = ref<'all' | 'whisper' | 'demucs' | 'aligner'>('all')
const searchQuery = ref('')

onMounted(async () => {
  await Promise.all([
    modelsStore.fetchHardware(),
    modelsStore.fetchCatalog(),
  ])
})

const filteredModels = computed(() => {
  return modelsStore.models.filter((m) => {
    if (activeTab.value !== 'all' && m.type !== activeTab.value) {
      return false
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      return (
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q)
      )
    }
    return true
  })
})

function formatSize(mb: number | null | undefined): string {
  if (!mb) return '—'
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${Math.round(mb)} MB`
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
    <div class="w-full max-w-3xl bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden max-h-[90vh]">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between bg-studio-surface/50">
        <div class="flex items-center space-x-2">
          <HardDrive class="w-5 h-5 text-sky-400" />
          <h2 class="text-base font-semibold text-white">Менеджер нейросетевых моделей</h2>
        </div>
        <button
          @click="emit('close')"
          class="text-studio-muted hover:text-white transition-colors"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Hardware Profile Banner -->
      <div
        v-if="modelsStore.hardware"
        class="mx-5 mt-4 p-3 rounded-lg border flex items-center justify-between text-xs"
        :class="[
          modelsStore.hardware.gpu_type === 'cuda'
            ? 'bg-emerald-950/30 border-emerald-800/50 text-emerald-300'
            : modelsStore.hardware.gpu_type === 'mps'
            ? 'bg-sky-950/30 border-sky-800/50 text-sky-300'
            : 'bg-amber-950/30 border-amber-800/50 text-amber-300'
        ]"
      >
        <div class="flex items-center space-x-3">
          <Cpu class="w-5 h-5 flex-shrink-0" />
          <div>
            <div class="font-semibold flex items-center space-x-2">
              <span>{{ modelsStore.hardware.gpu_name }}</span>
              <span
                class="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider"
                :class="modelsStore.hardware.gpu_type === 'cuda' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-sky-500/20 text-sky-300'"
              >
                {{ modelsStore.hardware.gpu_type }}
              </span>
            </div>
            <div class="text-[11px] opacity-80 mt-0.5">
              VRAM: {{ modelsStore.hardware.vram_gb }} GB &bull; RAM: {{ modelsStore.hardware.ram_gb }} GB &bull;
              Процессор: {{ modelsStore.hardware.cpu_cores }} ядер
            </div>
          </div>
        </div>
        <div class="text-right pl-3 border-l border-white/10">
          <div class="text-[10px] uppercase tracking-wider opacity-70">Режим системы</div>
          <div class="font-bold text-xs uppercase">{{ modelsStore.hardware.tier }}</div>
        </div>
      </div>

      <!-- Controls: Tabs + Search -->
      <div class="px-5 pt-4 pb-2 flex flex-col sm:flex-row items-center justify-between gap-3">
        <!-- Tabs -->
        <div class="flex rounded-lg bg-studio-surface p-1 border border-studio-border text-xs w-full sm:w-auto">
          <button
            @click="activeTab = 'all'"
            :class="[
              'px-3 py-1 rounded font-medium transition-colors',
              activeTab === 'all' ? 'bg-sky-600 text-white' : 'text-studio-muted hover:text-white'
            ]"
          >
            Все
          </button>
          <button
            @click="activeTab = 'whisper'"
            :class="[
              'px-3 py-1 rounded font-medium transition-colors',
              activeTab === 'whisper' ? 'bg-sky-600 text-white' : 'text-studio-muted hover:text-white'
            ]"
          >
            Whisper (Текст)
          </button>
          <button
            @click="activeTab = 'demucs'"
            :class="[
              'px-3 py-1 rounded font-medium transition-colors',
              activeTab === 'demucs' ? 'bg-sky-600 text-white' : 'text-studio-muted hover:text-white'
            ]"
          >
            Demucs (Вокал)
          </button>
          <button
            @click="activeTab = 'aligner'"
            :class="[
              'px-3 py-1 rounded font-medium transition-colors',
              activeTab === 'aligner' ? 'bg-sky-600 text-white' : 'text-studio-muted hover:text-white'
            ]"
          >
            Aligner (Слоги)
          </button>
        </div>

        <!-- Search -->
        <div class="relative w-full sm:w-64">
          <Search class="w-4 h-4 text-studio-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Поиск моделей..."
            class="w-full bg-studio-surface border border-studio-border rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-studio-muted focus:outline-none focus:border-sky-500"
          />
        </div>
      </div>

      <!-- Models List -->
      <div class="p-5 overflow-y-auto space-y-3 flex-1 min-h-[300px]">
        <div
          v-for="model in filteredModels"
          :key="model.id"
          class="p-4 rounded-xl border border-studio-border bg-studio-surface/40 hover:bg-studio-surface/70 transition-colors flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
        >
          <!-- Info -->
          <div class="space-y-1.5 flex-1">
            <div class="flex items-center space-x-2 flex-wrap gap-y-1">
              <span class="text-sm font-semibold text-white">{{ model.name }}</span>
              <span
                class="px-2 py-0.5 rounded text-[10px] font-medium"
                :class="{
                  'bg-sky-500/20 text-sky-300': model.type === 'whisper',
                  'bg-emerald-500/20 text-emerald-300': model.type === 'demucs',
                  'bg-purple-500/20 text-purple-300': model.type === 'aligner',
                }"
              >
                {{ model.type }}
              </span>

              <span
                v-if="model.is_default"
                class="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-300 flex items-center space-x-1"
              >
                <Sparkles class="w-3 h-3" />
                <span>По умолчанию</span>
              </span>

              <span
                v-if="modelsStore.hardware && (modelsStore.hardware.recommended_whisper === model.id || modelsStore.hardware.recommended_demucs === model.id)"
                class="px-2 py-0.5 rounded text-[10px] font-medium bg-teal-500/20 text-teal-300 flex items-center space-x-1"
              >
                <Zap class="w-3 h-3" />
                <span>Рекомендовано</span>
              </span>
            </div>

            <p class="text-xs text-studio-muted leading-relaxed">
              {{ model.description }}
            </p>

            <!-- Resource Specs -->
            <div class="flex items-center space-x-3 text-[11px] text-slate-400 pt-1 flex-wrap gap-y-1">
              <span>Загрузка: <b class="text-slate-200">{{ formatSize(model.download_size_mb) }}</b></span>
              <span>&bull;</span>
              <span>Требуется VRAM: <b class="text-slate-200">{{ model.min_vram_gb }} GB</b></span>
              <span>&bull;</span>
              <span>RAM: <b class="text-slate-200">{{ model.min_ram_gb }} GB</b></span>

              <!-- Warning if low VRAM -->
              <span
                v-if="modelsStore.hardware && modelsStore.hardware.vram_gb < model.min_vram_gb && modelsStore.hardware.gpu_type === 'cuda'"
                class="text-amber-400 flex items-center space-x-1 ml-2 font-medium"
              >
                <AlertTriangle class="w-3.5 h-3.5" />
                <span>Может быть медленной на вашей карте</span>
              </span>
            </div>
          </div>

          <!-- Actions / Status -->
          <div class="flex items-center space-x-2 self-end md:self-center flex-shrink-0">
            <!-- Downloaded -->
            <div v-if="model.is_downloaded" class="flex items-center space-x-2">
              <span class="px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 text-xs font-medium flex items-center space-x-1.5">
                <CheckCircle class="w-3.5 h-3.5" />
                <span>Готова ({{ formatSize(model.size_on_disk_mb) }})</span>
              </span>
              <button
                @click="modelsStore.deleteModel(model.id)"
                title="Удалить кэш модели"
                class="p-2 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>

            <!-- Downloading Progress -->
            <div v-else-if="model.status === 'downloading'" class="w-36 space-y-1">
              <div class="flex justify-between text-[11px] text-sky-400">
                <span>Загрузка...</span>
                <span>{{ model.progress }}%</span>
              </div>
              <div class="w-full h-1.5 bg-studio-surface rounded-full overflow-hidden">
                <div
                  class="h-full bg-sky-500 transition-all duration-300"
                  :style="{ width: `${model.progress}%` }"
                ></div>
              </div>
            </div>

            <!-- Not downloaded -->
            <button
              v-else
              @click="modelsStore.downloadModel(model.id)"
              class="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium transition-colors flex items-center space-x-1.5 shadow"
            >
              <Download class="w-3.5 h-3.5" />
              <span>Скачать</span>
            </button>
          </div>
        </div>

        <div v-if="filteredModels.length === 0" class="text-center py-12 text-studio-muted text-xs">
          Модели по запросу «{{ searchQuery }}» не найдены.
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-studio-border bg-studio-surface/40 flex justify-between items-center text-xs text-studio-muted">
        <span>Все загруженные модели сохраняются в локальном изолированном кэше.</span>
        <button
          @click="emit('close')"
          class="px-4 py-1.5 rounded-lg bg-studio-surface hover:bg-studio-border text-white transition-colors"
        >
          Закрыть
        </button>
      </div>
    </div>
  </div>
</template>
