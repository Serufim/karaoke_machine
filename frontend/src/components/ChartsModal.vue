<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  useChartsStore,
  PLATFORMS,
  type PlatformId,
} from '@/stores/charts'
import type { ChartTrack } from '@/types'
import {
  X,
  Flame,
  Search,
  ExternalLink,
  Mic,
  RefreshCw,
  AlertTriangle,
  Lock,
  Music2,
  TrendingUp,
  Sparkles,
  Check,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select-track', track: ChartTrack): void
}>()

const chartsStore = useChartsStore()
const activePlatformConfig = ref(PLATFORMS[0])

function onPlatformSelect(p: PlatformId) {
  const conf = PLATFORMS.find((x) => x.id === p)
  if (conf) activePlatformConfig.value = conf
  chartsStore.setPlatform(p)
}

function onCountrySelect(c: string) {
  chartsStore.setCountry(c)
}

function onSelectTrack(track: ChartTrack) {
  emit('select-track', track)
}

onMounted(() => {
  if (chartsStore.tracks.length === 0) {
    chartsStore.fetchCharts()
  }
})
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
    <div class="w-full max-w-4xl h-[88vh] bg-studio-panel border border-studio-border rounded-2xl shadow-2xl flex flex-col overflow-hidden">
      <!-- Modal Header -->
      <div class="px-6 py-4 border-b border-studio-border bg-gradient-to-r from-slate-900/90 via-studio-panel to-slate-900/90 flex items-center justify-between shrink-0">
        <div class="flex items-center space-x-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-rose-500/20 border border-amber-500/30 flex items-center justify-center shadow-inner">
            <Flame class="w-5 h-5 text-amber-400 animate-pulse" />
          </div>
          <div>
            <div class="flex items-center space-x-2">
              <h2 class="text-lg font-bold text-white tracking-wide">
                Тренды и Музыкальные Чарты
              </h2>
              <span class="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
                1-Click Караоке
              </span>
            </div>
            <p class="text-xs text-studio-muted">
              {{ chartsStore.chartDescription || 'Актуальные хиты из популярных музыкальных сервисов' }}
            </p>
          </div>
        </div>

        <div class="flex items-center space-x-3">
          <button
            type="button"
            @click="chartsStore.fetchCharts()"
            :disabled="chartsStore.isLoading"
            class="p-2 rounded-lg bg-studio-surface hover:bg-slate-700/60 border border-studio-border text-slate-300 hover:text-white transition-all disabled:opacity-50"
            title="Обновить чарт"
          >
            <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': chartsStore.isLoading }" />
          </button>
          <button
            type="button"
            @click="emit('close')"
            class="p-2 rounded-lg bg-studio-surface hover:bg-rose-500/20 border border-studio-border hover:border-rose-500/30 text-slate-400 hover:text-rose-400 transition-all"
            title="Закрыть"
          >
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Controls Bar: Platform Tabs & Filters -->
      <div class="px-6 py-3 border-b border-studio-border bg-studio-bg/60 shrink-0 space-y-3">
        <!-- Platform Selection Tabs -->
        <div class="flex items-center justify-between flex-wrap gap-2">
          <div class="flex items-center space-x-1.5 p-1 bg-studio-surface rounded-xl border border-studio-border">
            <button
              v-for="platform in PLATFORMS"
              :key="platform.id"
              type="button"
              @click="onPlatformSelect(platform.id)"
              :class="[
                'px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center space-x-1.5',
                chartsStore.selectedPlatform === platform.id
                  ? 'bg-slate-800 text-white shadow-md border border-slate-600/70 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
              ]"
            >
              <span :class="platform.iconColor">●</span>
              <span>{{ platform.name }}</span>
              <span
                v-if="platform.statusBadge"
                class="text-[9px] px-1.5 py-0.2 rounded bg-slate-700/70 text-slate-300 border border-slate-600/50"
              >
                {{ platform.statusBadge }}
              </span>
            </button>
          </div>

          <!-- Quick Search Filter -->
          <div class="relative w-64">
            <Search class="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              v-model="chartsStore.filterQuery"
              type="text"
              placeholder="Фильтр по треку или артисту..."
              class="w-full pl-9 pr-3 py-1.5 bg-studio-surface border border-studio-border rounded-xl text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500/70 transition-all"
            />
            <button
              v-if="chartsStore.filterQuery"
              @click="chartsStore.filterQuery = ''"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </div>

        <!-- Optional Regional Selector for Apple Music -->
        <div
          v-if="activePlatformConfig.countries && activePlatformConfig.countries.length > 0"
          class="flex items-center space-x-2 pt-1 border-t border-studio-border/40"
        >
          <span class="text-[11px] font-medium text-slate-400">Регион чарта:</span>
          <div class="flex items-center space-x-1.5">
            <button
              v-for="country in activePlatformConfig.countries"
              :key="country.code"
              type="button"
              @click="onCountrySelect(country.code)"
              :class="[
                'px-2.5 py-1 rounded-lg text-xs font-medium transition-all flex items-center space-x-1.5',
                chartsStore.selectedCountry === country.code
                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                  : 'bg-studio-surface text-slate-400 hover:text-slate-200 border border-studio-border'
              ]"
            >
              <span>{{ country.flag }}</span>
              <span>{{ country.label }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Content Area -->
      <div class="flex-1 overflow-y-auto p-6 min-h-0 bg-studio-bg/40">
        <!-- Loading State -->
        <div v-if="chartsStore.isLoading" class="h-full flex flex-col items-center justify-center space-y-3 text-slate-400">
          <RefreshCw class="w-8 h-8 text-sky-400 animate-spin" />
          <p class="text-sm font-medium">Загрузка актуального чарта...</p>
        </div>

        <!-- Service Status Warning (For Zvuk & VK) -->
        <div
          v-else-if="chartsStore.platformStatus === 'protected' || chartsStore.platformStatus === 'auth_required'"
          class="h-full flex flex-col items-center justify-center max-w-lg mx-auto text-center space-y-4"
        >
          <div class="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shadow-lg">
            <Lock v-if="chartsStore.platformStatus === 'protected'" class="w-8 h-8" />
            <AlertTriangle v-else class="w-8 h-8" />
          </div>
          <div>
            <h3 class="text-base font-bold text-white mb-1">
              {{ chartsStore.selectedPlatform === 'zvuk' ? 'СберЗвук защищен антифрод-системой' : 'Требуется авторизация ВКонтакте' }}
            </h3>
            <p class="text-xs text-slate-400 leading-relaxed">
              {{ chartsStore.platformMessage }}
            </p>
          </div>
          <div class="p-3 bg-studio-surface border border-studio-border rounded-xl text-left text-xs text-slate-300 space-y-1.5 w-full">
            <div class="font-semibold text-slate-200 flex items-center space-x-1.5">
              <Sparkles class="w-3.5 h-3.5 text-amber-400" />
              <span>Рекомендация:</span>
            </div>
            <p class="text-slate-400">
              Используйте <strong class="text-white">Яндекс Музыку</strong>, <strong class="text-white">Apple Music</strong> (с регионами РФ, Вьетнам, США) или <strong class="text-white">Spotify</strong> — их чарты работают открыто и мгновенно.
            </p>
          </div>
          <button
            type="button"
            @click="onPlatformSelect('yandex')"
            class="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-xs shadow-lg transition-all"
          >
            Перейти к Яндекс Музыке
          </button>
        </div>

        <!-- Error State -->
        <div
          v-else-if="chartsStore.error"
          class="h-full flex flex-col items-center justify-center text-center space-y-3"
        >
          <div class="w-12 h-12 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400">
            <AlertTriangle class="w-6 h-6" />
          </div>
          <p class="text-sm font-semibold text-white">{{ chartsStore.error }}</p>
          <button
            type="button"
            @click="chartsStore.fetchCharts()"
            class="px-3 py-1.5 rounded-lg bg-studio-surface border border-studio-border text-xs text-slate-200 hover:bg-slate-700"
          >
            Попробовать снова
          </button>
        </div>

        <!-- Empty Filter Results -->
        <div
          v-else-if="chartsStore.filteredTracks.length === 0"
          class="h-full flex flex-col items-center justify-center text-center text-slate-400 space-y-2"
        >
          <Music2 class="w-8 h-8 text-slate-500" />
          <p class="text-sm">Ничего не найдено по вашему фильтру</p>
        </div>

        <!-- Tracks List -->
        <div v-else class="space-y-1.5">
          <div
            v-for="track in chartsStore.filteredTracks"
            :key="`${track.platform}_${track.rank}_${track.title}`"
            class="group flex items-center justify-between p-2.5 rounded-xl bg-studio-surface/80 hover:bg-studio-surface border border-studio-border/70 hover:border-sky-500/50 transition-all duration-150 shadow-sm"
          >
            <!-- Left: Rank + Cover + Meta -->
            <div class="flex items-center space-x-3.5 min-w-0 flex-1 mr-3">
              <!-- Rank Badge -->
              <div class="w-8 text-center shrink-0">
                <span
                  v-if="track.rank === 1"
                  class="inline-block px-1.5 py-0.5 rounded font-bold text-xs bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                >
                  #1
                </span>
                <span
                  v-else-if="track.rank === 2"
                  class="inline-block px-1.5 py-0.5 rounded font-bold text-xs bg-slate-300/20 text-slate-200 border border-slate-300/30"
                >
                  #2
                </span>
                <span
                  v-else-if="track.rank === 3"
                  class="inline-block px-1.5 py-0.5 rounded font-bold text-xs bg-amber-700/20 text-amber-400 border border-amber-700/30"
                >
                  #3
                </span>
                <span v-else class="text-xs font-semibold text-slate-500 font-mono">
                  #{{ track.rank }}
                </span>
              </div>

              <!-- Cover Image -->
              <div class="w-12 h-12 rounded-lg bg-slate-800 border border-studio-border overflow-hidden shrink-0 relative group-hover:scale-105 transition-transform duration-200 shadow">
                <img
                  v-if="track.cover_url"
                  :src="track.cover_url"
                  :alt="track.title"
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
                <div v-else class="w-full h-full flex items-center justify-center text-slate-600">
                  <Music2 class="w-5 h-5" />
                </div>
              </div>

              <!-- Title, Artist & Trend -->
              <div class="min-w-0 flex-1">
                <div class="flex items-center space-x-2">
                  <h4 class="text-sm font-semibold text-white truncate group-hover:text-sky-300 transition-colors">
                    {{ track.title }}
                  </h4>
                  <span
                    v-if="track.trend"
                    :class="[
                      'text-[10px] font-mono px-1.5 py-0.2 rounded shrink-0 font-bold',
                      track.trend === 'NEW'
                        ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                        : track.trend.startsWith('+') || track.trend === '▲'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : track.trend.startsWith('-') || track.trend === '▼'
                        ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                        : 'bg-slate-700/50 text-slate-400'
                    ]"
                  >
                    {{ track.trend }}
                  </span>
                </div>
                <p class="text-xs text-slate-400 truncate mt-0.5">
                  {{ track.artist }}
                </p>
              </div>
            </div>

            <!-- Right: Actions -->
            <div class="flex items-center space-x-2 shrink-0">
              <a
                v-if="track.external_url"
                :href="track.external_url"
                target="_blank"
                rel="noreferrer"
                class="p-2 rounded-lg bg-studio-bg hover:bg-slate-700/70 text-slate-400 hover:text-white transition-colors"
                title="Открыть в сервисе"
              >
                <ExternalLink class="w-3.5 h-3.5" />
              </a>

              <button
                type="button"
                @click="onSelectTrack(track)"
                class="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 active:scale-95 text-white font-medium text-xs shadow-md transition-all flex items-center space-x-1.5"
              >
                <Mic class="w-3.5 h-3.5" />
                <span>Создать караоке</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="px-6 py-3 border-t border-studio-border bg-studio-panel flex items-center justify-between text-xs text-slate-400 shrink-0">
        <div class="flex items-center space-x-2">
          <span>Найдено: <strong class="text-white">{{ chartsStore.filteredTracks.length }}</strong> треков</span>
          <span class="text-slate-600">•</span>
          <span class="text-slate-400">Нажмите «Создать караоке», чтобы автоматически найти аудио и запустить проект</span>
        </div>
        <button
          type="button"
          @click="emit('close')"
          class="px-4 py-1.5 rounded-lg bg-studio-surface hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
        >
          Закрыть
        </button>
      </div>
    </div>
  </div>
</template>
