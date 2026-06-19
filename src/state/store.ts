import { useCallback, useEffect, useMemo, useState } from "react";
import { getSettings, getStatus, refreshLibrary, startBackend } from "../api/decky";
import { DeckSoundpadStatus, Settings, SoundItem } from "../types";
import { delay } from "../utils/timing";

export function useDeckSoundpadData(onActivity?: (message: string) => void) {
  const [status, setStatus] = useState<DeckSoundpadStatus | null>(null);
  const [sounds, setSounds] = useState<SoundItem[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [query, setQuery] = useState("");
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

  const reload = useCallback(async () => {
    await loadStatus({ showLoading: true });
  }, [loadStatus]);

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await getSettings());
    } catch {
      setSettings(null);
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    onActivity?.("Starting backend");
    try {
      const nextStatus = await startBackend();
      setStatus(nextStatus);
      onActivity?.("Backend start requested");
      window.setTimeout(() => {
        void reload();
        void refreshLibrary()
          .then((response) => {
            if (response.ok) {
              setSounds(response.sounds);
              onActivity?.(`Sound library loaded: ${response.sounds.length} sounds`);
            }
          })
          .catch(() => undefined);
      }, 900);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unable to start DeckSoundpad";
      onActivity?.(`Backend start failed: ${message}`);
      setError(message);
    }
  }, [onActivity, reload]);

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
        setSounds(response.sounds);
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

  const filteredSounds = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return sounds;
    }
    return sounds.filter((sound) =>
      `${sound.display_name} ${sound.category} ${sound.relative_path}`
        .toLowerCase()
        .includes(normalized),
    );
  }, [query, sounds]);

  return {
    status,
    settings,
    sounds,
    filteredSounds,
    query,
    setQuery,
    loading,
    error,
    start,
    reload,
    refresh,
    setStatus,
    setError,
  };
}

function isBackendRunning(status: DeckSoundpadStatus): boolean {
  return status.backend_running;
}
