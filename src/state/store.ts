import { useCallback, useEffect, useState } from "react";
import { getSettings, getStatus, refreshLibrary, startBackend } from "../api/decky";
import { DeckSoundpadStatus, Settings } from "../types";
import { delay } from "../utils/timing";

export function useDeckSoundpadData() {
  const [status, setStatus] = useState<DeckSoundpadStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getStatus());
    } catch {
      return;
    }
  }, []);

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
    try {
      if (!status?.backend_running) {
        await startBackend();
        // Decky callables return before the backend has finished repairing the
        // audio route, so give the worker one short tick before refreshing.
        await delay(700);
      }
      const response = await refreshLibrary();
      if (!response.ok) {
        setError(response.error ?? "Library refresh failed");
      }
      const nextStatus = await getStatus();
      setStatus(nextStatus);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Library refresh failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [status?.backend_running]);

  useEffect(() => {
    void loadStatus();
    void loadSettings();
    const statusTimer = window.setInterval(() => {
      void loadStatus();
    }, 2500);
    return () => window.clearInterval(statusTimer);
  }, [loadSettings, loadStatus]);

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
