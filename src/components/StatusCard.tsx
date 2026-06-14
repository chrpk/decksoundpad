import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useState } from "react";
import { FaTools } from "react-icons/fa";
import { repairAudioAndWait, startDaemon } from "../api/decky";
import { DeckSoundpadStatus } from "../types";

interface StatusCardProps {
  status: DeckSoundpadStatus | null;
  loading: boolean;
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
  if (!status?.daemon_running) {
    return "Daemon starting";
  }
  if (status.audio.state === "starting" || status.audio.state === "repairing") {
    return "Audio repair running";
  }
  if (status.audio.last_error === "Audio status pending") {
    return "Daemon running";
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

export function StatusCard({ status, loading, onStatus, onError, onActivity }: StatusCardProps) {
  const [busy, setBusy] = useState(false);
  const label = statusLabel(status, loading);
  const details = status
    ? `Sounds ${status.library.count} | Active ${status.player.active_playbacks}`
    : "Waiting for backend";
  const inputLabel = status?.audio.selected_real_mic_description ?? status?.audio.selected_real_mic ?? "No mic detected";

  return (
    <PanelSection title="Status">
      <PanelSectionRow>
        <div style={statusStackStyle}>
          <strong>{label}</strong>
          <span style={{ opacity: 0.76, fontSize: "12px" }}>{details}</span>
          <span style={routeLineStyle}>DeckSoundpad mic: Steam Deck mic + clicked sounds</span>
          <span style={routeLineStyle}>Mic: {inputLabel}</span>
          {status?.audio.last_error ? (
            <span style={{ color: "#ffb86b", fontSize: "12px" }}>{status.audio.last_error}</span>
          ) : null}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            onActivity("Starting daemon for audio initialization");
            try {
              await startDaemon();
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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const statusStackStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "5px",
  minWidth: 0,
} as const;

const routeLineStyle = {
  opacity: 0.78,
  fontSize: "12px",
  lineHeight: "1.3",
  overflowWrap: "anywhere",
} as const;
