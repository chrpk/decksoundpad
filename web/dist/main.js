let socket = null;
let socketReady = null;
let nextRequestId = 1;
const pendingRequests = new Map();
const eventHandlers = new Set();
const webSocketStateListeners = new Set();
let currentWebSocketState = "disconnected";
function setWebSocketState(state, detail) {
  if (currentWebSocketState === state && detail === undefined) {
    return;
  }
  currentWebSocketState = state;
  webSocketStateListeners.forEach((listener) => listener(state, detail));
}
async function request(path, init = {}) {
    const headers = new Headers(init.headers);
    const response = await fetch(path, { ...init, headers });
    if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
}
function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/api/v1/ws`;
}
async function connectWebSocket() {
    if (socket?.readyState === WebSocket.OPEN) {
        setWebSocketState("connected");
        return socket;
    }
    if (socketReady) {
        setWebSocketState("connecting");
        return socketReady;
    }
    socketReady = new Promise((resolve, reject) => {
        setWebSocketState("connecting");
        const nextSocket = new WebSocket(websocketUrl());
        const timeout = window.setTimeout(() => {
            nextSocket.close();
            setWebSocketState("error", "connection timed out");
            reject(new Error("websocket connection timed out"));
        }, 5000);
        nextSocket.addEventListener("open", () => {
            window.clearTimeout(timeout);
            socket = nextSocket;
            setWebSocketState("connected");
            resolve(nextSocket);
        });
        nextSocket.addEventListener("message", (message) => {
            handleSocketMessage(message.data);
        });
        nextSocket.addEventListener("close", () => {
            setWebSocketState("disconnected", "closed");
            if (socket === nextSocket) {
                socket = null;
            }
            socketReady = null;
            rejectPendingRequests(new Error("websocket disconnected"));
        });
        nextSocket.addEventListener("error", () => {
            window.clearTimeout(timeout);
            setWebSocketState("error", "connection error");
            if (socket === nextSocket) {
                socket = null;
            }
            socketReady = null;
            reject(new Error("websocket connection failed"));
        });
    });
    return socketReady;
}
function handleSocketMessage(raw) {
    const parsed = JSON.parse(String(raw));
    if (parsed.type === "response" && typeof parsed.id === "number") {
        const pending = pendingRequests.get(parsed.id);
        if (!pending) {
            return;
        }
        pendingRequests.delete(parsed.id);
        if (parsed.ok) {
            pending.resolve(parsed.result);
        }
        else {
            pending.reject(new Error(parsed.error ?? "websocket request failed"));
        }
    }
    else if (parsed.type === "event" && parsed.event) {
        eventHandlers.forEach((handler) => handler(parsed.event));
    }
}
function rejectPendingRequests(error) {
    pendingRequests.forEach((pending) => pending.reject(error));
    pendingRequests.clear();
}
async function websocketRequest(action, payload = {}, fallback) {
    try {
        const connected = await connectWebSocket();
        const id = nextRequestId++;
        const result = new Promise((resolve, reject) => {
            pendingRequests.set(id, {
                resolve: (value) => resolve(value),
                reject,
            });
        });
        connected.send(JSON.stringify({ id, action, payload }));
        return await result;
    }
    catch {
        return fallback();
    }
}
async function websocketRequiredRequest(action, payload = {}) {
    const connected = await connectWebSocket();
    const id = nextRequestId++;
    const result = new Promise((resolve, reject) => {
        pendingRequests.set(id, {
            resolve: (value) => resolve(value),
            reject,
        });
    });
    connected.send(JSON.stringify({ id, action, payload }));
    return result;
}
function subscribeServerEvents(handler) {
    eventHandlers.add(handler);
    void connectWebSocket().catch(() => undefined);
    return () => eventHandlers.delete(handler);
}
function subscribeWebSocketState(handler) {
    webSocketStateListeners.add(handler);
    handler(currentWebSocketState);
    void connectWebSocket().catch(() => undefined);
    return () => webSocketStateListeners.delete(handler);
}
function getStatus() {
    return websocketRequest("status_quick", {}, () => request("/api/v1/status/quick"));
}
async function listSounds() {
    const response = await websocketRequest("sounds", {}, () => request("/api/v1/sounds"));
    return response.sounds;
}
function playSound(soundId, volume) {
    return websocketRequiredRequest("play", { sound_id: soundId, volume });
}
function stopAll() {
    return websocketRequiredRequest("stop", { playback_id: null, sound_id: null });
}
function repairAudio() {
    return websocketRequiredRequest("audio_repair");
}
async function repairAudioAndWait(onProgress, timeoutMs = 15000) {
    await repairAudio();
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
function getLogsTail(lines = 120) {
    return websocketRequest("logs_tail", { lines }, () => request(`/api/v1/logs/tail?lines=${lines}`));
}
function audioTaskInProgress(status) {
    const state = status.audio?.state;
    if (state === "starting" || state === "repairing" || state === "pending") {
        return true;
    }
    const message = status.audio?.last_error ?? "";
    return (message === "Audio status pending" ||
        message === "Audio initialization already running" ||
        /^Audio (ensure|repair) started$/.test(message));
}
function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const sampleNames = [
    ["alert-ping", "alert ping"],
    ["button-pop", "button pop"],
    ["error-buzz", "error buzz"],
    ["ready-chime", "ready chime"],
    ["soft-noise", "soft noise"],
];
const fallbackSounds = sampleNames.map(([name, displayName]) => ({
    id: `sample:${name}`,
    display_name: displayName,
    category: "sample",
    relative_path: `sample/${name}.wav`,
}));

function getBuildDateTime() {
    const rawValue = typeof __BUILD_DATETIME__ === "string" ? __BUILD_DATETIME__ : window.DECKSOUNDPAD_BUILD_DATETIME;
    return formatBuildDateTime(rawValue);
}
function formatBuildDateTime(value) {
    if (!value) {
        return "development build";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())} ${formatTimezoneOffset(date)}`;
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

const KEY_BINDINGS_STORAGE_KEY = "decksoundpad.keyBindings.v1";
let selectedCategory = "all";
let query = "";
let volume = 1;
let renderedSounds = [];
let assigningSoundId = null;
const playingSoundIds = new Set();
const keyBindings = loadKeyBindings();
const grid = document.querySelector("#grid");
const categories = document.querySelector("#categories");
const search = document.querySelector("#search");
const volumeInput = document.querySelector("#volume");
const statusText = document.querySelector("#status-text");
const wsStatusText = document.querySelector("#ws-status");
const audioStatus = document.querySelector("#audio-status");
const buildDateTime = document.querySelector("#build-datetime");
const logs = document.querySelector("#logs");
const logStatus = document.querySelector("#log-status");
const activity = [];
function bindControls(onFilter) {
    search?.addEventListener("input", () => {
        query = search.value;
        onFilter();
    });
    volumeInput?.addEventListener("input", () => {
        volume = Number(volumeInput.value) / 100;
    });
    document.addEventListener("keydown", (event) => {
        handleKeyDown(event, onFilter);
    });
}
function appendLog(message) {
    const time = new Date().toLocaleTimeString();
    activity.unshift(`[${time}] ${message}`);
    if (activity.length > 60) {
        activity.length = 60;
    }
    renderLogs();
}
function renderBuildInfo() {
    if (buildDateTime) {
        buildDateTime.textContent = `Build ${getBuildDateTime()}`;
    }
}
function renderLogs(daemonLines = []) {
    if (!logs) {
        return;
    }
    const sections = [
        "Activity",
        ...activity,
        "",
        "Daemon",
        ...(daemonLines.length > 0 ? daemonLines : ["No daemon log lines loaded"]),
    ];
    logs.textContent = sections.join("\n");
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
    if (audioStatus) {
        const audio = status.audio;
        if (!audio) {
            audioStatus.textContent = "Audio status unavailable";
        }
        else if (audio.state === "starting" || audio.state === "repairing" || audio.state === "pending") {
            audioStatus.textContent = "Audio repair running";
        }
        else if (audio.last_error) {
            audioStatus.textContent = audio.last_error;
        }
        else if (!audio.virtual_mic_exists) {
            audioStatus.textContent = "Audio not configured";
        }
        else if (!audio.selected_real_mic) {
            audioStatus.textContent = "No real microphone detected";
        }
        else {
            audioStatus.textContent = audio.loopback_exists ? "Audio ready" : "Needs repair";
        }
    }
}
function renderConnectionStatus(state, detail) {
    if (!wsStatusText) {
        return;
    }
    let label;
    switch (state) {
        case "connected":
            label = "WebSocket connected";
            break;
        case "connecting":
            label = "WebSocket connecting";
            break;
        case "error":
            label = `WebSocket error${detail ? ` (${detail})` : ""}`;
            break;
        default:
            label = `WebSocket disconnected${detail ? ` (${detail})` : ""}`;
    }
    wsStatusText.textContent = label;
    wsStatusText.classList.remove("connected", "connecting", "disconnected", "error");
    wsStatusText.classList.add(state === "connected" ? "connected" : state === "connecting" ? "connecting" : "disconnected");
    if (state === "error") {
        wsStatusText.classList.add("error");
    }
}
function renderSounds(sounds) {
    if (!grid || !categories) {
        return;
    }
    renderedSounds = sounds;
    const categoryList = ["all", ...Array.from(new Set(sounds.map((sound) => sound.category)))];
    categories.replaceChildren(...categoryList.map((category) => {
        const button = document.createElement("button");
        button.textContent = category;
        button.className = category === selectedCategory ? "active" : "";
        button.addEventListener("click", () => {
            selectedCategory = category;
            renderSounds(sounds);
        });
        return button;
    }));
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
    grid.replaceChildren(...visible.map((sound) => {
        const tile = document.createElement("article");
        tile.className = playingSoundIds.has(sound.id) ? "sound playing" : "sound";
        tile.dataset.soundId = sound.id;
        const playButton = document.createElement("button");
        playButton.className = "sound-play";
        playButton.type = "button";
        playButton.textContent = sound.display_name;
        playButton.addEventListener("click", () => {
            void triggerSound(sound, "click");
        });
        const keyRow = document.createElement("div");
        keyRow.className = "sound-key-row";
        const binding = keyBindings.get(sound.id);
        const keyButton = document.createElement("button");
        keyButton.className = assigningSoundId === sound.id ? "sound-key assigning" : "sound-key";
        keyButton.type = "button";
        keyButton.textContent = assigningSoundId === sound.id ? "Press key" : binding?.label ?? "Set key";
        keyButton.title = binding ? `Keyboard shortcut: ${binding.label}` : "Assign keyboard shortcut";
        keyButton.addEventListener("click", () => {
            assigningSoundId = assigningSoundId === sound.id ? null : sound.id;
            renderSounds(renderedSounds);
        });
        keyRow.append(keyButton);
        if (binding) {
            const clearButton = document.createElement("button");
            clearButton.className = "sound-key-clear";
            clearButton.type = "button";
            clearButton.textContent = "Clear";
            clearButton.addEventListener("click", () => {
                keyBindings.delete(sound.id);
                if (assigningSoundId === sound.id) {
                    assigningSoundId = null;
                }
                saveKeyBindings();
                appendLog(`Keyboard shortcut cleared: ${sound.display_name}`);
                renderSounds(renderedSounds);
            });
            keyRow.append(clearButton);
        }
        tile.append(playButton, keyRow);
        return tile;
    }));
}
async function triggerSound(sound, source) {
    if (playingSoundIds.has(sound.id)) {
        return;
    }
    playingSoundIds.add(sound.id);
    updatePlayingState(sound.id, true);
    appendLog(source === "keyboard" ? `Keyboard play requested: ${sound.display_name}` : `Play requested: ${sound.display_name}`);
    appendLog(`Routing to DeckSoundpad mic at ${Math.round(volume * 100)}% volume`);
    try {
        const response = (await playSound(sound.id, volume));
        if (response.ok === false) {
            appendLog(`Play failed: ${response.error ?? "playback error"}`);
        }
        else {
            appendLog(`Play sent to DeckSoundpad mic: ${sound.display_name}`);
        }
    }
    catch (caught) {
        appendLog(`Play failed: DeckSoundpad daemon/audio route unavailable (${caught instanceof Error ? caught.message : "unknown error"})`);
    }
    finally {
        window.setTimeout(() => {
            playingSoundIds.delete(sound.id);
            updatePlayingState(sound.id, false);
        }, 250);
    }
}
function handleKeyDown(event, onFilter) {
    if (isEditableTarget(event.target)) {
        return;
    }
    if (assigningSoundId) {
        event.preventDefault();
        if (event.key === "Escape") {
            assigningSoundId = null;
            onFilter();
            return;
        }
        const binding = bindingFromEvent(event);
        if (!binding) {
            return;
        }
        removeExistingKeyBinding(binding.code);
        const assignedSound = renderedSounds.find((sound) => sound.id === assigningSoundId);
        keyBindings.set(assigningSoundId, binding);
        assigningSoundId = null;
        saveKeyBindings();
        appendLog(`Keyboard shortcut assigned: ${assignedSound?.display_name ?? "sound"} -> ${binding.label}`);
        onFilter();
        return;
    }
    if (event.repeat || hasModifier(event)) {
        return;
    }
    const soundId = soundIdForKey(event.code);
    if (!soundId) {
        return;
    }
    const sound = renderedSounds.find((item) => item.id === soundId);
    if (!sound) {
        return;
    }
    event.preventDefault();
    void triggerSound(sound, "keyboard");
}
function updatePlayingState(soundId, playing) {
    document.querySelectorAll(`.sound[data-sound-id="${cssEscape(soundId)}"]`).forEach((tile) => {
        tile.classList.toggle("playing", playing);
        tile.querySelectorAll("button").forEach((button) => {
            button.disabled = playing;
        });
    });
}
function loadKeyBindings() {
    try {
        const raw = window.localStorage.getItem(KEY_BINDINGS_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : {};
        if (!parsed || typeof parsed !== "object") {
            return new Map();
        }
        return new Map(Object.entries(parsed)
            .filter((entry) => {
            const binding = entry[1];
            return typeof binding.code === "string" && typeof binding.label === "string";
        })
            .map(([soundId, binding]) => [soundId, binding]));
    }
    catch {
        return new Map();
    }
}
function saveKeyBindings() {
    const payload = Object.fromEntries(keyBindings);
    try {
        window.localStorage.setItem(KEY_BINDINGS_STORAGE_KEY, JSON.stringify(payload));
    }
    catch {
        appendLog("Keyboard shortcuts could not be saved in this browser");
    }
}
function removeExistingKeyBinding(code) {
    keyBindings.forEach((binding, soundId) => {
        if (binding.code === code) {
            keyBindings.delete(soundId);
        }
    });
}
function soundIdForKey(code) {
    for (const [soundId, binding] of keyBindings.entries()) {
        if (binding.code === code) {
            return soundId;
        }
    }
    return null;
}
function bindingFromEvent(event) {
    if (event.repeat || hasModifier(event) || isReservedKey(event.key)) {
        return null;
    }
    return {
        code: event.code,
        label: keyLabel(event),
    };
}
function hasModifier(event) {
    return event.altKey || event.ctrlKey || event.metaKey || event.shiftKey;
}
function isReservedKey(key) {
    return key === "Escape" || key === "Tab" || key === "Enter" || key === "Backspace";
}
function keyLabel(event) {
    if (event.key && event.key !== " ") {
        return event.key.length === 1 ? event.key.toUpperCase() : event.key;
    }
    if (event.code === "Space") {
        return "Space";
    }
    return event.code.replace(/^Key/, "").replace(/^Digit/, "");
}
function isEditableTarget(target) {
    if (!(target instanceof HTMLElement)) {
        return false;
    }
    return Boolean(target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}
function cssEscape(value) {
    if (window.CSS?.escape) {
        return window.CSS.escape(value);
    }
    return value.replace(/["\\]/g, "\\$&");
}

let sounds = fallbackSounds;
let usingFallbackSounds = false;
let statusRefreshInFlight = false;
let logsRefreshInFlight = false;
let soundsRefreshInFlight = false;
function handleServerEvent(event) {
    if (event.type === "status") {
        renderStatus(event.payload);
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
        const payload = event.payload;
        appendLog(`Daemon error: ${payload.message ?? "unknown error"}`);
    }
}
function useFallbackSounds(reason) {
    sounds = fallbackSounds;
    if (!usingFallbackSounds) {
        appendLog(`${reason}; showing bundled samples`);
    }
    usingFallbackSounds = true;
    redrawSounds();
}
function redrawSounds() {
    renderSounds(sounds);
}
async function refreshSounds() {
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
    }
    finally {
        soundsRefreshInFlight = false;
    }
}
bindControls(redrawSounds);
renderBuildInfo();
subscribeWebSocketState(renderConnectionStatus);
subscribeServerEvents(handleServerEvent);
appendLog(`Loaded ${sounds.length} bundled sample sounds`);
appendLog("Playback is daemon-only; browser preview is disabled");
redrawSounds();
async function refreshStatus() {
    if (statusRefreshInFlight) {
        return;
    }
    statusRefreshInFlight = true;
    try {
        const status = await getStatus();
        renderStatus(status);
        appendLog(status.player?.backend ? "Status refreshed: ready" : "Status refreshed: no player backend");
    }
    finally {
        statusRefreshInFlight = false;
    }
}
async function refreshLogs() {
    if (logsRefreshInFlight || document.hidden) {
        return;
    }
    logsRefreshInFlight = true;
    try {
        const response = await getLogsTail();
        renderLogs(response.lines ?? []);
    }
    finally {
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
