#!/usr/bin/env python3
"""Draws Sakamoto Voice's app icon, "Bleep, speaking": our own little creature on the left and three
sound-wave arcs fanning out to the right, in glowing vector lines (the look of Space Flees 2100: a
hot, nearly white core in each line and a soft colored halo, as on a vector arcade display) on a
dark indigo fill. Needs Pillow and NumPy; offscreen.

    python3 ios/scripts/make-icon.py [--preview out.png]

It writes the Icon Composer document ios/SakamotoVoice/AppIcon.icon: icon.json (the fill, a dark
gradient with a darker one for the dark appearance, and two groups) and its two transparent
1024x1024 layers, Assets/creature.png and Assets/waves.png. Xcode compiles the document for iOS 26's
lit appearances (default, dark, tinted, and clear) and flattens it for iOS 18. --preview also writes
the composed icon, flat, with the corners rounded, for review.

Bleep: a rounded, boxy body drawn in warm coral outline, two round eyes, an open "O" mouth (it's
singing), one antenna with a glowing bead, two short legs, and two arms: the right one reaching
out toward the waves, its hand open, as if projecting its voice, and the left one hanging relaxed
at its side. The waves are teal, centered on the mouth's height.
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw

SIZE = 1024
SS = 4                                   # strokes drawn at 4x, then reduced: smooth curves

# Colors (sRGB, 0..1).
CORAL = (1.00, 0.45, 0.30)               # the creature
TEAL = (0.10, 0.90, 0.85)                # the waves
FILL_TOP, FILL_BOTTOM = (0.165, 0.110, 0.380), (0.035, 0.027, 0.110)          # indigo to night
DARK_TOP, DARK_BOTTOM = (0.090, 0.059, 0.220), (0.012, 0.012, 0.040)

# Each line: a near-white core, the line itself in its color, and two halos (Gaussian sigma in
# pixels at 1024, and strength).
HALOS = ((9, 0.85), (30, 0.75), (70, 0.35))
CORE_SHARE = 0.45                        # the core's width, as a share of the line's
CORE_WHITE = 0.65                        # how far the core goes toward white

LINE = 24                                # the line width at 1024 pixels: about 4 px at 60 pt @3x
SCALE = 1.1                              # the layout below, enlarged about the center


def gaussian(a, sigma):
    """A Gaussian blur of a 2-D float array, by FFT, padded so the edges don't wrap."""
    pad = int(3 * sigma) + 1
    p = np.pad(a, pad)
    fy = np.fft.fftfreq(p.shape[0])[:, None]
    fx = np.fft.rfftfreq(p.shape[1])[None, :]
    h = np.exp(-2 * (math.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    out = np.fft.irfft2(np.fft.rfft2(p) * h, s=p.shape)
    return np.clip(out[pad:-pad, pad:-pad], 0, None)


class Strokes:
    """Lines drawn at SS times the size, as a mask, and its narrower core."""

    def __init__(self):
        self.mask = Image.new('L', (SIZE * SS, SIZE * SS))
        self.core = Image.new('L', (SIZE * SS, SIZE * SS))

    def _each(self, fn):
        for image, share in ((self.mask, 1.0), (self.core, CORE_SHARE)):
            fn(ImageDraw.Draw(image), LINE * share * SS)

    @staticmethod
    def _p(x, y):
        """A point of the layout, scaled about the center, in drawing pixels."""
        c = SIZE / 2
        return (c + (x - c) * SCALE) * SS, (c + (y - c) * SCALE) * SS

    def _s(self, points):
        return [self._p(x, y) for x, y in points]

    def polyline(self, points, closed=False):
        pts = self._s(points + (points[:1] if closed else []))

        def fn(d, w):
            d.line(pts, fill=255, width=round(w), joint='curve')
            for x, y in pts:                                 # round ends and joints
                d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
        self._each(fn)

    def rounded_rect(self, box, radius):
        (x0, y0), (x1, y1) = self._p(*box[:2]), self._p(*box[2:])
        radius *= SCALE

        def fn(d, w):
            d.rounded_rectangle([x0 - w / 2, y0 - w / 2, x1 + w / 2, y1 + w / 2],
                                radius * SS + w / 2, fill=255)
            d.rounded_rectangle([x0 + w / 2, y0 + w / 2, x1 - w / 2, y1 - w / 2],
                                max(radius * SS - w / 2, 0), fill=0)
        self._each(fn)

    def ellipse(self, center, rx, ry):
        cx, cy = self._p(*center)
        rx, ry = rx * SCALE, ry * SCALE

        def fn(d, w):
            d.ellipse([cx - rx * SS - w / 2, cy - ry * SS - w / 2,
                       cx + rx * SS + w / 2, cy + ry * SS + w / 2], fill=255)
            d.ellipse([cx - rx * SS + w / 2, cy - ry * SS + w / 2,
                       cx + rx * SS - w / 2, cy + ry * SS - w / 2], fill=0)
        self._each(fn)

    def dot(self, center, r):
        cx, cy = self._p(*center)
        r *= SCALE

        def fn(d, w):
            rr = r * SS * (w / (LINE * SS)) ** 0.5           # the core a little smaller
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
        self._each(fn)

    def arc(self, center, radius, spread):
        """An arc around center, spread degrees each side of pointing right."""
        n = 64
        pts = [(center[0] + radius * math.cos(math.radians(a)),
                center[1] + radius * math.sin(math.radians(a)))
               for a in np.linspace(-spread, spread, n)]
        self.polyline(pts)

    def glow(self, color):
        """The layer: emitted light as straight RGBA (alpha the brightest channel), so that over the
        dark fill it looks added, as a vector display's light is."""
        def small(image):
            return np.asarray(image.resize((SIZE, SIZE), Image.BOX), dtype=np.float64) / 255

        line, core = small(self.mask), small(self.core)
        c = np.array(color)
        hot = c + (1 - c) * CORE_WHITE
        light = line[..., None] * c + core[..., None] * (hot - c)
        for sigma, strength in HALOS:
            light += gaussian(line, sigma)[..., None] * c * strength
        alpha = np.clip(light.max(axis=2), 0, 1)
        rgb = np.where(alpha[..., None] > 0, light / np.maximum(alpha[..., None], 1e-6), 0)
        rgba = np.dstack([np.clip(rgb, 0, 1), alpha])
        return Image.fromarray(np.round(rgba * 255).astype(np.uint8), 'RGBA')


# The layout, in pixels at 1024. The mouth's height is the waves' center.
BODY = (178, 382, 446, 618)              # left, top, right, bottom
MOUTH_Y = 548
OFFSET_X = 40                            # shifts the whole design to center it
WAVES_DX = 52                            # the waves' extra room, for the outstretched arm


def creature():
    s = Strokes()
    x0, y0, x1, y1 = (BODY[0] + OFFSET_X, BODY[1], BODY[2] + OFFSET_X, BODY[3])
    mid = (x0 + x1) / 2
    s.rounded_rect((x0, y0, x1, y1), 70)
    s.dot((mid - 58, 476), 24)                               # eyes
    s.dot((mid + 58, 476), 24)
    s.ellipse((mid, MOUTH_Y), 26, 30)                        # the open mouth
    s.polyline([(mid + 18, y0), (mid + 34, y0 - 58), (mid + 72, y0 - 92)])   # antenna, bent
    s.dot((mid + 72, y0 - 92), 20)                           # its bead
    for x, dx in ((x0 + 104, -6), (x1 - 104, 6)):           # two legs
        s.polyline([(x, y1), (x + dx, y1 + 52), (x + dx + (10 if dx > 0 else -10), y1 + 52)])
    # The right arm reaches out toward the waves, its hand open (three splayed fingers), projecting
    # its voice; the left one hangs relaxed at its side, curving gently down.
    hand = (x1 + 68, 492)
    s.polyline([(x1, 510), hand])
    for angle in (-58, -14, 30):                             # fingers, degrees below pointing right
        s.polyline([hand, (hand[0] + 26 * math.cos(math.radians(angle)),
                           hand[1] + 26 * math.sin(math.radians(angle)))])
    s.polyline([(x0 - 38 * math.sin(math.radians(a)), 592 - 92 * math.cos(math.radians(a)))
                for a in np.linspace(0, 90, 16)])
    return s.glow(CORAL)


def waves():
    s = Strokes()
    center = (BODY[2] + OFFSET_X + 18 + WAVES_DX, MOUTH_Y)
    for radius in (96, 190, 284):
        s.arc(center, radius, 44)
    return s.glow(TEAL)


def srgb(c):
    return 'srgb:' + ','.join('%.5f' % v for v in (*c, 1.0))


ICON_JSON = {
    'fill-specializations': [
        {'value': {'linear-gradient': [srgb(FILL_TOP), srgb(FILL_BOTTOM)]}},
        {'appearance': 'dark', 'value': {'linear-gradient': [srgb(DARK_TOP), srgb(DARK_BOTTOM)]}},
    ],
    'groups': [                                              # front to back
        {'name': 'Creature',
         'layers': [{'name': 'creature', 'image-name': 'creature.png', 'glass': False}],
         'shadow': {'kind': 'neutral', 'opacity': 0.4},
         'translucency': {'enabled': False, 'value': 0.5}},
        {'name': 'Waves',
         'layers': [{'name': 'waves', 'image-name': 'waves.png', 'glass': False}],
         'shadow': {'kind': 'neutral', 'opacity': 0.3},
         'translucency': {'enabled': False, 'value': 0.5}},
    ],
    'supported-platforms': {'squares': 'shared'},
}


def preview(layers, path):
    """The composed icon, flat: the fill's gradient, the layers back to front, rounded corners."""
    t = np.linspace(0, 1, SIZE)[:, None, None]
    fill = np.array(FILL_TOP) + (np.array(FILL_BOTTOM) - np.array(FILL_TOP)) * t
    image = Image.fromarray(np.round(np.broadcast_to(fill, (SIZE, SIZE, 3)) * 255)
                            .astype(np.uint8), 'RGB').convert('RGBA')
    for layer in reversed(layers):
        image = Image.alpha_composite(image, layer)
    mask = Image.new('L', (SIZE * SS, SIZE * SS))
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE * SS - 1, SIZE * SS - 1],
                                           round(0.2237 * SIZE * SS), fill=255)
    image.putalpha(mask.resize((SIZE, SIZE), Image.BOX))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    image.save(path, optimize=True)
    print(path)


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    package = os.path.normpath(os.path.join(here, '..', 'SakamotoVoice', 'AppIcon.icon'))
    assets = os.path.join(package, 'Assets')
    os.makedirs(assets, exist_ok=True)
    layers = [creature(), waves()]                           # front to back, as in icon.json
    for layer, group in zip(layers, ICON_JSON['groups']):
        path = os.path.join(assets, group['layers'][0]['image-name'])
        layer.save(path, optimize=True)
        print(path)
    with open(os.path.join(package, 'icon.json'), 'w') as f:
        json.dump(ICON_JSON, f, indent=2)
        f.write('\n')
    print(os.path.join(package, 'icon.json'))
    if len(argv) == 2 and argv[0] == '--preview':
        preview(layers, argv[1])
    elif argv:
        sys.exit(__doc__.split('\n\n')[1])


if __name__ == '__main__':
    main(sys.argv[1:])
