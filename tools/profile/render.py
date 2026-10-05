#!/usr/bin/env python3
"""
Renders the terminal-console profile as a stack of SVG slices.

Every slice draws the two side rails; only the header draws the top edge and
only the footer draws the bottom edge. Stacked in the README with align="top",
they read as one continuous window.

Fonts are subset per image to only the characters that image uses, because
GitHub renders README images in a sandbox that blocks all external resources.
"""

import base64
import datetime
import io
import json
import os
import pathlib

from fontTools.subset import Subsetter, Options
from fontTools.ttLib import TTFont

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ASSETS = ROOT / "assets"
FONTS = HERE / "fonts"

CFG = json.loads((HERE / "config.json").read_text())
T = CFG["theme"]

W = 880                      # console width
ADV = 0.6                    # JetBrains Mono advance width, in em
PAD = 40                     # inner left/right padding

WEIGHTS = {400: "JetBrainsMono-Regular.ttf",
           700: "JetBrainsMono-Bold.ttf",
           800: "JetBrainsMono-ExtraBold.ttf"}
FAMILY = {400: "JBM", 700: "JBMb", 800: "JBMx"}

_font_cache = {}


def subset_font(weight, chars):
    """Return a base64 woff2 containing only `chars` at this weight."""
    key = (weight, "".join(sorted(chars)))
    if key in _font_cache:
        return _font_cache[key]

    font = TTFont(FONTS / WEIGHTS[weight])
    opts = Options()
    opts.flavor = "woff2"
    opts.desubroutinize = True
    opts.layout_features = []
    opts.name_IDs = []
    opts.notdef_outline = False
    sub = Subsetter(options=opts)
    sub.populate(text="".join(sorted(chars)))
    sub.subset(font)

    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    out = base64.b64encode(buf.getvalue()).decode()
    _font_cache[key] = out
    return out


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def tw(s, size, ls=0.0):
    """Exact rendered width of a monospace string."""
    n = len(s)
    return n * size * ADV + max(0, n - 1) * ls


class Canvas:
    def __init__(self, w, h, x_offset=0, top=False, bottom=False,
                 left_rail=True, right_rail=True, extra_css=""):
        self.w, self.h = w, h
        self.x_offset = x_offset
        self.top, self.bottom = top, bottom
        self.left_rail, self.right_rail = left_rail, right_rail
        self.extra_css = extra_css
        self.body = []
        self.chars = {400: set(), 700: set(), 800: set()}
        self._chrome()

    # ---------- drawing primitives ----------

    def raw(self, s):
        self.body.append(s)

    def rect(self, x, y, w, h, fill="none", stroke="none", r=0, sw=1, op=1):
        self.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"/>')

    def line(self, x1, y1, x2, y2, stroke, sw=1, op=1, cls=""):
        c = f' class="{cls}"' if cls else ""
        self.raw(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                 f'stroke-width="{sw}" opacity="{op}"{c}/>')

    def text(self, x, y, s, size=13, weight=400, fill=None, ls=0.0,
             anchor="start", op=1, cls=""):
        s = str(s)
        if not s:
            return x
        fill = fill or T["body"]
        self.chars[weight].update(s)
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        l = f' letter-spacing="{ls}"' if ls else ""
        self.raw(f'<text x="{x}" y="{y}" font-family="{FAMILY[weight]}, \'JetBrains Mono\', ui-monospace, monospace" '
                 f'font-size="{size}" fill="{fill}"{l}{a} '
                 f'xml:space="preserve"{c}>{esc(s)}</text>')
        return x + tw(s, size, ls)

    def prompt(self, x, y, cmd, size=13):
        """A `$ command` line with the sigil in the signal colour."""
        x = self.text(x, y, "$ ", size, 400, T["signal"])
        return self.text(x, y, cmd, size, 400, T["muted"])

    # ---------- window chrome ----------

    def _chrome(self):
        w, h = self.w, self.h
        self.rect(0, 0, w, h, fill=T["ink"])

        # faint 40px grid; offsets keep it continuous across every cut
        for gx in range(0, w + 1, 40):
            ax = gx - (self.x_offset % 40)
            if 0 <= ax <= w:
                self.line(ax + .5, 0, ax + .5, h, T["grid"], op=.38)
        for gy in range(0, h + 1, 40):
            self.line(0, gy + .5, w, gy + .5, T["grid"], op=.38)

        r = 6
        rails = []
        if self.top:
            rails.append(f'M .5 {h} L .5 {r+.5} Q .5 .5 {r+.5} .5 '
                         f'L {w-r-.5} .5 Q {w-.5} .5 {w-.5} {r+.5} L {w-.5} {h}')
        elif self.bottom:
            rails.append(f'M .5 0 L .5 {h-r-.5} Q .5 {h-.5} {r+.5} {h-.5} '
                         f'L {w-r-.5} {h-.5} Q {w-.5} {h-.5} {w-.5} {h-r-.5} L {w-.5} 0')
        else:
            # run past both cuts so the glow never fades at a seam
            if self.left_rail:
                rails.append(f'M .5 -30 L .5 {h+30}')
            if self.right_rail:
                rails.append(f'M {w-.5} -30 L {w-.5} {h+30}')

        for d in rails:
            self.raw(f'<path d="{d}" fill="none" stroke="{T["signal"]}" '
                     f'stroke-width="2.5" opacity=".30" filter="url(#glow)"/>')
            self.raw(f'<path d="{d}" fill="none" stroke="{T["rail"]}" stroke-width="1.25"/>')

    # ---------- output ----------

    def render(self):
        faces = []
        for wgt, used in self.chars.items():
            if not used:
                continue
            b64 = subset_font(wgt, used)
            faces.append(f"@font-face{{font-family:{FAMILY[wgt]};"
                         f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
        css = "".join(faces) + self.extra_css
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
            f'font-family="{FAMILY[400]}, ui-monospace, monospace">'
            f'<defs><filter id="glow" x="-200%" y="-200%" width="500%" height="500%">'
            f'<feGaussianBlur stdDeviation="3"/></filter></defs>'
            f'<style>{css}</style>'
            + "".join(self.body) + "</svg>"
        )


def write(name, canvas):
    ASSETS.mkdir(parents=True, exist_ok=True)
    p = ASSETS / name
    p.write_text(canvas.render())
    print(f"  {name:<24} {canvas.w}x{canvas.h}  {p.stat().st_size/1024:6.1f} KB")


# ---------------------------------------------------------------- slices

BLINK = ("@keyframes bl{0%,49%{opacity:1}50%,100%{opacity:0}}"
         ".cur{animation:bl 1.1s step-end infinite}")
PULSE = ("@keyframes pl{0%,100%{opacity:.35}50%{opacity:1}}"
         ".pulse{animation:pl 2.6s ease-in-out infinite}")


def header(stats):
    c = Canvas(W, 320, top=True, extra_css=BLINK + PULSE)

    # title bar
    c.raw(f'<path d="M .5 .5 L .5 6.5 Q .5 .5 6.5 .5 L {W-6.5} .5 '
          f'Q {W-.5} .5 {W-.5} 6.5 L {W-.5} 40 L .5 40 Z" fill="{T["panel"]}"/>')
    c.line(0, 40.5, W, 40.5, T["rail"])
    c.text(28, 25, CFG["node_label"], 11, 400, T["muted"], ls=.6)

    right = f'all systems healthy    {stats.get("synced", "—")}'
    c.text(W - 28, 25, right, 11, 400, T["muted"], anchor="end", ls=.6)
    dotx = W - 28 - tw(right, 11, .6) - 20
    c.raw(f'<circle cx="{dotx}" cy="21" r="3.5" fill="{T["signal"]}" class="pulse"/>')

    # whoami
    c.prompt(PAD, 88, "whoami")

    # name — the one loud element on the page
    name = CFG["name"].upper()
    c.line(PAD, 112, PAD, 178, T["signal"], sw=3, op=.9)
    c.text(PAD + 20, 166, name, 58, 800, T["bright"], ls=5)

    for i, ln in enumerate(CFG["intro"]):
        y = 214 + i * 24
        c.text(PAD + 20, y, ">", 13, 700, T["signal"], op=.5)
        c.text(PAD + 44, y, ln, 13, 400, T["body"])

    c.prompt(PAD, 300, "")
    c.raw(f'<rect x="{PAD + tw("$ ", 13)}" y="289" width="9" height="15" '
          f'fill="{T["signal"]}" class="cur"/>')
    return c


def links_head():
    c = Canvas(W, 80)
    c.prompt(PAD, 50, "cat ~/.contact")
    return c


def link_button(i, link, n):
    base = W // n
    bw = base if i < n - 1 else W - base * (n - 1)
    c = Canvas(bw, 120, x_offset=i * base,
               left_rail=(i == 0), right_rail=(i == n - 1))
    x0 = 14 if i == 0 else 6
    x1 = bw - (14 if i == n - 1 else 6)
    c.rect(x0, 14, x1 - x0, 84, fill=T["panel"], stroke=T["rail"], r=3)
    c.line(x0, 14.5, x0 + 26, 14.5, T["signal"], sw=2, op=.8)

    c.text(x0 + 18, 50, link["mark"], 13, 700, T["signal"])
    c.text(x0 + 46, 50, link["label"], 13, 700, T["bright"])
    c.text(x0 + 18, 74, link["handle"], 10.5, 400, T["muted"])
    return c


def stat_card(c, x, y, w, h, label, value, sub, accent):
    c.rect(x, y, w, h, fill=T["panel"], stroke=T["rail"], r=3)
    c.line(x, y + .5, x + 26, y + .5, accent, sw=2, op=.85)
    c.text(x + 18, y + 26, label, 10.5, 400, T["muted"], ls=.5)
    c.text(x + 18, y + 62, value, 27, 700, T["bright"])
    c.text(x + 18, y + 84, sub, 10.5, 400, T["muted"])


def stats_panel(s):
    c = Canvas(W, 200)
    c.prompt(PAD, 50, f'gh stats --user {CFG["github_user"]}')

    cards = [
        ("repositories",  f'{s["repos"]:,}',       "public, original",         T["signal"]),
        ("contributions", f'{s["this_year"]:,}',   f'{s["all_time"]:,} all time', T["signal"]),
        ("current streak", f'{s["streak"]}d',      f'longest {s["longest"]}d', T["amber"]),
    ]
    cw = (W - 2 * PAD - 2 * 16) / 3
    for i, (lab, val, sub, acc) in enumerate(cards):
        stat_card(c, PAD + i * (cw + 16), 72, cw, 100, lab, val, sub, acc)
    return c


def stack_panel():
    c = Canvas(W, 360, extra_css=PULSE)
    c.prompt(PAD, 50, "systemctl status stack")

    look = {
        "active":   (T["signal"], "active",   "running"),
        "starting": (T["amber"],  "starting", "learning"),
        "queued":   (T["muted"],  "queued",   "next up"),
    }
    for i, u in enumerate(CFG["stack"]):
        y = 92 + i * 34
        col, state, _ = look[u["state"]]
        if u["state"] == "active":
            c.raw(f'<circle cx="{PAD+6}" cy="{y-4}" r="4" fill="{col}"/>')
        elif u["state"] == "starting":
            c.raw(f'<circle cx="{PAD+6}" cy="{y-4}" r="4" fill="none" '
                  f'stroke="{col}" stroke-width="2" class="pulse"/>')
        else:
            c.raw(f'<circle cx="{PAD+6}" cy="{y-4}" r="4" fill="none" '
                  f'stroke="{col}" stroke-width="1.5" opacity=".7"/>')
        c.text(PAD + 24, y, u["unit"], 13, 400, T["bright"])
        c.text(PAD + 280, y, state, 12, 700, col)
        c.text(PAD + 380, y, u["detail"], 12, 400, T["muted"])
    return c


def footer(stats):
    c = Canvas(W, 80, bottom=True)
    c.line(0, .5, W, .5, T["rail"], op=.5)
    c.prompt(PAD, 46, "exit")
    c.text(W - PAD, 46, 'rebuilt nightly',
           11, 400, T["muted"], op=.65, anchor="end")
    return c


# ---------------------------------------------------------------- main

PLACEHOLDER = {
    "stars": 0, "this_year": 0, "all_time": 0, "prs": 0, "merged": 0,
    "streak": 0, "longest": 0, "followers": 0, "forks": 0, "repos": 0,
    "since": "—",
    "languages": [["Python", 42.0], ["Java", 23.5], ["TypeScript", 12.8],
                  ["HCL", 9.1], ["Shell", 7.4], ["Other", 5.2]],
}


def main():
    data = HERE / "data" / "stats.json"
    stats = dict(PLACEHOLDER)
    if data.exists():
        stats.update(json.loads(data.read_text()))
    stats.setdefault("synced", datetime.date.today().isoformat())

    print("rendering console slices:")
    write("header.svg", header(stats))
    write("links-head.svg", links_head())
    n = len(CFG["links"])
    for i, link in enumerate(CFG["links"]):
        write(f"link-{i+1}.svg", link_button(i, link, n))
    write("stats.svg", stats_panel(stats))
    write("stack.svg", stack_panel())
    write("footer.svg", footer(stats))
    print("done.")


if __name__ == "__main__":
    main()
