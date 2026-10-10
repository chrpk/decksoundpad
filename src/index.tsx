import { staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaVolumeUp } from "react-icons/fa";
import { BUILD_METADATA } from "./buildInfo";
import { ControlsPanel } from "./components/ControlsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SoundGrid } from "./components/SoundGrid";
import { StatusCard } from "./components/StatusCard";
import { useDeckSoundpadData } from "./state/store";

function Content() {
  const {
    status,
    settings,
    loading,
    error,
    refresh,
    changeLibraryFolder,
    setStatus,
    setSettings,
    setError,
  } = useDeckSoundpadData();

  return (
    <div style={contentStyle}>
      <StatusCard
        status={status}
        loading={loading}
        error={error}
        onStatus={setStatus}
        onError={setError}
      />
      <SoundGrid
        libraryDirs={settings?.library_dirs ?? []}
        folderPickerStart={status?.library.dirs?.[0] ?? null}
        soundCount={status?.library.count ?? 0}
        loading={loading}
        onRefresh={() => void refresh()}
        onFolderChange={(folder) => void changeLibraryFolder(folder)}
      />
      <SettingsPanel
        status={status}
        settings={settings}
        onStatus={setStatus}
        onSettings={setSettings}
        onError={setError}
      />
      <ControlsPanel
        overlayHotkeyButton={settings?.overlay_hotkey_button ?? "l5"}
      />
      <div style={buildMetaStyle}>{BUILD_METADATA}</div>
    </div>
  );
}

const contentStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  width: "100%",
} as const;

const buildMetaStyle = {
  fontSize: "11px",
  fontVariantNumeric: "tabular-nums",
  lineHeight: "1.3",
  opacity: 0.5,
  overflowWrap: "anywhere",
  padding: "0 16px 8px",
  textAlign: "center",
} as const;

export default definePlugin(() => {
  return {
    name: "DeckSoundpad",
    titleView: <div className={staticClasses.Title}>DeckSoundpad</div>,
    content: <Content />,
    icon: <FaVolumeUp />,
  };
});
