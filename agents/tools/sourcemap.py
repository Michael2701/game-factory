"""Best-effort mapping of browser stack frames in a built bundle back to source files (M21).

`map_frames(text, project)` rewrites `http://…/assets/index-abc.js:68:9415` to
`src/scenes/GameScene.ts:56:9 (index-abc.js:68:9415)` using `dist/assets/*.js.map` (debug
build, see the template's vite.config.ts). Any problem (no map, bad map, unknown position)
leaves the frame as it is: the raw browser error must reach the fixer either way.
"""

import json
import re
from bisect import bisect_right
from pathlib import Path

B64 = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}
FRAME = re.compile(r"https?://[^\s()]+/assets/([\w.-]+\.js):(\d+):(\d+)")


def decode_vlq(segment: str) -> list[int]:
    values, value, shift = [], 0, 0
    for char in segment:
        digit = B64[char]
        value += (digit & 31) << shift
        if digit & 32:
            shift += 5
            continue
        values.append(-(value >> 1) if value & 1 else value >> 1)
        value, shift = 0, 0
    return values


class SourceMap:
    def __init__(self, data: dict):
        self.sources = data["sources"]
        self.lines: list[list[tuple[int, int, int, int]]] = []
        source = src_line = src_col = 0
        for line in data["mappings"].split(";"):
            column, segments = 0, []
            for segment in filter(None, line.split(",")):
                values = decode_vlq(segment)
                column += values[0]
                if len(values) >= 4:
                    source, src_line, src_col = source + values[1], src_line + values[2], src_col + values[3]
                    segments.append((column, source, src_line, src_col))
            self.lines.append(segments)

    def lookup(self, line: int, column: int) -> tuple[str, int, int] | None:
        """1-based generated line/column -> (source path, 1-based line, 1-based column)."""
        if not 0 < line <= len(self.lines) or not self.lines[line - 1]:
            return None
        segments = self.lines[line - 1]
        index = bisect_right([s[0] for s in segments], column - 1) - 1
        if index < 0:
            return None
        _, source, src_line, src_col = segments[index]
        return self.sources[source], src_line + 1, src_col + 1


def _project_path(source: str) -> str:
    """'../../src/scenes/GameScene.ts' -> 'src/scenes/GameScene.ts'; other sources keep their tail."""
    parts = source.replace("\\", "/").split("/")
    for anchor in ("src", "node_modules"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor):])
    return parts[-1]


def map_frames(text: str, project: Path) -> str:
    """Rewrite bundle frames in `text` to source positions; never raises."""
    cache: dict[str, SourceMap | None] = {}

    def load(bundle: str) -> SourceMap | None:
        if bundle not in cache:
            try:
                cache[bundle] = SourceMap(json.loads((project / "dist/assets" / f"{bundle}.map").read_text()))
            except (OSError, ValueError, KeyError, IndexError):
                cache[bundle] = None
        return cache[bundle]

    def replace(match: re.Match) -> str:
        bundle, line, column = match.group(1), int(match.group(2)), int(match.group(3))
        try:
            source_map = load(bundle)
            found = source_map.lookup(line, column) if source_map else None
        except (KeyError, IndexError):
            found = None
        if not found:
            return match.group(0)
        path, src_line, src_col = found
        return f"{_project_path(path)}:{src_line}:{src_col} ({bundle}:{line}:{column})"

    try:
        return FRAME.sub(replace, text)
    except Exception:  # best effort: raw text is always acceptable
        return text
