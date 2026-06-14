import { ButtonItem, Field, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import { FaSync, FaStop } from "react-icons/fa";
import { SoundItem } from "../types";
import { SoundButton } from "./SoundButton";

interface SoundGridProps {
  sounds: SoundItem[];
  query: string;
  setQuery: (query: string) => void;
  disabled: boolean;
  loading: boolean;
  activeCount: number;
  onRefresh: () => void;
  onStopAll: () => void;
  onError: (message: string) => void;
  onActivity: (message: string) => void;
}

export function SoundGrid({
  sounds,
  query,
  setQuery,
  disabled,
  loading,
  activeCount,
  onRefresh,
  onStopAll,
  onError,
  onActivity,
}: SoundGridProps) {
  const byCategory = sounds.reduce<Record<string, SoundItem[]>>((groups, sound) => {
    const category = sound.category || "uncategorized";
    groups[category] = [...(groups[category] ?? []), sound];
    return groups;
  }, {});

  return (
    <>
      <PanelSection title="Sounds">
        <PanelSectionRow>
          <Field label="Search">
            <TextField value={query} onChange={(event) => setQuery(event.target.value)} />
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={summaryStyle}>
            <span>{sounds.length} loaded</span>
            <span>{activeCount} playing</span>
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={loading} onClick={onRefresh}>
            <FaSync style={iconStyle} />
            Refresh sounds
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={onStopAll}>
            <FaStop style={iconStyle} />
            Stop all
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {sounds.length === 0 ? (
        <PanelSection title="Library">
          <PanelSectionRow>
            <div style={emptyStyle}>
              <strong>No sounds loaded</strong>
              <span>Refresh sounds to start the daemon and scan the library.</span>
            </div>
          </PanelSectionRow>
        </PanelSection>
      ) : null}
      {Object.entries(byCategory).map(([category, items]) => (
        <PanelSection key={category} title={category}>
          {items.map((sound) => (
            <PanelSectionRow key={sound.id}>
              <SoundButton sound={sound} disabled={disabled} onError={onError} onActivity={onActivity} />
            </PanelSectionRow>
          ))}
        </PanelSection>
      ))}
    </>
  );
}

const summaryStyle = {
  display: "flex",
  justifyContent: "space-between",
  gap: "12px",
  width: "100%",
  opacity: 0.78,
  fontSize: "12px",
} as const;

const emptyStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "5px",
  fontSize: "12px",
  lineHeight: "1.35",
} as const;

const iconStyle = {
  marginRight: "8px",
} as const;
