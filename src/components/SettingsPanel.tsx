import { DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { getInputDevices, getStatus, updateSettings } from "../api/decky";
import {
  DeckSoundpadStatus,
  OverlayHotkeyButton,
  OverlayInputDevice,
  Settings,
} from "../types";
import { errorMessage } from "../utils/errors";
import { isBackendRunning } from "../utils/status";

const OVERLAY_HOTKEY_OPTIONS: { data: OverlayHotkeyButton; label: string }[] = [
  { data: "l4", label: "L4" },
  { data: "l5", label: "L5" },
  { data: "r4", label: "R4" },
  { data: "r5", label: "R5" },
];

const AUTO_INPUT_DEVICE: OverlayInputDevice = {
  id: "auto",
  name: "Automatic",
  path: "",
  label: "Automatic (all compatible controllers)",
};

interface SettingsPanelProps {
  status: DeckSoundpadStatus | null;
  settings: Settings | null;
  onStatus: (status: DeckSoundpadStatus) => void;
  onSettings: (settings: Settings) => void;
  onError: (message: string) => void;
}

export function SettingsPanel({
  status,
  settings,
  onStatus,
  onSettings,
  onError,
}: SettingsPanelProps) {
  const [isUpdating, setUpdating] = useState(false);
  const [inputDevices, setInputDevices] = useState<OverlayInputDevice[]>([
    AUTO_INPUT_DEVICE,
  ]);
  const passthroughEnabled = settings?.mic_passthrough_enabled
    ?? Boolean(status?.mic_passthrough_enabled);
  const overlayHotkeyButton = settings?.overlay_hotkey_button ?? "l5";
  const overlayInputDevice = settings?.overlay_input_device ?? "auto";
  const disabled = !isBackendRunning(status) || isUpdating;

  useEffect(() => {
    let cancelled = false;
    void getInputDevices()
      .then((response) => {
        if (!cancelled) {
          setInputDevices(response.devices.length > 0 ? response.devices : [AUTO_INPUT_DEVICE]);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setInputDevices([AUTO_INPUT_DEVICE]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const inputDeviceOptions = inputDevices.map((device) => ({
    data: device.id,
    label: device.label,
  }));
  if (!inputDeviceOptions.some((option) => option.data === overlayInputDevice)) {
    inputDeviceOptions.push({
      data: overlayInputDevice,
      label: `Unavailable device (${overlayInputDevice.slice(-8)})`,
    });
  }

  const setPassthrough = useCallback(async (nextEnabled: boolean) => {
    if (!status) {
      onError("Status is not available yet");
      return;
    }
    setUpdating(true);
    try {
      onSettings(await updateSettings({ mic_passthrough_enabled: nextEnabled }));
      onStatus(await getStatus());
    } catch (caught) {
      onError(errorMessage(caught, "Failed to update mic input toggle"));
    } finally {
      setUpdating(false);
    }
  }, [onError, onSettings, onStatus, status]);

  const setOverlayHotkey = useCallback(async (button: OverlayHotkeyButton) => {
    setUpdating(true);
    try {
      onSettings(await updateSettings({ overlay_hotkey_button: button }));
    } catch (caught) {
      onError(errorMessage(caught, "Failed to update overlay button"));
    } finally {
      setUpdating(false);
    }
  }, [onError, onSettings]);

  const setOverlayInputDevice = useCallback(async (device: string) => {
    setUpdating(true);
    try {
      onSettings(await updateSettings({ overlay_input_device: device }));
    } catch (caught) {
      onError(errorMessage(caught, "Failed to update controller input"));
    } finally {
      setUpdating(false);
    }
  }, [onError, onSettings]);

  return (
    <PanelSection title="Settings">
      <DropdownItem
        label="Overlay button"
        description="Rear button used to open and close the in-game overlay."
        rgOptions={OVERLAY_HOTKEY_OPTIONS}
        selectedOption={overlayHotkeyButton}
        disabled={disabled}
        onChange={(option) => {
          void setOverlayHotkey(option.data as OverlayHotkeyButton);
        }}
      />
      <DropdownItem
        label="Controller input"
        description="Automatic uses the built-in Steam Deck path. Select a controller to use its evdev input only."
        rgOptions={inputDeviceOptions}
        selectedOption={overlayInputDevice}
        disabled={disabled}
        onChange={(option) => {
          void setOverlayInputDevice(String(option.data));
        }}
      />
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
