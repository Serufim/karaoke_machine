"""FFmpeg's machine-readable progress and a bounded output-file budget."""
import math
import time
from pathlib import Path
from typing import Callable, Optional


class RenderLimitError(RuntimeError):
    pass


def clock_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def number(value, default=0.0) -> float:
    try:
        result = float(str(value).strip().rstrip("x"))
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


class RenderProgress:
    def __init__(self, duration: float, output: Path, size_limit: int,
                 callback: Optional[Callable[[str, float], None]] = None):
        self.duration = duration
        self.output = output
        self.size_limit = size_limit
        self.callback = callback
        self.started = time.monotonic()
        self.last_report = 0.0
        self.last_console = 0.0
        self.processed = 0.0
        self.frame = 0
        self.fps = 0.0
        self.speed = 0.0
        self.size = 0
        self.packet = {}

    def line(self, line: str) -> None:
        key, separator, value = line.partition("=")
        if not separator:
            return
        self.packet[key] = value
        if key != "progress":
            return
        # FFmpeg out_time_ms is also in microseconds; prefer the explicit key.
        elapsed = number(self.packet.get("out_time_us", self.packet.get("out_time_ms"))) / 1_000_000
        if elapsed > self.duration + 1:
            raise RenderLimitError("FFmpeg превысил длительность аудио; рендер остановлен.")
        self.processed = max(self.processed, min(self.duration, elapsed))
        self.frame = max(self.frame, int(number(self.packet.get("frame"))))
        self.speed = number(self.packet.get("speed"))
        self.fps = number(self.packet.get("fps"))
        self.size = max(self.size, int(number(self.packet.get("total_size"))))
        self.packet.clear()
        self.tick(force=True)

    def tick(self, force: bool = False) -> None:
        if self.output.exists():
            self.size = max(self.size, self.output.stat().st_size)
        if self.size >= self.size_limit:
            raise RenderLimitError(
                f"Размер рендера превысил допустимый бюджет {self.size_limit / 1_000_000:.0f} МБ "
                f"для {clock_time(self.duration)}. Рендер остановлен; предыдущий ролик сохранён."
            )
        now = time.monotonic()
        if not force and now - self.last_report < 1:
            return
        self.last_report = now
        fraction = min(0.99, self.processed / self.duration)
        eta = clock_time((self.duration - self.processed) / self.speed) if self.speed > 0 else "расчёт…"
        phase = "Завершение MP4" if self.processed >= self.duration - 0.05 else f"Рендер {fraction:.0%}"
        message = (
            f"{phase} · {clock_time(self.processed)} / {clock_time(self.duration)} · "
            f"кадр {self.frame} · {self.fps:.1f} fps · {self.speed:.2f}× · "
            f"прошло {clock_time(now - self.started)} · осталось ≈ {eta} · "
            f"{self.size / 1_000_000:.1f} МБ"
        )
        if self.callback:
            self.callback(message, fraction)
        if now - self.last_console >= 2:
            print(f"[FFmpeg] {message}", flush=True)
            self.last_console = now
