/** HTTP client for the AIGM backend (docs/API.md). The transport is injected, so this file has no platform code. */

import { GameEvent, Json, parseEvent } from "./events";
import { LineSplitter, SSEDecoder } from "./sse";

export const DEFAULT_URL = "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class AbortedError extends Error {
  constructor() {
    super("aborted");
    this.name = "AbortedError";
  }
}

export interface JsonResponse {
  status: number;
  body: unknown;
}

/** How bytes move. `stream` calls `onChunk` with text as it arrives and resolves when the response ends. */
export interface Transport {
  json(method: string, url: string, body?: unknown): Promise<JsonResponse>;
  stream(
    url: string,
    body: unknown,
    onChunk: (text: string) => void,
    signal: AbortSignal,
  ): Promise<{ status: number; error?: string }>;
}

export function errorFromBody(status: number, body: unknown): ApiError {
  let code = "http_error";
  let message = `HTTP ${status}`;
  if (body && typeof body === "object") {
    const b = body as Json;
    const err = b.error;
    if (err && typeof err === "object") {
      code = String((err as Json).code ?? code);
      message = String((err as Json).message ?? message);
    } else if ("detail" in b) {
      code = "validation_error";
      message = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    }
  }
  return new ApiError(status, code, message);
}

function query(params: Record<string, string | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v as string)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export class ApiClient {
  baseUrl: string;

  constructor(
    baseUrl: string,
    public sessionId: string,
    private transport: Transport,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  private async request(method: string, path: string, params: Record<string, string | undefined> = {}, body?: unknown) {
    let res: JsonResponse;
    try {
      res = await this.transport.json(method, this.baseUrl + path + query(params), body);
    } catch (e) {
      throw new ApiError(0, "connection_error", `Cannot reach server at ${this.baseUrl} (${String(e)})`);
    }
    if (res.status >= 400) throw errorFromBody(res.status, res.body);
    return (res.body ?? {}) as Json;
  }

  private session(): Record<string, string> {
    return { session_id: this.sessionId };
  }

  health() {
    return this.request("GET", "/health");
  }
  debugStory() {
    return this.request("GET", "/debug/story", this.session());
  }
  debugHidden(q = "") {
    return this.request("GET", "/debug/hidden", { ...this.session(), q });
  }
  debugHiddenEntity(id: string) {
    return this.request("GET", `/debug/hidden/${encodeURIComponent(id)}`, this.session());
  }
  async setThinking(enabled: boolean): Promise<boolean> {
    return (await this.request("PUT", "/debug/thinking", {}, { enabled })).thinking === true;
  }
  compendium() {
    return this.request("GET", "/compendium", this.session());
  }
  compendiumList(category: string, q = "", status = "", sort = "name") {
    return this.request("GET", `/compendium/${category}`, { ...this.session(), sort, q, status });
  }
  compendiumEntity(id: string) {
    return this.request("GET", `/compendium/entities/${encodeURIComponent(id)}`, this.session());
  }
  /** Mark entries as read (null: all of them). Returns the new counts. */
  compendiumSeen(entities: string[] | null) {
    return this.request("POST", "/compendium/seen", this.session(), entities === null ? { all: true } : { entities });
  }
  status() {
    return this.request("GET", "/status", this.session());
  }
  characters() {
    return this.request("GET", "/characters", this.session());
  }
  character(name: string) {
    return this.request("GET", `/characters/${encodeURIComponent(name)}`, this.session());
  }
  chatState() {
    return this.request("GET", "/chat/history", this.session());
  }
  newGame() {
    return this.request("POST", "/chat/new", this.session());
  }
  async listHistories(): Promise<Json[]> {
    const r = await this.request("GET", "/history");
    return Array.isArray(r.histories) ? (r.histories as Json[]) : [];
  }
  historyInfo(name: string) {
    return this.request("GET", `/history/${encodeURIComponent(name)}`);
  }
  save(name: string, overwrite = false) {
    return this.request("PUT", `/history/${encodeURIComponent(name)}/save`, {
      ...this.session(),
      overwrite: overwrite ? "true" : undefined,
    });
  }
  restore(name: string) {
    return this.request("POST", `/history/${encodeURIComponent(name)}/restore`, this.session());
  }
  delete(name: string) {
    return this.request("DELETE", `/history/${encodeURIComponent(name)}`);
  }

  /** Yield typed events for one turn. Throws ApiError if the request is rejected up front (409/422...). Failures after
   * the stream starts are yielded as an error event, and a stream that ends without a terminal event yields one too.
   * Aborting `signal` (or stopping the iteration early) closes the request; the iteration then throws AbortedError. */
  async *streamChat(message: string, signal?: AbortSignal): AsyncGenerator<GameEvent> {
    const controller = new AbortController();
    const onAbort = () => {
      controller.abort();
      wake?.();
    };
    signal?.addEventListener("abort", onAbort);
    const queue: GameEvent[] = [];
    let wake: (() => void) | null = null;
    let finished = false;
    let rejected: ApiError | null = null;
    let terminal = false;
    const decoder = new SSEDecoder();
    const splitter = new LineSplitter();

    const feed = (lines: string[]) => {
      for (const line of lines) {
        const msg = decoder.decode(line);
        if (!msg) continue;
        const event = parseEvent(msg.event, msg.data);
        if (event) queue.push(event);
      }
      wake?.();
    };
    const url = `${this.baseUrl}/chat`;
    const body = { message, session_id: this.sessionId };
    const done = this.transport
      .stream(url, body, (text) => feed(splitter.push(text)), controller.signal)
      .then((res) => {
        feed(splitter.flush());
        if (res.status >= 400) {
          let parsed: unknown = null;
          try {
            parsed = JSON.parse(res.error ?? "");
          } catch {
            /* not JSON */
          }
          rejected = errorFromBody(res.status, parsed);
        } else if (res.status === 0 && !terminalSeen(queue)) {
          queue.push({ type: "error", code: "connection_error", message: `Connection lost: ${res.error ?? ""}`, retryable: true });
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          queue.push({ type: "error", code: "connection_error", message: `Connection lost: ${String(e)}`, retryable: true });
      })
      .finally(() => {
        finished = true;
        wake?.();
      });

    try {
      for (;;) {
        if (signal?.aborted) throw new AbortedError();
        while (queue.length) {
          const event = queue.shift() as GameEvent;
          yield event;
          if (event.type === "message_end" || event.type === "error") {
            terminal = true;
            return;
          }
        }
        if (rejected) throw rejected;
        if (finished) break;
        await new Promise<void>((resolve) => {
          wake = resolve;
          if (queue.length || finished || signal?.aborted) resolve();
        });
        wake = null;
      }
      if (rejected) throw rejected;
      if (!terminal) {
        yield { type: "error", code: "connection_closed", message: "Connection closed unexpectedly", retryable: true };
      }
    } finally {
      signal?.removeEventListener("abort", onAbort);
      controller.abort();
      await done;
    }
  }
}

function terminalSeen(queue: GameEvent[]): boolean {
  return queue.some((e) => e.type === "message_end" || e.type === "error");
}
