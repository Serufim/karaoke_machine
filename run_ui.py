#!/usr/bin/env python3
"""Entry point for launching AI Karaoke Studio."""
import sys
from pathlib import Path

# Ensure src/ is in sys.path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

if __name__ == "__main__":
    if "--gradio" in sys.argv:
        from karaoke.app_ui import launch_ui
        launch_ui(server_port=7860)
    else:
        from karaoke.server import main
        main()
