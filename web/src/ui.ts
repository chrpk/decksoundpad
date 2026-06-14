import { SoundItem, StatusResponse, playSound } from "./api";
import type { WebSocketState } from "./api";
import { getBuildDateTime } from "./buildInfo";

type KeyBinding = {
  code: string;
  label: string;
};

const KEY_BINDINGS_STORAGE_KEY = "decksoundpad.keyBindings.v1";

let selectedCategory = "all";
let query = "";
let volume = 1;
let renderedSounds: SoundItem[] = [];
let assigningSoundId: string | null = null;
const keyBindings = loadKeyBindings();

const grid = document.querySelector<HTMLDivElement>("#grid");
const categories = document.querySelector<HTMLElement>("#categories");
const search = document.querySelector<HTMLInputElement>("#search");
const volumeInput = document.querySelector<HTMLInputElement>("#volume");
const statusText = document.querySelector<HTMLElement>("#status-text");
const audioStatus = document.querySelector<HTMLElement>("#audio-status");
const wsStatusText = document.querySelector<HTMLElement>("#ws-status");
const buildDateTime = document.querySelector<HTMLElement>("#build-datetime");
const logs = document.querySelector<HTMLPreElement>("#logs");
const logStatus = document.querySelector<HTMLElement>("#log-status");
const activity: string[] = [];

export function bindControls(onFilter: () => void): void {
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

export function appendLog(message: string): void {
  const time = new Date().toLocaleTimeString();
  activity.unshift(`[${time}] ${message}`);
  if (activity.length > 60) {
    activity.length = 60;
  }
  renderLogs();
}

export function renderBuildInfo(): void {
  if (buildDateTime) {
    buildDateTime.textContent = `Build ${getBuildDateTime()}`;
  }
}

export function renderLogs(daemonLines: string[] = []): void {
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

export function renderStatus(status: StatusResponse): void {
  if (statusText) {
    statusText.textContent = status.player?.backend
      ? `Ready | ${status.player.active_playbacks} active`
      : "No player backend found";
  }
  if (audioStatus) {
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
}

export function renderConnectionStatus(state: WebSocketState, detail?: string): void {
  if (!wsStatusText) {
    return;
  }
  let label: string;
  switch (state) {
    case "connected": {
      label = "WebSocket connected";
      break;
    }
    case "connecting": {
      label = "WebSocket connecting";
      break;
    }
    case "error": {
      label = `WebSocket error${detail ? ` (${detail})` : ""}`;
      break;
    }
    default: {
      label = `WebSocket disconnected${detail ? ` (${detail})` : ""}`;
    }
  }
  wsStatusText.textContent = label;
  wsStatusText.classList.remove("connected", "connecting", "disconnected", "error");
  wsStatusText.classList.add(state === "connected" ? "connected" : state === "connecting" ? "connecting" : "disconnected");
  if (state === "error") {
    wsStatusText.classList.add("error");
  }
}

export function renderSounds(sounds: SoundItem[]): void {
  if (!grid || !categories) {
    return;
  }
  renderedSounds = sounds;
  const categoryList = ["all", ...Array.from(new Set(sounds.map((sound) => sound.category)))];
  categories.replaceChildren(
    ...categoryList.map((category) => {
      const button = document.createElement("button");
      button.textContent = category;
      button.className = category === selectedCategory ? "active" : "";
      button.addEventListener("click", () => {
        selectedCategory = category;
        renderSounds(sounds);
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
      const tile = document.createElement("article");
      tile.className = "sound";
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
    }),
  );
}

async function triggerSound(sound: SoundItem, source: "click" | "keyboard"): Promise<void> {
  appendLog(source === "keyboard" ? `Keyboard play requested: ${sound.display_name}` : `Play requested: ${sound.display_name}`);
  appendLog(`Routing to DeckSoundpad mic at ${Math.round(volume * 100)}% volume`);
  try {
    const response = (await playSound(sound.id, volume)) as { ok?: boolean; error?: string };
    if (response.ok === false) {
      appendLog(`Play failed: ${response.error ?? "playback error"}`);
    } else {
      appendLog(`Play sent to DeckSoundpad mic: ${sound.display_name}`);
    }
  } catch (caught) {
    appendLog(
      `Play failed: DeckSoundpad daemon/audio route unavailable (${caught instanceof Error ? caught.message : "unknown error"})`,
    );
  }
}

function handleKeyDown(event: KeyboardEvent, onFilter: () => void): void {
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

function loadKeyBindings(): Map<string, KeyBinding> {
  try {
    const raw = window.localStorage.getItem(KEY_BINDINGS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") {
      return new Map();
    }
    return new Map(
      Object.entries(parsed)
        .filter((entry): entry is [string, KeyBinding] => {
          const binding = entry[1] as Partial<KeyBinding>;
          return typeof binding.code === "string" && typeof binding.label === "string";
        })
        .map(([soundId, binding]) => [soundId, binding]),
    );
  } catch {
    return new Map();
  }
}

function saveKeyBindings(): void {
  const payload = Object.fromEntries(keyBindings);
  try {
    window.localStorage.setItem(KEY_BINDINGS_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    appendLog("Keyboard shortcuts could not be saved in this browser");
  }
}

function removeExistingKeyBinding(code: string): void {
  keyBindings.forEach((binding, soundId) => {
    if (binding.code === code) {
      keyBindings.delete(soundId);
    }
  });
}

function soundIdForKey(code: string): string | null {
  for (const [soundId, binding] of keyBindings.entries()) {
    if (binding.code === code) {
      return soundId;
    }
  }
  return null;
}

function bindingFromEvent(event: KeyboardEvent): KeyBinding | null {
  if (event.repeat || hasModifier(event) || isReservedKey(event.key)) {
    return null;
  }
  return {
    code: event.code,
    label: keyLabel(event),
  };
}

function hasModifier(event: KeyboardEvent): boolean {
  return event.altKey || event.ctrlKey || event.metaKey || event.shiftKey;
}

function isReservedKey(key: string): boolean {
  return key === "Escape" || key === "Tab" || key === "Enter" || key === "Backspace";
}

function keyLabel(event: KeyboardEvent): string {
  if (event.key && event.key !== " ") {
    return event.key.length === 1 ? event.key.toUpperCase() : event.key;
  }
  if (event.code === "Space") {
    return "Space";
  }
  return event.code.replace(/^Key/, "").replace(/^Digit/, "");
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}
