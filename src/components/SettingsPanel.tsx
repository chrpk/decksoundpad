import {
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
} from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { getInputDevices, getStatus, updateSettings } from "../api/decky";
import type {
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

// Sliders report every step while dragging; save once the value settles.
const VOLUME_SAVE_DELAY_MS = 350;
const MAX_VOLUME_PERCENT = 150;

type VolumeSetting = "master_volume" | "mic_passthrough_volume";

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
  const passthroughEnabled =
    settings?.mic_passthrough_enabled ??
    Boolean(status?.mic_passthrough_enabled);
  const realMic =
    status?.audio.selected_real_mic_description ??
    status?.audio.selected_real_mic ??
    null;
  const overlayHotkeyButton = settings?.overlay_hotkey_button ?? "l5";
  const overlayInputDevice = settings?.overlay_input_device ?? "auto";
  const backendDisabled = !isBackendRunning(status);
  const disabled = backendDisabled || isUpdating;

  useEffect(() => {
    let cancelled = false;
    void getInputDevices()
      .then((response) => {
        if (!cancelled) {
          setInputDevices(
            response.devices.length > 0
              ? response.devices
              : [AUTO_INPUT_DEVICE],
          );
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
  if (
    !inputDeviceOptions.some((option) => option.data === overlayInputDevice)
  ) {
    inputDeviceOptions.push({
      data: overlayInputDevice,
      label: `Unavailable device (${overlayInputDevice.slice(-8)})`,
    });
  }

  const setPassthrough = useCallback(
    async (nextEnabled: boolean) => {
      if (!status) {
        onError("Status is not available yet");
        return;
      }
      setUpdating(true);
      try {
        onSettings(
          await updateSettings({ mic_passthrough_enabled: nextEnabled }),
        );
        onStatus(await getStatus());
      } catch (caught) {
        onError(errorMessage(caught, "Failed to update mic input toggle"));
      } finally {
        setUpdating(false);
      }
    },
    [onError, onSettings, onStatus, status],
  );

  const setVolume = useCallback(
    async (key: VolumeSetting, volume: number) => {
      try {
        onSettings(await updateSettings({ [key]: volume }));
      } catch (caught) {
        onError(errorMessage(caught, "Failed to update volume"));
      }
    },
    [onError, onSettings],
  );

  const setOverlayHotkey = useCallback(
    async (button: OverlayHotkeyButton) => {
      setUpdating(true);
      try {
        onSettings(await updateSettings({ overlay_hotkey_button: button }));
      } catch (caught) {
        onError(errorMessage(caught, "Failed to update overlay button"));
      } finally {
        setUpdating(false);
      }
    },
    [onError, onSettings],
  );

  const setOverlayInputDevice = useCallback(
    async (device: string) => {
      setUpdating(true);
      try {
        onSettings(await updateSettings({ overlay_input_device: device }));
      } catch (caught) {
        onError(errorMessage(caught, "Failed to update controller input"));
      } finally {
        setUpdating(false);
      }
    },
    [onError, onSettings],
  );

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
        description="Controller that opens and drives the overlay. Automatic works for the built-in controls."
        rgOptions={inputDeviceOptions}
        selectedOption={overlayInputDevice}
        disabled={disabled}
        onChange={(option) => {
          void setOverlayInputDevice(String(option.data));
        }}
      />
      <VolumeSlider
        label="Sound volume"
        description="Soundboard playback level. Above 100% boosts quiet sounds."
        volume={settings?.master_volume ?? 1}
        disabled={backendDisabled}
        onSave={(volume) => setVolume("master_volume", volume)}
      />
      <PanelSectionRow>
        <ToggleField
          checked={passthroughEnabled}
          disabled={disabled}
          label="Real mic passthrough"
          description={
            passthroughEnabled
              ? "Your voice and soundboard audio both go to DeckSoundpad mic."
              : "Only soundboard audio goes to DeckSoundpad mic."
          }
          onChange={(checked) => {
            void setPassthrough(checked);
          }}
        />
      </PanelSectionRow>
      {passthroughEnabled ? (
        <VolumeSlider
          label="Mic volume"
          description={
            realMic
              ? `Using ${realMic}, the input device selected in Steam Settings > Audio.`
              : "No microphone found. DeckSoundpad uses the input device selected in Steam Settings > Audio."
          }
          volume={settings?.mic_passthrough_volume ?? 1}
          disabled={backendDisabled}
          onSave={(volume) => setVolume("mic_passthrough_volume", volume)}
        />
      ) : null}
    </PanelSection>
  );
}

interface VolumeSliderProps {
  label: string;
  description: string;
  volume: number;
  disabled: boolean;
  onSave: (volume: number) => Promise<void>;
}

function VolumeSlider({
  label,
  description,
  volume,
  disabled,
  onSave,
}: VolumeSliderProps) {
  // Holds the dragged value until the save returns, so the slider does not
  // jump back to the stored volume while the backend catches up.
  const [draft, setDraft] = useState<number | null>(null);
  const pending = useRef<number | null>(null);
  const saveTimer = useRef<number | undefined>(undefined);
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  const savePending = useCallback(() => {
    window.clearTimeout(saveTimer.current);
    const percent = pending.current;
    if (percent === null) {
      return;
    }
    pending.current = null;
    void onSaveRef.current(percent / 100).finally(() => {
      setDraft((current) => (current === percent ? null : current));
    });
  }, []);

  // Closing the menu unmounts the slider, so save a value still waiting on the delay.
  useEffect(() => savePending, [savePending]);

  return (
    <PanelSectionRow>
      <SliderField
        label={label}
        description={description}
        value={draft ?? Math.round(volume * 100)}
        min={0}
        max={MAX_VOLUME_PERCENT}
        step={5}
        notchCount={4}
        notchTicksVisible
        showValue
        valueSuffix="%"
        resetValue={100}
        disabled={disabled}
        onChange={(percent) => {
          setDraft(percent);
          pending.current = percent;
          window.clearTimeout(saveTimer.current);
          saveTimer.current = window.setTimeout(
            savePending,
            VOLUME_SAVE_DELAY_MS,
          );
        }}
      />
    </PanelSectionRow>
  );
}
