import { PanelSection, PanelSectionRow } from "@decky/ui";
import { DeckSoundpadStatus } from "../types";

interface SettingsPanelProps {
  status: DeckSoundpadStatus | null;
}

export function SettingsPanel({ status }: SettingsPanelProps) {
  const inputName =
    status?.audio.selected_real_mic_description ?? status?.audio.selected_real_mic ?? "Steam Deck mic not detected";

  return (
    <PanelSection title="Virtual input">
      <PanelSectionRow>
        <div style={routeBoxStyle}>
          <div style={routeItemStyle}>
            <strong>DeckSoundpad mic</strong>
            <span>Steam Deck mic + clicked sounds</span>
            <small>Mic: {inputName}</small>
          </div>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

const routeBoxStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "10px",
  width: "100%",
} as const;

const routeItemStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "3px",
  lineHeight: "1.3",
  overflowWrap: "anywhere",
} as const;
