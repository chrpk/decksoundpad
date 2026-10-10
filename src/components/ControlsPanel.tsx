import {
  ButtonItem,
  ConfirmModal,
  PanelSection,
  PanelSectionRow,
  showModal,
} from "@decky/ui";
import type { ReactNode } from "react";
import { FaFolderOpen, FaGamepad, FaMicrophone, FaTools } from "react-icons/fa";
import type { OverlayHotkeyButton } from "../types";

interface ControlDetail {
  label: string;
  detail: string;
}

function overlayControls(button: OverlayHotkeyButton): ControlDetail[] {
  const controls: ControlDetail[] = [
    {
      label: button.toUpperCase(),
      detail: "Open or close the in-game overlay.",
    },
    { label: "D-pad / stick", detail: "Move the highlight between sounds." },
    {
      label: "A",
      detail: "Play the highlighted sound and return to the game.",
    },
    {
      label: "X",
      detail: "Play the highlighted sound and keep the overlay open.",
    },
    { label: "Y", detail: "Stop all sounds." },
    { label: "B", detail: "Close the overlay without playing." },
    {
      label: "L1 / R1",
      detail:
        "Previous or next page. Pages run through Recent and each sound folder.",
    },
    {
      label: "Touch",
      detail:
        "Tap a sound to play it, a tab to jump to it, or outside the grid to close.",
    },
  ];
  if (button !== "r5") {
    // R5 doubles as the overlay button when selected, so replay is unavailable then.
    controls.splice(1, 0, {
      label: "R5",
      detail: "Replay the last sound, even with the overlay closed.",
    });
  }
  return controls;
}

const menuControls: ControlDetail[] = [
  {
    label: "Restart DeckSoundpad",
    detail:
      "Stops playback and reloads audio, sounds, settings, and controller input.",
  },
  {
    label: "Real mic passthrough",
    detail:
      "Mixes the input device selected in Steam Settings > Audio with soundboard playback.",
  },
  {
    label: "Volume",
    detail: "Sound and mic volume go up to 150% for quiet files or mics.",
  },
  {
    label: "Refresh sounds",
    detail:
      "Reloads WAV, FLAC, OGG, and MP3 files from the configured folders.",
  },
  {
    label: "Test sound",
    detail:
      "Plays a short beep through DeckSoundpad mic to check the audio route.",
  },
  {
    label: "Voice input",
    detail: "Select DeckSoundpad mic in your voice app.",
  },
];

interface ControlsPanelProps {
  overlayHotkeyButton: OverlayHotkeyButton;
}

function ControlsGuide({ overlayHotkeyButton }: ControlsPanelProps) {
  return (
    <>
      <style>{CONTROLS_SCROLL_STYLES}</style>
      <div className="decksoundpad-controls-scroll" style={panelStackStyle}>
        <GuideGroup
          icon={<FaGamepad />}
          title="In-game overlay"
          items={overlayControls(overlayHotkeyButton)}
        />
        <GuideGroup
          icon={<FaTools />}
          title="Decky menu"
          items={menuControls}
        />
        <div style={noteStyle}>
          <FaFolderOpen style={noteIconStyle} />
          <span>
            Add sounds to ~/Music/DeckSoundpad, then refresh from this menu.
          </span>
        </div>
        <div style={noteStyle}>
          <FaMicrophone style={noteIconStyle} />
          <span>For voice chat, the app input must be DeckSoundpad mic.</span>
        </div>
      </div>
    </>
  );
}

export function ControlsPanel({ overlayHotkeyButton }: ControlsPanelProps) {
  return (
    <PanelSection title="Controls">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => openControlsDialog(overlayHotkeyButton)}
        >
          <FaGamepad style={buttonIconStyle} />
          Controls guide
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function openControlsDialog(overlayHotkeyButton: OverlayHotkeyButton) {
  const modal = showModal(
    <ConfirmModal
      strTitle="Controls"
      strOKButtonText="Close"
      bAlertDialog
      bAllowFullSize
      onCancel={() => modal.Close()}
      onOK={() => modal.Close()}
      closeModal={() => modal.Close()}
    >
      <ControlsGuide overlayHotkeyButton={overlayHotkeyButton} />
    </ConfirmModal>,
    undefined,
    { strTitle: "Controls", bHideMainWindowForPopouts: false },
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

const buttonIconStyle = {
  marginRight: "8px",
} as const;

const CONTROLS_SCROLL_STYLES = `
.decksoundpad-controls-scroll {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.32) rgba(255, 255, 255, 0.06);
}
.decksoundpad-controls-scroll::-webkit-scrollbar {
  width: 8px;
}
.decksoundpad-controls-scroll::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
}
.decksoundpad-controls-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.32);
  border-radius: 4px;
}
.decksoundpad-controls-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.48);
}
`;

const panelStackStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  fontSize: "12px",
  lineHeight: "1.35",
  maxHeight: "50vh",
  minWidth: 0,
  overflowY: "auto",
  paddingRight: "10px",
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
  alignItems: "baseline",
  columnGap: "10px",
  display: "grid",
  gridTemplateColumns: "max-content minmax(0, 1fr)",
  minWidth: 0,
  rowGap: "5px",
} as const;

const controlRowStyle = {
  display: "contents",
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
