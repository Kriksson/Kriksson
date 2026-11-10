#!/usr/bin/env python3
"""Build self-contained animated SVG variants; keep original assets as fallbacks.

The GitHub README cannot run JavaScript. Motion lives inside image documents:
CSS transforms/opacity, clipped conveyor tracks, and rotating existing gears.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def element(name: str, **attrs) -> ET.Element:
    return ET.Element(f'{{{NS}}}{name}', {key.replace('_', '-'): str(value) for key, value in attrs.items()})


def original(path: str) -> str:
    path = path.replace('assets/profile/motion/', 'assets/profile/')
    # University banners are PNG source illustrations, SVG animation wrappers.
    if re.search(r'/about/university(?:-mobile)?\.svg$', path):
        path = path[:-4]+'.png'
    return path


def motion_path(path: str) -> str:
    return str(Path(original(path).replace('assets/profile/', 'assets/profile/motion/')).with_suffix('.svg'))


def animated_asset(path: Path, key: str) -> str:
    if path.suffix == '.png':
        with Image.open(path) as image:
            width, height = image.size
        root = element('svg', width=width, height=height, viewBox=f'0 0 {width} {height}', role='img')
        image = element('image', width=width, height=height,
                        href='data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode('ascii'))
        root.append(image)
    else:
        root = ET.fromstring(path.read_text())
    left, top, width, height = map(float, root.attrib['viewBox'].split())
    phase = int(hashlib.sha256(key.encode()).hexdigest()[:4], 16) % 800 / 100
    small = height <= 56
    belt_height = 2 if small else 7
    inset = 7 if small else 24
    y = top + height - (4 if small else 13)

    defs = element('defs')
    clip = element('clipPath', id='motion-frame')
    clip.append(element('rect', x=left+1, y=top+1, width=width-2, height=height-2, rx=5 if small else 14))
    defs.append(clip)
    belt_clip = element('clipPath', id='motion-belt')
    belt_clip.append(element('rect', x=left+inset, y=y, width=width-inset*2, height=belt_height, rx=1))
    defs.append(belt_clip)
    gradient = element('linearGradient', id='motion-sheen', x1='0', y1='0', x2='1', y2='.2')
    for offset, opacity in [('0', '0'), ('.46', '0'), ('.5', '.11'), ('.54', '0'), ('1', '0')]:
        gradient.append(element('stop', offset=offset, stop_color='#e2c6a4', stop_opacity=opacity))
    defs.append(gradient)
    root.insert(0, defs)

    style = element('style')
    style.text = f'''
@keyframes profile-belt {{ to {{ transform: translateX(32px); }} }}
@keyframes profile-sheen {{ to {{ transform: translateX({width*3:g}px); }} }}
@keyframes profile-gear {{ to {{ transform: rotate(360deg); }} }}
@keyframes profile-signal {{ 0%,100% {{ opacity: .35; }} 50% {{ opacity: .85; }} }}
.profile-conveyor {{ animation: profile-belt 1.6s linear infinite; }}
.profile-sheen {{ animation: profile-sheen 9s linear infinite; animation-delay: -{phase:g}s; }}
.profile-gear {{ transform-origin: 0px 0px; animation: profile-gear 24s linear infinite; }}
.profile-signal {{ animation: profile-signal 6s cubic-bezier(.77,0,.175,1) infinite; animation-delay: -{phase:g}s; }}
@media (prefers-reduced-motion: reduce) {{
 .profile-conveyor, .profile-sheen, .profile-gear, .profile-signal {{ animation: none; }}
 .profile-sheen {{ opacity: 0; }}
}}
'''
    root.insert(1, style)

    # Place the light sweep behind vector text; raster banners use a faint overlay.
    sheen = element('g', clip_path='url(#motion-frame)', pointer_events='none')
    sheen.append(element('rect', x=left-width, y=top, width=width, height=height,
                         fill='url(#motion-sheen)', **{'class': 'profile-sheen'}))
    background = next((child for child in root if child.tag in {f'{{{NS}}}rect', f'{{{NS}}}image'}), None)
    root.insert(list(root).index(background)+1 if background is not None else 2, sheen)

    # Existing heading gears rotate around their original local center.
    if '/headings/' in key:
        for group in list(root):
            if group.tag == f'{{{NS}}}g' and group.findall(f'{{{NS}}}circle'):
                rotor = element('g', **{'class': 'profile-gear'})
                for child in list(group):
                    group.remove(child)
                    rotor.append(child)
                group.append(rotor)

    belt = element('g', clip_path='url(#motion-belt)', pointer_events='none')
    belt.append(element('rect', x=left+inset, y=y, width=width-inset*2, height=belt_height, fill='#171d23'))
    cargo = element('g', **{'class': 'profile-conveyor'})
    for x in range(-32, int(width)+32, 32):
        cargo.append(element('path', d=f'M{left+x:g} {y:g}l{belt_height:g} {belt_height/2:g} -{belt_height:g} {belt_height/2:g}',
                             fill='none', stroke='#9e7956', stroke_width=1 if small else 1.5, opacity='.55'))
        if not small:
            cargo.append(element('rect', x=left+x+13, y=y+1, width=8, height=belt_height-2,
                                 fill='#a5a29b', opacity='.4'))
    belt.append(cargo)
    root.append(belt)

    if '/stack/' in key or '/study/' in key:
        # A small status light animates independently of the label.
        root.append(element('rect', x=9, y=10, width=5, height=8, rx=1.5,
                            fill='#d4b28e', **{'class': 'profile-signal'}))
    return ET.tostring(root, encoding='unicode')+'\n'


def rewrite_picture(match: re.Match) -> str:
    body = match.group(1)
    if '/stats/' in body:
        return match.group(0)
    img = re.search(r'<img\b[^>]*>', body).group(0)
    desktop = original(re.search(r'src="([^"]+)"', img).group(1))
    mobile_match = re.search(r'<source\b[^>]*media="\(max-width: 600px\)"[^>]*srcset="([^"]+)"', body)
    mobile = original(mobile_match.group(1)) if mobile_match else None
    lines = ['<picture>']
    if mobile:
        lines.append(f'  <source media="(prefers-reduced-motion: reduce) and (max-width: 600px)" srcset="{mobile}">')
    lines.append(f'  <source media="(prefers-reduced-motion: reduce)" srcset="{desktop}">')
    if mobile:
        lines.append(f'  <source media="(max-width: 600px)" srcset="{motion_path(mobile)}">')
    img = re.sub(r'src="[^"]+"', f'src="{motion_path(desktop)}"', img)
    lines.extend(['  '+img, '</picture>'])
    return '\n'.join(lines)


def build(root: Path = ROOT) -> int:
    readme = root/'README.md'
    text = readme.read_text()
    # Contact icons already have meaningful hyperlinks; keep them and add picture fallbacks.
    text = re.sub(r'(<a\b[^>]*>)(<img\b[^>]*>)(</a>)', r'\1<picture>\2</picture>\3', text)
    sources = sorted({original(path) for path in re.findall(r'(?:src|srcset)="(assets/profile/[^"]+)"', text)
                      if '/stats/' not in path})
    for source in sources:
        target = root/motion_path(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = animated_asset(root/source, source)
        if not target.exists() or target.read_text() != content:
            target.write_text(content)
    updated = re.sub(r'<picture>(.*?)</picture>', rewrite_picture, text, flags=re.S)
    if readme.read_text() != updated:
        readme.write_text(updated)
    return len(sources)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(f'Built {build(args.root)} animated SVG variants.')
