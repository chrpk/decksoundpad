const fallbackSounds = [
  sample("alert-ping", "alert ping"),
  sample("button-pop", "button pop"),
  sample("error-buzz", "error buzz"),
  sample("ready-chime", "ready chime"),
  sample("soft-noise", "soft noise"),
];
let sounds = fallbackSounds;
let usingFallbackSounds = false;
let statusRefreshInFlight = false;
let logsRefreshInFlight = false;
let soundsRefreshInFlight = false;
let selectedCategory = "all";
let query = "";
let volume = 1;
const playingSoundIds = new Set();
const activity = [];

const grid = document.querySelector("#grid");
const categories = document.querySelector("#categories");
const search = document.querySelector("#search");
const volumeInput = document.querySelector("#volume");
const statusText = document.querySelector("#status-text");
const audioStatus = document.querySelector("#audio-status");
const buildDateTime = document.querySelector("#build-datetime");
const logs = document.querySelector("#logs");
const logStatus = document.querySelector("#log-status");

function sample(name, displayName) {
  return {
    id: `sample:${name}`,
    display_name: displayName,
    category: "sample",
    relative_path: `sample/${name}.wav`,
  };
}

async function request(path, init = {}) {
  const headers = new Headers(init.headers);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function post(path, payload = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function getStatus() {
  return request("/api/v1/status/quick");
}

async function repairAudioAndWait(onProgress, timeoutMs = 15000) {
  await post("/api/v1/audio/repair");
  let status = await getStatus();
  onProgress?.(status);
  const deadline = Date.now() + timeoutMs;
  while (audioTaskInProgress(status) && Date.now() < deadline) {
    await delay(500);
    status = await getStatus();
    onProgress?.(status);
  }
  if (audioTaskInProgress(status)) {
    throw new Error("audio repair timed out");
  }
  return status;
}

function audioTaskInProgress(status) {
  const state = status.audio?.state;
  if (state === "starting" || state === "repairing" || state === "pending") {
    return true;
  }
  const message = status.audio?.last_error || "";
  return (
    message === "Audio status pending" ||
    message === "Audio initialization already running" ||
    /^Audio (ensure|repair) started$/.test(message)
  );
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function getBuildDateTime() {
  return formatBuildDateTime(window.DECKSOUNDPAD_BUILD_DATETIME);
}

function formatBuildDateTime(value) {
  if (!value) {
    return "development build";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())} ${formatTimezoneOffset(date)}`;
}

function formatTimezoneOffset(date) {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absoluteMinutes = Math.abs(offsetMinutes);
  return `${sign}${pad(Math.floor(absoluteMinutes / 60))}:${pad(absoluteMinutes % 60)}`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function renderBuildInfo() {
  if (buildDateTime) {
    buildDateTime.textContent = `Build ${getBuildDateTime()}`;
  }
}

function appendLog(message) {
  const time = new Date().toLocaleTimeString();
  activity.unshift(`[${time}] ${message}`);
  if (activity.length > 60) {
    activity.length = 60;
  }
  renderLogs();
}

function renderLogs(daemonLines = []) {
  if (!logs) {
    return;
  }
  logs.textContent = [
    "Activity",
    ...activity,
    "",
    "Daemon",
    ...(daemonLines.length > 0 ? daemonLines : ["No daemon log lines loaded"]),
  ].join("\n");
  if (logStatus) {
    logStatus.textContent = `${activity.length} activity events | ${daemonLines.length} daemon lines`;
  }
}

function renderStatus(status) {
  if (statusText) {
    statusText.textContent = status.player?.backend
      ? `Ready | ${status.player.active_playbacks} active`
      : "No player backend found";
  }
  if (!audioStatus) {
    return;
  }
  const audio = status.audio;
  if (!audio) {
    audioStatus.textContent = "Audio status unavailable";
  } else if (audio.state === "starting" || audio.state === "repairing" || audio.state === "pending") {
    audioStatus.textContent = "Audio repair running";
  } else if (audio.last_error) {
    audioStatus.textContent = audio.last_error;
  } else if (!audio.virtual_mic_exists) {
    audioStatus.textContent = "Audio not configured";
  } else if (!audio.selected_real_mic) {
    audioStatus.textContent = "No real microphone detected";
  } else {
    audioStatus.textContent = audio.loopback_exists ? "Audio ready" : "Needs repair";
  }
}

function useFallbackSounds(reason) {
  sounds = fallbackSounds;
  if (!usingFallbackSounds) {
    appendLog(`${reason}; showing bundled samples`);
  }
  usingFallbackSounds = true;
  renderSounds();
}

function renderSounds() {
  if (!grid || !categories) {
    return;
  }
  const categoryList = ["all", ...Array.from(new Set(sounds.map((sound) => sound.category)))];
  categories.replaceChildren(
    ...categoryList.map((category) => {
      const button = document.createElement("button");
      button.textContent = category;
      button.className = category === selectedCategory ? "active" : "";
      button.addEventListener("click", () => {
        selectedCategory = category;
        renderSounds();
      });
      return button;
    }),
  );

  const normalizedQuery = query.trim().toLowerCase();
  const visible = sounds.filter((sound) => {
    const inCategory = selectedCategory === "all" || sound.category === selectedCategory;
    const matchesQuery = `${sound.display_name} ${sound.relative_path}`
      .toLowerCase()
      .includes(normalizedQuery);
    return inCategory && matchesQuery;
  });

  if (visible.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Library empty";
    grid.replaceChildren(empty);
    return;
  }

  grid.replaceChildren(
    ...visible.map((sound) => {
      const button = document.createElement("button");
      button.className = "sound";
      button.textContent = sound.display_name;
      button.addEventListener("click", async () => {
        if (playingSoundIds.has(sound.id)) {
          return;
        }
        playingSoundIds.add(sound.id);
        button.disabled = true;
        button.classList.add("playing");
        appendLog(`Play requested: ${sound.display_name}`);
        appendLog(`Routing to DeckSoundpad mic at ${Math.round(volume * 100)}% volume`);
        try {
          const response = await post("/api/v1/play", { sound_id: sound.id, volume });
          if (response.ok === false) {
            appendLog(`Play failed: ${response.error || "playback error"}`);
          } else {
            appendLog(`Play sent to DeckSoundpad mic: ${sound.display_name}`);
          }
        } catch (caught) {
          appendLog(
            `Play failed: DeckSoundpad daemon/audio route unavailable (${caught instanceof Error ? caught.message : "unknown error"})`,
          );
        } finally {
          window.setTimeout(() => {
            playingSoundIds.delete(sound.id);
            button.disabled = false;
            button.classList.remove("playing");
          }, 250);
        }
      });
      return button;
    }),
  );
}

async function refreshStatus() {
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

async function refreshSounds() {
  if (soundsRefreshInFlight) {
    return;
  }
  soundsRefreshInFlight = true;
  try {
    const response = await request("/api/v1/sounds");
    sounds = response.sounds || [];
    usingFallbackSounds = false;
    appendLog(`Library refreshed: ${sounds.length} sounds`);
    renderSounds();
  } finally {
    soundsRefreshInFlight = false;
  }
}

async function refreshLogs() {
  if (logsRefreshInFlight || document.hidden) {
    return;
  }
  logsRefreshInFlight = true;
  try {
    const response = await request("/api/v1/logs/tail?lines=120");
    renderLogs(response.lines || []);
  } finally {
    logsRefreshInFlight = false;
  }
}

function connectEvents() {
  const events = new EventSource("/api/v1/events");
  events.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data);
      if (event.type === "status") {
        renderStatus(event.payload);
        appendLog("Event: status");
      } else if (event.type === "library_updated") {
        appendLog("Event: library updated");
        void refreshSounds();
      } else {
        appendLog(`Event: ${event.type}`);
      }
    } catch {
      return;
    }
  };
  events.onerror = () => {
    appendLog("Event stream disconnected");
    events.close();
    window.setTimeout(connectEvents, 3000);
  };
}

search?.addEventListener("input", () => {
  query = search.value;
  renderSounds();
});

volumeInput?.addEventListener("input", () => {
  volume = Number(volumeInput.value) / 100;
});

document.querySelector("#stop-all")?.addEventListener("click", () => {
  appendLog("Stop All requested");
  void post("/api/v1/stop", { playback_id: null, sound_id: null })
    .then(refreshStatus)
    .catch((error) => appendLog(`Stop All failed: ${error}`));
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

renderBuildInfo();
appendLog(`Loaded ${sounds.length} bundled sample sounds`);
appendLog("Playback is daemon-only; browser preview is disabled");
renderSounds();
await refreshSounds().catch(() => useFallbackSounds("Sound library unavailable"));
await refreshStatus().catch((error) => appendLog(`Status unavailable: ${error}`));
await refreshLogs().catch(() => appendLog("Daemon logs unavailable"));
connectEvents();

window.setInterval(() => {
  void refreshStatus().catch(() => undefined);
}, 10000);

window.setInterval(() => {
  void refreshLogs().catch(() => undefined);
}, 30000);

window.setInterval(() => {
  void refreshSounds().catch(() => useFallbackSounds("Sound library refresh unavailable"));
}, 60000);
