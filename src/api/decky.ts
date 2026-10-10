import { callable } from "@decky/api";
import type {
  DeckSoundpadStatus,
  InputDevicesResponse,
  LibraryFolderResponse,
  LibraryRefreshResponse,
  PlaybackResponse,
  Settings,
} from "../types";
import { delay } from "../utils/timing";

const rawGetStatus = callable<[], DeckSoundpadStatus>("get_status");
const rawStartBackend = callable<[], DeckSoundpadStatus>("start_backend");
const rawRefreshLibrary = callable<[], LibraryRefreshResponse>(
  "refresh_library",
);
const rawSetLibraryFolder = callable<[folder: string], LibraryFolderResponse>(
  "set_library_folder",
);
const rawPlayTestSound = callable<[], PlaybackResponse>("play_test_sound");
const rawRepairAudio = callable<[], DeckSoundpadStatus>("repair_audio");
const rawGetSettings = callable<[], Settings>("get_settings");
const rawGetInputDevices = callable<[], InputDevicesResponse>(
  "get_input_devices",
);
const rawUpdateSettings = callable<[patch: Partial<Settings>], Settings>(
  "update_settings",
);

function withTimeout<T>(
  label: string,
  promise: Promise<T>,
  timeoutMs = 1800,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${label} timed out`)),
      timeoutMs,
    );
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) {
      clearTimeout(timer);
    }
  });
}

export const getStatus = () => withTimeout("get_status", rawGetStatus(), 900);

export const startBackend = () =>
  withTimeout("start_backend", rawStartBackend(), 1200);

export const refreshLibrary = () =>
  withTimeout("refresh_library", rawRefreshLibrary(), 2200);

export const setLibraryFolder = (folder: string) =>
  withTimeout("set_library_folder", rawSetLibraryFolder(folder), 4000);

export const playTestSound = () =>
  withTimeout("play_test_sound", rawPlayTestSound(), 3000);

export const getSettings = () =>
  withTimeout("get_settings", rawGetSettings(), 1400);

export const getInputDevices = () =>
  withTimeout("get_input_devices", rawGetInputDevices(), 1800);

export const updateSettings = (patch: Partial<Settings>) =>
  withTimeout("update_settings", rawUpdateSettings(patch), 1600);

const repairAudio = () => withTimeout("repair_audio", rawRepairAudio(), 1500);

export async function restartDeckSoundpadAndWait(
  onProgress?: (status: DeckSoundpadStatus) => void,
  timeoutMs = 20000,
): Promise<DeckSoundpadStatus> {
  let status = await repairAudio();
  const restartId = status.restart_id;
  onProgress?.(status);
  const deadline = Date.now() + timeoutMs;
  // Restart runs in the backend worker. A terminal status is accepted only
  // after the exact restart operation requested above has completed.
  while (Date.now() < deadline) {
    if (restartId !== undefined) {
      if (
        status.restart_running !== true &&
        (status.restart_completed_id ?? 0) >= restartId
      ) {
        return status;
      }
    } else if (!audioTaskInProgress(status)) {
      return status;
    }
    await delay(500);
    status = await getStatus();
    onProgress?.(status);
  }
  throw new Error("DeckSoundpad restart timed out");
}

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
