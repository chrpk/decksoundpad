import type { DeckSoundpadStatus } from "../types";

export function isBackendRunning(status: DeckSoundpadStatus | null): boolean {
  return Boolean(status?.backend_running);
}
