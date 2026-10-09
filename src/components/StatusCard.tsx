import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { FaBell, FaTools } from "react-icons/fa";
import { playTestSound, restartDeckSoundpadAndWait } from "../api/decky";
import type { DeckSoundpadStatus } from "../types";
import { errorMessage } from "../utils/errors";
import { isBackendRunning } from "../utils/status";

const TEST_SOUND_FEEDBACK_MS = 3000;
const RESTART_HINT = "Use Restart DeckSoundpad below to fix this.";

interface StatusCardProps {
  status: DeckSoundpadStatus | null;
  loading: boolean;
  error: string | null;
  onStatus: (status: DeckSoundpadStatus) => void;
  onError: (message: string | null) => void;
}

interface StatusSummary {
  label: string;
  hint?: string;
}

function statusSummary(
  status: DeckSoundpadStatus | null,
  loading: boolean,
): StatusSummary {
  if (loading && !status) {
    return { label: "Checking status" };
  }
  if (!status) {
    return { label: "Waiting for status" };
  }
  if (!isBackendRunning(status)) {
    return { label: "Backend starting" };
  }
  if (status.audio.state === "starting" || status.audio.state === "repairing") {
    return { label: "DeckSoundpad restarting" };
  }
  if (status.audio.last_error === "Audio status pending") {
    return { label: "Backend running" };
  }
  if (!status.audio.pactl_available || !status.audio.pipewire_available) {
    return {
      label: "PipeWire/PulseAudio unavailable",
      hint: "DeckSoundpad needs PipeWire with its PulseAudio service running.",
    };
  }
  if (!status.player.backend) {
    return { label: "No player backend found" };
  }
  if (status.audio.state === "ready") {
    return { label: "Ready" };
  }
  if (!status.audio.sink_exists || !status.audio.virtual_mic_exists) {
    return { label: "Audio not configured", hint: RESTART_HINT };
  }
  if (!status.audio.selected_real_mic) {
    return {
      label: "No real microphone detected",
      hint: "Sounds still play; only real mic passthrough needs a microphone.",
    };
  }
  if (status.audio.state === "needs_repair" || !status.audio.loopback_exists) {
    return { label: "Needs restart", hint: RESTART_HINT };
  }
  return { label: status.audio.state ?? "Ready" };
}

function statusTone(
  status: DeckSoundpadStatus | null,
  loading: boolean,
): "good" | "pending" | "bad" {
  if (loading && !status) {
    return "pending";
  }
  if (!status || !isBackendRunning(status)) {
    return "bad";
  }
  if (
    status.audio.state === "starting" ||
    status.audio.state === "repairing" ||
    status.audio.state === "pending"
  ) {
    return "pending";
  }
  if (status.audio.state === "ready") {
    return "good";
  }
  return "bad";
}

export function StatusCard({
  status,
  loading,
  error,
  onStatus,
  onError,
}: StatusCardProps) {
  const { label, hint } = statusSummary(status, loading);
  const tone = statusTone(status, loading);
  const [testing, setTesting] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [testPlayed, setTestPlayed] = useState(false);
  const feedbackTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(feedbackTimer.current), []);

  const playBeep = async () => {
    setTesting(true);
    setTestPlayed(false);
    window.clearTimeout(feedbackTimer.current);
    try {
      const response = await playTestSound();
      if (response.ok) {
        onError(null);
        setTestPlayed(true);
        feedbackTimer.current = window.setTimeout(
          () => setTestPlayed(false),
          TEST_SOUND_FEEDBACK_MS,
        );
      } else {
        onError(response.error ?? "Test sound failed");
      }
    } catch (caught) {
      onError(errorMessage(caught, "Test sound failed"));
    } finally {
      setTesting(false);
    }
  };

  const restart = async () => {
    setRestarting(true);
    try {
      const nextStatus = await restartDeckSoundpadAndWait(onStatus);
      onStatus(nextStatus);
      onError(null);
    } catch (caught) {
      onError(errorMessage(caught, "Restart failed"));
    } finally {
      setRestarting(false);
    }
  };

  return (
    <PanelSection title="Status">
      <PanelSectionRow>
        <div style={statusStackStyle}>
          <div style={statusHeaderStyle}>
            <span style={statusDotStyle[tone]} />
            <strong>{label}</strong>
          </div>
          {hint ? <span style={hintStyle}>{hint}</span> : null}
          {status?.audio.last_error ? (
            <span style={warningStyle}>{status.audio.last_error}</span>
          ) : null}
          {error ? <span style={errorStyle}>{error}</span> : null}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={testing || !isBackendRunning(status)}
          description={
            testPlayed ? "Beep played through DeckSoundpad mic." : undefined
          }
          onClick={() => void playBeep()}
        >
          <FaBell style={buttonIconStyle} />
          {testing ? "Playing…" : "Test sound"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={restarting}
          description="Stops playback and reloads audio, sounds, settings, and controller input."
          onClick={() => void restart()}
        >
          <FaTools style={buttonIconStyle} />
          {restarting ? "Restarting…" : "Restart DeckSoundpad"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

const buttonIconStyle = {
  marginRight: "8px",
} as const;

const statusStackStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "5px",
  minWidth: 0,
} as const;

const statusHeaderStyle = {
  alignItems: "center",
  display: "flex",
  gap: "8px",
  minWidth: 0,
} as const;

const hintStyle = {
  fontSize: "12px",
  lineHeight: "1.35",
  opacity: 0.78,
} as const;

const warningStyle = {
  color: "#ffb86b",
  fontSize: "12px",
  overflowWrap: "anywhere",
} as const;

const errorStyle = {
  color: "#ff8a8a",
  fontSize: "12px",
  overflowWrap: "anywhere",
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
