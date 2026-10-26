import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePlayerStore = defineStore('player', () => {
  const currentTime = ref<number>(0)
  const isPlaying = ref<boolean>(false)
  const masterVolume = ref<number>(1.0)
  const liveVocalMultiplier = ref<number>(0.0) // 0% to 150% booster
  const isLooping = ref<boolean>(false)

  const selStart = ref<number | null>(null)
  const selEnd = ref<number | null>(null)

  // Media element handles
  const videoEl = ref<HTMLVideoElement | null>(null)
  const audioEl = ref<HTMLAudioElement | null>(null)

  function bindMedia(video: HTMLVideoElement | null, audio: HTMLAudioElement | null) {
    videoEl.value = video
    audioEl.value = audio

    if (video) {
      video.volume = masterVolume.value
    }
    if (audio) {
      audio.volume = Math.min(1.0, masterVolume.value * liveVocalMultiplier.value)
    }
  }

  function seek(targetSec: number) {
    currentTime.value = Math.max(0, targetSec)
    if (videoEl.value) {
      try {
        videoEl.value.currentTime = currentTime.value
      } catch (_) {}
    }
    if (audioEl.value && audioEl.value.src) {
      try {
        audioEl.value.currentTime = currentTime.value
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

    videoEl.value.play().catch(() => {})
    if (audioEl.value && audioEl.value.src && liveVocalMultiplier.value > 0) {
      audioEl.value.play().catch(() => {})
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

    // Drift correction between video and vocals audio (if playing)
    if (videoEl.value && audioEl.value && audioEl.value.src && liveVocalMultiplier.value > 0) {
      const diff = Math.abs(audioEl.value.currentTime - videoEl.value.currentTime)
      if (diff > 0.08) {
        audioEl.value.currentTime = videoEl.value.currentTime
      }
    }

    // Loop selection handling
    if (isLooping.value && selStart.value !== null && selEnd.value !== null) {
      const s = Math.min(selStart.value, selEnd.value)
      const e = Math.max(selStart.value, selEnd.value)
      if (time >= e) {
        seek(s)
        if (videoEl.value && !videoEl.value.paused) {
          videoEl.value.play().catch(() => {})
        }
      }
    }
  }

  function setLiveVocalMultiplier(val: number) {
    liveVocalMultiplier.value = val
    if (audioEl.value) {
      audioEl.value.volume = Math.min(1.0, masterVolume.value * val)
      if (val > 0 && isPlaying.value && audioEl.value.paused) {
        audioEl.value.currentTime = currentTime.value
        audioEl.value.play().catch(() => {})
      } else if (val === 0 && !audioEl.value.paused) {
        audioEl.value.pause()
      }
    }
  }

  function setMasterVolume(val: number) {
    masterVolume.value = val
    if (videoEl.value) videoEl.value.volume = val
    if (audioEl.value) audioEl.value.volume = Math.min(1.0, val * liveVocalMultiplier.value)
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
    isLooping,
    selStart,
    selEnd,
    bindMedia,
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
