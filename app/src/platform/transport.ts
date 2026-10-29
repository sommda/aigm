/** The real transport: `fetch` for JSON routes, and XMLHttpRequest for the event stream.
 *
 * XMLHttpRequest is used for the stream because it hands over the response text as it arrives, in the browser and in
 * React Native alike, while `fetch` in React Native does not stream response bodies. If a platform needs another way
 * (a WebSocket, long polling), only this file changes. */

import { JsonResponse, Transport } from "../core/api";

async function json(method: string, url: string, body?: unknown): Promise<JsonResponse> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  return { status: res.status, body: parsed };
}

function stream(
  url: string,
  body: unknown,
  onChunk: (text: string) => void,
  signal: AbortSignal,
): Promise<{ status: number; error?: string }> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    let seen = 0;
    let settled = false;
    const finish = (r: { status: number; error?: string }) => {
      if (!settled) {
        settled = true;
        resolve(r);
      }
    };
    const feed = () => {
      if (xhr.status < 200 || xhr.status >= 300) return; // an error body is read whole when the request ends
      const text = xhr.responseText ?? "";
      if (text.length > seen) {
        const chunk = text.slice(seen);
        seen = text.length;
        onChunk(chunk);
      }
    };
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Accept", "text/event-stream");
    xhr.onprogress = feed;
    xhr.onreadystatechange = () => {
      if (xhr.readyState >= 3) feed();
    };
    xhr.onload = () => {
      feed();
      finish(xhr.status >= 400 ? { status: xhr.status, error: xhr.responseText } : { status: xhr.status });
    };
    xhr.onerror = () => finish({ status: 0, error: "network error" });
    xhr.ontimeout = () => finish({ status: 0, error: "timed out" });
    xhr.onabort = () => finish({ status: 0, error: "aborted" });
    if (signal.aborted) return finish({ status: 0, error: "aborted" });
    signal.addEventListener("abort", () => xhr.abort());
    xhr.send(JSON.stringify(body));
  });
}

export const transport: Transport = { json, stream };
