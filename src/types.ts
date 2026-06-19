export interface AudioStatus {
  pipewire_available: boolean;
  pactl_available: boolean;
  sink_exists: boolean;
  virtual_mic_exists: boolean;
  loopback_exists: boolean;
  selected_real_mic: string | null;
  selected_real_mic_description: string | null;
  default_source: string | null;
  is_default_source: boolean;
  last_error: string | null;
  state?: string;
}

export interface PlayerStatus {
  backend: string | null;
  pw_play_available: boolean;
  ffmpeg_available: boolean;
  mpv_available: boolean;
  active_playbacks: number;
}

export interface LibraryStatus {
  count: number;
  last_scan_at: string | null;
}

export interface DeckSoundpadStatus {
  version?: string;
  backend_running: boolean;
  audio: AudioStatus;
  player: PlayerStatus;
  library: LibraryStatus;
  mic_passthrough_enabled?: boolean;
}

export interface Settings {
  library_dirs: string[];
  mic_passthrough_enabled: boolean;
}
