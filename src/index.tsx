import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { useCallback, useState } from "react";
import { FaVolumeUp } from "react-icons/fa";
import { BUILD_DATETIME } from "./buildInfo";
import { ControlsPanel } from "./components/ControlsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SoundGrid } from "./components/SoundGrid";
import { RepairAudioRoutingPanel, StatusCard } from "./components/StatusCard";
import { useDeckSoundpadData } from "./state/store";

function Content() {
  const [, setActivity] = useState<string[]>(() => [formatActivity("Panel opened")]);
  const addActivity = useCallback((message: string) => {
    setActivity((entries) => [formatActivity(message), ...entries].slice(0, 30));
  }, []);
  const {
    status,
    settings,
    loading,
    error,
    refresh,
    setStatus,
    setError,
  } = useDeckSoundpadData(addActivity);

  return (
    <div style={contentStyle}>
      <div style={topBuildMetaStyle}>Build {BUILD_DATETIME}</div>
      <StatusCard status={status} loading={loading} />
      <SettingsPanel
        status={status}
        onStatus={setStatus}
        onError={setError}
        onActivity={addActivity}
      />
      <ControlsPanel />
      {error ? (
        <PanelSection title="Playback error">
          <PanelSectionRow>{error}</PanelSectionRow>
        </PanelSection>
      ) : null}
      <SoundGrid
        libraryDirs={settings?.library_dirs ?? []}
        soundCount={status?.library.count ?? 0}
        loading={loading}
        onRefresh={() => void refresh()}
      />
      <RepairAudioRoutingPanel onStatus={setStatus} onError={setError} onActivity={addActivity} />
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

export default definePlugin(() => {
  return {
    name: "DeckSoundpad",
    titleView: <div className={staticClasses.Title}>DeckSoundpad</div>,
    content: <Content />,
    icon: <FaVolumeUp />,
  };
});
