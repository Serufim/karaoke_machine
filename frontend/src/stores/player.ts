import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useProjectStore } from '@/stores/project'

export const usePlayerStore = defineStore('player', () => {
  const currentTime = ref<number>(0)
  const isPlaying = ref<boolean>(false)
  const masterVolume = ref<number>(1.0)
  const liveVocalMultiplier = ref<number>(0.0) // 0% to 150% booster
  const timelineVocalVolume = ref<number>(0.0) // Active vocal_interval volume from timeline
  const isLooping = ref<boolean>(false)

  const selStart = ref<number | null>(null)
  const selEnd = ref<number | null>(null)

  // Media element handles
  const videoEl = ref<HTMLVideoElement | null>(null)
  const audioEl = ref<HTMLAudioElement | null>(null)

  // Guards against WebKit seek-storms and AbortError during slider dragging
  let audioPlayPending = false
  let lastAudioSyncMs = 0

  const effectiveVocalMultiplier = computed(() =>
    Math.max(liveVocalMultiplier.value, timelineVocalVolume.value)
  )

  function computeTimelineVocalAt(timeSec: number): number {
    const projectStore = useProjectStore()
    const intervals = projectStore.currentProject?.vocal_intervals
    if (!intervals || !Array.isArray(intervals) || intervals.length === 0) {
      return 0.0
    }
    let maxVol = 0.0
    for (const itv of intervals) {
      const s = Number(itv.start ?? 0)
      const e = Number(itv.end ?? 0)
      if (timeSec >= s && timeSec <= e) {
        const vol = Number(itv.volume ?? 0.5)
        if (vol > maxVol) maxVol = vol
      }
    }
    return maxVol
  }

  function applyVolumes() {
    const effVocal = effectiveVocalMultiplier.value
    const master = Math.max(0, Math.min(1.0, masterVolume.value))

    if (videoEl.value) {
      // When lead vocal is boosted above 100% (up to 150%), gently duck the backing track
      // so the lead vocal stands out clearly without digital clipping
      const backingScale = effVocal > 1.0 ? 1.0 / effVocal : 1.0
      videoEl.value.muted = master === 0
      videoEl.value.volume = Math.max(0, Math.min(1.0, master * backingScale))
    }

    if (audioEl.value) {
      const vocalActive = master > 0 && effVocal > 0.005
      audioEl.value.muted = !vocalActive
      audioEl.value.volume = vocalActive
        ? Math.max(0, Math.min(1.0, master * Math.min(1.0, effVocal)))
        : 0.0
    }
  }

  function syncAudioToVideo(forceSeek: boolean = false) {
    const v = videoEl.value
    const a = audioEl.value
    if (!v || !a || !a.src) return

    applyVolumes()

    const now = Date.now()
    const canSeek = !a.seeking && !v.seeking && a.readyState >= 1
    const diff = Math.abs((a.currentTime || 0) - (v.currentTime || 0))

    if (canSeek && (forceSeek ? diff > 0.05 : diff > 0.25 && now - lastAudioSyncMs > 1200)) {
      try {
        a.currentTime = v.currentTime
        lastAudioSyncMs = now
      } catch (_) {}
    }

    if (!v.paused && !v.ended) {
      if (a.paused && !audioPlayPending) {
        audioPlayPending = true
        a.play()
          .catch(() => {})
          .finally(() => {
            audioPlayPending = false
          })
      }
    }
  }

  function bindMedia(video: HTMLVideoElement | null, audio: HTMLAudioElement | null) {
    videoEl.value = video
    audioEl.value = audio
    timelineVocalVolume.value = computeTimelineVocalAt(currentTime.value)
    applyVolumes()
  }

  function resetForNewProject() {
    pause()
    currentTime.value = 0
    timelineVocalVolume.value = 0
    audioPlayPending = false
    lastAudioSyncMs = 0
  }

  function seek(targetSec: number) {
    currentTime.value = Math.max(0, targetSec)
    timelineVocalVolume.value = computeTimelineVocalAt(currentTime.value)
    applyVolumes()

    if (videoEl.value) {
      try {
        videoEl.value.currentTime = currentTime.value
      } catch (_) {}
    }
    if (audioEl.value && audioEl.value.src) {
      try {
        audioEl.value.currentTime = currentTime.value
        lastAudioSyncMs = Date.now()
      } catch (_) {}
    }
  }

  function play() {
    if (!videoEl.value) return

    // If selection active and outside selection, jump to selection start
    if (selStart.value !== null && selEnd.value !== null) {
      const s = Math.min(selStart.value, selEnd.value)
      const e = Math.max(selStart.value, selEnd.value)
      if (currentTime.value < s || currentTime.value >= e - 0.05) {
        seek(s)
      }
    }

    timelineVocalVolume.value = computeTimelineVocalAt(currentTime.value)
    applyVolumes()

    videoEl.value.play().catch(() => {})

    // Always start audioEl on the user's Play gesture so WebKit unlocks the audio element
    // and keeps it buffered in lockstep with videoEl (muted when vocal level is 0%)
    if (audioEl.value && audioEl.value.src) {
      if (
        audioEl.value.readyState >= 1 &&
        !audioEl.value.seeking &&
        Math.abs(audioEl.value.currentTime - videoEl.value.currentTime) > 0.1
      ) {
        try {
          audioEl.value.currentTime = videoEl.value.currentTime
          lastAudioSyncMs = Date.now()
        } catch (_) {}
      }
      audioPlayPending = true
      audioEl.value
        .play()
        .catch(() => {})
        .finally(() => {
          audioPlayPending = false
        })
    }

    isPlaying.value = true
  }

  function pause() {
    if (videoEl.value) videoEl.value.pause()
    if (audioEl.value) audioEl.value.pause()
    isPlaying.value = false
  }

  function togglePlay() {
    if (isPlaying.value) {
      pause()
    } else {
      play()
    }
  }

  function onTimeUpdate(time: number) {
    currentTime.value = time
    timelineVocalVolume.value = computeTimelineVocalAt(time)

    // Keep volumes and drift in sync without interrupting in-flight seeks
    syncAudioToVideo(false)

    // Loop selection handling
    if (isLooping.value && selStart.value !== null && selEnd.value !== null) {
      const s = Math.min(selStart.value, selEnd.value)
      const e = Math.max(selStart.value, selEnd.value)
      if (time >= e) {
        seek(s)
        if (videoEl.value && !videoEl.value.paused) {
          videoEl.value.play().catch(() => {})
        }
        if (audioEl.value && !audioEl.value.paused) {
          audioEl.value.play().catch(() => {})
        }
      }
    }
  }

  function setLiveVocalMultiplier(val: number) {
    liveVocalMultiplier.value = Math.max(0, Math.min(1.5, val))
    applyVolumes()
    if (isPlaying.value) {
      syncAudioToVideo(false)
    }
  }

  function setMasterVolume(val: number) {
    masterVolume.value = Math.max(0, Math.min(1.0, val))
    applyVolumes()
  }

  function setSelection(start: number | null, end: number | null) {
    selStart.value = start
    selEnd.value = end
  }

  function clearSelection() {
    selStart.value = null
    selEnd.value = null
  }

  function toggleLoop() {
    isLooping.value = !isLooping.value
  }

  return {
    currentTime,
    isPlaying,
    masterVolume,
    liveVocalMultiplier,
    timelineVocalVolume,
    effectiveVocalMultiplier,
    isLooping,
    selStart,
    selEnd,
    bindMedia,
    resetForNewProject,
    seek,
    play,
    pause,
    togglePlay,
    onTimeUpdate,
    setLiveVocalMultiplier,
    setMasterVolume,
    setSelection,
    clearSelection,
    toggleLoop,
  }
})
