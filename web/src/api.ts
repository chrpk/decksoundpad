export interface SoundItem {
  id: string;
  display_name: string;
  category: string;
  relative_path: string;
}

export interface StatusResponse {
  audio?: {
    sink_exists: boolean;
    virtual_mic_exists: boolean;
    loopback_exists: boolean;
    selected_real_mic: string | null;
    last_error: string | null;
    state?: string;
  };
  player?: {
    backend: string | null;
    active_playbacks: number;
  };
  library?: {
    count: number;
  };
}

export interface LogsResponse {
  ok: boolean;
  lines: string[];
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getStatus(): Promise<StatusResponse> {
  return request("/api/v1/status/quick");
}

export async function listSounds(): Promise<SoundItem[]> {
  const response = await request<{ sounds: SoundItem[] }>("/api/v1/sounds");
  return response.sounds;
}

export function playSound(soundId: string, volume: number): Promise<unknown> {
  return request("/api/v1/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sound_id: soundId, volume }),
  });
}

export function stopAll(): Promise<unknown> {
  return request("/api/v1/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ playback_id: null, sound_id: null }),
  });
}

export function repairAudio(): Promise<unknown> {
  return request("/api/v1/audio/repair", { method: "POST" });
}

export async function repairAudioAndWait(
  onProgress?: (status: StatusResponse) => void,
  timeoutMs = 15000,
): Promise<StatusResponse> {
  await repairAudio();
  let status = await getStatus();
  onProgress?.(status);
  const deadline = Date.now() + timeoutMs;
  while (audioTaskInProgress(status) && Date.now() < deadline) {
    await delay(500);
    status = await getStatus();
    onProgress?.(status);
  }
  if (audioTaskInProgress(status)) {
    throw new Error("audio repair timed out");
  }
  return status;
}

export function getLogsTail(lines = 120): Promise<LogsResponse> {
  return request(`/api/v1/logs/tail?lines=${lines}`);
}

function audioTaskInProgress(status: StatusResponse): boolean {
  const state = status.audio?.state;
  if (state === "starting" || state === "repairing" || state === "pending") {
    return true;
  }
  const message = status.audio?.last_error ?? "";
  return (
    message === "Audio status pending" ||
    message === "Audio initialization already running" ||
    /^Audio (ensure|repair) started$/.test(message)
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
