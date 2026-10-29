/** A small markdown parser for the GM's narration, written to be safe on partly received text.
 *
 * Instead of "healing" the text with extra markers, an inline style that is still open at the end of the text simply
 * stays on to the end, and a marker with nothing after it draws nothing. Every prefix of a reply therefore renders
 * sensibly, and the finished text renders exactly as a one-shot parse of it. Supported: paragraphs, headings, bullet and
 * numbered lists, block quotes, fenced code, rules, tables (shown as aligned plain text), and **bold**, *italic*,
 * `code`, ~~strike~~ and [links](shown as their text). */

export interface Span {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
  strike?: boolean;
}

export type MdBlock =
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "heading"; level: number; spans: Span[] }
  | { kind: "list"; ordered: boolean; start: number; items: Span[][] }
  | { kind: "quote"; spans: Span[] }
  | { kind: "code"; text: string }
  | { kind: "rule" }
  | { kind: "table"; rows: string[][] };

const isSpace = (c: string | undefined) => c === undefined || /\s/.test(c);
const isWord = (c: string | undefined) => c !== undefined && /[\p{L}\p{N}]/u.test(c);

/** Inline markup to styled runs. */
export function parseInline(src: string): Span[] {
  const spans: Span[] = [];
  let bold = false;
  let italic = false;
  let strike = false;
  let buf = "";

  const flush = () => {
    if (!buf) return;
    const last = spans[spans.length - 1];
    const style = { bold: bold || undefined, italic: italic || undefined, strike: strike || undefined };
    if (last && !last.code && last.bold === style.bold && last.italic === style.italic && last.strike === style.strike) {
      last.text += buf;
    } else {
      spans.push({ text: buf, ...style });
    }
    buf = "";
  };

  let i = 0;
  while (i < src.length) {
    const c = src[i];
    const next = src[i + 1];
    const prev = src[i - 1];

    if (c === "\\" && next !== undefined && /[\\`*_{}\[\]()#+\-.!~>|]/.test(next)) {
      buf += next;
      i += 2;
      continue;
    }
    if (c === "`") {
      let n = 1;
      while (src[i + n] === "`") n++;
      const fence = "`".repeat(n);
      const close = src.indexOf(fence, i + n);
      flush();
      const text = close < 0 ? src.slice(i + n) : src.slice(i + n, close);
      if (text) spans.push({ text: close < 0 ? text : text.replace(/^ (.*) $/, "$1"), code: true });
      i = close < 0 ? src.length : close + n;
      continue;
    }
    if (c === "[") {
      const m = /^\[([^\]]*)\]\(([^)]*)\)?/.exec(src.slice(i));
      if (m) {
        buf += m[1];
        i += m[0].length;
        continue;
      }
    }
    if (c === "~" && next === "~") {
      if (strike ? !isSpace(prev) : !isSpace(src[i + 2])) {
        flush();
        strike = !strike;
        i += 2;
        continue;
      }
    }
    if (c === "*" || c === "_") {
      const double = next === c;
      const width = double ? 2 : 1;
      const after = src[i + width];
      const open = c === "*" ? !isSpace(after) : !isSpace(after) && !isWord(prev);
      const active = double ? bold : italic;
      const closing = active && !isSpace(prev) && (c === "*" || !isWord(after));
      const opening = !active && open;
      if (opening || closing) {
        flush();
        if (double) bold = !bold;
        else italic = !italic;
        i += width;
        continue;
      }
    }
    buf += c;
    i++;
  }
  flush();
  return spans;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$/;
const BULLET = /^ {0,3}[-+*][ \t]+(.*)$/;
const NUMBER = /^ {0,3}(\d{1,9})[.)][ \t]+(.*)$/;
const QUOTE = /^ {0,3}>[ \t]?(.*)$/;
const RULE = /^ {0,3}([-*_])([ \t]*\1){2,}[ \t]*$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_DIVIDER = /^\s*\|?[\s:|-]+\|?\s*$/;
// a line that is only a block marker: nothing can be drawn for it yet
const LONE_MARKER = /^ {0,3}(#{1,6}|>+|[-+*]|=+|\d{1,9}[.)])[ \t]*$/;

/** Parse a whole reply (or the part received so far, with `streaming` true). */
export function parseMarkdown(text: string, streaming = false): MdBlock[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (streaming && lines.length && LONE_MARKER.test(lines[lines.length - 1]) && !RULE.test(lines[lines.length - 1])) {
    lines.pop();
  }
  const blocks: MdBlock[] = [];
  let para: string[] = [];

  const endParagraph = () => {
    if (para.length) blocks.push({ kind: "paragraph", spans: parseInline(para.join("\n")) });
    para = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = FENCE.exec(line);
    if (fence) {
      endParagraph();
      const marker = fence[1];
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(marker[0].repeat(marker.length)) && /^[`~]+$/.test(lines[i].trim()))) {
        body.push(lines[i]);
        i++;
      }
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    if (!line.trim()) {
      endParagraph();
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      endParagraph();
      blocks.push({ kind: "heading", level: heading[1].length, spans: parseInline(heading[2]) });
      continue;
    }
    if (RULE.test(line)) {
      endParagraph();
      blocks.push({ kind: "rule" });
      continue;
    }
    const quote = QUOTE.exec(line);
    if (quote) {
      endParagraph();
      const body = [quote[1]];
      while (i + 1 < lines.length && QUOTE.test(lines[i + 1])) body.push((QUOTE.exec(lines[++i]) as RegExpExecArray)[1]);
      blocks.push({ kind: "quote", spans: parseInline(body.join("\n")) });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBER.exec(line);
    if (bullet || numbered) {
      endParagraph();
      const ordered = !bullet;
      const start = numbered ? parseInt(numbered[1], 10) : 1;
      const items: Span[][] = [];
      let current = [(bullet ? bullet[1] : (numbered as RegExpExecArray)[2]) as string];
      while (i + 1 < lines.length) {
        const nxt = lines[i + 1];
        const nb = BULLET.exec(nxt);
        const nn = NUMBER.exec(nxt);
        if ((ordered && nn) || (!ordered && nb)) {
          items.push(parseInline(current.join("\n")));
          current = [(nb ? nb[1] : (nn as RegExpExecArray)[2]) as string];
          i++;
        } else if (/^\s{2,}\S/.test(nxt) && !FENCE.test(nxt)) {
          current.push(nxt.trim());
          i++;
        } else break;
      }
      items.push(parseInline(current.join("\n")));
      blocks.push({ kind: "list", ordered, start, items });
      continue;
    }
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      endParagraph();
      const rows: string[][] = [splitRow(line)];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i])) rows.push(splitRow(lines[i++]));
      i--;
      blocks.push({ kind: "table", rows });
      continue;
    }
    para.push(line.trim());
  }
  endParagraph();
  return blocks;
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim().replace(/\*\*|__|`/g, ""));
}

/** The plain text of some spans (for tests and copy). */
export function plainText(spans: Span[]): string {
  return spans.map((s) => s.text).join("");
}
