import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaVolumeUp } from "react-icons/fa";
import { BUILD_METADATA } from "./buildInfo";
import { ControlsPanel } from "./components/ControlsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SoundGrid } from "./components/SoundGrid";
import { RecoveryPanel, StatusCard } from "./components/StatusCard";
import { useDeckSoundpadData } from "./state/store";

function Content() {
  const {
    status,
    settings,
    loading,
    error,
    refresh,
    setStatus,
    setSettings,
    setError,
  } = useDeckSoundpadData();

  return (
    <div style={contentStyle}>
      <div style={topBuildMetaStyle}>{BUILD_METADATA}</div>
      <StatusCard status={status} loading={loading} />
      <SettingsPanel
        status={status}
        settings={settings}
        onStatus={setStatus}
        onSettings={setSettings}
        onError={setError}
      />
      <ControlsPanel overlayHotkeyButton={settings?.overlay_hotkey_button ?? "l5"} />
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
      <RecoveryPanel onStatus={setStatus} onError={setError} />
    </div>
  );
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
