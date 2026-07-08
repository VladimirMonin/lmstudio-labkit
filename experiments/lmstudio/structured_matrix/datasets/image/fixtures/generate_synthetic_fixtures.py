#!/usr/bin/env python3
"""Generate deterministic public-safe synthetic image fixtures for L3.15.

The generator intentionally uses only the Python standard library so the fixture
pack is reproducible without adding image-processing dependencies. It writes six
small PNG files plus no sidecar metadata; hashes and contracts are recorded in
../manifest.yaml and ../expected/*.expected.yaml.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

Color = tuple[int, int, int]
PixelFn = Callable[[int, int], Color]

ROOT = Path(__file__).resolve().parent

WIDTH = 320
HEIGHT = 200

WHITE: Color = (255, 255, 255)
INK: Color = (36, 45, 56)
MUTED: Color = (113, 128, 150)
BLUE: Color = (55, 125, 255)
GREEN: Color = (48, 167, 96)
RED: Color = (214, 74, 74)
YELLOW: Color = (242, 178, 61)
PURPLE: Color = (130, 93, 212)
CYAN: Color = (61, 178, 204)
PANEL: Color = (242, 246, 252)
GRID: Color = (211, 220, 232)
SKIN_SAFE: Color = (198, 154, 118)


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def write_png(path: Path, width: int, height: int, pixel: PixelFn) -> None:
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(pixel(x, y))
        rows.append(bytes(row))
    payload = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(payload, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(data)


class Canvas:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT, background: Color = WHITE) -> None:
        self.width = width
        self.height = height
        self.pixels: list[list[Color]] = [[background for _ in range(width)] for _ in range(height)]

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
        for y in range(max(0, y0), min(self.height, y1)):
            row = self.pixels[y]
            for x in range(max(0, x0), min(self.width, x1)):
                row[x] = color

    def frame(self, x0: int, y0: int, x1: int, y1: int, color: Color, thickness: int = 1) -> None:
        self.rect(x0, y0, x1, y0 + thickness, color)
        self.rect(x0, y1 - thickness, x1, y1, color)
        self.rect(x0, y0, x0 + thickness, y1, color)
        self.rect(x1 - thickness, y0, x1, y1, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: Color, thickness: int = 1) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self.rect(x, y, x + thickness, y + thickness, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def circle(self, cx: int, cy: int, radius: int, color: Color) -> None:
        r2 = radius * radius
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    self.rect(x, y, x + 1, y + 1, color)

    def save(self, name: str) -> None:
        write_png(ROOT / name, self.width, self.height, lambda x, y: self.pixels[y][x])


def build_ui_screenshot() -> None:
    c = Canvas(background=(248, 250, 252))
    c.rect(0, 0, 320, 34, (30, 41, 59))
    c.rect(0, 34, 70, 200, (226, 232, 240))
    for y in (52, 76, 100, 124):
        c.rect(14, y, 54, y + 10, BLUE if y == 52 else (148, 163, 184))
    for x0, color in ((92, BLUE), (166, GREEN), (240, YELLOW)):
        c.rect(x0, 54, x0 + 54, 94, color)
        c.rect(x0 + 8, 102, x0 + 44, 108, MUTED)
    c.frame(92, 126, 292, 180, GRID)
    c.line(104, 166, 142, 150, BLUE, 2)
    c.line(142, 150, 184, 158, BLUE, 2)
    c.line(184, 158, 226, 136, BLUE, 2)
    c.line(226, 136, 278, 144, BLUE, 2)
    c.save("ui_screenshot.png")


def build_code_screenshot() -> None:
    c = Canvas(background=(15, 23, 42))
    c.rect(0, 0, 320, 24, (30, 41, 59))
    for idx, color in enumerate((RED, YELLOW, GREEN)):
        c.circle(16 + idx * 18, 12, 5, color)
    for row in range(9):
        y = 42 + row * 15
        c.rect(24, y, 36, y + 4, MUTED)
        c.rect(50, y, 88 + (row % 3) * 18, y + 5, CYAN if row % 2 else PURPLE)
        c.rect(96 + (row % 3) * 18, y, 176 + row * 4, y + 5, (226, 232, 240))
        if row in (2, 5, 7):
            c.rect(188, y, 246, y + 5, GREEN)
    c.frame(44, 34, 292, 184, (51, 65, 85))
    c.save("code_screenshot.png")


def build_document_table() -> None:
    c = Canvas(background=WHITE)
    c.rect(30, 22, 290, 48, PANEL)
    c.rect(48, 64, 272, 166, WHITE)
    c.frame(48, 64, 272, 166, INK)
    for x in (104, 160, 216):
        c.line(x, 64, x, 166, GRID)
    for y in (88, 112, 136):
        c.line(48, y, 272, y, GRID)
    c.rect(48, 64, 272, 88, (226, 232, 240))
    for row in range(3):
        y = 98 + row * 24
        c.rect(58, y, 90, y + 5, MUTED)
        c.rect(114, y, 146, y + 5, BLUE)
        c.rect(170, y, 202, y + 5, GREEN)
        c.rect(226, y, 258, y + 5, YELLOW)
    c.save("document_table.png")


def build_chart_graph() -> None:
    c = Canvas(background=WHITE)
    c.rect(34, 24, 292, 172, PANEL)
    c.line(58, 150, 276, 150, INK, 2)
    c.line(58, 44, 58, 150, INK, 2)
    for y in (70, 96, 122):
        c.line(58, y, 276, y, GRID)
    for idx, height in enumerate((34, 58, 78, 48)):
        x = 86 + idx * 44
        c.rect(x, 150 - height, x + 22, 150, (BLUE, GREEN, PURPLE, YELLOW)[idx])
    c.line(86, 128, 130, 112, RED, 2)
    c.line(130, 112, 174, 84, RED, 2)
    c.line(174, 84, 218, 104, RED, 2)
    c.line(218, 104, 262, 76, RED, 2)
    c.save("chart_graph.png")


def build_people_scene() -> None:
    c = Canvas(background=(236, 248, 255))
    c.rect(0, 145, 320, 200, (214, 240, 224))
    c.rect(32, 44, 130, 132, (255, 247, 237))
    c.frame(32, 44, 130, 132, GRID, 2)
    c.rect(170, 54, 286, 128, (239, 246, 255))
    c.frame(170, 54, 286, 128, GRID, 2)
    for cx, color in ((88, BLUE), (196, PURPLE), (244, GREEN)):
        c.circle(cx, 102, 13, SKIN_SAFE)
        c.rect(cx - 12, 116, cx + 12, 150, color)
        c.line(cx - 12, 124, cx - 28, 142, color, 3)
        c.line(cx + 12, 124, cx + 28, 142, color, 3)
    c.save("people_scene.png")


def build_mixed_text_image() -> None:
    c = Canvas(background=WHITE)
    c.rect(22, 24, 142, 176, (239, 246, 255))
    c.circle(76, 78, 26, YELLOW)
    c.rect(38, 118, 126, 152, GREEN)
    c.rect(166, 34, 292, 54, BLUE)
    for y, width, color in ((76, 108, INK), (96, 92, MUTED), (116, 118, MUTED), (148, 72, RED)):
        c.rect(166, y, 166 + width, y + 8, color)
    c.frame(18, 20, 300, 184, GRID)
    c.save("mixed_text_image.png")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    build_ui_screenshot()
    build_code_screenshot()
    build_document_table()
    build_chart_graph()
    build_people_scene()
    build_mixed_text_image()
    for path in sorted(ROOT.glob("*.png")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{path.name} sha256:{digest} {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
