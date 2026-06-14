import { SoundItem, StatusResponse, playSound } from "./api";
import { getBuildDateTime } from "./buildInfo";

let selectedCategory = "all";
let query = "";
let volume = 1;
const playingSoundIds = new Set<string>();

const grid = document.querySelector<HTMLDivElement>("#grid");
const categories = document.querySelector<HTMLElement>("#categories");
const search = document.querySelector<HTMLInputElement>("#search");
const volumeInput = document.querySelector<HTMLInputElement>("#volume");
const statusText = document.querySelector<HTMLElement>("#status-text");
const audioStatus = document.querySelector<HTMLElement>("#audio-status");
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

export function renderSounds(sounds: SoundItem[]): void {
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
