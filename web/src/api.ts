export interface SoundItem {
  id: string;
  display_name: string;
  category: string;
  relative_path: string;
}

export interface StatusResponse {
  audio?: {
    sink_exists: boolean;
    virtual_mic_exists: boolean;
    loopback_exists: boolean;
    selected_real_mic: string | null;
    last_error: string | null;
    state?: string;
  };
  player?: {
    backend: string | null;
    active_playbacks: number;
  };
  library?: {
    count: number;
  };
}

export interface LogsResponse {
  ok: boolean;
  lines: string[];
}

export interface ServerEvent {
  type: string;
  payload: unknown;
}

export type WebSocketState = "connecting" | "connected" | "disconnected" | "error";

type WebSocketStateListener = (state: WebSocketState, detail?: string) => void;

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

type EventHandler = (event: ServerEvent) => void;

let socket: WebSocket | null = null;
let socketReady: Promise<WebSocket> | null = null;
let nextRequestId = 1;
const pendingRequests = new Map<number, PendingRequest>();
const eventHandlers = new Set<EventHandler>();
const webSocketStateListeners = new Set<WebSocketStateListener>();
let currentWebSocketState: WebSocketState = "disconnected";

function setWebSocketState(state: WebSocketState, detail?: string): void {
  if (currentWebSocketState === state && detail === undefined) {
    return;
  }
  currentWebSocketState = state;
  webSocketStateListeners.forEach((listener) => listener(state, detail));
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function websocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/ws`;
}

async function connectWebSocket(): Promise<WebSocket> {
  if (socket?.readyState === WebSocket.OPEN) {
    setWebSocketState("connected");
    return socket;
  }
  if (socketReady) {
    setWebSocketState("connecting");
    return socketReady;
  }
  socketReady = new Promise<WebSocket>((resolve, reject) => {
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

function handleSocketMessage(raw: unknown): void {
  const parsed = JSON.parse(String(raw)) as {
    type?: string;
    id?: number;
    ok?: boolean;
    result?: unknown;
    error?: string;
    event?: ServerEvent;
  };
  if (parsed.type === "response" && typeof parsed.id === "number") {
    const pending = pendingRequests.get(parsed.id);
    if (!pending) {
      return;
    }
    pendingRequests.delete(parsed.id);
    if (parsed.ok) {
      pending.resolve(parsed.result);
    } else {
      pending.reject(new Error(parsed.error ?? "websocket request failed"));
    }
  } else if (parsed.type === "event" && parsed.event) {
    eventHandlers.forEach((handler) => handler(parsed.event as ServerEvent));
  }
}

function rejectPendingRequests(error: Error): void {
  pendingRequests.forEach((pending) => pending.reject(error));
  pendingRequests.clear();
}

async function websocketRequest<T>(
  action: string,
  payload: Record<string, unknown> = {},
  fallback: () => Promise<T>,
): Promise<T> {
  try {
    const connected = await connectWebSocket();
    const id = nextRequestId++;
    const result = new Promise<T>((resolve, reject) => {
      pendingRequests.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
      });
    });
    connected.send(JSON.stringify({ id, action, payload }));
    return await result;
  } catch {
    return fallback();
  }
}

async function websocketRequiredRequest<T>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
  const connected = await connectWebSocket();
  const id = nextRequestId++;
  const result = new Promise<T>((resolve, reject) => {
    pendingRequests.set(id, {
      resolve: (value) => resolve(value as T),
      reject,
    });
  });
  connected.send(JSON.stringify({ id, action, payload }));
  return result;
}

export function subscribeServerEvents(handler: EventHandler): () => void {
  eventHandlers.add(handler);
  void connectWebSocket().catch(() => undefined);
  return () => eventHandlers.delete(handler);
}

export function subscribeWebSocketState(handler: WebSocketStateListener): () => void {
  webSocketStateListeners.add(handler);
  handler(currentWebSocketState);
  void connectWebSocket().catch(() => undefined);
  return () => webSocketStateListeners.delete(handler);
}

export function getStatus(): Promise<StatusResponse> {
  return websocketRequest("status_quick", {}, () => request("/api/v1/status/quick"));
}

export async function listSounds(): Promise<SoundItem[]> {
  const response = await websocketRequest<{ sounds: SoundItem[] }>("sounds", {}, () => request("/api/v1/sounds"));
  return response.sounds;
}

export function playSound(soundId: string, volume: number): Promise<unknown> {
  return websocketRequiredRequest("play", { sound_id: soundId, volume });
}

export function stopAll(): Promise<unknown> {
  return websocketRequiredRequest("stop", { playback_id: null, sound_id: null });
}

export function repairAudio(): Promise<unknown> {
  return websocketRequiredRequest("audio_repair");
}

export async function repairAudioAndWait(
  onProgress?: (status: StatusResponse) => void,
  timeoutMs = 15000,
): Promise<StatusResponse> {
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

export function getLogsTail(lines = 120): Promise<LogsResponse> {
  return websocketRequest("logs_tail", { lines }, () => request(`/api/v1/logs/tail?lines=${lines}`));
}

function audioTaskInProgress(status: StatusResponse): boolean {
  const state = status.audio?.state;
  if (state === "starting" || state === "repairing" || state === "pending") {
    return true;
  }
  const message = status.audio?.last_error ?? "";
  return (
    message === "Audio status pending" ||
    message === "Audio initialization already running" ||
    /^Audio (ensure|repair) started$/.test(message)
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
