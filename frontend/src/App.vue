<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import StudioHeader from '@/components/StudioHeader.vue'
import MediaStage from '@/components/MediaStage.vue'
import LyricsInspector from '@/components/LyricsInspector.vue'
import StudioTimeline from '@/components/StudioTimeline.vue'
import NewProjectModal from '@/components/NewProjectModal.vue'
import ExportModal from '@/components/ExportModal.vue'
import ProgressModal from '@/components/ProgressModal.vue'

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()

const showNewModal = ref(false)
const showExportModal = ref(false)

onMounted(async () => {
  pipelineStore.initWebSocket()
  await projectStore.fetchProjects()
  if (projectStore.projects.length > 0) {
    await projectStore.loadProject(projectStore.projects[0].title)
  }
})
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-studio-bg overflow-hidden text-studio-text select-none">
    <!-- Top Bar -->
    <StudioHeader
      @open-new="showNewModal = true"
      @open-export="showExportModal = true"
    />

    <!-- Middle Workspace: Media Player + Lyrics Inspector -->
    <main class="flex-1 flex overflow-hidden min-h-0">
      <MediaStage />
      <LyricsInspector />
    </main>

    <!-- Bottom: Multi-Track Timeline -->
    <StudioTimeline />

    <!-- Modals -->
    <NewProjectModal
      v-if="showNewModal"
      @close="showNewModal = false"
    />

    <ExportModal
      v-if="showExportModal"
      @close="showExportModal = false"
    />

    <ProgressModal />
  </div>
</template>
