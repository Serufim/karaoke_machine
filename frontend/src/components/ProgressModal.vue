<script setup lang="ts">
import { computed } from 'vue'
import { usePipelineStore } from '@/stores/pipeline'
import {
  Loader2,
  XOctagon,
  CheckCircle2,
  AlertCircle,
} from 'lucide-vue-next'

const pipelineStore = usePipelineStore()

const percentage = computed(() => {
  return Math.round((pipelineStore.progressFraction || 0) * 100)
})

const isError = computed(() => pipelineStore.stage === 'error')
const isSuccess = computed(() => pipelineStore.stage === 'completed')
</script>

<template>
  <div
    v-if="pipelineStore.showModal"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4"
  >
    <div class="w-full max-w-md bg-studio-panel border border-studio-border rounded-xl shadow-2xl p-6 text-center space-y-4">
      <!-- Status Icon -->
      <div class="flex justify-center">
        <div v-if="isSuccess" class="w-14 h-14 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
          <CheckCircle2 class="w-8 h-8" />
        </div>
        <div v-else-if="isError" class="w-14 h-14 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center">
          <AlertCircle class="w-8 h-8" />
        </div>
        <div v-else class="w-14 h-14 rounded-full bg-sky-500/20 text-sky-400 flex items-center justify-center">
          <Loader2 class="w-8 h-8 animate-spin" />
        </div>
      </div>

      <!-- Stage & Percentage -->
      <div>
        <h3 class="text-base font-semibold text-white">
          {{ isSuccess ? 'Готово!' : isError ? 'Ошибка обработки' : 'Обработка караоке' }}
        </h3>
        <p class="text-xs text-slate-300 mt-1 min-h-[1.5rem] leading-relaxed">
          {{ pipelineStore.statusMessage }}
        </p>
      </div>

      <!-- Progress Bar -->
      <div v-if="!isError" class="space-y-1">
        <div class="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden border border-studio-border/60">
          <div
            class="bg-gradient-to-r from-sky-500 to-indigo-500 h-2.5 rounded-full transition-all duration-300"
            :style="{ width: `${percentage}%` }"
          ></div>
        </div>
        <div class="text-[11px] font-mono text-studio-muted text-right">
          {{ percentage }}%
        </div>
      </div>

      <!-- Action Button -->
      <div class="pt-2">
        <button
          v-if="pipelineStore.isRunning"
          @click="pipelineStore.cancel()"
          class="inline-flex items-center space-x-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-red-600/20 text-red-300 border border-red-500/30 hover:bg-red-600/30 transition-colors"
        >
          <XOctagon class="w-4 h-4" />
          <span>Отменить операцию</span>
        </button>

        <button
          v-else
          @click="pipelineStore.showModal = false"
          class="px-5 py-2 rounded-lg text-xs font-semibold bg-studio-surface hover:bg-slate-700 text-white border border-studio-border transition-colors"
        >
          Закрыть
        </button>
      </div>
    </div>
  </div>
</template>
