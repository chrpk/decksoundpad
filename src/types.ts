type OverlapMode = "overlap" | "single" | "per_sound";

interface SoundItem {
  id: string;
  display_name: string;
  path: string;
  relative_path: string;
  category: string;
  extension: string;
}

interface AudioStatus {
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

interface PlayerStatus {
  backend: string | null;
}

interface LibraryStatus {
  count: number;
}

interface PlaybackRoute {
  backend: string | null;
  virtual_input: "decksoundpad_mic";
  sink: "decksoundpad_sink";
  mode: "stream_to_internal_sink" | "offline";
}

export interface DeckSoundpadStatus {
  version?: string;
  backend_running: boolean;
  audio: AudioStatus;
  player: PlayerStatus;
  library: LibraryStatus;
  mic_passthrough_enabled?: boolean;
  playback_route?: PlaybackRoute;
}

export interface Settings {
  library_dirs: string[];
  master_volume: number;
  overlap_mode: OverlapMode;
  max_concurrent_sounds: number;
  max_playback_seconds: number;
  selected_mic_source: string | null;
  mic_passthrough_enabled: boolean;
  auto_repair_on_resume: boolean;
  background_healthcheck_enabled: boolean;
  allowed_extensions: string[];
  allow_symlinks_outside_libraries: boolean;
}

export interface LibraryRefreshResponse {
  ok: boolean;
  error?: string;
  sounds: SoundItem[];
}
