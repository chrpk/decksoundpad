import { SoundItem } from "./api";

const sampleNames = [
  ["alert-ping", "alert ping"],
  ["button-pop", "button pop"],
  ["error-buzz", "error buzz"],
  ["ready-chime", "ready chime"],
  ["soft-noise", "soft noise"],
] as const;

export const fallbackSounds: SoundItem[] = sampleNames.map(([name, displayName]) => ({
  id: `sample:${name}`,
  display_name: displayName,
  category: "sample",
  relative_path: `sample/${name}.wav`,
}));
