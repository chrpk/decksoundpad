import { ButtonItem } from "@decky/ui";
import { useRef, useState } from "react";
import { FaPlay } from "react-icons/fa";
import { playSound } from "../api/decky";
import { SoundItem } from "../types";

interface SoundButtonProps {
  sound: SoundItem;
  disabled: boolean;
  onError: (message: string) => void;
  onActivity: (message: string) => void;
}

export function SoundButton({ sound, disabled, onError, onActivity }: SoundButtonProps) {
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);

  const handlePlay = async () => {
    if (disabled || playingRef.current) {
      return;
    }
    playingRef.current = true;
    setPlaying(true);
    onActivity(`Play requested: ${sound.display_name}`);
    try {
      const response = await playSound(sound.id);
      if (!response.ok) {
        onError(response.error ?? "Playback error");
        onActivity(`Playback failed: ${response.error ?? "unknown error"}`);
      } else {
        onActivity(`Playback sent to DeckSoundpad mic: ${sound.display_name}`);
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Playback error";
      onError(message);
      onActivity(`Playback failed: ${message}`);
    } finally {
      window.setTimeout(() => {
        playingRef.current = false;
        setPlaying(false);
      }, 250);
    }
  };

  return (
    <ButtonItem
      disabled={disabled || playing}
      layout="below"
      onClick={() => void handlePlay()}
    >
      <span style={buttonContentStyle}>
        <FaPlay style={iconStyle} />
        <span style={labelStyle}>{sound.display_name}</span>
      </span>
    </ButtonItem>
  );
}

const buttonContentStyle = {
  alignItems: "center",
  display: "flex",
  gap: "8px",
  minHeight: "44px",
  minWidth: 0,
  width: "100%",
} as const;

const iconStyle = {
  flex: "0 0 auto",
} as const;

const labelStyle = {
  display: "block",
  minWidth: 0,
  overflowWrap: "anywhere",
  textAlign: "left",
  whiteSpace: "normal",
} as const;
