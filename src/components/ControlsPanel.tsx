import { PanelSection, PanelSectionRow } from "@decky/ui";
import type { ReactNode } from "react";
import { FaFolderOpen, FaGamepad, FaMicrophone, FaTools } from "react-icons/fa";

interface ControlDetail {
  label: string;
  detail: string;
}

const overlayControls: ControlDetail[] = [
  { label: "L5", detail: "Open or close the in-game overlay." },
  { label: "D-pad", detail: "Move the highlighted sound." },
  { label: "A", detail: "Play the highlighted sound and return to the game." },
  { label: "L1 / R1", detail: "Move to the previous or next sound page." },
  { label: "Touch / click", detail: "Play a sound tile directly." },
];

const menuControls: ControlDetail[] = [
  { label: "Repair audio routing", detail: "Rebuilds the virtual mic route after setup, sleep, or game changes." },
  { label: "Real mic passthrough", detail: "Keeps your physical microphone mixed with soundboard playback." },
  { label: "Refresh sounds", detail: "Reloads WAV, FLAC, OGG, and MP3 files from the configured folders." },
  { label: "Voice input", detail: "Select DeckSoundpad mic in Discord, Steam Voice, games, or browser voice chat." },
];

export function ControlsPanel() {
  return (
    <PanelSection title="Controls">
      <PanelSectionRow>
        <div style={panelStackStyle}>
          <GuideGroup icon={<FaGamepad />} title="In-game overlay" items={overlayControls} />
          <GuideGroup icon={<FaTools />} title="Decky menu" items={menuControls} />
          <div style={noteStyle}>
            <FaFolderOpen style={noteIconStyle} />
            <span>Add sounds to ~/Music/DeckSoundpad, then refresh from this menu.</span>
          </div>
          <div style={noteStyle}>
            <FaMicrophone style={noteIconStyle} />
            <span>For voice chat, the app input must be DeckSoundpad mic.</span>
          </div>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

interface GuideGroupProps {
  icon: ReactNode;
  title: string;
  items: ControlDetail[];
}

function GuideGroup({ icon, title, items }: GuideGroupProps) {
  return (
    <div style={groupStyle}>
      <div style={groupHeaderStyle}>
        <span style={groupIconStyle}>{icon}</span>
        <strong>{title}</strong>
      </div>
      <div style={controlListStyle}>
        {items.map((item) => (
          <div key={item.label} style={controlRowStyle}>
            <span style={controlKeyStyle}>{item.label}</span>
            <span style={controlDetailStyle}>{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const panelStackStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  fontSize: "12px",
  lineHeight: "1.35",
  minWidth: 0,
  width: "100%",
} as const;

const groupStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "7px",
  minWidth: 0,
} as const;

const groupHeaderStyle = {
  alignItems: "center",
  display: "flex",
  gap: "8px",
  minWidth: 0,
} as const;

const groupIconStyle = {
  alignItems: "center",
  color: "#74d8e8",
  display: "inline-flex",
  flex: "0 0 auto",
  width: "14px",
} as const;

const controlListStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "5px",
  minWidth: 0,
} as const;

const controlRowStyle = {
  alignItems: "baseline",
  display: "grid",
  gap: "8px",
  gridTemplateColumns: "74px minmax(0, 1fr)",
  minWidth: 0,
} as const;

const controlKeyStyle = {
  color: "#ffffff",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
  minWidth: 0,
  overflowWrap: "anywhere",
} as const;

const controlDetailStyle = {
  minWidth: 0,
  opacity: 0.78,
  overflowWrap: "anywhere",
} as const;

const noteStyle = {
  alignItems: "flex-start",
  display: "flex",
  gap: "8px",
  minWidth: 0,
  opacity: 0.82,
} as const;

const noteIconStyle = {
  color: "#74d8e8",
  flex: "0 0 auto",
  marginTop: "2px",
} as const;
