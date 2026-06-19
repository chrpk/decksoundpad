import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useState } from "react";
import { FaTools } from "react-icons/fa";
import { repairAudioAndWait, startBackend } from "../api/decky";
import { DeckSoundpadStatus } from "../types";
import { delay } from "../utils/timing";

interface StatusCardProps {
  status: DeckSoundpadStatus | null;
  loading: boolean;
}

interface RepairAudioRoutingPanelProps {
  onStatus: (status: DeckSoundpadStatus) => void;
  onError: (message: string) => void;
  onActivity: (message: string) => void;
}

function statusLabel(status: DeckSoundpadStatus | null, loading: boolean): string {
  if (loading && !status) {
    return "Checking status";
  }
  if (!status) {
    return "Safe start";
  }
  if (!isBackendRunning(status)) {
    return "Backend starting";
  }
  if (status.audio.state === "starting" || status.audio.state === "repairing") {
    return "Audio repair running";
  }
  if (status.audio.last_error === "Audio status pending") {
    return "Backend running";
  }
  if (!status.audio.pactl_available || !status.audio.pipewire_available) {
    return "PipeWire/PulseAudio unavailable";
  }
  if (!status.player.backend) {
    return "No player backend found";
  }
  if (status.audio.state === "ready") {
    return "Ready";
  }
  if (!status.audio.sink_exists || !status.audio.virtual_mic_exists) {
    return "Audio not configured";
  }
  if (!status.audio.selected_real_mic) {
    return "No real microphone detected";
  }
  if (status.audio.state === "needs_repair" || !status.audio.loopback_exists) {
    return "Needs repair";
  }
  return status.audio.state ?? "Ready";
}

function statusTone(status: DeckSoundpadStatus | null, loading: boolean): "good" | "pending" | "bad" {
  if (loading && !status) {
    return "pending";
  }
  if (!status || !isBackendRunning(status)) {
    return "bad";
  }
  if (status.audio.state === "starting" || status.audio.state === "repairing" || status.audio.state === "pending") {
    return "pending";
  }
  if (status.audio.state === "ready") {
    return "good";
  }
  return "bad";
}

export function StatusCard({ status, loading }: StatusCardProps) {
  const label = statusLabel(status, loading);
  const tone = statusTone(status, loading);

  return (
    <PanelSection title="Status">
      <PanelSectionRow>
        <div style={statusStackStyle}>
          <div style={statusHeaderStyle}>
            <span style={statusDotStyle[tone]} />
            <strong>{label}</strong>
          </div>
          {status?.audio.last_error ? (
            <span style={{ color: "#ffb86b", fontSize: "12px" }}>{status.audio.last_error}</span>
          ) : null}
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export function RepairAudioRoutingPanel({ onStatus, onError, onActivity }: RepairAudioRoutingPanelProps) {
  const [busy, setBusy] = useState(false);

  return (
    <PanelSection title="Audio routing">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            onActivity("Starting backend for audio initialization");
            try {
              await startBackend();
              await delay(700);
              onActivity("Audio initialization requested");
              const nextStatus = await repairAudioAndWait(onStatus);
              onStatus(nextStatus);
              onActivity(
                nextStatus.audio.last_error
                  ? `Audio repair finished: ${nextStatus.audio.last_error}`
                  : "Audio repair finished",
              );
            } catch (caught) {
              const message = caught instanceof Error ? caught.message : "Repair failed";
              onError(message);
              onActivity(`Repair audio failed: ${message}`);
            } finally {
              setBusy(false);
            }
          }}
        >
          <FaTools style={{ marginRight: "8px" }} />
          Repair audio routing
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

const statusStackStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "5px",
  minWidth: 0,
} as const;

function isBackendRunning(status: DeckSoundpadStatus | null): boolean {
  return Boolean(status?.backend_running);
}

const statusHeaderStyle = {
  alignItems: "center",
  display: "flex",
  gap: "8px",
  minWidth: 0,
} as const;

const statusDotBaseStyle = {
  borderRadius: "999px",
  display: "inline-block",
  flex: "0 0 auto",
  height: "10px",
  width: "10px",
} as const;

const statusDotStyle = {
  good: {
    ...statusDotBaseStyle,
    backgroundColor: "#59d185",
    boxShadow: "0 0 0 2px rgba(89, 209, 133, 0.22)",
  },
  pending: {
    ...statusDotBaseStyle,
    backgroundColor: "#ffb86b",
    boxShadow: "0 0 0 2px rgba(255, 184, 107, 0.22)",
  },
  bad: {
    ...statusDotBaseStyle,
    backgroundColor: "#ff6b6b",
    boxShadow: "0 0 0 2px rgba(255, 107, 107, 0.22)",
  },
} as const;
