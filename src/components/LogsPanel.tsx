import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useCallback, useState } from "react";
import { FaClipboardList, FaSync } from "react-icons/fa";
import { getDiagnostics, getLogsTail } from "../api/decky";

interface LogsPanelProps {
  onActivity: (message: string) => void;
}

export function LogsPanel({ onActivity }: LogsPanelProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [publicLogDir, setPublicLogDir] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshLogs = useCallback(async () => {
    setBusy(true);
    setError(null);
    onActivity("Loading bridge/daemon log tail");
    try {
      const response = await getLogsTail(120);
      setPublicLogDir(response.public_log_dir ?? null);
      setLines(response.lines ?? []);
      if (!response.ok) {
        setError("Log tail unavailable");
        onActivity("Bridge/daemon log tail unavailable");
      } else {
        onActivity(`Bridge/daemon log tail loaded: ${response.lines?.length ?? 0} lines`);
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Log tail unavailable";
      setPublicLogDir(null);
      setError(message);
      onActivity(`Daemon log tail failed: ${message}`);
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <PanelSection title="Logs">
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void refreshLogs()}>
          <FaSync style={{ marginRight: "8px" }} />
          Refresh Logs
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            onActivity("Loading diagnostics");
            try {
              const response = await getDiagnostics();
              setDiagnostics(JSON.stringify(response.diagnostics, null, 2));
              onActivity("Diagnostics loaded");
            } catch (caught) {
              const message = caught instanceof Error ? caught.message : "Diagnostics unavailable";
              setError(message);
              onActivity(`Diagnostics failed: ${message}`);
            } finally {
              setBusy(false);
            }
          }}
        >
          <FaClipboardList style={{ marginRight: "8px" }} />
          Load Diagnostics
        </ButtonItem>
      </PanelSectionRow>
      {error ? <PanelSectionRow>{error}</PanelSectionRow> : null}
      {publicLogDir ? <PanelSectionRow>Public logs: {publicLogDir}</PanelSectionRow> : null}
      {lines.length > 0 ? (
        <PanelSectionRow>
          <pre style={logStyle}>{lines.join("\n")}</pre>
        </PanelSectionRow>
      ) : null}
      {diagnostics ? (
        <PanelSectionRow>
          <pre style={logStyle}>{diagnostics}</pre>
        </PanelSectionRow>
      ) : null}
    </PanelSection>
  );
}

const logStyle = {
  maxHeight: "260px",
  overflowY: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontSize: "11px",
  lineHeight: "1.35",
  margin: 0,
  width: "100%",
} as const;
