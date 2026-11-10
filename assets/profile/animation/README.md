The two PNGs are generated typing keyframes matching the existing Factorio
illustration. The renderer composites only a feathered keyboard/hand patch
from the alternate pose, keeping the rest of the scene stationary.

Run `python3 -m pip install -r scripts/animation-requirements.txt` and then
`python3 scripts/render_profile_animation.py` from the repository root.
It reads only the aggregate `metrics/code-stats.json`, and writes desktop and
mobile GIFs plus static PNGs for visitors requesting reduced motion.
The hourly counter workflow runs the renderer after collecting fresh totals.
Byte-identical output is left untouched.

The eight-second loop releases each label from the monitor, then anchors all
three above it for reading. It uses cubic-bezier(.23, 1, .32, 1) for each
850ms arrival, with a 250ms stagger and neutral grey/stone lettering.
It does not interpolate fictitious counter values. The third number is GitHub
contributions over the past year, including private contributions, rather than
only commits or pull requests.

Counter font: Tiny5, sampled on its native eight-pixel grid and enlarged with
nearest-neighbor filtering. SIL Open Font License in `../fonts/Tiny5-LICENSE.txt`.
Source: google/fonts at `f265cc2d8e08067dac782ba633458b97661ab85d`, `ofl/tiny5`.

Run `python3 scripts/build_profile_motion.py` to rebuild animated SVG variants
for every other README image. Original assets remain reduced-motion fallbacks.
This uses image-contained CSS transforms and opacity; no page JavaScript.
