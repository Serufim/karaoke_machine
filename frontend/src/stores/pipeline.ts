import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { PipelineProgress } from '@/types'
import { useProjectStore } from './project'
import { useModelsStore } from './models'

export const usePipelineStore = defineStore('pipeline', () => {
  const isRunning = ref<boolean>(false)
  const isRebuilding = ref<boolean>(false)
  const progressFraction = ref<number>(0.0)
  const statusMessage = ref<string>('Готов к работе')
  const stage = ref<string>('idle')
  const showModal = ref<boolean>(false)
  const activeJobTitle = ref<string>('')
  const lastError = ref<string | null>(null)

  let socket: WebSocket | null = null

  function initWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/progress`

    try {
      socket = new WebSocket(wsUrl)
      socket.onmessage = (event) => {
        try {
          const data: PipelineProgress = JSON.parse(event.data)
          handleMessage(data)
        } catch (_) {}
      }
      socket.onclose = () => {
        setTimeout(initWebSocket, 3000)
      }
    } catch (_) {}
  }

  function handleMessage(data: PipelineProgress) {
    if (data.type === 'model_progress') {
      const modelsStore = useModelsStore()
      modelsStore.handleProgressEvent(data)
      return
    }
    if (data.type === 'progress') {
      isRunning.value = true
      progressFraction.value = data.fraction || 0
      statusMessage.value = data.message || 'Обработка...'
      if (data.stage) stage.value = data.stage
      showModal.value = true
    } else if (data.type === 'completed') {
      isRunning.value = false
      isRebuilding.value = false
      progressFraction.value = 1.0
      statusMessage.value = data.message || 'Готово!'
      stage.value = 'completed'

      // Reload project state in store
      if (data.title) {
        const projectStore = useProjectStore()
        projectStore.fetchProjects().then(async () => {
          await projectStore.loadProject(data.title!)
          projectStore.mediaTimestamp = Date.now()
        })
      }
      setTimeout(() => {
        showModal.value = false
      }, 1500)
    } else if (data.type === 'project_updated') {
      if (data.title) {
        const projectStore = useProjectStore()
        projectStore.fetchProjects().then(async () => {
          await projectStore.loadProject(data.title!)
          projectStore.mediaTimestamp = Date.now()
        })
      }
    } else if (data.type === 'cancelled') {
      isRunning.value = false
      isRebuilding.value = false
      progressFraction.value = 0.0
      statusMessage.value = data.message || 'Остановлено.'
      stage.value = 'cancelled'
    } else if (data.type === 'error') {
      isRunning.value = false
      isRebuilding.value = false
      statusMessage.value = data.message || 'Ошибка обработки.'
      lastError.value = data.message || 'Неизвестная ошибка'
      stage.value = 'error'
    }
  }

  async function cancel() {
    try {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: 'cancel' }))
      }
      await fetch('/api/pipeline/cancel', { method: 'POST' })
    } catch (_) {}
  }

  async function startGenerate(formData: FormData) {
    lastError.value = null
    isRunning.value = true
    isRebuilding.value = false
    progressFraction.value = 0.02
    statusMessage.value = 'Отправка данных на сервер...'
    stage.value = 'uploading'
    showModal.value = true

    try {
      const res = await fetch('/api/pipeline/generate', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Ошибка запуска генерации')
      }
    } catch (e: any) {
      isRunning.value = false
      lastError.value = e.message
      statusMessage.value = e.message
      stage.value = 'error'
    }
  }

  async function startRebuild(payload: any) {
    lastError.value = null
    isRunning.value = true
    isRebuilding.value = true
    progressFraction.value = 0.05
    statusMessage.value = 'Запуск пересборки видео...'
    stage.value = 'rebuilding'
    showModal.value = true

    try {
      const res = await fetch('/api/pipeline/rebuild', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Ошибка пересборки')
      }
    } catch (e: any) {
      isRunning.value = false
      isRebuilding.value = false
      lastError.value = e.message
      statusMessage.value = e.message
      stage.value = 'error'
    }
  }

  async function quickRebuild() {
    const projectStore = useProjectStore()
    if (!projectStore.currentProject) return

    // Ensure pending edits are saved to current project state
    try {
      await projectStore.saveProject()
    } catch (_) {}

    const p = projectStore.currentProject
    const exportDir = localStorage.getItem('studio_export_dir') || undefined
    const numLines = p.generation_params?.num_lines ?? 4
    const vocalVolume = (p.generation_params?.vocal_volume_pct ?? 0) / 100
    const useVideoBg = p.generation_params?.use_video_bg ?? (Boolean(p.video_bg) && !p.custom_bg)
    const useCoverBg = !p.custom_bg && !useVideoBg

    await startRebuild({
      title: p.title,
      editor_text: p.editor_text,
      vocal_volume: vocalVolume,
      vocal_intervals: p.vocal_intervals || [],
      fx_intervals: p.fx_intervals || [],
      emoji_intervals: p.emoji_intervals || [],
      num_lines: numLines,
      video_quality: 'balanced',
      use_cover_bg: useCoverBg,
      use_video_bg: useVideoBg,
      visual_effects: 'sparkles_pulse',
      edge_color_mode: 'cyberpunk',
      font_size_mode: 'large',
      highlight_color: 'gold_neon',
      dual_audio_mp4: true,
      watermark_text: p.watermark_text || null,
      custom_bg_path: p.custom_bg || null,
      export_dir: exportDir,
    })
  }

  return {
    isRunning,
    isRebuilding,
    progressFraction,
    statusMessage,
    stage,
    showModal,
    activeJobTitle,
    lastError,
    initWebSocket,
    cancel,
    startGenerate,
    startRebuild,
    quickRebuild,
  }
})
