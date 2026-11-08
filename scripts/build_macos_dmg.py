#!/usr/bin/env python3
"""
macOS .app bundle and .dmg disk image builder for AI Karaoke Studio.

Creates:
1. Custom macOS App Icon (`AppIcon.icns`) rendered with Pillow + `iconutil`.
2. Native `dist/AI Karaoke Studio.app` bundle with `Info.plist` and launcher executable
   that starts the native macOS desktop window (`karaoke.desktop_app`) with Homebrew FFmpeg
   and Node.js on PATH.
3. Distributable `dist/AI_Karaoke_Studio_macOS.dmg` disk image (with `/Applications` symlink)
   using macOS native `hdiutil`.
"""
import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_DIR = ROOT_DIR / "dist"
APP_NAME = "AI Karaoke Studio"
APP_BUNDLE = DIST_DIR / f"{APP_NAME}.app"
DMG_PATH = DIST_DIR / "AI_Karaoke_Studio_macOS.dmg"


def create_app_icon_icns(output_icns: Path) -> None:
    """Generates a sleek neon karaoke microphone icon and converts it to .icns via macOS iconutil."""
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded macOS squircle background (#0B0F19 with neon border)
    pad = 40
    draw.rounded_rectangle(
        [(pad, pad), (size - pad, size - pad)],
        radius=210,
        fill=(13, 17, 30, 255),
        outline=(0, 240, 255, 255),
        width=18,
    )
    # Inner magenta glow ring
    draw.rounded_rectangle(
        [(pad + 22, pad + 22), (size - pad - 22, size - pad - 22)],
        radius=190,
        outline=(255, 20, 147, 180),
        width=8,
    )

    # Draw stylized neon microphone / studio emblem in the center
    cx, cy = size // 2, size // 2 - 45
    # Mic head (gold neon capsule)
    draw.rounded_rectangle(
        [(cx - 115, cy - 210), (cx + 115, cy + 70)],
        radius=115,
        fill=(255, 215, 0, 255),
        outline=(255, 255, 255, 255),
        width=10,
    )
    # Mic grille lines
    for y_line in range(cy - 150, cy + 30, 42):
        draw.line([(cx - 85, y_line), (cx + 85, y_line)], fill=(20, 24, 38, 220), width=12)

    # Mic cradle arc
    draw.arc(
        [(cx - 175, cy - 110), (cx + 175, cy + 160)],
        start=0,
        end=180,
        fill=(0, 240, 255, 255),
        width=24,
    )
    # Mic stand vertical post & base
    draw.line([(cx, cy + 160), (cx, cy + 285)], fill=(0, 240, 255, 255), width=24)
    draw.line([(cx - 120, cy + 285), (cx + 120, cy + 285)], fill=(255, 20, 147, 255), width=26)

    # "AI KARAOKE" label at bottom
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 76)
    except Exception:
        font = ImageFont.load_default()
    label = "KARAOKE"
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((size - tw) // 2, size - 215), label, fill=(255, 255, 255, 255), font=font)

    with tempfile.TemporaryDirectory(prefix="karaoke_icon_") as tmp:
        iconset_dir = Path(tmp) / "AppIcon.iconset"
        iconset_dir.mkdir(parents=True, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            img.resize((s, s), Image.Resampling.LANCZOS).save(iconset_dir / f"icon_{s}x{s}.png")
            img.resize((s * 2, s * 2), Image.Resampling.LANCZOS).save(iconset_dir / f"icon_{s}x{s}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_icns)],
            check=True,
        )


def build_macos_app_and_dmg() -> Path:
    print("==================================================")
    print("🍎 Сборка AI Karaoke Studio.app и .DMG для macOS")
    print("==================================================")

    # 1. Ensure frontend is built fresh
    print("📦 Компиляция фронтенда (npm run build)...")
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if APP_BUNDLE.exists():
        shutil.rmtree(APP_BUNDLE)

    contents_dir = APP_BUNDLE / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # 2. Generate AppIcon.icns
    icns_path = resources_dir / "AppIcon.icns"
    print("🎨 Генерация иконки приложения AppIcon.icns...")
    create_app_icon_icns(icns_path)

    # 3. Copy source code and assets into Resources for self-contained execution
    print("📋 Копирование исходных файлов и ассетов в Resources...")
    shutil.copytree(ROOT_DIR / "src", resources_dir / "src", dirs_exist_ok=True)
    shutil.copy2(ROOT_DIR / "pyproject.toml", resources_dir / "pyproject.toml")
    shutil.copy2(ROOT_DIR / "run_ui.py", resources_dir / "run_ui.py")
    if (FRONTEND_DIR / "dist").exists():
        shutil.copytree(FRONTEND_DIR / "dist", resources_dir / "frontend" / "dist", dirs_exist_ok=True)

    # 4. Write Info.plist
    info_plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "ru.karaokestudio.ai.app",
        "CFBundleVersion": "0.5.2",
        "CFBundleShortVersionString": "0.5.2",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "AIKaraokeStudioLauncher",
        "CFBundleIconFile": "AppIcon.icns",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
    }
    with open(contents_dir / "Info.plist", "wb") as f:
        plistlib.dump(info_plist, f)

    # 5. Write native launcher script inside Contents/MacOS/AIKaraokeStudioLauncher
    venv_python = ROOT_DIR / ".venv" / "bin" / "python"
    launcher_path = macos_dir / "AIKaraokeStudioLauncher"
    launcher_script = f"""#!/bin/zsh
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PYTHONIOENCODING="utf-8"
export LANG="en_US.UTF-8"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Determine working root directory
if [ -d "{ROOT_DIR}/src" ]; then
    APP_ROOT="{ROOT_DIR}"
elif [ -d "$RESOURCES_DIR/src" ]; then
    APP_ROOT="$RESOURCES_DIR"
else
    APP_ROOT="$CONTENTS_DIR"
fi

cd "$APP_ROOT" || exit 1

LOG_DIR="$HOME/Library/Logs/AIKaraokeStudio"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/desktop_app.log"

export PYTHONPATH="$APP_ROOT/src:$PYTHONPATH"

if [ -x "{venv_python}" ]; then
    exec "{venv_python}" -m karaoke.desktop_app >> "$LOG_FILE" 2>&1
elif [ -x "$HOME/karaoke_machine/.venv/bin/python" ]; then
    exec "$HOME/karaoke_machine/.venv/bin/python" -m karaoke.desktop_app >> "$LOG_FILE" 2>&1
elif command -v uv >/dev/null 2>&1; then
    exec uv run --directory "$APP_ROOT" python -m karaoke.desktop_app >> "$LOG_FILE" 2>&1
elif command -v python3.11 >/dev/null 2>&1; then
    exec python3.11 -m karaoke.desktop_app >> "$LOG_FILE" 2>&1
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m karaoke.desktop_app >> "$LOG_FILE" 2>&1
else
    osascript -e 'display alert "AI Karaoke Studio" message "Python 3.11 или менеджер uv не найдены.\\nУстановите uv через терминал:\\ncurl -LsSf https://astral.sh/uv/install.sh | sh" as critical'
    exit 1
fi
"""
    launcher_path.write_text(launcher_script, encoding="utf-8")
    launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Ad-hoc codesign so macOS Gatekeeper launches cleanly locally
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP_BUNDLE)], check=False)
    print(f"✅ Собран бандл приложения: {APP_BUNDLE}")

    # 5. Build .DMG disk image with /Applications shortcut
    if DMG_PATH.exists():
        DMG_PATH.unlink()

    print(f"💿 Упаковка образа диска {DMG_PATH.name}...")
    with tempfile.TemporaryDirectory(prefix="karaoke_dmg_stage_") as stage_str:
        stage_dir = Path(stage_str)
        shutil.copytree(APP_BUNDLE, stage_dir / APP_BUNDLE.name, symlinks=True)
        os.symlink("/Applications", stage_dir / "Applications")

        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                APP_NAME,
                "-srcfolder",
                str(stage_dir),
                "-ov",
                "-format",
                "UDZO",
                str(DMG_PATH),
            ],
            check=True,
        )

    print(f"🎉 Образ диска .DMG успешно создан: {DMG_PATH} ({DMG_PATH.stat().st_size / 1_000_000:.2f} МБ)")
    return DMG_PATH


if __name__ == "__main__":
    build_macos_app_and_dmg()
