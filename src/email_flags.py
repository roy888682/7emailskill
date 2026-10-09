"""Draw email-safe flags and embed them in standalone reports."""
import base64
import io
import math
import re
from functools import lru_cache
from PIL import Image, ImageDraw

_SCALE = 4
_US_RED, _US_BLUE = "#B22234", "#3C3B6E"
_KR_RED, _KR_BLUE = "#CD2E3A", "#0047A0"

def _star_points(cx, cy, radius):
    return [(cx + (radius if i % 2 == 0 else radius * .381966) * math.cos(-math.pi / 2 + i * math.pi / 5),
             cy + (radius if i % 2 == 0 else radius * .381966) * math.sin(-math.pi / 2 + i * math.pi / 5))
            for i in range(10)]

def _draw_us(draw, width, height):
    stripe = height / 13
    for row in range(13):
        draw.rectangle((0, round(row * stripe), width, round((row + 1) * stripe) - 1),
                       fill=_US_RED if row % 2 == 0 else "white")
    cw, ch = width * .4, stripe * 7
    draw.rectangle((0, 0, round(cw) - 1, round(ch) - 1), fill=_US_BLUE)
    for row in range(9):
        columns = 6 if row % 2 == 0 else 5
        for column in range(columns):
            x = (2 * column + (1 if columns == 6 else 2)) * cw / 12
            draw.polygon(_star_points(x, (row + 1) * ch / 10, height * .0308), fill="white")

def _draw_kr(draw, width, height):
    cx, cy, radius = width / 2, height / 2, height / 4
    angle = math.atan2(2, 3)
    dx, dy = math.cos(angle), math.sin(angle)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=_KR_BLUE)
    arc = [(cx + radius * math.cos(angle + math.pi + i * math.pi / 180),
            cy + radius * math.sin(angle + math.pi + i * math.pi / 180)) for i in range(181)]
    draw.polygon(arc, fill=_KR_RED)
    half = radius / 2
    for sign, color in ((-1, _KR_RED), (1, _KR_BLUE)):
        x, y = cx + sign * dx * half, cy + sign * dy * half
        draw.ellipse((x - half, y - half, x + half, y + half), fill=color)
    length, bar, gap = height / 4, height / 24, height / 48
    offset = radius + height / 12 + (3 * bar + 2 * gap) / 2
    def polygon(x, y, nx, ny, left, right, radial):
        tx, ty = -ny, nx
        return [(x + tx * t + nx * r, y + ty * t + ny * r)
                for t, r in ((left, radial - bar / 2), (right, radial - bar / 2),
                             (right, radial + bar / 2), (left, radial + bar / 2))]
    # Geon, Gam, Ri, Gon at upper-left/right and lower-left/right.
    for sx, sy, pattern in ((-1,-1,(False,False,False)), (1,-1,(True,False,True)),
                            (-1,1,(False,True,False)), (1,1,(True,True,True))):
        nx, ny = sx * dx, sy * dy
        x, y = cx + nx * offset, cy + ny * offset
        for index, broken in enumerate(pattern):
            radial = (index - 1) * (bar + gap)
            segments = ((-length/2,-bar/2),(bar/2,length/2)) if broken else ((-length/2,length/2),)
            for left, right in segments:
                draw.polygon(polygon(x,y,nx,ny,left,right,radial), fill="black")

@lru_cache(maxsize=2)
def _flag_png(country):
    width, height = (152, 80) if country == "us" else (120, 80)
    image = Image.new("RGB", (width * _SCALE, height * _SCALE), "white")
    draw = ImageDraw.Draw(image)
    (_draw_us if country == "us" else _draw_kr)(draw, width * _SCALE, height * _SCALE)
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    original = output.getvalue()
    # Lossless PNG filtering/compression changes no drawn flag pixels.
    from zopfli.png import optimize
    packed = optimize(original, lossy_transparent=False, lossy_8bit=False,
                      filter_strategies="01234mepb", num_iterations=15,
                      num_iterations_large=5)
    if Image.open(io.BytesIO(packed)).convert("RGB").tobytes() != image.tobytes():
        raise RuntimeError("Lossless flag compression changed pixels")
    return packed if len(packed) < len(original) else original

def flag_images():
    return {"us": _flag_png("us"), "kr": _flag_png("kr")}

def flag_html(market):
    country = "us" if str(market).upper() in ("US", "USD") else "kr"
    cid = "u" if country == "us" else "k"
    height, label = (16, "성조기") if country == "us" else (20, "태극기")
    return (f'<img src="cid:{cid}" width="30" height="{height}" alt="{label}" '
            'style="vertical-align:middle;margin-right:6px;border:1px solid #e2e8f0">')

def inline_flag_sources(html):
    encoded = {country: base64.b64encode(png).decode("ascii") for country,png in flag_images().items()}
    pattern = r"""\bsrc\s*=\s*(?:["']cid:(u|k|ath-flag-us|ath-flag-kr)["']|cid:(u|k)(?=[\s/>]))"""
    def replace(match):
        cid = match.group(1) or match.group(2)
        country = "us" if cid in ("u", "ath-flag-us") else "kr"
        return 'src="data:image/png;base64,' + encoded[country] + '"'
    return re.sub(pattern, replace, html)
