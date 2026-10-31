"""Render pauta's link-preview card (og.png, 1200x630) and PNG icons into src/pauta/static.

macOS only (uses the system SF font). Run: uv run --no-project --with pillow python
tools/render_images.py src/pauta/static
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(sys.argv[1])
SF = "/System/Library/Fonts/SFNS.ttf"
VIOLET, ORANGE = (123, 92, 255), (255, 106, 61)
S = 2  # supersample


def font(size, weight="Bold"):
    f = ImageFont.truetype(SF, size * S)
    f.set_variation_by_name(weight)
    return f


def gradient(w, h, a=VIOLET, b=ORANGE):
    g = Image.new("RGB", (w, h))
    px = g.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return g


def logo(size):
    """The app icon: gradient rounded square, three bars and a dot (icon.svg)."""
    k = size / 64
    tile = gradient(size, size)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=16 * k, fill=255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img)
    for x, y, w, op in ((15, 17, 34, 255), (15, 29, 24, 217), (15, 41, 14, 178)):
        d.rounded_rectangle(
            [x * k, y * k, (x + w) * k, (y + 6) * k], radius=3 * k, fill=(255, 255, 255, op)
        )
    d.ellipse([40 * k, 39 * k, 50 * k, 49 * k], fill=(255, 255, 255, 255))
    return img


def card():
    W, H = 1200 * S, 630 * S
    img = Image.new("RGB", (W, H), (14, 14, 18))
    glow = Image.new("RGB", (W, H), (14, 14, 18))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-260 * S, -300 * S, 520 * S, 420 * S], fill=(62, 46, 140))
    gd.ellipse([760 * S, 300 * S, 1500 * S, 980 * S], fill=(120, 52, 34))
    img = glow.filter(ImageFilter.GaussianBlur(150 * S))
    d = ImageDraw.Draw(img)

    # left: logo, wordmark, tagline, address
    lg = logo(112 * S)
    img.paste(lg, (88 * S, 150 * S), lg)
    d.text((86 * S, 282 * S), "pauta", font=font(132, "Heavy"), fill=(242, 242, 247))
    d.text((90 * S, 448 * S), "Os pedidos do time,", font=font(40, "Medium"), fill=(200, 199, 210))
    d.text((90 * S, 498 * S), "num lugar só.", font=font(40, "Medium"), fill=(200, 199, 210))

    # right: three request cards, slightly fanned, like the board
    cards = [
        (
            "Clínica Bem Estar",
            "Campanha de limpeza de pele",
            "Em andamento",
            (122, 167, 255),
            "Amanhã",
        ),
        (
            "Padaria Trigo de Ouro",
            "Novos criativos do panetone",
            "A fazer",
            (163, 177, 198),
            "Hoje",
        ),
        ("Studio Lume Pilates", "Aula experimental grátis", "Concluído", (95, 211, 139), "✓"),
    ]
    for i, (client, what, status, color, due) in enumerate(cards):
        cw, ch = 440 * S, 166 * S
        layer = Image.new("RGBA", (cw + 80 * S, ch + 80 * S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ox, oy = 40 * S, 40 * S
        ld.rounded_rectangle(
            [ox, oy + 10 * S, ox + cw, oy + ch + 10 * S], radius=22 * S, fill=(0, 0, 0, 90)
        )
        layer = layer.filter(ImageFilter.GaussianBlur(14 * S))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle(
            [ox, oy, ox + cw, oy + ch],
            radius=22 * S,
            fill=(28, 28, 36, 255),
            outline=(52, 52, 64, 255),
            width=2 * S,
        )
        initials = "".join(w[0] for w in client.split()[:1] + client.split()[-1:]).upper()
        h = [(64, 46, 140), (110, 74, 30), (34, 92, 60)][i]
        ld.rounded_rectangle(
            [ox + 24 * S, oy + 24 * S, ox + 60 * S, oy + 60 * S], radius=10 * S, fill=h
        )
        ld.text(
            (ox + 42 * S, oy + 42 * S),
            initials,
            font=font(15, "Bold"),
            fill=(240, 240, 245),
            anchor="mm",
        )
        ld.text(
            (ox + 74 * S, oy + 42 * S),
            client,
            font=font(21, "Semibold"),
            fill=(205, 204, 214),
            anchor="lm",
        )
        ld.text((ox + 24 * S, oy + 74 * S), what, font=font(24, "Semibold"), fill=(240, 240, 245))
        pf = font(18, "Semibold")
        tw = ld.textlength(status, font=pf)
        px, py = ox + 24 * S, oy + 134 * S
        pill = tuple(int(c * 0.22 + 28 * 0.78) for c in color)
        ld.rounded_rectangle(
            [px, py - 15 * S, px + tw + 44 * S, py + 15 * S], radius=15 * S, fill=pill
        )
        ld.ellipse([px + 13 * S, py - 4 * S, px + 21 * S, py + 4 * S], fill=color)
        ld.text((px + 30 * S, py), status, font=pf, fill=color, anchor="lm")
        due_color = (245, 166, 91) if due in ("Hoje", "Amanhã") else (140, 138, 150)
        ld.text((ox + cw - 24 * S, py), due, font=pf, fill=due_color, anchor="rm")
        layer = layer.rotate([-4, 2, -1][i], resample=Image.BICUBIC, expand=False)
        img.paste(layer, ((630 + [10, 60, 25][i]) * S, (22 + i * 182) * S), layer)

    d = ImageDraw.Draw(img)
    d.text((90 * S, 566 * S), "pauta.cc", font=font(22, "Semibold"), fill=(150, 148, 162))
    img.resize((1200, 630), Image.LANCZOS).save(OUT / "og.png", optimize=True)


def icons():
    for size, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        # full-bleed square: iOS and Android round the corners themselves
        big = gradient(size * 2, size * 2)
        d = ImageDraw.Draw(big)
        k = size * 2 / 64
        for x, y, w, op in ((15, 17, 34, 255), (15, 29, 24, 217), (15, 41, 14, 178)):
            c = tuple(
                int(255 * op / 255 + big.getpixel((int(x * k), int(y * k)))[i] * (1 - op / 255))
                for i in range(3)
            )
            d.rounded_rectangle([x * k, y * k, (x + w) * k, (y + 6) * k], radius=3 * k, fill=c)
        d.ellipse([40 * k, 39 * k, 50 * k, 49 * k], fill=(255, 255, 255))
        big.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)


card()
icons()
print(sorted(p.name for p in OUT.glob("*.png")))
