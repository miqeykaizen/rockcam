#!/usr/bin/env python3
"""
RockCam v2 - Rock Pi 4C+ / IMX219
Custom-painted controls:
  * ModeSwitch   - round toggle switch, PHOTO on the left, VIDEO on the right
  * Knob         - rotary knob with a meter arc (drag up/down, wheel, arrow keys,
                   double-click to reset)
  * ShutterButton- circular button with a hexagonal aperture icon

!! Replace the CONFIG block values with the ones that work on YOUR board !!
"""
import sys
import math
import pathlib
import subprocess
import datetime
import time

import numpy as np
import cv2
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst
from PyQt5 import QtCore, QtGui, QtWidgets

# ----------------------------- CONFIG -----------------------------
VIDEO_DEV = "/dev/video0"           # your working capture node
SENSOR_SUBDEV = "/dev/v4l-subdev2"  # your imx219 subdev (exposure / gain)
W, H, FPS = 1280, 720, 30
OUT_DIR = pathlib.Path.home() / "Pictures" / "RockCam"
EXP_MIN, EXP_MAX = 4, 4095
GAIN_MIN, GAIN_MAX = 256, 4096      # 256 = 1.0x

# Keep the pipeline that works for you (format must be one your node lists)
PIPELINE = (
    f"v4l2src device={VIDEO_DEV} ! "
    f"video/x-raw,format=NV16,width={W},height={H} ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false"
)
# ------------------------------------------------------------------

# ----------------------------- THEME ------------------------------
BG = QtGui.QColor("#1b1d21")
PANEL = QtGui.QColor("#23262b")
TRACK = QtGui.QColor("#363b43")
BODY = QtGui.QColor("#2c3037")
BODY_EDGE = QtGui.QColor("#454b55")
TEXT = QtGui.QColor("#e8eaed")
DIM = QtGui.QColor("#7d8590")
ACCENT = QtGui.QColor("#ffb020")
REC = QtGui.QColor("#e5484d")
REC_DARK = QtGui.QColor("#a8262b")
# ------------------------------------------------------------------


def mix(a, b, t):
    return QtGui.QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def set_ctrl(name: str, value: int):
    print(f"set_ctrl: {name}={int(value)}", flush=True)
    subprocess.Popen(
        ["v4l2-ctl", "-d", SENSOR_SUBDEV, "--set-ctrl", f"{name}={int(value)}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )


def process(frame, zoom, warmth, sharp):
    """Digital zoom, warmth (R/B gain) and sharpness, all in software."""
    if zoom > 1.0:
        h, w = frame.shape[:2]
        ch, cw = int(h / zoom), int(w / zoom)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        frame = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (w, h),
                           interpolation=cv2.INTER_LINEAR)
    if warmth != 0:
        k = warmth / 100.0
        frame = cv2.multiply(frame, (1.0 - k, 1.0, 1.0 + k, 0), dtype=cv2.CV_8U)
    if sharp > 0:
        blur = cv2.GaussianBlur(frame, (0, 0), 2.0)
        frame = cv2.addWeighted(frame, 1.0 + sharp / 50.0, blur, -sharp / 50.0, 0)
    return frame


# =====================================================================
#  Custom widgets
# =====================================================================
class VideoWidget(QtWidgets.QWidget):
    """Paints the latest frame scaled to fill the widget, keeping aspect ratio."""

    def __init__(self):
        super().__init__()
        self.img = None
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)

    def set_image(self, img):
        self.img = img
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#0e0f11"))
        if self.img is None:
            p.setPen(DIM)
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "Waiting for camera...")
            return
        s = self.img.size().scaled(self.size(), QtCore.Qt.KeepAspectRatio)
        x = (self.width() - s.width()) // 2
        y = (self.height() - s.height()) // 2
        p.drawImage(QtCore.QRect(x, y, s.width(), s.height()), self.img)


class ModeSwitch(QtWidgets.QAbstractButton):
    """Round toggle switch: PHOTO (left) <-> VIDEO (right). checked = VIDEO."""

    def __init__(self, left="PHOTO", right="VIDEO"):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._left, self._right = left, right
        self._pos = 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QtCore.QEasingCurve.InOutQuad)
        self.toggled.connect(self._on_toggled)
        self.setFixedHeight(44)
        self.setMinimumWidth(230)

    def sizeHint(self):
        return QtCore.QSize(240, 44)

    def _get_pos(self):
        return self._pos

    def _set_pos(self, v):
        self._pos = v
        self.update()

    knobPos = QtCore.pyqtProperty(float, _get_pos, _set_pos)

    def _on_toggled(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tw, th = 58, 28
        tx, ty = (w - tw) / 2, (h - th) / 2
        t = self._pos

        # track
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(mix(ACCENT, REC, t))
        p.drawRoundedRect(QtCore.QRectF(tx, ty, tw, th), th / 2, th / 2)
        # round knob
        d = th - 6
        kx = tx + 3 + t * (tw - th)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QRectF(kx, ty + 3, d, d))

        # labels at both ends
        f = p.font()
        f.setBold(True)
        f.setPointSize(10)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(TEXT if t < 0.5 else DIM)
        p.drawText(QtCore.QRectF(0, 0, tx - 12, h),
                   QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, self._left)
        p.setPen(TEXT if t >= 0.5 else DIM)
        p.drawText(QtCore.QRectF(tx + tw + 12, 0, w - (tx + tw + 12), h),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self._right)


class Knob(QtWidgets.QAbstractSlider):
    """Rotary knob with a meter arc.

    Drag up/down, mouse wheel, arrow keys. Double-click resets to default.
    origin: value where the meter fill starts (e.g. 0 for a +/- control).
    """
    START, SWEEP = 225.0, 270.0   # degrees, Qt convention (CCW from 3 o'clock)

    def __init__(self, title, lo, hi, val, fmt=str, origin=None):
        super().__init__()
        self.setRange(lo, hi)
        self.setValue(val)
        self._title = title
        self._fmt = fmt
        self._default = val
        self._origin = lo if origin is None else origin
        self._drag = None
        span = hi - lo
        self.setSingleStep(max(1, span // 100))
        self.setPageStep(max(1, span // 10))
        self.setFixedSize(130, 146)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.valueChanged.connect(lambda _: self.update())

    def _frac(self, v):
        span = self.maximum() - self.minimum()
        return 0.0 if span <= 0 else (v - self.minimum()) / span

    # ---- input ----
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag = (e.y(), self.value())
            self.setFocus()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            y0, v0 = self._drag
            span = self.maximum() - self.minimum()
            self.setValue(int(v0 + (y0 - e.y()) * span / 200.0))

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.setValue(self._default)

    # ---- painting ----
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        cx, cy = self.width() / 2, 58

        # meter ring: grey track + coloured level
        ring = QtCore.QRectF(cx - 44, cy - 44, 88, 88)
        pen = QtGui.QPen(TRACK, 7, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, int(self.START * 16), int(-self.SWEEP * 16))

        a0 = self.START - self.SWEEP * self._frac(self._origin)
        a1 = self.START - self.SWEEP * self._frac(self.value())
        if abs(a1 - a0) > 0.1:
            pen.setColor(ACCENT)
            p.setPen(pen)
            p.drawArc(ring, int(a0 * 16), int((a1 - a0) * 16))

        # knob body
        grad = QtGui.QRadialGradient(cx - 8, cy - 10, 40)
        grad.setColorAt(0, QtGui.QColor("#3a3f48"))
        grad.setColorAt(1, BODY)
        p.setPen(QtGui.QPen(BODY_EDGE, 1.5))
        p.setBrush(grad)
        p.drawEllipse(QtCore.QPointF(cx, cy), 31, 31)

        # pointer
        ang = math.radians(a1)
        dx, dy = math.cos(ang), -math.sin(ang)
        p.setPen(QtGui.QPen(ACCENT, 3.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(cx + 11 * dx, cy + 11 * dy),
                   QtCore.QPointF(cx + 25 * dx, cy + 25 * dy))

        # focus hint
        if self.hasFocus():
            p.setPen(QtGui.QPen(mix(BG, ACCENT, 0.5), 1, QtCore.Qt.DotLine))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(cx, cy), 38, 38)

        # value + title
        f = p.font()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(TEXT)
        p.drawText(QtCore.QRectF(0, 107, self.width(), 18), QtCore.Qt.AlignCenter,
                   self._fmt(self.value()))
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(DIM)
        p.drawText(QtCore.QRectF(0, 125, self.width(), 18), QtCore.Qt.AlignCenter,
                   self._title)


def _hex_points(c, r, rot_deg):
    return [QtCore.QPointF(c.x() + r * math.cos(math.radians(60 * i + rot_deg)),
                           c.y() + r * math.sin(math.radians(60 * i + rot_deg)))
            for i in range(6)]


class ShutterButton(QtWidgets.QAbstractButton):
    """Circular capture / record button with a hexagonal aperture icon."""

    def __init__(self):
        super().__init__()
        self._video = False
        self._rec = False
        self.setFixedSize(100, 100)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def set_mode(self, video: bool):
        self._video = video
        self.update()

    def set_recording(self, rec: bool):
        self._rec = rec
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        down = self.isDown()

        # outer ring
        ring = REC if self._rec else QtGui.QColor("#f1f3f5")
        p.setPen(QtGui.QPen(ring, 4))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, 45, 45)

        # inner disc
        if self._rec:
            fill, icon, r = REC_DARK, QtGui.QColor("#ffffff"), 31
        elif self._video:
            fill, icon, r = REC, QtGui.QColor("#ffffff"), 35
        else:
            fill, icon, r = QtGui.QColor("#f1f3f5"), QtGui.QColor("#1b1d21"), 35
        if down:
            fill = mix(fill, QtGui.QColor("#000000"), 0.25)
            r -= 3
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(fill)
        p.drawEllipse(c, r, r)

        # hexagonal shutter icon: outer hexagon + pinwheel blades + inner hexagon
        s = r / 35.0
        outer = _hex_points(c, 21 * s, -90)
        inner = _hex_points(c, 9 * s, -60)
        pen = QtGui.QPen(icon, 2.4 * s, QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolygon(QtGui.QPolygonF(outer))
        p.drawPolygon(QtGui.QPolygonF(inner))
        for i in range(6):
            p.drawLine(outer[i], inner[i])
def make_icon_pixmap(size=256):
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(size / 128.0, size / 128.0)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(BG)
    p.drawRoundedRect(QtCore.QRectF(0, 0, 128, 128), 28, 28)
    c = QtCore.QPointF(64, 64)
    p.setPen(QtGui.QPen(ACCENT, 7))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(c, 46, 46)
    outer = _hex_points(c, 34, -90)
    inner = _hex_points(c, 15, -60)
    p.setPen(QtGui.QPen(QtGui.QColor("#f1f3f5"), 5, QtCore.Qt.SolidLine,
                        QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
    p.drawPolygon(QtGui.QPolygonF(outer))
    p.drawPolygon(QtGui.QPolygonF(inner))
    for i in range(6):
        p.drawLine(outer[i], inner[i])
    p.end()
    return pm

# =====================================================================
#  Main window
# =====================================================================
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockCam")
        self.resize(1200, 720)
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        self.writer = None
        self.rec_start = 0.0
        self.rec_frames = 0
        self.last_frame = None

        # ---- GStreamer ----
        Gst.init(None)
        self.pipeline = Gst.parse_launch(PIPELINE)
        self.sink = self.pipeline.get_by_name("sink")
        self.pipeline.set_state(Gst.State.PLAYING)

        # ---- widgets ----
        self.view = VideoWidget()

        self.mode_sw = ModeSwitch("PHOTO", "VIDEO")
        self.mode_sw.toggled.connect(self.on_mode)

        self.exp = Knob("Exposure", EXP_MIN, EXP_MAX, 1575)
        self.gain = Knob("Gain", GAIN_MIN, GAIN_MAX, GAIN_MIN,
                         fmt=lambda v: f"{v / 256:.1f}x")
        self.zoom = Knob("Zoom", 10, 40, 10, fmt=lambda v: f"{v / 10:.1f}x")
        self.warm = Knob("Warmth", -50, 50, 0, fmt=lambda v: f"{v:+d}", origin=0)
        self.focus = Knob("Sharpness", 0, 100, 0)  # software; V2 lens is fixed focus

        # debounced sensor updates (works for drag, wheel and keys)
        self.exp_timer = QtCore.QTimer(self, singleShot=True, interval=250)
        self.exp_timer.timeout.connect(self.apply_sensor)
        self.exp.valueChanged.connect(lambda _: self.exp_timer.start())
        self.gain.valueChanged.connect(lambda _: self.exp_timer.start())

        self.start_btn = ShutterButton()
        self.start_btn.clicked.connect(self.on_start)
        self.start_btn.setToolTip("Capture photo / start-stop recording")

        # ---- layout ----
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        grid.addWidget(self.exp, 0, 0, QtCore.Qt.AlignCenter)
        grid.addWidget(self.gain, 0, 1, QtCore.Qt.AlignCenter)
        grid.addWidget(self.zoom, 1, 0, QtCore.Qt.AlignCenter)
        grid.addWidget(self.warm, 1, 1, QtCore.Qt.AlignCenter)
        grid.addWidget(self.focus, 2, 0, 1, 2, QtCore.Qt.AlignCenter)

        hint = QtWidgets.QLabel("Drag knobs up/down  •  double-click to reset")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setStyleSheet("color:#7d8590;font-size:10px;")

        panel = QtWidgets.QVBoxLayout()
        panel.setContentsMargins(14, 14, 14, 14)
        panel.addWidget(self.mode_sw, 0, QtCore.Qt.AlignHCenter)
        panel.addSpacing(8)
        panel.addLayout(grid)
        panel.addWidget(hint)
        panel.addStretch()
        panel.addWidget(self.start_btn, 0, QtCore.Qt.AlignHCenter)

        panel_w = QtWidgets.QFrame()
        panel_w.setObjectName("panel")
        panel_w.setLayout(panel)
        panel_w.setFixedWidth(310)
        panel_w.setStyleSheet(
            f"#panel{{background:{PANEL.name()};border-radius:16px;}}")

        root = QtWidgets.QHBoxLayout()
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self.view, 1)
        root.addWidget(panel_w)
        central = QtWidgets.QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Saving to {OUT_DIR}")

        # ---- shortcuts ----
        QtWidgets.QShortcut(QtGui.QKeySequence("F11"), self,
                            activated=self.toggle_fullscreen)
        QtWidgets.QShortcut(QtGui.QKeySequence("Esc"), self,
                            activated=self.showNormal)

        # ---- frame timer (~30 fps) ----
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)

        self.apply_sensor()

    # ---- helpers ----
    def apply_sensor(self):
        set_ctrl("exposure", self.exp.value())
        set_ctrl("gain", self.gain.value())

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # ---- frame loop ----
    def update_frame(self):
        bus = self.pipeline.get_bus()
        msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.WARNING)
        if msg:
            err, dbg = (msg.parse_error() if msg.type == Gst.MessageType.ERROR
                        else msg.parse_warning())
            self.statusBar().showMessage(f"GStreamer: {err.message}")
            print("GStreamer:", err.message, dbg, flush=True)

        sample = self.sink.emit("try-pull-sample", 0)
        if sample is None:
            return
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        w, h = caps.get_value("width"), caps.get_value("height")
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return
        frame = np.frombuffer(info.data, np.uint8).reshape(h, w, 3).copy()
        buf.unmap(info)

        frame = process(frame, self.zoom.value() / 10.0,
                        self.warm.value(), self.focus.value())
        self.last_frame = frame

        if self.writer is not None:
            target = int((time.monotonic() - self.rec_start) * FPS) + 1
            while self.rec_frames < target:
                self.writer.write(frame)
                self.rec_frames += 1

        img = QtGui.QImage(frame.data, w, h, w * 3, QtGui.QImage.Format_BGR888)
        self.view.set_image(img.copy())

    # ---- controls ----
    def on_mode(self, video: bool):
        if self.writer is not None:
            self.stop_recording()
        self.start_btn.set_mode(video)

    def on_start(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if not self.mode_sw.isChecked():                       # photo
            if self.last_frame is None:
                return
            path = OUT_DIR / f"IMG_{stamp}.jpg"
            cv2.imwrite(str(path), self.last_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            self.statusBar().showMessage(f"Saved {path}", 5000)
        elif self.writer is None:                               # start video
            if self.last_frame is None:
                return
            hh, ww = self.last_frame.shape[:2]
            path = OUT_DIR / f"VID_{stamp}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(str(path), fourcc, FPS, (ww, hh))
            self.rec_start = time.monotonic()
            self.rec_frames = 0
            self.start_btn.set_recording(True)
            self.start_btn.set_recording(True)
            self.statusBar().showMessage(f"Recording {path}")
        else:
            self.stop_recording()

    def stop_recording(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            self.statusBar().showMessage("Recording saved", 5000)
        self.start_btn.set_recording(False)

    def closeEvent(self, e):
        self.stop_recording()
        self.pipeline.set_state(Gst.State.NULL)
        super().closeEvent(e)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("rockcam")      # matches StartupWMClass in the menu entry
    app.setDesktopFileName("rockcam")

    # used by the package builder: write the icon as a PNG, then quit
    if "--export-icon" in sys.argv:
        i = sys.argv.index("--export-icon")
        make_icon_pixmap(int(sys.argv[i + 2])).save(sys.argv[i + 1])
        sys.exit(0)

    app.setStyle("Fusion")
    icon = QtGui.QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(make_icon_pixmap(sz))
    app.setWindowIcon(icon)
    app.setStyleSheet(
        f"QMainWindow, QWidget#central{{background:{BG.name()};}}"
        f"QMainWindow{{background:{BG.name()};}}"
        f"QStatusBar{{color:{DIM.name()};}}"
    )
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())