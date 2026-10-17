# AIGM: notes for Claude

One git repo, two independent uv Python projects: `server/` (FastAPI + SSE + Anthropic SDK) and `client/` (Textual
terminal client). They share nothing but the HTTP API. See `README.md` for setup and `docs/` for the designs.

## Documentation standard

- **Keep every line in Markdown files at 120 characters or fewer** (README.md, everything in `docs/`, and any new
  `.md` doc). Wrap prose and list items at a word boundary, indenting continuation lines to the item's text.
- Never split an inline code span across lines.
- **Tables are exempt.** Markdown tables cannot wrap, so table rows may exceed 120 characters. Keep cells
  reasonably concise, and prefer a list when a table's cells are mostly long prose.
- Wrap long lines inside code blocks by hand (break JSON across lines, put trailing comments on their own line).
- Check before finishing a docs change:
  `awk '{ if (length($0) > 120 && $0 !~ /^\|/) print FILENAME": "FNR }' README.md docs/*.md` should print
  nothing. (macOS `awk` counts bytes, so also check non-ASCII lines with Python's `len`.)
- Prompt files under `server/src/aigm/prompts/` are model input, not docs: this limit does not apply to them.

## Tests

`cd server && uv run pytest` and `cd client && uv run pytest` must both pass before work is called done.
