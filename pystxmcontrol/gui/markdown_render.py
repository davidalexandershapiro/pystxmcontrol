"""Shared Markdown→HTML rendering for the logbook view and the agent text flow.

Renders entry/response bodies as Markdown (including pipe tables) for display in a
QTextBrowser. Degrades to escaped plain text if the markdown package is unavailable.
"""


def _looks_like_table_sep(line: str) -> bool:
    """A Markdown table separator row, e.g. |---|:--:|."""
    s = line.strip().strip("|").strip()
    return bool(s) and "-" in s and set(s) <= set("-: |")


def _normalize_tables(text: str) -> str:
    """Insert the blank line a pipe-table header needs when a non-blank line directly
    precedes it, so the common 'lead-in line then table' case renders without the user
    having to remember the blank line."""
    lines = text.split("\n")
    out: list = []
    for i, line in enumerate(lines):
        is_header = ("|" in line and i + 1 < len(lines)
                     and _looks_like_table_sep(lines[i + 1]))
        if is_header and out and out[-1].strip() != "":
            out.append("")
        out.append(line)
    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Render Markdown (incl. pipe tables) to HTML; fall back to escaped plain text."""
    try:
        import markdown as _markdown
        return _markdown.markdown(
            _normalize_tables(text), extensions=["tables", "fenced_code", "sane_lists"]
        )
    except Exception:
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return esc.replace("\n", "<br>")


# Document-level CSS for the tables/code Markdown emits. Colours are left to the theme;
# only borders use a mid-grey that reads on light or dark. Apply with
# QTextBrowser.document().setDefaultStyleSheet(TABLE_STYLESHEET).
TABLE_STYLESHEET = (
    "table { border-collapse: collapse; margin: 4px 0; }"
    "th, td { border: 1px solid #888; padding: 3px 7px; }"
    "th { font-weight: bold; }"
    "code, pre { font-family: monospace; }"
)
