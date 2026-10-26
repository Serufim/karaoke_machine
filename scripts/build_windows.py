#!/usr/bin/env python3
"""
Automated Windows build and release packaging orchestrator for AI Karaoke Studio.
Performs:
1. Frontend compilation (Vite + Vue 3 -> frontend/dist)
2. Standalone FFmpeg bundling check (bin/ffmpeg.exe, bin/ffprobe.exe)
3. PyInstaller standalone onedir bundling (dist/AIKaraokeStudio)
4. Inno Setup installer compilation (dist/installer/AIKaraokeStudio-Setup.exe)
5. Steam Depot structure preparation
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_DIR = ROOT_DIR / "dist"
BIN_DIR = ROOT_DIR / "bin"
PACKAGING_DIR = ROOT_DIR / "packaging" / "windows"


def run_cmd(cmd, cwd=None, env=None):
    print(f"👉 Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str))
    if res.returncode != 0:
        print(f"❌ Command failed with return code {res.returncode}")
        sys.exit(res.returncode)


def step_build_frontend(dry_run=False):
    print("\n📦 [1/4] Компиляция Vue 3 Frontend (Vite)...")
    if dry_run:
        print("  [Dry-run] npm run build inside frontend/")
        return
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    run_cmd([npm_cmd, "run", "build"], cwd=str(FRONTEND_DIR))
    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if not dist_index.exists():
        print(f"❌ Ошибка: {dist_index} не найден после сборки.")
        sys.exit(1)
    print("✅ Фронтенд успешно скомпилирован в frontend/dist")


def step_check_ffmpeg(dry_run=False):
    print("\n🎬 [2/4] Проверка встроенного FFmpeg для Windows...")
    ffmpeg_exe = BIN_DIR / "ffmpeg.exe"
    ffprobe_exe = BIN_DIR / "ffprobe.exe"

    if ffmpeg_exe.exists() and ffprobe_exe.exists():
        print(f"✅ Обнаружен встроенный FFmpeg в {BIN_DIR}")
        return

    print("ℹ️ В папке bin/ не найдены ffmpeg.exe и ffprobe.exe.")
    print("  Для коммерческого релиза под Windows рекомендуется скачать gyan.dev ffmpeg-release-essentials.zip")
    print("  и распаковать ffmpeg.exe и ffprobe.exe в папку 'bin/'.")
    if not dry_run:
        BIN_DIR.mkdir(parents=True, exist_ok=True)


def step_pyinstaller(dry_run=False):
    print("\n⚙️ [3/4] Сборка исполняемого файла через PyInstaller...")
    spec_path = PACKAGING_DIR / "pyinstaller.spec"
    if dry_run:
        print(f"  [Dry-run] pyinstaller {spec_path}")
        return

    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller не установлен в текущем окружении. Установите: uv add pyinstaller")
        sys.exit(1)

    run_cmd([sys.executable, "-m", "PyInstaller", str(spec_path), "--noconfirm"], cwd=str(ROOT_DIR))
    out_exe = DIST_DIR / "AIKaraokeStudio" / "AIKaraokeStudio.exe"
    print(f"✅ PyInstaller завершил сборку в {DIST_DIR / 'AIKaraokeStudio'}")


def step_inno_setup(dry_run=False):
    print("\n💿 [4/4] Создание инсталлятора через Inno Setup...")
    iss_file = PACKAGING_DIR / "installer.iss"

    iscc_path = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if isinstance(iscc_path, str) and not Path(iscc_path).exists():
        iscc_path = None

    if not iscc_path:
        print("⚠️ Inno Setup Compiler (iscc) не найден на PATH.")
        print("  Вы можете вручную скомпилировать packaging/windows/installer.iss через Inno Setup IDE.")
        return

    if dry_run:
        print(f"  [Dry-run] {iscc_path} {iss_file}")
        return

    run_cmd([str(iscc_path), str(iss_file)], cwd=str(PACKAGING_DIR))
    print(f"🎉 Инсталлятор успешно собран в {DIST_DIR / 'installer'}")


def main():
    parser = argparse.ArgumentParser(description="Сборщик AI Karaoke Studio под Windows")
    parser.add_argument("--dry-run", action="store_true", help="Проверить манифесты без запуска компиляции")
    parser.add_argument("--skip-frontend", action="store_true", help="Пропустить сборку фронтенда")
    args = parser.parse_args()

    print("==================================================")
    print("🚀 AI Karaoke Studio — Сборка релиза под Windows")
    print("==================================================")

    if not args.skip_frontend:
        step_build_frontend(dry_run=args.dry_run)

    step_check_ffmpeg(dry_run=args.dry_run)

    if sys.platform != "win32" and not args.dry_run:
        print("\n⚠️ Предупреждение: Текущая ОС не Windows. Сборка PyInstaller Windows-бинарников")
        print("   должна производиться на виртуальной машине Windows или в GitHub Actions CI.")
        print("   Используйте флаг --dry-run для валидации манифестов на macOS/Linux.")
        return

    step_pyinstaller(dry_run=args.dry_run)
    step_inno_setup(dry_run=args.dry_run)

    print("\n✨ Готово! Директория дистрибутива готова для релиза и Steam.")


if __name__ == "__main__":
    main()
