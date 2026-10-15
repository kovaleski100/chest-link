"""X11 navigation for the normal UI smoke; endpoint bytes remain the assertion.

Pixel checks synchronize navigation only. They never assert Pokemon contents.
All windows/storage belong to the isolated test run.
"""
import re
import subprocess
import time
from Xlib import display, X, XK
from Xlib.ext import xtest
from PIL import Image


class NormalUIDriver:
    def __init__(self, console, debug_dir=None):
        self.console = console
        self.debug_dir = debug_dir
        self.connection = display.Display()
        title = 'melonDS' if console == 'ds' else 'Azahar'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rows = [row for row in subprocess.check_output(['wmctrl', '-lp'], text=True).splitlines()
                    if title in row]
            if len(rows) == 1:
                self.window_id = rows[0].split()[0]
                self.window = self.connection.create_resource_object('window', int(self.window_id, 16))
                subprocess.run(['wmctrl', '-ia', self.window_id], check=True)
                return
            time.sleep(.1)
        raise RuntimeError('Cannot identify a unique isolated emulator window.')

    def image(self, screen):
        g = self.window.get_geometry()
        data = self.window.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xFFFFFFFF)
        image = Image.frombytes('RGB', (g.width, g.height), data.data, 'raw', 'BGRX')
        # Standard vertical layout selected by the lab profiles.
        height = (g.height - 22 - (30 if self.console == '3ds' else 0)) / 2
        width = height * ((400 if screen == 'top' and self.console == '3ds' else 320) / 240)
        x = (g.width - width) / 2
        y = 22 + (height if screen == 'bottom' else 0)
        rect = (round(x), round(y), round(x + width), round(y + height))
        return image.crop(rect).resize((400 if screen == 'top' and self.console == '3ds' else 320, 240))

    @staticmethod
    def white(image, rect):
        pixels = list(image.crop(rect).getdata())
        return sum(r > 215 and g > 215 and b > 190 for r, g, b in pixels) / len(pixels)

    def home(self):
        top = self.image('top')
        rect = (top.width // 2 - 40, 65, top.width // 2 + 40, 140)
        return sum(r > 180 and g > 150 and b < 100 for r, g, b in top.crop(rect).getdata()) > 30

    def bank(self):
        top = self.image('top')
        return self.white(top, (top.width - 100, 60, top.width - 10, 205)) > .5

    def dialog(self):
        return not self.bank() and self.white(self.image('bottom'), (35, 177, 140, 194)) > .30

    def digits(self):
        image = self.image('bottom')
        # The white strip above the glyphs identifies fields without counting
        # the individual strokes of the digits or the thin sprite borders.
        for y in range(82, 87):
            columns = [all(value > threshold for value, threshold in
                           zip(image.getpixel((x, y)), (215, 215, 190)))
                       for x in range(15, 306)]
            count = 0; span = 0
            for white in columns + [False]:
                if white:
                    span += 1
                else:
                    if span > 24: count += 1
                    span = 0
            if count in (4, 6): return count
        return 0

    def wait(self, predicate, name, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                print('Normal UI: ' + name, flush=True)
                return
            time.sleep(.15)
        if self.debug_dir:
            self.image('top').save(self.debug_dir / 'ui-top-failure.png')
            self.image('bottom').save(self.debug_dir / 'ui-bottom-failure.png')
        print('UI diagnostic: number fields=' + str(self.digits()) + ', dialog=' + str(self.dialog()), flush=True)
        raise TimeoutError('Normal UI navigation timed out: ' + name)

    def click(self, x, y):
        subprocess.run(['wmctrl', '-ia', self.window_id], check=True)
        info = subprocess.check_output(['xwininfo', '-id', self.window_id], text=True)
        px = int(re.search(r'Absolute upper-left X:\s+(-?\d+)', info).group(1))
        py = int(re.search(r'Absolute upper-left Y:\s+(-?\d+)', info).group(1))
        g = self.window.get_geometry()
        height = (g.height - 22 - (30 if self.console == '3ds' else 0)) / 2
        width = height * 320 / 240
        rx = px + (g.width - width) / 2 + x * width / 320
        ry = py + 22 + height + y * height / 240
        xtest.fake_input(self.connection, X.MotionNotify, root=self.connection.screen().root.id,
                        x=round(rx), y=round(ry))
        self.connection.sync()
        xtest.fake_input(self.connection, X.ButtonPress, detail=1)
        self.connection.sync(); time.sleep(.15)
        xtest.fake_input(self.connection, X.ButtonRelease, detail=1)
        self.connection.sync(); time.sleep(.25)

    def key(self, name):
        key = self.connection.keysym_to_keycode(XK.string_to_keysym(name))
        xtest.fake_input(self.connection, X.KeyPress, detail=key)
        self.connection.sync(); time.sleep(.12)
        xtest.fake_input(self.connection, X.KeyRelease, detail=key)
        self.connection.sync(); time.sleep(.25)

    def send_all_to_pc(self):
        self.wait(self.home, 'main menu')
        self.click(160, 15 + (2 if self.console == 'ds' else 1) * 24 + 12)
        self.wait(lambda: self.white(self.image('bottom'), (30, 44, 290, 54)) < .1,
                  'bank menu')
        self.click(160, 27)
        self.wait(self.bank, 'private FireRed bank')
        self.key('s' if self.console == 'ds' else 'z')
        self.click(266, 90)
        self.wait(self.dialog, 'transfer confirmation', timeout=45)
        self.click(80, 185)
        self.wait(lambda: self.dialog() and self.digits() == 4, 'configured PC IP')
        self.click(80, 185)
        self.wait(lambda: self.dialog() and self.digits() == 6, 'configured PC PIN')
        self.click(80, 185)
