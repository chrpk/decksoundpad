import { useQuickAccessVisible } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import {
  getSettings,
  getStatus,
  refreshLibrary,
  setLibraryFolder,
  startBackend,
} from "../api/decky";
import type { DeckSoundpadStatus, Settings } from "../types";
import { errorMessage } from "../utils/errors";
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
      // Polling is best effort. User-triggered operations surface their own
      // errors, so a transient status failure should not replace that message.
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
      setError(errorMessage(caught, "Library refresh failed"));
    } finally {
      setLoading(false);
    }
  }, [status?.backend_running]);

  const changeLibraryFolder = useCallback(async (folder: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await setLibraryFolder(folder);
      setSettings(response.settings);
      if (!response.ok) {
        setError(response.error ?? "Could not use that sound folder");
      }
      setStatus(await getStatus());
    } catch (caught) {
      setError(errorMessage(caught, "Could not change sound folder"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  // The panel stays mounted after the Quick Access menu closes, so poll only
  // while it is on screen and refresh as soon as it reopens.
  const quickAccessVisible = useQuickAccessVisible();
  useEffect(() => {
    if (!quickAccessVisible) {
      return;
    }
    void loadStatus();
    const statusTimer = window.setInterval(() => {
      void loadStatus();
    }, 2500);
    return () => window.clearInterval(statusTimer);
  }, [loadStatus, quickAccessVisible]);

  return {
    status,
    settings,
    loading,
    error,
    refresh,
    changeLibraryFolder,
    setStatus,
    setSettings,
    setError,
  };
}
