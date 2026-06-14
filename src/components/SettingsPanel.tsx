import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useCallback, useState } from "react";
import { FaMicrophone } from "react-icons/fa";
import { getStatus, updateSettings } from "../api/decky";
import { DeckSoundpadStatus } from "../types";

interface SettingsPanelProps {
  status: DeckSoundpadStatus | null;
  onStatus: (status: DeckSoundpadStatus) => void;
  onError: (message: string) => void;
  onActivity: (message: string) => void;
}

export function SettingsPanel({ status, onStatus, onError, onActivity }: SettingsPanelProps) {
  const inputName =
    status?.audio.selected_real_mic_description ?? status?.audio.selected_real_mic ?? "Steam Deck mic not detected";
  const [isUpdating, setUpdating] = useState(false);
  const passthroughEnabled = Boolean(status?.mic_passthrough_enabled);
  const disabled = !status?.daemon_running || isUpdating;

  const togglePassthrough = useCallback(async () => {
    if (!status) {
      onError("Status is not available yet");
      return;
    }
    setUpdating(true);
    try {
      const nextEnabled = !passthroughEnabled;
      onActivity(
        `Updating real microphone passthrough: ${nextEnabled ? "enabling" : "disabling"}`,
      );
      await updateSettings({ mic_passthrough_enabled: nextEnabled });
      onStatus(await getStatus());
      onActivity(`Real microphone passthrough ${nextEnabled ? "enabled" : "disabled"}`);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Failed to update mic input toggle");
      onActivity("Failed to update real microphone passthrough");
    } finally {
      setUpdating(false);
    }
  }, [passthroughEnabled, onActivity, onError, onStatus, status]);

  return (
    <PanelSection title="Virtual input">
      <PanelSectionRow>
        <div style={routeBoxStyle}>
          <div style={routeItemStyle}>
            <strong>DeckSoundpad mic</strong>
            <span>Steam Deck mic + clicked sounds</span>
            <small>Mic: {inputName}</small>
            <small>
              Real mic passthrough:
              <strong style={{ marginLeft: "6px" }}>{passthroughEnabled ? "On" : "Off"}</strong>
            </small>
            <small style={{ opacity: 0.72, fontSize: "12px" }}>
              {passthroughEnabled
                ? "Real mic is routed into DeckSoundpad mic."
                : "Real mic input is ignored; only clicked sounds are routed."}
            </small>
            <ButtonItem
              layout="below"
              disabled={disabled}
              onClick={() => {
                void togglePassthrough();
              }}
            >
              <FaMicrophone style={iconStyle} />
              {passthroughEnabled ? "Disable" : "Enable"} real mic passthrough
            </ButtonItem>
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

const iconStyle = {
  marginRight: "8px",
} as const;
