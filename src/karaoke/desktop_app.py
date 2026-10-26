"""
Native desktop window launcher for AI Karaoke Studio.
Provides native OS window wrapper (Edge WebView2 on Windows, WebKit on macOS),
resizing support, geometry persistence, and automated server lifecycle.
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import uvicorn

from karaoke.config import DATA_DIR, setup_isolated_environment

# Ensure isolated cache and paths
setup_isolated_environment()

SETTINGS_FILE = DATA_DIR / "desktop_settings.json"


def find_free_port(preferred_port: int = 7860) -> int:
    """Finds an available TCP port starting from preferred_port."""
    for port in range(preferred_port, preferred_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred_port


def load_window_geometry() -> Dict[str, int]:
    """Loads saved window dimensions and position."""
    defaults = {"width": 1440, "height": 900}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "width": max(1024, data.get("width", 1440)),
                    "height": max(680, data.get("height", 900)),
                    "x": data.get("x"),
                    "y": data.get("y"),
                }
        except Exception:
            pass
    return defaults


def save_window_geometry(geometry: Dict[str, Any]) -> None:
    """Saves window geometry to isolated settings file."""
    try:
        current = {}
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        current.update(geometry)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception as e:
        print(f"[Desktop] Could not save geometry: {e}")


class ServerThread(threading.Thread):
    """Runs Uvicorn in a background thread."""

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        config = uvicorn.Config(
            "karaoke.server:app",
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Waits until the server is accepting HTTP connections."""
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main():
    use_browser = "--browser" in sys.argv or os.environ.get("USE_BROWSER") == "1"

    port = find_free_port(int(os.environ.get("PORT", "7860")))
    host = "127.0.0.1"

    print(f"🚀 Запуск бэкенда AI Karaoke Studio на http://{host}:{port}...")
    server_thread = ServerThread(host, port)
    server_thread.start()

    if not wait_for_server(host, port):
        print("❌ Ошибка: Сервер не ответил вовремя при запуске.")
        sys.exit(1)

    url = f"http://{host}:{port}"

    if use_browser:
        import webbrowser
        webbrowser.open(url)
        print("🌐 Открыт браузер по умолчанию. Нажмите Ctrl+C для выхода.")
        try:
            while server_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server_thread.stop()
        return

    try:
        import webview
    except ImportError:
        print("⚠️ pywebview не найден, открываем в стандартном браузере...")
        import webbrowser
        webbrowser.open(url)
        try:
            while server_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server_thread.stop()
        return

    geo = load_window_geometry()

    print("🖥️ Открытие нативного окна приложения...")
    window = webview.create_window(
        title="AI Karaoke Studio",
        url=url,
        width=geo.get("width", 1440),
        height=geo.get("height", 900),
        x=geo.get("x"),
        y=geo.get("y"),
        min_size=(1024, 680),
        resizable=True,
        background_color="#090d16",
    )

    def on_closed():
        # Save geometry
        try:
            save_window_geometry({
                "width": window.width,
                "height": window.height,
                "x": window.x,
                "y": window.y,
            })
        except Exception:
            pass
        server_thread.stop()

    window.events.closed += on_closed

    # Start native event loop (blocks until window is closed)
    webview.start(debug=False)
    server_thread.stop()


if __name__ == "__main__":
    main()
