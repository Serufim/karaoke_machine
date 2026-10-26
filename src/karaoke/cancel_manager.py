import subprocess
import threading
import os
import selectors
from typing import Set, List, Optional, Callable


class GenerationCancelledError(Exception):
    """Raised when the user clicks the Cancel Generation button."""
    pass


_lock = threading.Lock()
_cancel_event = threading.Event()
_active_procs: Set[subprocess.Popen] = set()


def reset_cancel() -> None:
    """Clears the cancellation flag before starting a new generation or rebuild."""
    with _lock:
        _cancel_event.clear()


def is_cancelled() -> bool:
    """Returns True if cancellation has been requested."""
    return _cancel_event.is_set()


def check_cancelled() -> None:
    """Raises GenerationCancelledError if cancellation has been requested."""
    if _cancel_event.is_set():
        raise GenerationCancelledError("🛑 Генерация остановлена пользователем.")


def register_process(proc: subprocess.Popen) -> None:
    """Registers an active child process so it can be terminated on cancel."""
    with _lock:
        _active_procs.add(proc)


def unregister_process(proc: subprocess.Popen) -> None:
    """Removes a child process from the active set."""
    with _lock:
        _active_procs.discard(proc)


def request_cancel() -> int:
    """
    Sets the cancellation flag and immediately terminates all active child processes
    (such as Demucs or FFmpeg). Returns the number of terminated processes.
    """
    with _lock:
        _cancel_event.set()
        procs = list(_active_procs)

    killed_count = 0
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                killed_count += 1
        except Exception as e:
            print(f"[Karaoke] Ошибка при остановке процесса: {e}")
        finally:
            unregister_process(proc)

    print(f"[Karaoke] 🛑 Запрошена отмена генерации (остановлено процессов: {killed_count}).")
    return killed_count


def run_cancellable_command(
    cmd: List[str], prefix: str = "Cmd",
    on_stdout_line: Optional[Callable[[str], None]] = None,
    on_tick: Optional[Callable[[], None]] = None,
) -> None:
    """
    Drain both pipes continuously with bounded log storage. Callbacks run on the
    caller's thread (required by Gradio progress), even when FFmpeg is silent.
    Always reap the child before returning, including when a callback fails.
    """
    check_cancelled()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    register_process(proc)
    selector = selectors.DefaultSelector()
    stdout_data = b""
    stderr_data = b""
    pending = b""
    try:
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            check_cancelled()
            if on_tick:
                on_tick()
            for key, _ in selector.select(timeout=0.25):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stderr":
                    stderr_data = (stderr_data + chunk)[-65536:]
                else:
                    stdout_data = (stdout_data + chunk)[-65536:]
                    if on_stdout_line:
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            on_stdout_line(line.decode("utf-8", errors="replace").rstrip("\r"))
                        pending = pending[-65536:]
        proc.wait()
        check_cancelled()
        if on_tick:
            on_tick()
        if pending and on_stdout_line:
            on_stdout_line(pending.decode("utf-8", errors="replace"))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
        unregister_process(proc)

    check_cancelled()
    if proc.returncode != 0:
        err = subprocess.CalledProcessError(proc.returncode, cmd)
        err.stdout = stdout_data
        err.stderr = stderr_data
        raise err
