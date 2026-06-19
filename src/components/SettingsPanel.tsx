import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useCallback, useState } from "react";
import { getStatus, updateSettings } from "../api/decky";
import { DeckSoundpadStatus } from "../types";

interface SettingsPanelProps {
  status: DeckSoundpadStatus | null;
  onStatus: (status: DeckSoundpadStatus) => void;
  onError: (message: string) => void;
  onActivity: (message: string) => void;
}

export function SettingsPanel({ status, onStatus, onError, onActivity }: SettingsPanelProps) {
  const [isUpdating, setUpdating] = useState(false);
  const passthroughEnabled = Boolean(status?.mic_passthrough_enabled);
  const disabled = !isBackendRunning(status) || isUpdating;

  const setPassthrough = useCallback(async (nextEnabled: boolean) => {
    if (!status) {
      onError("Status is not available yet");
      return;
    }
    setUpdating(true);
    try {
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
  }, [onActivity, onError, onStatus, status]);

  return (
    <PanelSection title="Settings">
      <PanelSectionRow>
        <ToggleField
          checked={passthroughEnabled}
          disabled={disabled}
          label="Real mic passthrough"
          description={passthroughEnabled ? "Yes - include real mic input" : "No - soundboard audio only"}
          onChange={(checked) => {
            void setPassthrough(checked);
          }}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

function isBackendRunning(status: DeckSoundpadStatus | null): boolean {
  return Boolean(status?.backend_running);
}
