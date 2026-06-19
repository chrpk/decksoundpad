import { callable } from "@decky/api";
import { DeckSoundpadStatus, Settings } from "../types";
import { delay } from "../utils/timing";

type OkResponse<T> = {
  ok: boolean;
  error?: string;
} & T;

const rawGetStatus = callable<[], DeckSoundpadStatus>("get_status");
const rawStartBackend = callable<[], DeckSoundpadStatus>("start_backend");
const rawRefreshLibrary = callable<[], OkResponse<{ sounds: unknown[] }>>("refresh_library");
const rawEnsureAudio = callable<[], DeckSoundpadStatus>("ensure_audio");
const rawRepairAudio = callable<[], DeckSoundpadStatus>("repair_audio");
const rawGetSettings = callable<[], Settings>("get_settings");
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
export const ensureAudio = () => withTimeout("ensure_audio", rawEnsureAudio(), 1500);
export const repairAudio = () => withTimeout("repair_audio", rawRepairAudio(), 1500);
export async function repairAudioAndWait(
  onProgress?: (status: DeckSoundpadStatus) => void,
  timeoutMs = 15000,
): Promise<DeckSoundpadStatus> {
  let status = await repairAudio();
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
export const getSettings = () => withTimeout("get_settings", rawGetSettings(), 1400);
export const updateSettings = (patch: Partial<Settings>) =>
  withTimeout("update_settings", rawUpdateSettings(patch), 1600);

function audioTaskInProgress(status: DeckSoundpadStatus): boolean {
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
