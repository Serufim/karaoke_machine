import asyncio
import os
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from karaoke.api.routes import router as api_router
from karaoke.api.websocket import websocket_endpoint, ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register the running event loop in ws_manager
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    yield


app = FastAPI(
    title="AI Karaoke Studio API",
    version="0.3.0",
    description="Backend API and WebSocket engine for AI Karaoke Studio",
    lifespan=lifespan,
)

# Enable CORS for local Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API and WebSocket
app.include_router(api_router)
app.add_api_websocket_route("/api/ws/progress", websocket_endpoint)

# Frontend static files path
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        target = FRONTEND_DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def fallback_root():
        return {
            "name": "AI Karaoke Studio API",
            "version": "0.3.0",
            "status": "ready",
            "hint": "Frontend build not detected in frontend/dist. Start Vite dev server on port 5173 or run 'npm run build' inside frontend/.",
        }


def main():
    import sys
    port = int(os.environ.get("PORT", "7860"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"🚀 AI Karaoke Studio запускается на http://{host}:{port}")

    # Optionally auto-open browser if running standalone
    if "--no-browser" not in sys.argv and os.environ.get("NO_BROWSER") != "1":
        def open_browser():
            import time
            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}")

        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run("karaoke.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
