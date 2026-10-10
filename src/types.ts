type OverlapMode = "overlap" | "single" | "per_sound";
export type OverlayHotkeyButton = "l4" | "l5" | "r4" | "r5";

export interface OverlayInputDevice {
  id: string;
  name: string;
  path: string;
  label: string;
}

export interface InputDevicesResponse {
  devices: OverlayInputDevice[];
}

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
  dirs?: string[];
}

interface PlaybackRoute {
  backend: string | null;
  virtual_input: "decksoundpad_mic";
  sink: "decksoundpad_sink";
  mode: "stream_to_internal_sink" | "offline";
}

export interface DeckSoundpadStatus {
  backend_running: boolean;
  version?: string;
  restart_running?: boolean;
  restart_id?: number;
  restart_completed_id?: number;
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
  mic_passthrough_volume: number;
  auto_repair_on_resume: boolean;
  background_healthcheck_enabled: boolean;
  overlay_hotkey_button: OverlayHotkeyButton;
  overlay_input_device: string;
  allowed_extensions: string[];
  allow_symlinks_outside_libraries: boolean;
}

export interface LibraryRefreshResponse {
  ok: boolean;
  error?: string;
  sounds: SoundItem[];
}

export interface LibraryFolderResponse {
  ok: boolean;
  error?: string;
  settings: Settings;
  sounds: SoundItem[];
}

export interface PlaybackResponse {
  ok: boolean;
  error?: string;
}
