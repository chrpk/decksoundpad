import {
  getLogsTail,
  getStatus,
  listSounds,
  subscribeWebSocketState,
  repairAudioAndWait,
  stopAll,
  subscribeServerEvents,
} from "./api";
import type { ServerEvent, StatusResponse } from "./api";
import { fallbackSounds } from "./samples";
import {
  appendLog,
  bindControls,
  renderBuildInfo,
  renderConnectionStatus,
  renderLogs,
  renderSounds,
  renderStatus,
} from "./ui";

let sounds = fallbackSounds;
let usingFallbackSounds = false;
let statusRefreshInFlight = false;
let logsRefreshInFlight = false;
let soundsRefreshInFlight = false;

function handleServerEvent(event: ServerEvent): void {
  if (event.type === "status") {
    renderStatus(event.payload as StatusResponse);
    return;
  }
  if (event.type === "playback_started") {
    appendLog("Playback started");
    void refreshStatus().catch(() => undefined);
    return;
  }
  if (event.type === "playback_finished") {
    appendLog("Playback finished");
    void refreshStatus().catch(() => undefined);
    return;
  }
  if (event.type === "library_updated") {
    void refreshSounds().catch(() => useFallbackSounds("Sound library refresh unavailable"));
    return;
  }
  if (event.type === "error" && event.payload && typeof event.payload === "object") {
    const payload = event.payload as { message?: string };
    appendLog(`Daemon error: ${payload.message ?? "unknown error"}`);
  }
}

function useFallbackSounds(reason: string): void {
  sounds = fallbackSounds;
  if (!usingFallbackSounds) {
    appendLog(`${reason}; showing bundled samples`);
  }
  usingFallbackSounds = true;
  redrawSounds();
}

function redrawSounds(): void {
  renderSounds(sounds);
}

async function refreshSounds(): Promise<void> {
  if (soundsRefreshInFlight) {
    return;
  }
  soundsRefreshInFlight = true;
  try {
    const next = await listSounds();
    sounds = next;
    usingFallbackSounds = false;
    appendLog(`Library refreshed: ${sounds.length} sounds`);
    redrawSounds();
  } finally {
    soundsRefreshInFlight = false;
  }
}

bindControls(redrawSounds);
renderBuildInfo();
subscribeServerEvents(handleServerEvent);
appendLog(`Loaded ${sounds.length} bundled sample sounds`);
appendLog("Playback is daemon-only; browser preview is disabled");
redrawSounds();
subscribeWebSocketState(renderConnectionStatus);

async function refreshStatus(): Promise<void> {
  if (statusRefreshInFlight) {
    return;
  }
  statusRefreshInFlight = true;
  try {
    const status = await getStatus();
    renderStatus(status);
    appendLog(status.player?.backend ? "Status refreshed: ready" : "Status refreshed: no player backend");
  } finally {
    statusRefreshInFlight = false;
  }
}

async function refreshLogs(): Promise<void> {
  if (logsRefreshInFlight || document.hidden) {
    return;
  }
  logsRefreshInFlight = true;
  try {
    const response = await getLogsTail();
    renderLogs(response.lines ?? []);
  } finally {
    logsRefreshInFlight = false;
  }
}

document.querySelector("#stop-all")?.addEventListener("click", () => {
  appendLog("Stop All requested");
  void stopAll().then(refreshStatus).catch((error) => appendLog(`Stop All failed: ${error}`));
});

document.querySelector("#repair")?.addEventListener("click", () => {
  appendLog("Repair requested");
  void repairAudioAndWait(renderStatus)
    .then((status) => {
      renderStatus(status);
      appendLog(status.audio?.last_error ? `Repair finished: ${status.audio.last_error}` : "Repair finished");
    })
    .catch((error) => appendLog(`Repair failed: ${error}`));
});

document.querySelector("#refresh-logs")?.addEventListener("click", () => {
  appendLog("Daemon log refresh requested");
  void refreshLogs().catch((error) => appendLog(`Log refresh failed: ${error}`));
});

await refreshSounds().catch(() => useFallbackSounds("Sound library unavailable"));
await refreshStatus().catch(() => undefined);
await refreshLogs().catch(() => appendLog("Daemon logs unavailable"));
window.setInterval(() => {
  void refreshStatus().catch(() => undefined);
}, 10000);

window.setInterval(() => {
  void refreshLogs().catch(() => undefined);
}, 30000);

window.setInterval(() => {
  void refreshSounds().catch(() => useFallbackSounds("Sound library refresh unavailable"));
}, 60000);
