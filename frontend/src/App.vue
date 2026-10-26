<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import StudioHeader from '@/components/StudioHeader.vue'
import MediaStage from '@/components/MediaStage.vue'
import LyricsInspector from '@/components/LyricsInspector.vue'
import StudioTimeline from '@/components/StudioTimeline.vue'
import NewProjectModal from '@/components/NewProjectModal.vue'
import ExportModal from '@/components/ExportModal.vue'
import ProgressModal from '@/components/ProgressModal.vue'
import ModelManagerModal from '@/components/ModelManagerModal.vue'

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()

const showNewModal = ref(false)
const showExportModal = ref(false)
const showModelsModal = ref(false)

// Resizable panel dimensions with persistence
const defaultLyricsWidth = 340
const defaultTimelineHeight = 250

const lyricsWidth = ref<number>(
  parseInt(localStorage.getItem('studio_lyrics_width') || `${defaultLyricsWidth}`, 10)
)
const timelineHeight = ref<number>(
  parseInt(localStorage.getItem('studio_timeline_height') || `${defaultTimelineHeight}`, 10)
)

const isDraggingCol = ref(false)
const isDraggingRow = ref(false)

function onColMouseDown(e: MouseEvent) {
  isDraggingCol.value = true
  e.preventDefault()
}

function onRowMouseDown(e: MouseEvent) {
  isDraggingRow.value = true
  e.preventDefault()
}

function onMouseMove(e: MouseEvent) {
  if (isDraggingCol.value) {
    const newW = window.innerWidth - e.clientX
    // Constrain width between 260px and 650px
    if (newW >= 260 && newW <= 650) {
      lyricsWidth.value = newW
      localStorage.setItem('studio_lyrics_width', String(newW))
    }
  } else if (isDraggingRow.value) {
    const newH = window.innerHeight - e.clientY
    // Constrain height between 180px and 500px
    if (newH >= 180 && newH <= 500) {
      timelineHeight.value = newH
      localStorage.setItem('studio_timeline_height', String(newH))
    }
  }
}

function onMouseUp() {
  isDraggingCol.value = false
  isDraggingRow.value = false
}

onMounted(async () => {
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)

  pipelineStore.initWebSocket()
  await projectStore.fetchProjects()
  if (projectStore.projects.length > 0) {
    await projectStore.loadProject(projectStore.projects[0].title)
  }
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
})
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-studio-bg overflow-hidden text-studio-text select-none">
    <!-- Top Bar -->
    <StudioHeader
      @open-new="showNewModal = true"
      @open-export="showExportModal = true"
      @open-models="showModelsModal = true"
    />

    <!-- Middle Workspace: Media Player + Splitter + Lyrics Inspector -->
    <main class="flex-1 flex overflow-hidden min-h-0 relative">
      <!-- Media Player Area -->
      <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
        <MediaStage />
      </div>

      <!-- Vertical Resizer Handle -->
      <div
        @mousedown="onColMouseDown"
        class="w-1.5 hover:w-2 bg-studio-border/70 hover:bg-sky-500 cursor-col-resize z-20 transition-all duration-150 flex items-center justify-center group select-none"
        :class="{ 'bg-sky-500 w-2': isDraggingCol }"
        title="Перетащите для изменения ширины панели текста"
      >
        <div class="w-0.5 h-8 bg-slate-500 group-hover:bg-white rounded-full"></div>
      </div>

      <!-- Lyrics Inspector Area -->
      <div
        :style="{ width: `${lyricsWidth}px` }"
        class="flex-shrink-0 h-full overflow-hidden"
      >
        <LyricsInspector />
      </div>
    </main>

    <!-- Horizontal Resizer Handle -->
    <div
      @mousedown="onRowMouseDown"
      class="h-1.5 hover:h-2 bg-studio-border/70 hover:bg-sky-500 cursor-row-resize z-20 transition-all duration-150 flex items-center justify-center group select-none"
      :class="{ 'bg-sky-500 h-2': isDraggingRow }"
      title="Перетащите для изменения высоты таймлайна"
    >
      <div class="h-0.5 w-12 bg-slate-500 group-hover:bg-white rounded-full"></div>
    </div>

    <!-- Bottom: Multi-Track Timeline with Dynamic Height -->
    <div
      :style="{ height: `${timelineHeight}px` }"
      class="flex-shrink-0 flex flex-col overflow-hidden"
    >
      <StudioTimeline />
    </div>

    <!-- Modals -->
    <NewProjectModal
      v-if="showNewModal"
      @close="showNewModal = false"
      @open-models="showModelsModal = true"
    />

    <ExportModal
      v-if="showExportModal"
      @close="showExportModal = false"
    />

    <ModelManagerModal
      v-if="showModelsModal"
      @close="showModelsModal = false"
    />

    <ProgressModal />
  </div>
</template>
