import { callable } from "@decky/api";
import { DeckSoundpadStatus, Diagnostics, LogsTail, Settings, SoundItem, WebAccess } from "../types";

type OkResponse<T> = {
  ok: boolean;
  error?: string;
} & T;

const rawGetStatus = callable<[], DeckSoundpadStatus>("get_status");
const rawStartDaemon = callable<[], DeckSoundpadStatus>("start_daemon");
const rawListSounds = callable<[], OkResponse<{ sounds: SoundItem[] }>>("list_sounds");
const rawPlaySound = callable<[soundId: string, volume?: number], OkResponse<{ playback_id?: string }>>("play_sound");
const rawStopAll = callable<[], OkResponse<Record<string, never>>>("stop_all");
const rawRefreshLibrary = callable<[], OkResponse<{ sounds: SoundItem[] }>>("refresh_library");
const rawEnsureAudio = callable<[], DeckSoundpadStatus>("ensure_audio");
const rawRepairAudio = callable<[], DeckSoundpadStatus>("repair_audio");
const rawGetWebAccess = callable<[], WebAccess>("get_web_access");
const rawGetSettings = callable<[], Settings>("get_settings");
const rawUpdateSettings = callable<[patch: Partial<Settings>], Settings>("update_settings");
const rawGetLogsTail = callable<[lines?: number], LogsTail>("get_logs_tail");
const rawGetDiagnostics = callable<[], Diagnostics>("get_diagnostics");

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
export const startDaemon = () => withTimeout("start_daemon", rawStartDaemon(), 1200);
export const listSounds = () => withTimeout("list_sounds", rawListSounds(), 1600);
export const playSound = (soundId: string, volume?: number) =>
  withTimeout("play_sound", rawPlaySound(soundId, volume), 6500);
export const stopAll = () => withTimeout("stop_all", rawStopAll(), 1200);
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
export const getWebAccess = () => withTimeout("get_web_access", rawGetWebAccess(), 1000);
export const getSettings = () => withTimeout("get_settings", rawGetSettings(), 1400);
export const updateSettings = (patch: Partial<Settings>) =>
  withTimeout("update_settings", rawUpdateSettings(patch), 1600);
export const getLogsTail = (lines?: number) => withTimeout("get_logs_tail", rawGetLogsTail(lines), 1800);
export const getDiagnostics = () => withTimeout("get_diagnostics", rawGetDiagnostics(), 2400);

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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
