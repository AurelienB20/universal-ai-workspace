"""A stand-in for the API in CI: answers POST /ask/stream slowly, with no model, so the
production stack's proxies (Caddy, Next.js) can be checked to pass events on as they
come. Runs in the backend image, which has Starlette and Uvicorn."""

import asyncio
import json

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

DELAY_SECONDS = 0.5
DELTAS = ["Signatures ", "are checked ", "by `verify_signature` ", "[S1]", "."]


def event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def ask_stream(request: Request) -> Response:
    async def events():  # type: ignore[no-untyped-def]
        yield event("sources", {"repository": "o/r", "commit_sha": "a" * 40, "passages": []})
        for text in DELTAS:
            await asyncio.sleep(DELAY_SECONDS)
            yield event("delta", {"text": text})
        yield event("done", {"answer": "".join(DELTAS)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


app = Starlette(
    routes=[Route("/health", health), Route("/ask/stream", ask_stream, methods=["POST"])]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
