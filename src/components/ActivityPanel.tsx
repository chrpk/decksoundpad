import { PanelSection, PanelSectionRow } from "@decky/ui";

interface ActivityPanelProps {
  entries: string[];
}

export function ActivityPanel({ entries }: ActivityPanelProps) {
  return (
    <PanelSection title="Recent activity">
      <PanelSectionRow>
        <div style={activityStyle}>
          {entries.length > 0
            ? entries.map((entry, index) => <div key={`${index}-${entry}`}>{entry}</div>)
            : "No activity yet"}
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

const activityStyle = {
  display: "flex",
  flexDirection: "column",
  gap: "4px",
  maxHeight: "150px",
  overflowY: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontSize: "11px",
  lineHeight: "1.35",
  width: "100%",
} as const;
