import { FileSelectionType, openFilePicker } from "@decky/api";
import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { FaFolderOpen, FaSync } from "react-icons/fa";

interface SoundGridProps {
  libraryDirs: string[];
  folderPickerStart: string | null;
  soundCount: number;
  loading: boolean;
  onRefresh: () => void;
  onFolderChange: (folder: string) => void;
}

export function SoundGrid({
  libraryDirs,
  folderPickerStart,
  soundCount,
  loading,
  onRefresh,
  onFolderChange,
}: SoundGridProps) {
  const pickFolder = async () => {
    if (!folderPickerStart) {
      return;
    }
    try {
      const picked = await openFilePicker(
        FileSelectionType.FOLDER,
        folderPickerStart,
      );
      onFolderChange(picked.realpath || picked.path);
    } catch {
      // Closing the picker without choosing keeps the current folder.
    }
  };

  return (
    <PanelSection title="Sounds">
      <PanelSectionRow>
        <div style={summaryStyle}>
          <strong>
            {soundCount === 1 ? "1 sound" : `${soundCount} sounds`}
          </strong>
          {soundCount === 0 && !loading ? (
            <span>
              Add WAV, FLAC, OGG, or MP3 files to this folder, then refresh.
            </span>
          ) : null}
          <div style={pathListStyle}>
            {libraryDirs.length > 0 ? (
              libraryDirs.map((path) => <span key={path}>{path}</span>)
            ) : (
              <span>Sound folder unavailable</span>
            )}
          </div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={loading} onClick={onRefresh}>
          <FaSync style={iconStyle} />
          {loading ? "Refreshing…" : "Refresh sounds"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={loading || !folderPickerStart}
          onClick={() => void pickFolder()}
        >
          <FaFolderOpen style={iconStyle} />
          Change sound folder
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

const summaryStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "6px",
  fontSize: "12px",
  lineHeight: "1.35",
  minWidth: 0,
  width: "100%",
} as const;

const pathListStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "3px",
  opacity: 0.78,
  overflowWrap: "anywhere",
} as const;

const iconStyle = {
  marginRight: "8px",
} as const;
