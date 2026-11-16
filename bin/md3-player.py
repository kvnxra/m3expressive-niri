#!/usr/bin/env python3
"""md3-player — мини-плеер Material 3 Expressive для waybar.

GTK4 + gtk4-layer-shell. Процесс живёт в фоне и почти ничего не потребляет: пока окно скрыто,
таймеров нет. Клик по чипу в waybar шлёт SIGUSR1 — окно показывается/скрывается мгновенно.
Данные берутся из playerctl в фоновых потоках, интерфейс никогда на них не ждёт.
Без blur и теней. Цвета: ~/.config/md3/colors.json (генерирует `md3`). Лог: ~/.cache/md3/player.log
MD3_PLAYER_RESIDENT=0 — закрывать процесс вместе с окном (медленнее открывается, зато ничего не висит).
"""
import base64
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
CACHE_ROOT = os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache"))
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "md3-player.pid")
COLORS_JSON = os.path.join(CONFIG, "md3", "colors.json")
ART_DIR = os.path.join(CACHE_ROOT, "md3", "art")
LOG_FILE = os.path.join(CACHE_ROOT, "md3", "player.log")
RESIDENT = os.environ.get("MD3_PLAYER_RESIDENT", "1") != "0"

CARD_WIDTH = 400
ART_SIZE = 128
SEEK_PAD = 10
WAVE_LEN = 28.0
WAVE_AMP = 3.0

# Material Symbols Rounded (codepoints)
I_PLAY, I_PAUSE = "\ue037", "\ue034"
I_PREV, I_NEXT = "\ue045", "\ue044"
I_SHUFFLE, I_REPEAT, I_REPEAT_ONE = "\ue043", "\ue040", "\ue041"
I_NOTE, I_SWAP = "\ue405", "\ue8d4"

FMT = "\t".join([
    "{{status}}", "{{playerInstance}}", "{{title}}", "{{artist}}",
    "{{mpris:artUrl}}", "{{xesam:url}}", "{{mpris:length}}", "{{position}}",
])

NAMES = {
    "plasma-browser-integration": "Браузер", "firefox": "Firefox", "zen": "Zen", "chromium": "Chromium",
    "chrome": "Chrome", "brave": "Brave", "spotify": "Spotify", "mpv": "mpv", "vlc": "VLC",
    "vesktop": "Discord", "discord": "Discord", "telegram": "Telegram", "yandex-music": "Яндекс Музыка",
}

# M3 baseline (dark, tonal spot, seed #6750A4) — запасная палитра, если colors.json ещё нет
DEFAULT_COLORS = {
    "primary": "#D0BCFF", "on_primary": "#381E72",
    "primary_container": "#4F378B", "on_primary_container": "#EADDFF",
    "secondary_container": "#4A4458", "on_secondary_container": "#E8DEF8",
    "surface": "#141218", "surface_container_low": "#1D1B20", "surface_container": "#211F26",
    "surface_container_high": "#2B2930", "surface_container_highest": "#36343B",
    "on_surface": "#E6E0E9", "on_surface_variant": "#CAC4D0",
    "outline": "#938F99", "outline_variant": "#49454F", "error": "#F2B8B5",
    "tertiary": "#EFB8C8", "tertiary_container": "#633B48", "on_tertiary_container": "#FFD8E4",
}

CSS = """
window.md3 { background: transparent; box-shadow: none; }

.card {
  background-color: @@surface_container_high@@;
  color: @@on_surface@@;
  border-radius: 28px;
  padding: 20px;
}

.icon { font-family: "Material Symbols Rounded"; font-size: 24px; font-variation-settings: "FILL" 1; }

.art-ph { font-size: 52px; color: @@on_tertiary_container@@; }

.title {
  font-family: "Google Sans Flex", "Google Sans", sans-serif;
  font-size: 24px; font-weight: 700;
  font-variation-settings: "ROND" 100;
  color: @@on_surface@@;
}

.chip {
  font-family: "Google Sans Flex", "Google Sans", sans-serif;
  font-size: 13px; font-weight: 600;
  font-variation-settings: "ROND" 100;
  background-color: @@tertiary_container@@;
  color: @@on_tertiary_container@@;
  border-radius: 14px;
  padding: 3px 12px;
}

.time {
  font-family: "Google Sans Flex", "Google Sans", sans-serif;
  font-size: 12px; font-weight: 600;
  font-variation-settings: "ROND" 100;
  background-color: @@surface_container_highest@@;
  color: @@on_surface@@;
  border-radius: 10px;
  padding: 2px 10px;
}

.caption { font-family: "Google Sans Flex", "Google Sans", sans-serif; font-size: 13px; font-weight: 600; font-variation-settings: "ROND" 100; }

button.m3 {
  all: unset;
  min-width: 72px; min-height: 56px;
  border-radius: 20px;
  background-color: @@secondary_container@@;
  color: @@on_secondary_container@@;
}
button.m3:hover { background-color: @@secondary_container_h@@; }
button.m3:active { background-color: @@secondary_container_p@@; border-radius: 14px; }
button.m3 .icon { font-size: 28px; }
button.m3:disabled { opacity: 0.38; }

button.play {
  min-width: 112px;
  border-radius: 28px;
  background-color: @@primary@@;
  color: @@on_primary@@;
}
button.play:hover { background-color: @@primary_h@@; }
button.play:active { background-color: @@primary_p@@; border-radius: 16px; }
button.play .icon { font-size: 34px; }
button.play.playing { border-radius: 20px; }

/* connected button group: внешние углы круглые, внутренние — маленькие */
button.tog {
  all: unset;
  min-width: 48px; min-height: 40px;
  background-color: @@surface_container_highest@@;
  color: @@on_surface_variant@@;
  border-radius: 6px;
}
button.tog:first-child { border-radius: 20px 6px 6px 20px; }
button.tog:last-child { border-radius: 6px 20px 20px 6px; }
button.tog .icon { font-size: 22px; }
button.tog:hover { background-color: @@surface_container_highest_h@@; }
button.tog:active { border-radius: 10px; }
button.tog.on { background-color: @@secondary_container@@; color: @@on_secondary_container@@; }
button.tog.on:hover { background-color: @@secondary_container_h@@; }
button.tog:disabled { opacity: 0.38; }

/* источник (какое приложение управляется) */
button.src {
  all: unset;
  min-height: 40px;
  padding: 0 16px;
  border-radius: 20px;
  background-color: @@surface_container_highest@@;
  color: @@on_surface@@;
}
button.src:hover { background-color: @@surface_container_highest_h@@; }
button.src:active { border-radius: 12px; }
button.src.pinned { background-color: @@secondary_container@@; color: @@on_secondary_container@@; }
button.src.pinned:hover { background-color: @@secondary_container_h@@; }
button.src:disabled { opacity: 1; }
button.src .icon { font-size: 20px; }
"""


# ---------------------------------------------------------------- чистые функции
def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def trim_log(max_bytes=100000):
    try:
        if os.path.getsize(LOG_FILE) > max_bytes:
            with open(LOG_FILE, "rb") as f:
                f.seek(-max_bytes // 2, os.SEEK_END)
                tail = f.read()
            with open(LOG_FILE, "wb") as f:
                f.write(tail)
    except OSError:
        pass


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(t):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in t)


def mix(a, b, t):
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def fmt_time(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def to_seconds(us):
    try:
        return max(0.0, float(us) / 1e6)
    except (TypeError, ValueError):
        return 0.0


def friendly(inst):
    base = (inst or "").split(".")[0]
    return NAMES.get(base, base[:1].upper() + base[1:])


def parse_line(line):
    """status, instance, title, artist, artUrl, url, length(us), position(us) через табуляцию."""
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 8:
        return None
    middle = parts[2:-4]
    art, url, length, pos = parts[-4:]
    return {
        "status": parts[0],
        "inst": parts[1],
        "title": middle[0] if middle else "",
        "artist": "\t".join(middle[1:]),
        "art": art.strip(),
        "url": url.strip(),
        "length": to_seconds(length),
        "pos": to_seconds(pos),
    }


def parse_players(text):
    return [p for p in (parse_line(l) for l in text.splitlines()) if p]


def choose_player(players, pinned=None):
    if not players:
        return None
    if pinned:
        for p in players:
            if p["inst"] == pinned:
                return p
    for p in players:
        if p["status"] == "Playing":
            return p
    return players[0]


_YT = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def youtube_thumbs(url):
    m = _YT.search(url or "")
    if not m:
        return []
    vid = m.group(1)
    return ["https://i.ytimg.com/vi/%s/maxresdefault.jpg" % vid,
            "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid]


def art_candidates(art, url):
    """Обложка от плеера, а если её нет или не загрузилась — миниатюра YouTube по адресу страницы."""
    out = [art] if art else []
    for t in youtube_thumbs(url):
        if t not in out:
            out.append(t)
    return out


def fix_ytimg(url):
    if "ytimg.com/vi_webp/" in url:
        url = url.replace("/vi_webp/", "/vi/")
    if "ytimg.com/" in url and url.endswith(".webp"):
        url = url[:-5] + ".jpg"
    return url


def cache_path(url):
    os.makedirs(ART_DIR, exist_ok=True)
    return os.path.join(ART_DIR, hashlib.sha1(url.encode()).hexdigest())


def resolve_art(url):
    """Локальный путь к картинке для file:/data:/http(s):/абсолютного пути, либо None."""
    url = fix_ytimg(url.strip())
    if url.startswith("/"):
        return url if os.path.isfile(url) else None
    u = urllib.parse.urlparse(url)
    if u.scheme == "file":
        p = urllib.parse.unquote(u.path)
        return p if os.path.isfile(p) else None
    if u.scheme == "data":
        try:
            head, _, payload = url[5:].partition(",")
            raw = base64.b64decode(payload) if ";base64" in head else urllib.parse.unquote_to_bytes(payload)
        except ValueError:
            return None
        path = cache_path(url)
        with open(path, "wb") as f:
            f.write(raw)
        return path
    if u.scheme in ("http", "https"):
        path = cache_path(url)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 md3-player"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = r.read(8 * 1024 * 1024)
            if not data:
                return None
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
            return path
        except Exception as e:  # сеть, 404, таймаут
            log("art download failed: %s (%s)" % (url, e))
            return None
    return None


def load_colors():
    c = dict(DEFAULT_COLORS)
    try:
        with open(COLORS_JSON) as f:
            data = json.load(f)
        c.update({k: v for k, v in data.items() if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)})
    except (OSError, ValueError):
        pass
    # state layers по MD3: hover 8 %, pressed 10 %
    for name, on in (
        ("surface_container_highest", "on_surface"),
        ("primary", "on_primary"),
        ("secondary_container", "on_secondary_container"),
    ):
        c[name + "_h"] = mix(c[name], c[on], 0.08)
        c[name + "_p"] = mix(c[name], c[on], 0.10)
    return c


def build_css(colors):
    return re.sub(r"@@(\w+)@@", lambda m: colors[m.group(1)], CSS)


def running_pid():
    """PID уже запущенного плеера или None."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            if b"md3-player" not in f.read():
                return None
        return pid
    except (OSError, ValueError):
        return None


def clean_env():
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)  # не тащим layer-shell в каждый playerctl
    return env


def playerctl(*args, timeout=2.0):
    try:
        out = subprocess.run(["playerctl", *args], capture_output=True, text=True,
                             timeout=timeout, env=clean_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def shape_points(w, h, t, lobes=9, steps=200):
    """Контур обложки в полярных координатах. t=0 — скруглённый квадрат (суперэллипс), t=1 — «cookie» с лепестками.
    Между ними — плавное превращение (shape morph из M3 Expressive)."""
    cx, cy = w / 2.0, h / 2.0
    radius = min(w, h) / 2.0 - 1.0
    pts = []
    for i in range(steps):
        th = 2 * math.pi * i / steps
        c, s = math.cos(th), math.sin(th)
        r_sq = radius / ((abs(c) ** 4 + abs(s) ** 4) ** 0.25)
        r_ck = radius * (0.935 + 0.065 * math.cos(lobes * th))
        r = r_sq * (1 - t) + r_ck * t
        pts.append((cx + r * c, cy + r * s))
    return pts


# ---------------------------------------------------------------- GTK
Gtk = Gdk = GLib = Gio = Pango = LayerShell = cairo = Graphene = Gsk = None


def load_gtk():
    global Gtk, Gdk, GLib, Gio, Pango, LayerShell, cairo, Graphene, Gsk
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gsk", "4.0")
    gi.require_version("Graphene", "1.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk as _Gdk, Gio as _Gio, GLib as _GLib, Gtk as _Gtk, Pango as _Pango
    from gi.repository import Graphene as _Graphene, Gsk as _Gsk
    from gi.repository import Gtk4LayerShell as _LayerShell
    import cairo as _cairo
    Gtk, Gdk, GLib, Gio, Pango, LayerShell, cairo = _Gtk, _Gdk, _GLib, _Gio, _Pango, _LayerShell, _cairo
    Graphene, Gsk = _Graphene, _Gsk


def make_art_class():
    """Виджет обложки: рисует картинку внутри произвольной формы (маска по альфе, всё на GPU)."""
    class ArtWidget(Gtk.Widget):
        __gtype_name__ = "Md3Art"

        def __init__(self, size, fill_hex):
            super().__init__()
            self.size = size
            self.texture = None
            self.morph = 0.0
            self.target = 0.0
            self.fill = Gdk.RGBA()
            self.set_fill(fill_hex)
            self.set_size_request(size, size)
            self.set_halign(Gtk.Align.START)
            self.set_valign(Gtk.Align.START)

        def set_fill(self, hex_color):
            self.fill.parse(hex_color)
            self.queue_draw()

        def set_texture(self, texture):
            self.texture = texture
            self.queue_draw()

        def step(self):
            """Шаг анимации превращения формы; вызывается из tick()."""
            diff = self.target - self.morph
            if abs(diff) < 0.01:
                if diff != 0:
                    self.morph = self.target
                    self.queue_draw()
                return
            self.morph += diff * 0.35
            self.queue_draw()

        def do_measure(self, orientation, for_size):
            return (self.size, self.size, -1, -1)

        def do_snapshot(self, snapshot):
            w, h = self.get_width(), self.get_height()
            if w <= 0 or h <= 0:
                return
            rect = Graphene.Rect().init(0, 0, w, h)
            snapshot.push_mask(Gsk.MaskMode.ALPHA)
            cr = snapshot.append_cairo(rect)
            pts = shape_points(w, h, self.morph)
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.close_path()
            cr.set_source_rgba(0, 0, 0, 1)
            cr.fill()
            snapshot.pop()
            if self.texture is not None:
                iw, ih = self.texture.get_width(), self.texture.get_height()
                scale = max(w / iw, h / ih)          # cover: заполнить форму целиком
                dw, dh = iw * scale, ih * scale
                snapshot.save()
                snapshot.translate(Graphene.Point().init((w - dw) / 2.0, (h - dh) / 2.0))
                self.texture.snapshot(snapshot, dw, dh)
                snapshot.restore()
            else:
                snapshot.append_color(self.fill, rect)
            snapshot.pop()

    return ArtWidget


class Ui:
    def __init__(self, app, colors):
        self.app = app
        self.provider = None
        self.colors_mtime = self.mtime()
        self.rgb = {}
        self.install_theme(colors)

        self.visible = False
        self.t_poll = 0
        self.t_tick = 0
        self.close_id = 0

        self.inst = None
        self.pinned = None          # None = авто (играющий), иначе instance выбранного плеера
        self.players = []
        self.last = None
        self.playing = False
        self.length = 0.0
        self.base_pos = 0.0
        self.base_t = time.monotonic()
        self.phase = 0.0
        self.dragging = False
        self.drag_frac = 0.0
        self.drag_x0 = 0.0
        self.inside = False
        self.art_key = None
        self.art_gen = 0
        self.shuffle_on = False
        self.loop = "None"
        self.modes_dirty = True
        self.busy = False
        self.again = False
        self.last_sec = -1

        self.build()
        self.apply_idle()

    # ------------------------------------------------------------ тема
    @staticmethod
    def mtime():
        try:
            return os.path.getmtime(COLORS_JSON)
        except OSError:
            return 0

    def install_theme(self, colors):
        display = Gdk.Display.get_default()
        if self.provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self.provider)
        self.provider = Gtk.CssProvider()
        css = build_css(colors)
        if hasattr(self.provider, "load_from_string"):
            self.provider.load_from_string(css)
        else:
            self.provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(display, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.colors = colors
        self.rgb = {k: tuple(x / 255 for x in hex_rgb(v)) for k, v in colors.items()}
        if getattr(self, "art", None) is not None:
            self.art.set_fill(colors["tertiary_container"])

    def maybe_reload_theme(self):
        m = self.mtime()
        if m != self.colors_mtime:
            self.colors_mtime = m
            self.install_theme(load_colors())

    # ------------------------------------------------------------ построение
    def icon(self, ch, *classes):
        lab = Gtk.Label(label=ch)
        lab.add_css_class("icon")
        for k in classes:
            lab.add_css_class(k)
        return lab

    def button(self, ch, classes, cb):
        btn = Gtk.Button()
        lab = self.icon(ch)
        btn.set_child(lab)
        btn.set_focusable(False)
        for k in classes:
            btn.add_css_class(k)
        btn.connect("clicked", cb)
        return btn, lab

    def build(self):
        win = Gtk.ApplicationWindow(application=self.app)
        win.add_css_class("md3")
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_default_size(CARD_WIDTH, 1)
        self.win = win

        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "md3-player")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(win, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(win, LayerShell.Edge.RIGHT, True)
        LayerShell.set_margin(win, LayerShell.Edge.TOP, 56)    # под баром: 8 + 40 + 8
        LayerShell.set_margin(win, LayerShell.Edge.RIGHT, 12)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.ON_DEMAND)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("card")
        card.set_size_request(CARD_WIDTH, -1)

        # --- верх: обложка + название + исполнитель
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        self.art = make_art_class()(ART_SIZE, self.colors["tertiary_container"])
        self.art_ph = self.icon(I_NOTE, "art-ph")
        self.art_ph.set_halign(Gtk.Align.CENTER)
        self.art_ph.set_valign(Gtk.Align.CENTER)
        art_box = Gtk.Overlay()
        art_box.set_child(self.art)
        art_box.add_overlay(self.art_ph)
        art_box.set_valign(Gtk.Align.START)
        top.append(art_box)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("title")
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.set_max_width_chars(13)
        self.title.set_halign(Gtk.Align.START)
        self.artist = Gtk.Label(xalign=0)
        self.artist.add_css_class("chip")
        self.artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist.set_max_width_chars(24)
        self.artist.set_halign(Gtk.Align.START)
        texts.append(self.title)
        texts.append(self.artist)
        top.append(texts)
        card.append(top)

        # --- волнистый seekbar + время
        self.seek = Gtk.DrawingArea()
        self.seek.set_content_height(28)
        self.seek.set_hexpand(True)
        self.seek.set_draw_func(self.draw_seek, None)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.seek.add_controller(drag)
        card.append(self.seek)

        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.cur = Gtk.Label(label="0:00")
        self.cur.add_css_class("time")
        self.cur.set_hexpand(True)
        self.cur.set_halign(Gtk.Align.START)
        self.total = Gtk.Label(label="0:00")
        self.total.add_css_class("time")
        self.total.set_halign(Gtk.Align.END)
        times.append(self.cur)
        times.append(self.total)
        card.append(times)

        # --- управление
        ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ctrl.set_halign(Gtk.Align.CENTER)
        self.btn_prev, _ = self.button(I_PREV, ["m3"], lambda *_: self.act("previous"))
        self.btn_play, self.play_lab = self.button(I_PLAY, ["m3", "play"], lambda *_: self.act("play-pause"))
        self.btn_next, _ = self.button(I_NEXT, ["m3"], lambda *_: self.act("next"))
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            ctrl.append(b)
        card.append(ctrl)

        # --- низ: shuffle | repeat (connected group) и источник
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        seg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        seg.set_halign(Gtk.Align.START)
        self.btn_shuffle, _ = self.button(I_SHUFFLE, ["tog"], self.on_shuffle)
        self.btn_repeat, self.repeat_lab = self.button(I_REPEAT, ["tog"], self.on_repeat)
        seg.append(self.btn_shuffle)
        seg.append(self.btn_repeat)
        foot.append(seg)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        foot.append(spacer)

        self.src_btn = Gtk.Button()
        self.src_btn.add_css_class("src")
        self.src_btn.set_focusable(False)
        src_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.src_name = Gtk.Label(label="")
        self.src_name.add_css_class("caption")
        self.src_icon = self.icon(I_SWAP)
        src_box.append(self.src_name)
        src_box.append(self.src_icon)
        self.src_btn.set_child(src_box)
        self.src_btn.connect("clicked", self.on_source)
        foot.append(self.src_btn)
        card.append(foot)

        self.controls = [self.btn_prev, self.btn_play, self.btn_next, self.btn_shuffle, self.btn_repeat, self.seek]

        # --- закрытие: Esc, уход курсора, повторный клик по чипу в баре
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self.on_key)
        win.add_controller(key)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_enter)
        motion.connect("leave", self.on_leave)
        card.add_controller(motion)

        win.set_child(card)

    # ------------------------------------------------------------ показ / скрытие
    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def show(self):
        if self.visible:
            return
        self.visible = True
        self.maybe_reload_theme()
        if self.last:
            self.apply(self.last, None)     # мгновенно показать то, что видели в прошлый раз
        self.win.present()
        self.refresh()                      # актуальные данные придут из фонового потока
        self.t_poll = GLib.timeout_add_seconds(1, self.on_poll)
        self.t_tick = GLib.timeout_add(66, self.tick)
        self.arm_close(3000)                # если курсор так и не зашёл в окно — скрыться

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.cancel_close()
        for attr in ("t_poll", "t_tick"):
            sid = getattr(self, attr)
            if sid:
                GLib.source_remove(sid)
                setattr(self, attr, 0)
        self.dragging = False
        self.inside = False
        self.win.set_visible(False)
        if not RESIDENT:
            self.app.quit()

    def arm_close(self, ms):
        self.cancel_close()
        self.close_id = GLib.timeout_add(ms, self.close_cb)

    def cancel_close(self):
        if self.close_id:
            GLib.source_remove(self.close_id)
            self.close_id = 0

    def close_cb(self):
        self.close_id = 0
        self.hide()
        return False

    def on_enter(self, _ctrl, _x, _y):
        self.inside = True
        self.cancel_close()

    def on_leave(self, _ctrl):
        self.inside = False
        if not self.dragging:
            self.arm_close(450)

    def on_key(self, _ctrl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    # ------------------------------------------------------------ данные (фоновые потоки)
    def refresh(self):
        if self.busy:
            self.again = True
            return
        self.busy = True
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        players, chosen, modes = [], None, None
        try:
            out = playerctl("-a", "metadata", "--format", FMT)
            players = parse_players(out) if out else []
            chosen = choose_player(players, self.pinned)
            if chosen and (self.modes_dirty or chosen["inst"] != self.inst):
                modes = (playerctl("-p", chosen["inst"], "shuffle") or "",
                         playerctl("-p", chosen["inst"], "loop") or "")
        except Exception as e:
            log("refresh failed: %r" % e)
        GLib.idle_add(self.on_refreshed, players, chosen, modes)

    def on_refreshed(self, players, chosen, modes):
        self.busy = False
        self.players = players
        if self.pinned and not any(p["inst"] == self.pinned for p in players):
            self.pinned = None
            chosen = choose_player(players, None)
        if self.visible:
            if chosen is None:
                self.apply_idle()
            else:
                self.apply(chosen, modes)
        if self.again:
            self.again = False
            self.refresh()
        return False

    def on_poll(self):
        self.refresh()
        return True

    def refresh_once(self):
        self.refresh()
        return False

    # ------------------------------------------------------------ отображение состояния
    def set_class(self, widget, name, on):
        if on:
            widget.add_css_class(name)
        else:
            widget.remove_css_class(name)

    def apply_idle(self):
        self.inst = None
        self.playing = False
        self.length = 0.0
        self.base_pos = 0.0
        self.last = None
        self.title.set_text("Ничего не играет")
        self.artist.set_visible(False)
        self.play_lab.set_text(I_PLAY)
        self.set_class(self.btn_play, "playing", False)
        for w in self.controls:
            w.set_sensitive(False)
        self.src_btn.set_visible(False)
        self.set_art([])
        self.art.target = 0.0
        self.seek.queue_draw()

    def apply(self, p, modes):
        self.last = p
        self.inst = p["inst"]
        self.playing = p["status"] == "Playing"
        self.length = p["length"]
        if not self.dragging:
            self.base_pos = p["pos"]
            self.base_t = time.monotonic()
        self.title.set_text(p["title"] or "Без названия")
        self.artist.set_text(p["artist"])
        self.artist.set_visible(bool(p["artist"]))
        self.play_lab.set_text(I_PAUSE if self.playing else I_PLAY)
        self.set_class(self.btn_play, "playing", self.playing)
        self.art.target = 1.0 if self.playing else 0.0
        for w in self.controls:
            w.set_sensitive(True)
        self.seek.set_sensitive(self.length > 0)
        self.set_art(art_candidates(p["art"], p["url"]))
        if modes is not None:
            self.shuffle_on = modes[0].strip().lower() == "on"
            self.loop = modes[1].strip() or "None"
            self.modes_dirty = False
        self.set_class(self.btn_shuffle, "on", self.shuffle_on)
        self.set_class(self.btn_repeat, "on", self.loop != "None")
        self.repeat_lab.set_text(I_REPEAT_ONE if self.loop == "Track" else I_REPEAT)

        many = len(self.players) > 1
        self.src_btn.set_visible(True)
        self.src_name.set_text(friendly(p["inst"]))
        self.src_icon.set_visible(many)
        self.src_btn.set_sensitive(many)
        self.set_class(self.src_btn, "pinned", self.pinned is not None)

    # ------------------------------------------------------------ действия
    def act(self, *args):
        if not self.inst:
            return
        try:
            subprocess.Popen(["playerctl", "-p", self.inst, *args], env=clean_env(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return
        GLib.timeout_add(200, self.refresh_once)

    def on_shuffle(self, *_):
        self.act("shuffle", "Toggle")
        self.modes_dirty = True

    def on_repeat(self, *_):
        nxt = {"None": "Playlist", "Playlist": "Track", "Track": "None"}.get(self.loop, "None")
        self.act("loop", nxt)
        self.modes_dirty = True

    def on_source(self, *_):
        """Авто → плеер 1 → плеер 2 → … → авто."""
        insts = [p["inst"] for p in self.players]
        if len(insts) < 2:
            return
        cycle = [None] + insts
        cur = self.pinned if self.pinned in insts else None
        self.pinned = cycle[(cycle.index(cur) + 1) % len(cycle)]
        self.modes_dirty = True
        self.refresh()

    # ------------------------------------------------------------ seekbar
    def position(self):
        if self.dragging:
            return self.drag_frac * self.length
        pos = self.base_pos + ((time.monotonic() - self.base_t) if self.playing else 0.0)
        return min(pos, self.length) if self.length > 0 else pos

    def frac_at(self, x):
        span = max(1.0, self.seek.get_width() - 2 * SEEK_PAD)
        return min(1.0, max(0.0, (x - SEEK_PAD) / span))

    def on_drag_begin(self, _g, x, _y):
        self.dragging = True
        self.drag_x0 = x
        self.drag_frac = self.frac_at(x)
        self.cancel_close()
        self.seek.queue_draw()

    def on_drag_update(self, _g, dx, _dy):
        self.drag_frac = self.frac_at(self.drag_x0 + dx)
        self.seek.queue_draw()

    def on_drag_end(self, _g, dx, _dy):
        self.drag_frac = self.frac_at(self.drag_x0 + dx)
        self.dragging = False
        if self.length > 0 and self.inst:
            seconds = self.drag_frac * self.length
            self.act("position", "%.2f" % seconds)
            self.base_pos = seconds
            self.base_t = time.monotonic()
        if not self.inside:
            self.arm_close(450)

    def tick(self):
        self.art.step()
        animated = self.playing or self.dragging
        if animated:
            self.phase = (self.phase + 0.28) % (2 * math.pi)
        pos = self.position()
        sec = int(pos)
        if sec != self.last_sec:
            self.last_sec = sec
            self.cur.set_text(fmt_time(pos))
            self.total.set_text(fmt_time(self.length) if self.length > 0 else "–:–")
        if animated:
            self.seek.queue_draw()
        return True

    def draw_seek(self, _area, cr, w, h, _data=None):
        c = self.rgb
        mid = h / 2.0
        x0, x1 = SEEK_PAD, max(SEEK_PAD + 1, w - SEEK_PAD)
        frac = (self.position() / self.length) if self.length > 0 else 0.0
        frac = min(1.0, max(0.0, frac))
        xp = x0 + (x1 - x0) * frac
        amp = WAVE_AMP if (self.playing or self.dragging) else 0.0

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(4)

        # оставшаяся часть — прямая линия
        cr.set_source_rgb(*c["outline_variant"])
        cr.move_to(xp, mid)
        cr.line_to(x1, mid)
        cr.stroke()

        # пройденная часть — волна (выпрямляется на паузе)
        cr.set_source_rgb(*c["primary"])
        k = 2 * math.pi / WAVE_LEN
        x = x0
        cr.move_to(x0, mid + amp * math.sin(-self.phase))
        while x < xp:
            x = min(xp, x + 2.0)
            cr.line_to(x, mid + amp * math.sin((x - x0) * k - self.phase))
        cr.stroke()

        # ручка с зазором под цвет карточки
        cr.set_source_rgb(*c["surface_container_high"])
        cr.arc(xp, mid, 10, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*c["primary"])
        cr.arc(xp, mid, 6.5, 0, 2 * math.pi)
        cr.fill()
        if frac < 0.96:
            cr.arc(x1, mid, 2.5, 0, 2 * math.pi)
            cr.fill()

    # ------------------------------------------------------------ обложка: цепочка источников
    def set_art(self, cands):
        key = tuple(cands)
        if key == self.art_key:
            return
        self.art_key = key
        self.art_gen += 1
        self.art.set_texture(None)
        self.art_ph.set_visible(True)
        log("art candidates: %s" % (list(cands),))
        self.try_art(self.art_gen, list(cands))

    def try_art(self, gen, cands):
        if gen != self.art_gen or not cands:
            return
        threading.Thread(target=self.art_worker, args=(gen, cands[0], cands[1:]), daemon=True).start()

    def art_worker(self, gen, url, rest):
        path = None
        try:
            path = resolve_art(url)
        except Exception as e:
            log("art resolve failed: %s (%r)" % (url, e))
        GLib.idle_add(self.art_ready, gen, url, path, rest)

    def art_ready(self, gen, url, path, rest):
        if gen != self.art_gen:
            return False
        shown = False
        if path:
            try:
                self.art.set_texture(Gdk.Texture.new_from_filename(path))
                self.art_ph.set_visible(False)
                shown = True
                log("art shown: %s" % url)
            except Exception as e:  # формат не поддерживается / битый файл
                log("art decode failed: %s (%s)" % (url, e))
        if not shown:
            self.try_art(gen, rest)
        return False


def prune_cache(keep=40):
    try:
        files = sorted((os.path.join(ART_DIR, f) for f in os.listdir(ART_DIR)),
                       key=os.path.getmtime, reverse=True)
        for f in files[keep:]:
            os.remove(f)
    except OSError:
        pass


def main(argv):
    flags = set(argv[1:])
    pid = running_pid()
    if pid:  # уже запущен: показать/скрыть окно
        if "--daemon" not in flags:
            try:
                os.kill(pid, signal.SIGUSR1)
            except OSError:
                pass
        return 0

    signal.signal(signal.SIGUSR1, signal.SIG_IGN)  # пока не готовы — сигнал не должен убить процесс
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    def cleanup():
        try:
            os.remove(PIDFILE)
        except OSError:
            pass

    try:
        load_gtk()
    except (ImportError, ValueError) as e:
        cleanup()
        print("md3-player: не хватает зависимостей (%s)\n"
              "  sudo pacman -S --needed gtk4-layer-shell python-gobject python-cairo" % e, file=sys.stderr)
        log("missing deps: %s" % e)
        return 1

    trim_log()
    prune_cache()

    app = Gtk.Application(application_id="dev.md3.player", flags=Gio.ApplicationFlags.NON_UNIQUE)
    keep = []

    def on_activate(application):
        application.hold()
        ui = Ui(application, load_colors())
        keep.append(ui)
        if "--daemon" not in flags:
            ui.show()

    def on_toggle(_data=None):
        if keep:
            keep[0].toggle()
        return True

    def on_term(_data=None):
        app.quit()
        return False

    app.connect("activate", on_activate)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, on_toggle, None)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, on_term, None)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, on_term, None)
    try:
        return app.run(None)
    except Exception as e:
        log("fatal: %r" % e)
        raise
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
