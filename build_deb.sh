#!/usr/bin/env bash
# Builds rockcam_<version>_<arch>.deb from camera_app_v2.py
# Run on the Radxa:  ./build_deb.sh
# Install result:    sudo apt install ./build/rockcam_*.deb
# Remove:            sudo apt remove rockcam
set -e

VER="1.0.0"
ARCH="$(dpkg --print-architecture)"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/camera_app_v2.py"
PKG="$HERE/build/rockcam_${VER}_${ARCH}"

[ -f "$APP" ] || { echo "ERROR: camera_app_v2.py not found next to this script" >&2; exit 1; }
command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb not found" >&2; exit 1; }

rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/rockcam" "$PKG/usr/bin" "$PKG/usr/share/applications"

# ---- app ----
install -m 644 "$APP" "$PKG/opt/rockcam/rockcam.py"

# ---- icons (rendered by the app itself, no display needed) ----
for s in 16 24 32 48 64 128 256; do
  d="$PKG/usr/share/icons/hicolor/${s}x${s}/apps"
  mkdir -p "$d"
  QT_QPA_PLATFORM=offscreen /usr/bin/python3 "$APP" --export-icon "$d/rockcam.png" "$s"
  [ -s "$d/rockcam.png" ] || { echo "ERROR: icon export failed (size $s). Did you apply the Step 1 edits?" >&2; exit 1; }
done

# ---- launcher command ----
cat > "$PKG/usr/bin/rockcam" <<'EOF'
#!/bin/sh
mkdir -p "$HOME/.cache"
exec /usr/bin/python3 /opt/rockcam/rockcam.py "$@" >> "$HOME/.cache/rockcam.log" 2>&1
EOF
chmod 755 "$PKG/usr/bin/rockcam"

# ---- menu entry ----
cat > "$PKG/usr/share/applications/rockcam.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=RockCam
GenericName=Camera
Comment=Live camera view, photo and video capture
Exec=rockcam
Icon=rockcam
Terminal=false
Categories=AudioVideo;Video;Graphics;
StartupWMClass=rockcam
EOF
chmod 644 "$PKG/usr/share/applications/rockcam.desktop"

# ---- package metadata ----
cat > "$PKG/DEBIAN/control" <<EOF
Package: rockcam
Version: $VER
Section: video
Priority: optional
Architecture: $ARCH
Depends: python3, python3-pyqt5, python3-gi, python3-numpy, python3-opencv, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, v4l-utils
Maintainer: RockCam <rockcam@localhost>
Description: RockCam camera app
 Live view, photo and video capture for the Raspberry Pi Camera V2
 on Rockchip boards, with knob-style image controls.
EOF

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true
exit 0
EOF
cp "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$PKG" >/dev/null
echo
echo "Built: $PKG.deb"
echo "Install with:  sudo apt install $PKG.deb"
