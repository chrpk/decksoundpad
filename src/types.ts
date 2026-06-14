export type OverlapMode = "overlap" | "single" | "per_sound";

export interface SoundItem {
  id: string;
  name: string;
  display_name: string;
  path: string;
  relative_path: string;
  category: string;
  extension: string;
  size_bytes: number;
  modified_at: string;
  duration_ms: number | null;
  tags: string[];
  volume: number;
  favorite: boolean;
}

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

export interface WebStatus {
  url: string | null;
  port: number;
}

export interface DeckSoundpadStatus {
  version?: string;
  daemon_running: boolean;
  audio: AudioStatus;
  player: PlayerStatus;
  library: LibraryStatus;
  web: WebStatus;
}

export interface Settings {
  library_dirs: string[];
  web_host: string;
  web_port: number;
  auth_enabled: boolean;
  master_volume: number;
  overlap_mode: OverlapMode;
  max_concurrent_sounds: number;
  selected_mic_source: string | null;
  mic_passthrough_enabled: boolean;
  set_default_source: boolean;
  play_to_output: boolean;
  restore_previous_default_on_unload: boolean;
  auto_repair_on_resume: boolean;
  background_healthcheck_enabled: boolean;
  allowed_extensions: string[];
  allow_symlinks_outside_libraries: boolean;
  auto_port: boolean;
  stop_daemon_on_plugin_unload: boolean;
}

export interface WebAccess {
  url: string | null;
  error?: string;
}

export interface LogsTail {
  ok: boolean;
  public_log_dir?: string | null;
  lines: string[];
}

export interface Diagnostics {
  ok: boolean;
  diagnostics: Record<string, unknown>;
}
