#!/usr/bin/env python3
"""Render the profile's typing loop using aggregate statistics only.

The factory stays still. Only the programmer's keyboard/forearm area changes
between generated poses. No network requests or private repository data.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FPS = 20
FRAME_COUNT = 160
BACKGROUND = '#0d1117'
COLORS = ('#dedbd5', '#b7bcc2', '#c6bba9')


def ease_out(progress: float) -> float:
    """cubic-bezier(.23, 1, .32, 1), solved for elapsed time."""
    progress = max(0.0, min(1.0, progress))
    lo, hi = 0.0, 1.0
    for _ in range(20):
        t = (lo + hi) / 2
        x = 3*(1-t)**2*t*.23 + 3*(1-t)*t*t*.32 + t**3
        if x < progress:
            lo = t
        else:
            hi = t
    return 1-(1-(lo+hi)/2)**3


def arrival(seconds: float, row: int) -> float:
    # Stagger the flights; each value settles and stays in place for reading.
    return ease_out((seconds - .35 - row*.25) / .85)


def labels(data: dict) -> tuple[str, str, str]:
    return (f"+{data['added_lines']:,} lines of code",
            f"+{data['total_repositories']:,} repositories",
            f"+{data['contributions_last_year']:,} contributions")


def render(data: dict, mobile: bool = False, *, artwork_root: Path = ROOT) -> dict[str, bytes]:
    width = 720 if mobile else 1200
    header = 90 if mobile else 40
    art_height = round(width / 3)
    size = (width, header + art_height)
    assets = artwork_root / 'assets/profile'
    # Tiny5 is drawn on an integer pixel grid, then enlarged with nearest-neighbor.
    font = ImageFont.truetype(str(assets/'fonts/Tiny5-Pixel.ttf'), 8)
    original = Image.open(assets/'animation/typing-base.png').convert('RGB')
    alternate = Image.open(assets/'animation/typing-alternate.png').convert('RGB').resize(original.size)
    # Coordinates are normalized to the original 2048 x 683 composition.
    region = (365, 250, 580, 340)
    scale_x, scale_y = original.width / 2048, original.height / 683
    box = tuple(round(v * (scale_x if i % 2 == 0 else scale_y)) for i, v in enumerate(region))
    # Feather the local pose patch, without touching the stationary factory.
    mask = Image.new('L', original.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=18 * scale_x, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(5 * scale_x))
    poses = [original, Image.composite(alternate, original, mask)]
    poses = [pose.resize((width, art_height), Image.Resampling.LANCZOS) for pose in poses]
    values = labels(data)
    positions = [(24 if mobile else 96, 13 + row*30) for row in range(3)]
    # Each label emerges from the actual screen, then anchors above the monitor.
    origin = (width * 425/2048, header + art_height * 230/683)
    tiles = []
    for value, color in zip(values, COLORS):
        bounds = font.getbbox(value)
        glyphs = Image.new('L', (round(font.getlength(value))+2, 8), 0)
        ImageDraw.Draw(glyphs).text((1, -bounds[1]), value, font=font, fill=255)
        glyphs = glyphs.point(lambda alpha: 255 if alpha >= 128 else 0)
        tile = Image.new('RGBA', glyphs.size, color)
        tile.putalpha(glyphs)
        tiles.append(tile.resize((tile.width*4, tile.height*4), Image.Resampling.NEAREST))
    # One shared palette prevents color flicker between frames.
    sample = Image.new('RGB', size, BACKGROUND)
    sample.paste(poses[0], (0, header))
    for tile, pos in zip(tiles, positions):
        sample.paste(tile, pos, tile)
    palette = sample.quantize(colors=256)

    def frame(index: int, complete: bool = False) -> Image.Image:
        canvas = Image.new('RGB', size, BACKGROUND)
        canvas.paste(poses[(index // 4) % 2] if not complete else poses[0], (0, header))
        seconds = index / FPS
        for row, (tile, pos) in enumerate(zip(tiles, positions)):
            progress = 1.0 if complete else arrival(seconds, row)
            if progress < .001:
                continue
            scale = .94 + .06*progress
            visible = tile.resize((round(tile.width*scale), round(tile.height*scale)), Image.Resampling.NEAREST)
            # Fade only at the loop boundary; settled values remain completely still.
            exit_opacity = 1.0 if complete else min(1.0, max(0.0, (8.0-seconds)/.4))
            opacity = progress * exit_opacity
            visible.putalpha(visible.getchannel('A').point(lambda alpha: round(alpha*opacity)))
            start = (origin[0]-tile.width/2, origin[1]-tile.height/2)
            x = round(start[0] + (pos[0]-start[0])*progress)
            y = round(start[1] + (pos[1]-start[1])*progress)
            canvas.paste(visible, (x, y), visible)
        return canvas

    final = frame(FRAME_COUNT - 1, complete=True)
    png = BytesIO()
    final.save(png, format='PNG', optimize=True)
    frames = [frame(i).quantize(palette=palette, dither=Image.Dither.NONE) for i in range(FRAME_COUNT)]
    gif = BytesIO()
    frames[0].save(gif, format='GIF', save_all=True, append_images=frames[1:],
                   duration=1000 // FPS, loop=0, optimize=True, disposal=1)
    suffix = '-mobile' if mobile else ''
    return {f'code-counter{suffix}.gif': gif.getvalue(),
            f'code-counter{suffix}.png': png.getvalue()}


def update(root: Path = ROOT) -> bool:
    data = json.loads((root/'metrics/code-stats.json').read_text())
    outputs = {**render(data), **render(data, mobile=True)}
    target = root/'assets/profile/stats'
    target.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, content in outputs.items():
        path = target/name
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
            changed = True
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print('Animation updated.' if update(args.root) else 'Animation unchanged.')
