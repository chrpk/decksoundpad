import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { FaSync } from "react-icons/fa";

interface SoundGridProps {
  libraryDirs: string[];
  soundCount: number;
  loading: boolean;
  onRefresh: () => void;
}

export function SoundGrid({ libraryDirs, soundCount, loading, onRefresh }: SoundGridProps) {
  return (
    <PanelSection title="Sounds">
      <PanelSectionRow>
        <div style={summaryStyle}>
          <strong>{soundCount} sounds</strong>
          <div style={pathListStyle}>
            {libraryDirs.length > 0
              ? libraryDirs.map((path) => <span key={path}>{path}</span>)
              : <span>Sound folder unavailable</span>}
          </div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={loading} onClick={onRefresh}>
          <FaSync style={iconStyle} />
          Refresh sounds
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
