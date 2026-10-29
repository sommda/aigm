import { ApiClient, JsonResponse, Transport } from "../src/core/api";

export function sse(...events: [string, object][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export const turn = (text: string, extra: [string, object][] = []): string =>
  sse(
    ["message_start", { message_id: "m1", phase: "adventure" }],
    ...extra,
    ["text", { delta: text }],
    ["message_end", { message_id: "m1", stop_reason: "end_turn", phase: "adventure" }],
  );

type JsonHandler = (method: string, url: string, body?: unknown) => JsonResponse | Promise<JsonResponse>;

/** A transport that answers JSON routes from a function and streams a canned body in small chunks. */
export class FakeTransport implements Transport {
  calls: { method: string; url: string; body?: unknown }[] = [];
  streamBody = "";
  streamStatus = 200;
  chunk = 7;
  hang = false;

  constructor(public handler: JsonHandler = () => ({ status: 200, body: {} })) {}

  async json(method: string, url: string, body?: unknown): Promise<JsonResponse> {
    this.calls.push({ method, url, body });
    return this.handler(method, url, body);
  }

  async stream(url: string, body: unknown, onChunk: (t: string) => void, signal: AbortSignal) {
    this.calls.push({ method: "POST", url, body });
    if (this.streamStatus >= 400) return { status: this.streamStatus, error: this.streamBody };
    for (let i = 0; i < this.streamBody.length; i += this.chunk) {
      if (signal.aborted) return { status: 0, error: "aborted" };
      onChunk(this.streamBody.slice(i, i + this.chunk));
      await Promise.resolve();
    }
    if (this.hang) await new Promise<void>((r) => signal.addEventListener("abort", () => r()));
    return { status: 200 };
  }
}

export const apiWith = (t: Transport) => new ApiClient("http://x", "default", t);
