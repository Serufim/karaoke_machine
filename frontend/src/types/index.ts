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

export interface GenerationParams {
  model_size?: string
  demucs_model?: string
  language?: string
  vad?: string
  use_ctc_align?: boolean
  use_video_bg?: boolean
  condition_on_previous_text?: boolean
  strict_repeats?: boolean
  vocal_volume_pct?: number
  num_lines?: number
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
  cover_edge_colors?: Record<string, string>
  custom_bg?: string
  video_bg?: string
  no_vocals_wav?: string
  vocals_wav?: string
  watermark_text?: string
  source?: string
  source_type?: 'file' | 'url'
  reference_lyrics?: string
  generation_params?: GenerationParams
}

export interface ProjectMeta {
  title: string
  mtime: number
  has_video: boolean
  has_cover: boolean
}

export interface PipelineProgress {
  type: 'progress' | 'completed' | 'cancelled' | 'error' | 'model_progress'
  fraction?: number
  message?: string
  stage?: string
  title?: string
  action?: string
  video_path?: string
  success?: boolean
  model_id?: string
  status?: string
  progress?: number
}

export interface HardwareProfile {
  platform: string
  os_name: string
  architecture: string
  cpu_name: string
  cpu_cores: number
  ram_gb: number
  gpu_type: 'cuda' | 'mps' | 'cpu'
  gpu_name: string
  vram_gb: number
  cuda_available: boolean
  cuda_version: string | null
  cuda_compute_capability: string | null
  mps_available: boolean
  tier: 'ultra' | 'high' | 'medium' | 'low'
  recommended_whisper: string
  recommended_demucs: string
  allow_fp16: boolean
  status_summary: string
}

export interface ModelItem {
  id: string
  name: string
  type: 'whisper' | 'demucs' | 'aligner'
  description: string
  download_size_mb: number
  min_vram_gb: number
  min_ram_gb: number
  recommended_for: string
  is_default: boolean
  is_hf: boolean
  is_downloaded: boolean
  size_on_disk_mb: number | null
  status: 'ready' | 'not_downloaded' | 'downloading' | 'error'
  progress: number
}

export interface ChartTrack {
  rank: number
  title: string
  artist: string
  cover_url: string | null
  platform: 'yandex' | 'apple' | 'spotify' | 'zvuk' | 'vk'
  trend?: string | null
  search_query: string
  external_url?: string | null
}

export interface ChartResponse {
  status: 'ok' | 'protected' | 'auth_required' | 'error'
  platform: string
  platform_name: string
  country: string
  description?: string
  message?: string
  tracks: ChartTrack[]
}


