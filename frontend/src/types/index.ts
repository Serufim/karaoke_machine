export interface Word {
  text: string
  start: number
  end: number
  syllables?: number
}

export interface LyricLine {
  start: number
  end: number
  text: string
  words?: Word[]
}

export interface VocalInterval {
  start: number
  end: number
  volume: number
}

export interface FxInterval {
  start: number
  end: number
  effect: string
  intensity: number
  emojis?: string
}

export interface EmojiInterval {
  start: number
  end: number
  emojis: string
  intensity: number
}

export interface ProjectState {
  title: string
  duration: number
  inst_peaks: number[]
  vocal_peaks: number[]
  vocal_intervals: VocalInterval[]
  fx_intervals: FxInterval[]
  emoji_intervals?: EmojiInterval[]
  lines: any[]
  editor_text: string
  has_video?: boolean
  cover_image?: string
  no_vocals_wav?: string
  vocals_wav?: string
}

export interface ProjectMeta {
  title: string
  mtime: number
  has_video: boolean
  has_cover: boolean
}

export interface PipelineProgress {
  type: 'progress' | 'completed' | 'cancelled' | 'error'
  fraction: number
  message: string
  stage?: string
  title?: string
  action?: string
  video_path?: string
  success?: boolean
}
