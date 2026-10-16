"""Transcript line store and pager state machine. No UI dependencies.

The transcript is a list of blocks rendered to terminal lines at the current width. The
pager decides how many lines are *revealed*: the current page is `page_height` lines
starting at `page_start`; lines beyond it are *held* until the user advances. Receiving
never stops: blocks keep growing while lines are held.
"""

from aigm_client.blocks import Block, Line, MarkdownBlock, RenderContext, UserBlock


class Transcript:
    def __init__(self, width: int = 80, height: int = 24, ascii_only: bool = False) -> None:
        self.width = width
        self.page_height = max(height, 1)
        self.ascii_only = ascii_only
        self.show_reasoning = False
        self.blocks: list[Block] = []
        self.page_start = 0
        self.following = True  # False while the user is scrolled back into history
        self.scroll_top = 0
        self.page_overlap = 3  # lines of the previous page kept at the top after advancing
        self.view_top_override: int | None = None  # set by the widget during a page-turn animation
        # block id -> (the block itself, render key, lines). Holding the block keeps its id from being
        # reused by a new block, and the identity check below guards against stale hits.
        self._cache: dict[int, tuple[Block, tuple, list[Line]]] = {}
        self._lines: list[Line] = []
        self._starts: list[int] = []
        self._dirty = True

    # ---- layout -------------------------------------------------------------------------

    def invalidate(self) -> None:
        self._dirty = True

    def _layout(self) -> None:
        if not self._dirty:
            return
        ctx = RenderContext(self.width, self.show_reasoning, self.ascii_only)
        lines: list[Line] = []
        starts: list[int] = []
        live_ids = set()
        for block in self.blocks:
            key = (self.width, self.show_reasoning, self.ascii_only, block.version)
            cached = self._cache.get(id(block))
            if cached is None or cached[0] is not block or cached[1] != key:
                cached = (block, key, block.render(ctx))
                self._cache[id(block)] = cached
            live_ids.add(id(block))
            starts.append(len(lines))
            lines.extend(cached[2])
        for stale in set(self._cache) - live_ids:
            del self._cache[stale]
        self._lines, self._starts, self._dirty = lines, starts, False

    @property
    def lines(self) -> list[Line]:
        self._layout()
        return self._lines

    # ---- content ------------------------------------------------------------------------

    def add(self, block: Block) -> Block:
        self.blocks.append(block)
        self._dirty = True
        return block

    def touch(self, block: Block) -> None:
        """Call after mutating a block in place (e.g. appending streamed text)."""
        self._dirty = True

    def clear(self) -> None:
        self.blocks.clear()
        self.page_start = 0
        self.scroll_top = 0
        self.following = True
        self._dirty = True

    def replace_blocks(self, blocks: list[Block]) -> None:
        self.clear()
        self.blocks.extend(blocks)
        self.show_last_page()

    def start_user_message(self, text: str) -> UserBlock:
        """Echo the user's message into the flow. If the current page is already full,
        sending counts as the user's page turn and the message starts a new page."""
        n = len(self.lines)
        if n - self.page_start >= self.page_height:
            self.page_start = n
        self.following = True
        block = UserBlock(text)
        self.add(block)
        return block

    # ---- pager --------------------------------------------------------------------------

    @property
    def revealed_end(self) -> int:
        return min(len(self.lines), self.page_start + self.page_height)

    @property
    def held(self) -> int:
        return len(self.lines) - self.revealed_end

    @property
    def scrolled_back(self) -> bool:
        return not self.following

    def visible_range(self) -> tuple[int, int]:
        if self.following:
            top = self.view_top_override
            if top is not None:  # mid page-turn: window slides toward page_start, never past it
                return top, min(top + self.page_height, self.revealed_end)
            return self.page_start, self.revealed_end
        top = self.scroll_top
        return top, min(top + self.page_height, self.revealed_end)

    def visible_lines(self) -> list[Line]:
        top, end = self.visible_range()
        return self.lines[top:end]

    def advance(self) -> str:
        """Space/Enter/click. Returns "returned" (left scrollback), "advanced" or "none"."""
        if not self.following:
            self.following = True
            return "returned"
        if self.held > 0:
            # Keep a few lines of the old page at the top for continuity.
            overlap = max(0, min(self.page_overlap, self.page_height - 1))
            self.page_start = max(self.page_start + 1, self.revealed_end - overlap)
            return "advanced"
        return "none"

    def scroll_by(self, delta: int) -> None:
        """Scroll through revealed content. Negative = up (toward older text)."""
        if delta == 0:
            return
        max_top = max(0, self.revealed_end - self.page_height)
        if self.following:
            if delta > 0:
                return
            self.scroll_top = self.page_start
            self.following = False
        new_top = self.scroll_top + delta
        if delta > 0 and (new_top >= max_top or new_top >= self.page_start):
            self.following = True
            return
        self.scroll_top = max(0, min(new_top, max_top))

    def scroll_to_top(self) -> None:
        self.following = False
        self.scroll_top = 0

    def scroll_to_live(self) -> None:
        self.following = True

    def show_last_page(self) -> None:
        self.page_start = max(0, len(self.lines) - self.page_height)
        self.following = True

    # ---- resize / options ---------------------------------------------------------------

    def _anchor(self) -> tuple[int, int]:
        """(block index, line offset within block) of the first line of the current page."""
        self._layout()
        for i in range(len(self.blocks) - 1, -1, -1):
            if self._starts[i] <= self.page_start:
                return i, self.page_start - self._starts[i]
        return 0, 0

    def _restore_anchor(self, anchor: tuple[int, int]) -> None:
        self._layout()
        if not self.blocks:
            self.page_start = 0
            return
        i, offset = anchor
        i = min(i, len(self.blocks) - 1)
        end = self._starts[i + 1] if i + 1 < len(self.blocks) else len(self._lines)
        self.page_start = min(self._starts[i] + offset, max(end - 1, self._starts[i]))

    def set_size(self, width: int, height: int) -> None:
        width, height = max(width, 1), max(height, 1)
        if (width, height) == (self.width, self.page_height):
            return
        anchor = self._anchor()
        self.width, self.page_height = width, height
        self._dirty = True
        self._restore_anchor(anchor)
        self.scroll_top = min(self.scroll_top, max(0, self.revealed_end - self.page_height))

    def set_show_reasoning(self, show: bool) -> None:
        if show != self.show_reasoning:
            anchor = self._anchor()
            self.show_reasoning = show
            self._dirty = True
            self._restore_anchor(anchor)

    # ---- helpers ------------------------------------------------------------------------

    def finalize_markdown(self) -> None:
        for block in self.blocks:
            if isinstance(block, MarkdownBlock):
                block.finalize()
        self._dirty = True
