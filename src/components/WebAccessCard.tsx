import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useState } from "react";
import { FaGlobe } from "react-icons/fa";
import { getWebAccess, startDaemon } from "../api/decky";
import { WebAccess } from "../types";

interface WebAccessCardProps {
  onActivity: (message: string) => void;
}

export function WebAccessCard({ onActivity }: WebAccessCardProps) {
  const [access, setAccess] = useState<WebAccess | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAccess = async () => {
    setBusy(true);
    setError(null);
    onActivity("Starting daemon for Web UI");
    try {
      await startDaemon();
      onActivity("Loading Web UI URL");
      for (let attempt = 0; attempt < 10; attempt += 1) {
        if (attempt > 0) {
          await delay(500);
        }
        const nextAccess = await getWebAccess();
        setAccess(nextAccess);
        if (nextAccess.url) {
          onActivity("Web UI URL loaded");
          setBusy(false);
          return;
        }
      }
      setError("Daemon is still starting. Try Load Web URL again in a few seconds.");
      onActivity("Web UI URL unavailable: daemon is still starting");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Web access unavailable";
      setError(message);
      onActivity(`Web UI URL load failed: ${message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Web UI">
      <PanelSectionRow>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <span>{access?.url ?? "Load web URL when needed"}</span>
          {error ? <span style={{ color: "#ffb86b", fontSize: "12px" }}>{error}</span> : null}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void loadAccess()}>
          <FaGlobe style={{ marginRight: "8px" }} />
          Start / Load Web URL
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
