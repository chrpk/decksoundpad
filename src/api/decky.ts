import { callable } from "@decky/api";
import {
  DeckSoundpadStatus,
  InputDevicesResponse,
  LibraryRefreshResponse,
  Settings,
} from "../types";
import { delay } from "../utils/timing";

const rawGetStatus = callable<[], DeckSoundpadStatus>("get_status");
const rawStartBackend = callable<[], DeckSoundpadStatus>("start_backend");
const rawRefreshLibrary = callable<[], LibraryRefreshResponse>("refresh_library");
const rawRepairAudio = callable<[], DeckSoundpadStatus>("repair_audio");
const rawGetSettings = callable<[], Settings>("get_settings");
const rawGetInputDevices = callable<[], InputDevicesResponse>("get_input_devices");
const rawUpdateSettings = callable<[patch: Partial<Settings>], Settings>("update_settings");

function withTimeout<T>(label: string, promise: Promise<T>, timeoutMs = 1800): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) {
      clearTimeout(timer);
    }
  });
}

export const getStatus = () => withTimeout("get_status", rawGetStatus(), 900);
export const startBackend = () => withTimeout("start_backend", rawStartBackend(), 1200);
export const refreshLibrary = () => withTimeout("refresh_library", rawRefreshLibrary(), 2200);
const repairAudio = () => withTimeout("repair_audio", rawRepairAudio(), 1500);
export async function repairAudioAndWait(
  onProgress?: (status: DeckSoundpadStatus) => void,
  timeoutMs = 15000,
): Promise<DeckSoundpadStatus> {
  let status = await repairAudio();
  onProgress?.(status);
  const deadline = Date.now() + timeoutMs;
  // Audio repair runs in the backend worker; keep polling until it publishes
  // a terminal status instead of treating the first "repairing" reply as done.
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
export const getSettings = () => withTimeout("get_settings", rawGetSettings(), 1400);
export const getInputDevices = () =>
  withTimeout("get_input_devices", rawGetInputDevices(), 1800);
export const updateSettings = (patch: Partial<Settings>) =>
  withTimeout("update_settings", rawUpdateSettings(patch), 1600);

function audioTaskInProgress(status: DeckSoundpadStatus): boolean {
  const state = status.audio?.state;
  if (state === "starting" || state === "repairing" || state === "pending") {
    return true;
  }
  const message = status.audio?.last_error ?? "";
  // Older backend responses used progress messages before state values were
  // added, so the UI still recognizes both shapes while repair is running.
  return (
    message === "Audio status pending" ||
    message === "Audio initialization already running" ||
    message === "Audio repair started"
  );
}
