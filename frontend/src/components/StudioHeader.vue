<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useModelsStore } from '@/stores/models'
import {
  Mic,
  PlusCircle,
  Save,
  Video,
  Undo2,
  Redo2,
  FolderOpen,
  RefreshCw,
  Cpu,
  HardDrive,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'open-new'): void
  (e: 'open-export'): void
  (e: 'open-models'): void
}>()

const projectStore = useProjectStore()
const modelsStore = useModelsStore()

onMounted(() => {
  modelsStore.fetchHardware()
})

const currentTitle = computed(() => projectStore.currentProject?.title || '')


function onSelectProject(e: Event) {
  const target = e.target as HTMLSelectElement
  if (target.value) {
    projectStore.loadProject(target.value)
  }
}
</script>

<template>
  <header class="h-14 bg-studio-panel border-b border-studio-border px-4 flex items-center justify-between z-10 shrink-0">
    <!-- Left: Brand & Project Selector -->
    <div class="flex items-center space-x-4">
      <div class="flex items-center space-x-2 text-sky-400 font-bold text-lg tracking-wide">
        <Mic class="w-6 h-6 text-sky-400" />
        <span class="bg-gradient-to-r from-sky-400 to-indigo-400 bg-clip-text text-transparent">
          AI Karaoke Studio
        </span>
      </div>

      <div class="h-5 w-px bg-studio-border"></div>

      <!-- Project Picker -->
      <div class="flex items-center space-x-2">
        <FolderOpen class="w-4 h-4 text-studio-muted" />
        <select
          :value="currentTitle"
          @change="onSelectProject"
          class="bg-studio-surface border border-studio-border text-sm rounded px-2.5 py-1 text-slate-200 focus:outline-none focus:border-sky-500 max-w-xs truncate"
        >
          <option value="" disabled>-- Выберите проект --</option>
          <option
            v-for="p in projectStore.projects"
            :key="p.title"
            :value="p.title"
          >
            {{ p.title }} {{ p.has_video ? '🎬' : '' }}
          </option>
        </select>

        <button
          @click="projectStore.fetchProjects()"
          title="Обновить список"
          class="p-1 text-studio-muted hover:text-white rounded hover:bg-studio-surface transition-colors"
        >
          <RefreshCw class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- Dirty state indicator -->
      <span
        v-if="projectStore.isDirty"
        class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30"
      >
        Не сохранены изменения
      </span>
    </div>

    <!-- Right: Action Buttons -->
    <div class="flex items-center space-x-2.5">
      <!-- Undo / Redo -->
      <button
        @click="projectStore.undo()"
        :disabled="!projectStore.canUndo"
        title="Отменить (Ctrl+Z)"
        class="p-1.5 rounded text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Undo2 class="w-4 h-4" />
      </button>

      <button
        @click="projectStore.redo()"
        :disabled="!projectStore.canRedo"
        title="Повторить (Ctrl+Y)"
        class="p-1.5 rounded text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Redo2 class="w-4 h-4" />
      </button>

      <!-- Hardware & Models Button -->
      <button
        @click="emit('open-models')"
        class="flex items-center space-x-1.5 px-2.5 py-1.5 text-xs font-medium rounded bg-studio-surface hover:bg-slate-700 text-slate-200 border border-studio-border transition-colors"
        title="Менеджер моделей и параметры оборудования"
      >
        <span
          class="w-2 h-2 rounded-full"
          :class="modelsStore.hardware?.gpu_type === 'cuda' ? 'bg-emerald-400' : modelsStore.hardware?.gpu_type === 'mps' ? 'bg-sky-400' : 'bg-amber-400'"
        ></span>
        <HardDrive class="w-3.5 h-3.5 text-studio-muted" />
        <span class="max-w-[130px] truncate hidden md:inline">
          {{ modelsStore.hardware ? (modelsStore.hardware.gpu_type === 'cuda' ? 'CUDA ' + modelsStore.hardware.vram_gb + 'G' : modelsStore.hardware.gpu_type === 'mps' ? 'Apple Silicon' : 'CPU Режим') : 'Модели' }}
        </span>
      </button>

      <div class="h-5 w-px bg-studio-border"></div>

      <!-- Save Button -->
      <button
        @click="projectStore.saveProject()"
        :disabled="!projectStore.hasProject || !projectStore.isDirty"
        class="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium rounded bg-studio-surface hover:bg-slate-700 text-slate-200 border border-studio-border disabled:opacity-40 transition-colors"
      >
        <Save class="w-3.5 h-3.5 text-sky-400" />
        <span>Сохранить</span>
      </button>

      <!-- Rebuild Button -->
      <button
        @click="emit('open-export')"
        :disabled="!projectStore.hasProject"
        class="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded bg-sky-600 hover:bg-sky-500 text-white shadow-sm disabled:opacity-40 transition-colors"
      >
        <Video class="w-3.5 h-3.5" />
        <span>Пересобрать MP4</span>
      </button>

      <!-- New Project Button -->
      <button
        @click="emit('open-new')"
        class="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm transition-colors"
      >
        <PlusCircle class="w-3.5 h-3.5" />
        <span>Новый трек</span>
      </button>
    </div>
  </header>
</template>
