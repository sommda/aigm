"""Partial-markdown "healing" for streaming display.

`heal(text)` returns a copy of `text` in which constructs still open at the end of the
buffer are provisionally closed (or, if they have no content yet, hidden), so a CommonMark
renderer shows the formatting instead of literal markers. The raw text is never modified by
callers; the final render after the stream ends uses the unhealed text. For text that is
already well formed, `heal(text) == text`.
"""

import re
import unicodedata

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LINE_MARKER = re.compile(r"^ {0,3}(#{1,6}|>+|[-+*]|=+|\d{1,9}[.)])[ \t]*$")
_BLOCK_START = re.compile(r"^ {0,3}([-+*][ \t]|\d{1,9}[.)][ \t]|#{1,6}[ \t]|>)")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def heal(text: str) -> str:
    if not text:
        return text
    closer = _open_fence_closer(text)
    if closer is not None:
        return text + ("" if text.endswith("\n") else "\n") + closer
    text = _hold_back_line_marker(text)
    split = _tail_start(text)
    return text[:split] + _heal_inline(text[split:])


def _open_fence_closer(text: str) -> str | None:
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        if fence is None:
            m = _FENCE_OPEN.match(line)
            if m:
                marker = m.group(1)
                if marker[0] == "`" and "`" in line[m.end():]:
                    continue  # ```inline``` is a code span, not a fence
                fence = (marker[0], len(marker))
        else:
            stripped = line.strip()
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= fence[1]:
                fence = None
    return None if fence is None else fence[0] * fence[1]


def _hold_back_line_marker(text: str) -> str:
    """Hide a final line that is only a block marker (`#`, `>`, `-`, `1.`, `===`), since it
    would otherwise render as literal text (or a setext heading) until more arrives."""
    start = text.rfind("\n") + 1
    if _LINE_MARKER.match(text[start:]):
        return text[:start]
    return text


def _tail_start(text: str) -> int:
    """Index where inline healing should start: the last paragraph, narrowed to the last
    list item / heading / quote line within it (emphasis cannot span those)."""
    start = 0
    for m in _BLANK_LINE.finditer(text):
        start = m.end()
    pos = start
    for line in text[start:].split("\n"):
        if _BLOCK_START.match(line):
            start = pos
        pos += len(line) + 1
    return start


def _is_space(c: str) -> bool:
    return c == "" or c.isspace()


def _is_punct(c: str) -> bool:
    return c != "" and unicodedata.category(c).startswith(("P", "S"))


def _flanking(char: str, prev: str, nxt: str) -> tuple[bool, bool]:
    """CommonMark left/right-flanking rules -> (can_open, can_close)."""
    left = not _is_space(nxt) and (not _is_punct(nxt) or _is_space(prev) or _is_punct(prev))
    right = not _is_space(prev) and (not _is_punct(prev) or _is_space(nxt) or _is_punct(nxt))
    if char == "_":
        return left and (not right or _is_punct(prev)), right and (not left or _is_punct(nxt))
    return left, right


def _heal_inline(s: str) -> str:
    n = len(s)
    em: list[list] = []  # [char, size, pos] of open emphasis delimiter runs
    brackets: list[int] = []  # positions of unmatched '[' (or '!' of '![')
    removals: list[tuple[int, int]] = []  # (start, length) of text to hide
    suffix = ""
    i = 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c == "`":
            k = 1
            while i + k < n and s[i + k] == "`":
                k += 1
            m = re.compile(r"(?<!`)`{%d}(?!`)" % k).search(s, i + k)
            if m:
                i = m.end()
            elif s[i + k:].strip():
                suffix = "`" * k  # unclosed code span with content: close it
                break
            else:
                removals.append((i, n - i))  # lone trailing backticks: hide
                break
        elif c == "[":
            brackets.append(i - 1 if i > 0 and s[i - 1] == "!" else i)
            i += 1
        elif c == "]":
            if brackets and i + 1 < n and s[i + 1] == "(" and ")" not in s[i + 2:]:
                # "[text](partial-url" at the end: keep the text, drop brackets and url
                bp = brackets.pop()
                off = 2 if s[bp] == "!" else 1
                removals.append((i, n - i))
                removals.append((bp, off))
                break
            if brackets:
                brackets.pop()
            i += 1
        elif c in "*_~":
            k = 1
            while i + k < n and s[i + k] == c:
                k += 1
            if c == "~" and k != 2:
                i += k
                continue
            prev = s[i - 1] if i > 0 else ""
            nxt = s[i + k] if i + k < n else ""
            can_open, can_close = _flanking(c, prev, nxt)
            remaining = k
            if can_close:
                while remaining > 0:
                    idx = next((j for j in range(len(em) - 1, -1, -1) if em[j][0] == c), None)
                    if idx is None:
                        break
                    del em[idx + 1:]  # delimiters opened inside are literal
                    used = min(em[idx][1], remaining)
                    em[idx][1] -= used
                    remaining -= used
                    if em[idx][1] == 0:
                        del em[idx]
            pending = i + k == n and _is_space(prev)  # trailing run: an opener still awaiting its text
            if remaining > 0 and (can_open or pending):
                em.append([c, remaining, i])
            i += k
        else:
            i += 1

    # Hide trailing openers that have no content yet ("word **" -> "word ").
    end = n if not suffix else n
    while em:
        ch, size, pos = em[-1]
        if s[pos + size:end].strip() == "" and not suffix:
            removals.append((pos, size))
            end = pos
            em.pop()
        else:
            break
    for bp in brackets:
        removals.append((bp, 2 if s[bp] == "!" else 1))

    out = s
    for start, length in sorted(set(removals), reverse=True):
        out = out[:start] + out[start + length:]
    closers = "".join(ch * size for ch, size, _ in reversed(em))
    out += suffix
    if closers:  # a closing delimiter must follow text, so place it before trailing whitespace
        body = out.rstrip()
        out = body + closers + out[len(body):]
    return out
