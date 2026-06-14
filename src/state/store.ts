import { useCallback, useEffect, useMemo, useState } from "react";
import { getStatus, refreshLibrary, startDaemon } from "../api/decky";
import { DeckSoundpadStatus, SoundItem } from "../types";

export function useDeckSoundpadData(onActivity?: (message: string) => void) {
  const [status, setStatus] = useState<DeckSoundpadStatus | null>(null);
  const [sounds, setSounds] = useState<SoundItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    onActivity?.("Requesting daemon status");
    try {
      const nextStatus = await getStatus();
      setStatus(nextStatus);
      if (!nextStatus.daemon_running) {
        onActivity?.("Daemon is not running");
      } else if (nextStatus.audio.last_error === "Audio status pending") {
        onActivity?.("Daemon is running; audio check is pending");
      } else if (nextStatus.audio.last_error) {
        onActivity?.(`Audio status: ${nextStatus.audio.last_error}`);
      } else {
        onActivity?.("Daemon status loaded");
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unable to load DeckSoundpad";
      onActivity?.(`Quick status failed: ${message}`);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [onActivity]);

  const start = useCallback(async () => {
    setError(null);
    onActivity?.("Starting daemon");
    try {
      const nextStatus = await startDaemon();
      setStatus(nextStatus);
      onActivity?.("Daemon start requested");
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
      onActivity?.(`Daemon start failed: ${message}`);
      setError(message);
    }
  }, [onActivity, reload]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    onActivity?.("Refreshing sound library");
    try {
      await startDaemon();
      await delay(700);
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
  }, [onActivity]);

  useEffect(() => {
    onActivity?.("Safe open: no daemon or audio commands started automatically");
  }, [onActivity]);

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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
