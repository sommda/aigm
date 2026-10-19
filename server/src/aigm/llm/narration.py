"""Pulls the `narration` string out of a tool call's JSON while the model is still writing it
(docs/NARRATION_STREAMING.md).

The model's tool input arrives as fragments of JSON text that can end anywhere: inside a key, inside an escape such as
`\\u00e9`, between a key and its value. `NarrationStream` is a small character-by-character state machine, so what it
produces depends only on the whole input and never on how it was split. It knows nothing about the loop, the clock or
the network. The input is validated separately, when the tool runs."""

_WS = " \t\n\r"
_SIMPLE = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_HEX = "0123456789abcdefABCDEF"
_REPLACEMENT = "�"


class _JsonString:
    """Decodes the inside of a JSON string one character at a time."""

    def __init__(self) -> None:
        self._escape = False
        self._hex: str | None = None  # hex digits of a \uXXXX escape being read
        self._high: int | None = None  # a high surrogate waiting for its low half

    def feed(self, ch: str) -> tuple[str, bool, bool]:
        """Returns (decoded text, closed, ok). `ok` is false for an invalid escape."""
        if self._hex is not None:
            if ch not in _HEX:
                return "", False, False
            self._hex += ch
            if len(self._hex) < 4:
                return "", False, True
            code, self._hex = int(self._hex, 16), None
            return self._unit(code), False, True
        if self._escape:
            self._escape = False
            if ch == "u":
                self._hex = ""
                return "", False, True
            if ch not in _SIMPLE:
                return "", False, False
            return self._flush() + _SIMPLE[ch], False, True
        if ch == "\\":
            self._escape = True
            return "", False, True
        if ch == '"':
            return self._flush(), True, True
        return self._flush() + ch, False, True

    def _flush(self) -> str:
        """A high surrogate that no low half followed becomes a replacement character."""
        if self._high is None:
            return ""
        self._high = None
        return _REPLACEMENT

    def _unit(self, code: int) -> str:
        if self._high is not None:
            high, self._high = self._high, None
            if 0xDC00 <= code <= 0xDFFF:
                return chr(0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00))
            return _REPLACEMENT + self._unit(code)
        if 0xD800 <= code <= 0xDBFF:
            self._high = code
            return ""
        if 0xDC00 <= code <= 0xDFFF:
            return _REPLACEMENT
        return chr(code)


class NarrationStream:
    """Feed it the `partial_json` fragments of one tool call; it returns the narration text that can be shown.

    - Only the top-level `"narration"` key counts. Other keys, nested objects and the word "narration" inside other
      values are skipped. A duplicate `narration` key, malformed JSON or a narration that is not a string stops the
      text (`failed` is set for the first two); what was already returned stays valid.
    - Leading whitespace of the narration is dropped, and trailing whitespace is held back until more text shows it
      was inside, so whatever is still held when the string closes is never returned."""

    def __init__(self) -> None:
        self._state = "start"
        self._key = _JsonString()
        self._key_text = ""
        self._string = _JsonString()
        self._seen = False
        self._nested = 0  # depth inside a skipped object or array
        self._in_string = False  # inside a string of a skipped object or array
        self._escape = False
        self._started = False  # the first non-space character of the narration was returned
        self._held = ""  # whitespace waiting for a later character
        self._current = ""  # the key whose value is being read
        self.failed = False

    @property
    def complete(self) -> bool:
        return self._state == "done"

    def feed(self, partial_json: str) -> str:
        out: list[str] = []
        for ch in partial_json:
            if self.failed:
                break
            self._step(ch, out)
        return "".join(out)

    def finish(self) -> str:
        """The input ended. Nothing is held that could still be shown; an unfinished object marks a failure."""
        if self._state != "done":
            self.failed = True
        return ""

    # ---- the state machine --------------------------------------------------------------

    def _fail(self) -> None:
        self.failed = True

    def _step(self, ch: str, out: list[str]) -> None:
        state = self._state
        if state == "narration":
            self._narration_char(ch, out)
        elif state == "key":
            text, closed, ok = self._key.feed(ch)
            if not ok:
                return self._fail()
            self._key_text += text
            if closed:
                self._current, self._state = self._key_text, "colon"
        elif state == "skip_string":
            self._skip_string_char(ch)
        elif state == "skip_nested":
            self._skip_nested_char(ch)
        elif state == "skip_scalar":
            if ch in ",}":
                self._state = "after"
                self._step(ch, out)
            elif ch in _WS:
                self._state = "after"
        elif ch in _WS:
            return
        elif state == "start":
            self._state = "key_or_end" if ch == "{" else "bad"
            if self._state == "bad":
                self._fail()
        elif state in ("key_or_end", "key_next"):
            if ch == '"':
                self._key, self._key_text, self._state = _JsonString(), "", "key"
            elif ch == "}" and state == "key_or_end":
                self._state = "done"
            else:
                self._fail()
        elif state == "colon":
            if ch == ":":
                self._state = "value"
            else:
                self._fail()
        elif state == "value":
            self._start_value(ch)
        elif state == "after":
            if ch == ",":
                self._state = "key_next"
            elif ch == "}":
                self._state = "done"
            else:
                self._fail()
        else:  # done: only whitespace may follow
            self._fail()

    def _start_value(self, ch: str) -> None:
        if self._current == "narration":
            if self._seen:
                return self._fail()  # json.loads keeps the last one, so the streamed text could differ
            self._seen = True
            if ch == '"':
                self._string, self._state = _JsonString(), "narration"
                return
        if ch == '"':
            self._escape, self._state = False, "skip_string"
        elif ch in "{[":
            self._nested, self._in_string, self._escape, self._state = 1, False, False, "skip_nested"
        elif ch in "}],":
            self._fail()  # a value is missing
        else:
            self._state = "skip_scalar"

    def _skip_string_char(self, ch: str) -> None:
        if self._escape:
            self._escape = False
        elif ch == "\\":
            self._escape = True
        elif ch == '"':
            self._state = "after"

    def _skip_nested_char(self, ch: str) -> None:
        if self._in_string:
            if self._escape:
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                self._in_string = False
        elif ch == '"':
            self._in_string = True
        elif ch in "{[":
            self._nested += 1
        elif ch in "}]":
            self._nested -= 1
            if self._nested == 0:
                self._state = "after"

    def _narration_char(self, ch: str, out: list[str]) -> None:
        text, closed, ok = self._string.feed(ch)
        if not ok:
            return self._fail()
        for c in text:
            if c in _WS or c.isspace():
                if self._started:
                    self._held += c
            else:
                out.append(self._held + c)
                self._held, self._started = "", True
        if closed:
            self._held = ""  # trailing whitespace is dropped
            self._state = "after"
