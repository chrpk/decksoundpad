import { ButtonItem, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { useCallback, useState } from "react";
import { FaChevronDown, FaChevronRight, FaSync, FaVolumeUp } from "react-icons/fa";
import { stopAll } from "./api/decky";
import { BUILD_DATETIME } from "./buildInfo";
import { ActivityPanel } from "./components/ActivityPanel";
import { LogsPanel } from "./components/LogsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SoundGrid } from "./components/SoundGrid";
import { StatusCard } from "./components/StatusCard";
import { WebAccessCard } from "./components/WebAccessCard";
import { useDeckSoundpadData } from "./state/store";

function Content() {
  const [activity, setActivity] = useState<string[]>(() => [formatActivity("Panel opened")]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const addActivity = useCallback((message: string) => {
    setActivity((entries) => [formatActivity(message), ...entries].slice(0, 30));
  }, []);
  const {
    status,
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
  } = useDeckSoundpadData(addActivity);

  const playbackDisabled = !status?.daemon_running;
  const stopAllSounds = useCallback(async () => {
    addActivity("Stop all requested");
    try {
      const response = await stopAll();
      if (response.ok === false) {
        addActivity(`Stop all failed: ${response.error ?? "unknown error"}`);
        setError(response.error ?? "Stop all failed");
        return;
      }
      addActivity("All playback stopped");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Stop all failed";
      addActivity(`Stop all failed: ${message}`);
      setError(message);
    }
  }, [addActivity, setError]);

  return (
    <div style={contentStyle}>
      <div style={topBuildMetaStyle}>Build {BUILD_DATETIME}</div>
      <StatusCard status={status} loading={loading} onStatus={setStatus} onError={setError} onActivity={addActivity} />
      {error ? (
        <PanelSection title="Playback error">
          <PanelSectionRow>{error}</PanelSectionRow>
        </PanelSection>
      ) : null}
      <SoundGrid
        sounds={filteredSounds}
        query={query}
        setQuery={setQuery}
        disabled={Boolean(playbackDisabled)}
        loading={loading}
        activeCount={status?.player.active_playbacks ?? 0}
        onRefresh={() => void refresh()}
        onStopAll={() => void stopAllSounds()}
        onError={setError}
        onActivity={addActivity}
      />
      <SettingsPanel status={status} />
      <PanelSection title="Advanced">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setAdvancedOpen((open) => !open)}>
            {advancedOpen ? <FaChevronDown style={iconStyle} /> : <FaChevronRight style={iconStyle} />}
            {advancedOpen ? "Hide diagnostics" : "Show diagnostics"}
          </ButtonItem>
        </PanelSectionRow>
        {advancedOpen ? (
          <>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={loading}
                onClick={() => {
                  addActivity("Manual daemon start requested");
                  void start();
                }}
              >
                <FaSync style={iconStyle} />
                Start daemon
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={loading}
                onClick={() => {
                  addActivity("Manual status check requested");
                  void reload();
                }}
              >
                <FaSync style={iconStyle} />
                Check status
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : null}
      </PanelSection>
      {advancedOpen ? (
        <>
          <ActivityPanel entries={activity} />
          <WebAccessCard onActivity={addActivity} />
          <LogsPanel onActivity={addActivity} />
        </>
      ) : null}
    </div>
  );
}

function formatActivity(message: string): string {
  return `[${new Date().toLocaleTimeString()}] ${message}`;
}

const contentStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  width: "100%",
} as const;

const topBuildMetaStyle = {
  fontSize: "11px",
  fontVariantNumeric: "tabular-nums",
  lineHeight: "1.3",
  opacity: 0.68,
  overflowWrap: "anywhere",
  textAlign: "right",
} as const;

const iconStyle = {
  marginRight: "8px",
} as const;

export default definePlugin(() => ({
  name: "DeckSoundpad",
  titleView: <div className={staticClasses.Title}>DeckSoundpad</div>,
  content: <Content />,
  icon: <FaVolumeUp />,
  onDismount() {
    console.log("DeckSoundpad frontend unloaded");
  },
}));
