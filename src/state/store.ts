import { useCallback, useEffect, useState } from "react";
import { getSettings, getStatus, refreshLibrary, startBackend } from "../api/decky";
import { DeckSoundpadStatus, Settings } from "../types";
import { delay } from "../utils/timing";

export function useDeckSoundpadData(onActivity?: (message: string) => void) {
  const [status, setStatus] = useState<DeckSoundpadStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(
    async ({ silent = false, showLoading = false }: { silent?: boolean; showLoading?: boolean } = {}) => {
      if (showLoading) {
        setLoading(true);
      }
      if (!silent) {
        setError(null);
        onActivity?.("Requesting backend status");
      }
      try {
        const nextStatus = await getStatus();
        setStatus(nextStatus);
        if (!silent) {
          if (!isBackendRunning(nextStatus)) {
            onActivity?.("Backend is not running");
          } else if (nextStatus.audio.last_error === "Audio status pending") {
            onActivity?.("Backend is running; audio check is pending");
          } else if (nextStatus.audio.last_error) {
            onActivity?.(`Audio status: ${nextStatus.audio.last_error}`);
          } else {
            onActivity?.("Backend status loaded");
          }
        }
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "Unable to load DeckSoundpad";
        if (!silent) {
          onActivity?.(`Quick status failed: ${message}`);
          setError(message);
        }
      } finally {
        if (showLoading) {
          setLoading(false);
        }
      }
    },
    [onActivity],
  );

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await getSettings());
    } catch {
      setSettings(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    onActivity?.("Refreshing sound library");
    try {
      if (!status?.backend_running) {
        await startBackend();
        await delay(700);
      }
      const response = await refreshLibrary();
      if (response.ok) {
        onActivity?.(`Sound library loaded: ${response.sounds.length} sounds`);
      } else {
        setError(response.error ?? "Library refresh failed");
        onActivity?.(`Sound library refresh failed: ${response.error ?? "unknown error"}`);
      }
      const nextStatus = await getStatus();
      setStatus(nextStatus);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Library refresh failed";
      setError(message);
      onActivity?.(`Sound library refresh failed: ${message}`);
    } finally {
      setLoading(false);
    }
  }, [onActivity, status?.backend_running]);

  useEffect(() => {
    onActivity?.("Safe open: no audio commands started automatically");
    void loadStatus({ silent: true });
    void loadSettings();
    const statusTimer = window.setInterval(() => {
      void loadStatus({ silent: true });
    }, 2500);
    return () => window.clearInterval(statusTimer);
  }, [loadSettings, loadStatus, onActivity]);

  return {
    status,
    settings,
    loading,
    error,
    refresh,
    setStatus,
    setError,
  };
}

function isBackendRunning(status: DeckSoundpadStatus): boolean {
  return status.backend_running;
}
