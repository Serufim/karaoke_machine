import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { HardwareProfile, ModelItem } from '@/types'

export const useModelsStore = defineStore('models', () => {
  const hardware = ref<HardwareProfile | null>(null)
  const models = ref<ModelItem[]>([])
  const isLoading = ref<boolean>(false)
  const lastError = ref<string | null>(null)

  async function fetchHardware() {
    try {
      const res = await fetch('/api/system/hardware')
      if (res.ok) {
        hardware.value = await res.json()
      }
    } catch (e: any) {
      console.error('Failed to fetch hardware:', e)
    }
  }

  async function fetchCatalog() {
    isLoading.value = true
    try {
      const res = await fetch('/api/models/catalog')
      if (res.ok) {
        const data = await res.json()
        models.value = data.models || []
      }
    } catch (e: any) {
      lastError.value = e.message || 'Ошибка загрузки каталога моделей'
    } finally {
      isLoading.value = false
    }
  }

  async function downloadModel(modelId: string) {
    try {
      const item = models.value.find((m) => m.id === modelId)
      if (item) {
        item.status = 'downloading'
        item.progress = 5
      }
      const res = await fetch('/api/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: modelId }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Не удалось запустить загрузку')
      }
    } catch (e: any) {
      const item = models.value.find((m) => m.id === modelId)
      if (item) {
        item.status = 'error'
      }
      alert(`Ошибка: ${e.message}`)
    }
  }

  async function deleteModel(modelId: string) {
    if (!confirm(`Удалить кэш модели ${modelId} для освобождения места?`)) {
      return
    }
    try {
      const res = await fetch(`/api/models/${encodeURIComponent(modelId)}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        const item = models.value.find((m) => m.id === modelId)
        if (item) {
          item.is_downloaded = false
          item.status = 'not_downloaded'
          item.size_on_disk_mb = null
          item.progress = 0
        }
      } else {
        const err = await res.json()
        alert(`Ошибка удаления: ${err.detail || 'Неизвестная ошибка'}`)
      }
    } catch (e: any) {
      alert(`Ошибка удаления: ${e.message}`)
    }
  }

  function handleProgressEvent(data: any) {
    if (data.type === 'model_progress' && data.model_id) {
      const item = models.value.find((m) => m.id === data.model_id)
      if (item) {
        item.status = data.status || 'downloading'
        item.progress = data.progress || 0
        if (data.status === 'ready') {
          item.is_downloaded = true
          fetchCatalog()
        }
      }
    }
  }

  return {
    hardware,
    models,
    isLoading,
    lastError,
    fetchHardware,
    fetchCatalog,
    downloadModel,
    deleteModel,
    handleProgressEvent,
  }
})
