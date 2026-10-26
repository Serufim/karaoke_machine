<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
  HardDrive,
  ChevronDown,
  Check,
  Film,
  Music,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'open-new'): void
  (e: 'open-export'): void
  (e: 'open-models'): void
}>()

const projectStore = useProjectStore()
const modelsStore = useModelsStore()

const isDropdownOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

const currentTitle = computed(() => projectStore.currentProject?.title || '')

function selectProject(title: string) {
  isDropdownOpen.value = false
  if (title && title !== currentTitle.value) {
    projectStore.loadProject(title)
  }
}

function handleClickOutside(e: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    isDropdownOpen.value = false
  }
}

onMounted(() => {
  modelsStore.fetchHardware()
  window.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('mousedown', handleClickOutside)
})
</script>

<template>
  <header class="h-14 bg-studio-panel border-b border-studio-border px-4 flex items-center justify-between z-30 shrink-0 select-none">
    <!-- Left: Brand & Custom Project Selector -->
    <div class="flex items-center space-x-3.5">
      <div class="flex items-center space-x-2 text-sky-400 font-bold text-lg tracking-wide">
        <div class="w-8 h-8 rounded-lg bg-sky-500/15 border border-sky-500/30 flex items-center justify-center shadow-inner">
          <Mic class="w-4 h-4 text-sky-400" />
        </div>
        <span class="bg-gradient-to-r from-sky-400 via-cyan-300 to-indigo-400 bg-clip-text text-transparent">
          AI Karaoke Studio
        </span>
      </div>

      <div class="h-5 w-px bg-studio-border"></div>

      <!-- Custom Modern Project Picker Dropdown -->
      <div ref="dropdownRef" class="relative flex items-center space-x-1.5">
        <button
          type="button"
          @click="isDropdownOpen = !isDropdownOpen"
          class="group flex items-center justify-between space-x-2.5 bg-[#131c2e] hover:bg-[#19253d] border border-[#26354d] hover:border-sky-500/70 rounded-lg px-3 py-1.5 text-xs text-slate-100 shadow-sm transition-all min-w-[240px] max-w-[340px]"
        >
          <div class="flex items-center space-x-2 min-w-0">
            <FolderOpen class="w-3.5 h-3.5 text-sky-400 shrink-0" />
            <span class="truncate font-medium">
              {{ currentTitle || 'Выберите проект...' }}
            </span>
          </div>
          <ChevronDown
            class="w-3.5 h-3.5 text-sky-400 shrink-0 transition-transform duration-150"
            :class="{ 'rotate-180': isDropdownOpen }"
          />
        </button>

        <!-- Dropdown Menu Panel -->
        <div
          v-if="isDropdownOpen"
          class="absolute left-0 top-full mt-1.5 w-[380px] max-h-[360px] overflow-y-auto rounded-xl bg-[#0f172a]/95 backdrop-blur-md border border-slate-700/80 shadow-2xl py-1.5 z-50"
        >
          <div class="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400 border-b border-slate-800/80 flex items-center justify-between">
            <span>Проекты в рабочей папке ({{ projectStore.projects.length }})</span>
            <span class="text-sky-400 font-mono">output/work</span>
          </div>

          <div v-if="projectStore.projects.length === 0" class="px-4 py-6 text-center text-xs text-slate-400">
            Нет сохраненных проектов
          </div>

          <button
            v-for="p in projectStore.projects"
            :key="p.title"
            type="button"
            @click="selectProject(p.title)"
            class="w-full px-3 py-2 text-left text-xs flex items-center justify-between hover:bg-sky-500/15 transition-colors group"
            :class="p.title === currentTitle ? 'bg-sky-500/10 text-sky-300 font-semibold' : 'text-slate-200'"
          >
            <div class="flex items-center space-x-2.5 min-w-0 pr-2">
              <Check
                v-if="p.title === currentTitle"
                class="w-3.5 h-3.5 text-sky-400 shrink-0"
              />
              <div v-else class="w-3.5 h-3.5 shrink-0 flex items-center justify-center">
                <Film v-if="p.has_video" class="w-3 h-3 text-emerald-400/80" />
                <Music v-else class="w-3 h-3 text-slate-500" />
              </div>
              <span class="truncate">{{ p.title }}</span>
            </div>

            <span
              v-if="p.has_video"
              class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-medium"
            >
              MP4
            </span>
            <span
              v-else
              class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700"
            >
              Стемы
            </span>
          </button>
        </div>

        <button
          @click="projectStore.fetchProjects()"
          title="Обновить список проектов"
          class="p-1.5 text-studio-muted hover:text-white rounded-lg bg-[#131c2e] hover:bg-[#19253d] border border-[#26354d] transition-colors"
        >
          <RefreshCw class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- Dirty state indicator -->
      <span
        v-if="projectStore.isDirty"
        class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30"
      >
        ● Не сохранено
      </span>
    </div>

    <!-- Right: Action Buttons -->
    <div class="flex items-center space-x-2.5">
      <!-- Undo / Redo -->
      <button
        @click="projectStore.undo()"
        :disabled="!projectStore.canUndo"
        title="Отменить (Ctrl+Z)"
        class="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Undo2 class="w-4 h-4" />
      </button>

      <button
        @click="projectStore.redo()"
        :disabled="!projectStore.canRedo"
        title="Повторить (Ctrl+Y)"
        class="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Redo2 class="w-4 h-4" />
      </button>

      <!-- Hardware & Models Button -->
      <button
        @click="emit('open-models')"
        class="flex items-center space-x-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-[#131c2e] hover:bg-[#19253d] text-slate-200 border border-[#26354d] transition-colors"
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
        class="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#131c2e] hover:bg-[#19253d] text-slate-200 border border-[#26354d] disabled:opacity-40 transition-colors"
      >
        <Save class="w-3.5 h-3.5 text-sky-400" />
        <span>Сохранить</span>
      </button>

      <!-- Rebuild Button -->
      <button
        @click="emit('open-export')"
        :disabled="!projectStore.hasProject"
        class="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow-sm disabled:opacity-40 transition-colors"
      >
        <Video class="w-3.5 h-3.5" />
        <span>Пересобрать MP4</span>
      </button>

      <!-- New Project Button -->
      <button
        @click="emit('open-new')"
        class="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm transition-colors"
      >
        <PlusCircle class="w-3.5 h-3.5" />
        <span>Новый трек</span>
      </button>
    </div>
  </header>
</template>
