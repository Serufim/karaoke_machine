import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChartTrack, ChartResponse } from '@/types'

export type PlatformId = 'yandex' | 'apple' | 'spotify' | 'zvuk' | 'vk'

export interface PlatformConfig {
  id: PlatformId
  name: string
  iconColor: string
  badgeColor: string
  countries?: { code: string; label: string; flag: string }[]
  statusBadge?: string
}

export const PLATFORMS: PlatformConfig[] = [
  {
    id: 'yandex',
    name: 'Яндекс Музыка',
    iconColor: 'text-amber-400',
    badgeColor: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  },
  {
    id: 'apple',
    name: 'Apple Music',
    iconColor: 'text-rose-400',
    badgeColor: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    countries: [
      { code: 'ru', label: 'Россия', flag: '🇷🇺' },
      { code: 'vn', label: 'Вьетнам', flag: '🇻🇳' },
      { code: 'us', label: 'США / Global', flag: '🇺🇸' },
      { code: 'kz', label: 'Казахстан', flag: '🇰🇿' },
    ],
  },
  {
    id: 'spotify',
    name: 'Spotify',
    iconColor: 'text-emerald-400',
    badgeColor: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  },
  {
    id: 'zvuk',
    name: 'СберЗвук',
    iconColor: 'text-green-500',
    badgeColor: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
    statusBadge: 'Защита',
  },
  {
    id: 'vk',
    name: 'ВК Музыка',
    iconColor: 'text-sky-400',
    badgeColor: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
    statusBadge: 'Нужен токен',
  },
]

export const useChartsStore = defineStore('charts', () => {
  const selectedPlatform = ref<PlatformId>('yandex')
  const selectedCountry = ref<string>('ru')
  const tracks = ref<ChartTrack[]>([])
  const isLoading = ref<boolean>(false)
  const error = ref<string | null>(null)
  const platformStatus = ref<string>('ok')
  const platformMessage = ref<string | null>(null)
  const chartDescription = ref<string>('')
  const filterQuery = ref<string>('')
  const selectedTrackForKaraoke = ref<ChartTrack | null>(null)

  const filteredTracks = computed(() => {
    const q = filterQuery.value.trim().toLowerCase()
    if (!q) return tracks.value
    return tracks.value.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        String(t.rank).includes(q)
    )
  })

  async function fetchCharts(platform?: PlatformId, country?: string) {
    if (platform) selectedPlatform.value = platform
    if (country) selectedCountry.value = country

    isLoading.value = true
    error.value = null
    platformMessage.value = null

    try {
      const p = selectedPlatform.value
      const c = selectedCountry.value
      const res = await fetch(`/api/charts?platform=${p}&country=${c}&limit=50`)
      if (!res.ok) {
        throw new Error(`Ошибка сервера: ${res.status} ${res.statusText}`)
      }
      const data: ChartResponse = await res.json()
      platformStatus.value = data.status
      chartDescription.value = data.description || ''
      platformMessage.value = data.message || null
      tracks.value = data.tracks || []
    } catch (err: any) {
      error.value = err.message || 'Не удалось загрузить чарт'
      tracks.value = []
    } finally {
      isLoading.value = false
    }
  }

  function setPlatform(p: PlatformId) {
    selectedPlatform.value = p
    if (p === 'apple') {
      selectedCountry.value = 'ru'
    }
    fetchCharts(p)
  }

  function setCountry(c: string) {
    selectedCountry.value = c
    fetchCharts(selectedPlatform.value, c)
  }

  return {
    selectedPlatform,
    selectedCountry,
    tracks,
    filteredTracks,
    isLoading,
    error,
    platformStatus,
    platformMessage,
    chartDescription,
    filterQuery,
    selectedTrackForKaraoke,
    fetchCharts,
    setPlatform,
    setCountry,
  }
})
