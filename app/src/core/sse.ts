/** Server-Sent Events decoding (docs/API.md, "SSE framing"). No React Native imports in this folder. */

export interface SSEMessage {
  event: string;
  data: string;
}

/** Feed it one line at a time (without the terminator); it returns a message when a blank line completes one.
 * Comment lines (": ping") and unknown fields are ignored. */
export class SSEDecoder {
  private event: string | null = null;
  private data: string[] = [];

  decode(rawLine: string): SSEMessage | null {
    const line = rawLine.replace(/[\r\n]+$/, "");
    if (line === "") {
      if (this.event === null && this.data.length === 0) return null;
      const msg = { event: this.event ?? "message", data: this.data.join("\n") };
      this.event = null;
      this.data = [];
      return msg;
    }
    if (line.startsWith(":")) return null;
    const at = line.indexOf(":");
    const name = at < 0 ? line : line.slice(0, at);
    let value = at < 0 ? "" : line.slice(at + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (name === "event") this.event = value;
    else if (name === "data") this.data.push(value);
    return null;
  }
}

/** Cuts a stream of text chunks into lines (a chunk may end mid-line, and a CRLF may be split in two). */
export class LineSplitter {
  private tail = "";

  push(chunk: string): string[] {
    const text = this.tail + chunk;
    const lines = text.split(/\r\n|\n|\r(?!$)/);
    this.tail = lines.pop() ?? "";
    return lines;
  }

  /** What is left when the stream ends. */
  flush(): string[] {
    const rest = this.tail.replace(/\r$/, "");
    this.tail = "";
    return rest ? [rest] : [];
  }
}
