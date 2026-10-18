"""NexVora Voice AI - FastAPI application."""
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .audio import sniff_audio, to_wav_bytes
from .config import Settings, load_settings
from .errors import ApiError
from .model_service import GenerationFailed, ModelService, ModelUnavailable
from .options import DESIGN_OPTIONS, MAX_SPEED, MIN_SPEED
from .ratelimit import SlidingWindowLimiter
from .schemas import GenerateRequest
from .storage import cleanup_dir, new_temp_path, remove_quietly

logger = logging.getLogger("nexvora.api")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CLONE_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class BodyLimitMiddleware:
    """Reject oversized / unsized request bodies before any parsing happens."""

    def __init__(self, app, settings: Settings):
        self.app, self.s = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("POST", "PUT", "PATCH"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            is_clone = scope["path"].endswith("/generate-clone")
            limit = self.s.max_upload_bytes + 64 * 1024 if is_clone else self.s.max_json_bytes
            err = None
            if "transfer-encoding" in headers or "content-length" not in headers:
                err = (411, "length_required", "Content-Length header is required.")
            else:
                try:
                    if int(headers["content-length"]) > limit:
                        err = (413, "payload_too_large", "Request body is too large.")
                except ValueError:
                    err = (400, "validation_error", "Invalid Content-Length header.")
            if err:
                body = json.dumps({"error": {"code": err[1], "message": err[2]}}).encode()
                await send({"type": "http.response.start", "status": err[0],
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def create_app(settings: Optional[Settings] = None,
               service: Optional[ModelService] = None) -> FastAPI:
    settings = settings or load_settings()
    service = service or ModelService(settings)
    limiter = SlidingWindowLimiter(settings.rate_limit_per_min, 60)
    health_limiter = SlidingWindowLimiter(120, 60)
    inflight_ips: set = set()
    counters = {"pending": 0}
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    async def sweeper():
        while True:
            await asyncio.sleep(60)
            await run_in_threadpool(cleanup_dir, settings.output_dir, settings.output_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        cleanup_dir(settings.output_dir, 0)  # remove leftovers from a previous run
        tasks = [asyncio.create_task(sweeper())]
        if settings.load_on_startup:
            tasks.append(asyncio.create_task(run_in_threadpool(service.load)))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="NexVora Voice AI", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                       expose_headers=["X-Audio-Duration", "Content-Disposition", "Retry-After"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ---- error handling ------------------------------------------------------------
    def err_json(status: int, code: str, message: str, headers=None) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}},
                            status_code=status, headers=headers)

    @app.exception_handler(ApiError)
    async def _api_error(_r: Request, exc: ApiError):
        return err_json(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError):
        msgs = []
        for e in exc.errors()[:3]:  # never echo the submitted input back
            where = ".".join(str(p) for p in e.get("loc", ())[1:]) or "request"
            msgs.append(f"{where}: {e.get('msg', 'invalid')}")
        return err_json(422, "validation_error", "; ".join(msgs))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return err_json(exc.status_code, code, "Request could not be handled.")

    @app.exception_handler(Exception)
    async def _unhandled(_r: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return err_json(500, "internal_error", "Internal server error.")

    # ---- helpers -----------------------------------------------------------------
    def client_ip(request: Request) -> str:
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[-1].strip()  # rightmost = added by our own proxy
        return request.client.host if request.client else "unknown"

    def enforce_rate_limit(lim: SlidingWindowLimiter, ip: str) -> None:
        ok, retry = lim.check(ip)
        if not ok:
            raise ApiError(429, "rate_limited", "Too many requests. Please wait and try again.",
                           {"Retry-After": str(retry)})

    def clean_text(raw: str) -> str:
        text = _CTRL.sub("", raw).strip()
        if not text:
            raise ApiError(422, "text_empty", "Please enter some text.")
        if len(text) > settings.max_text_chars:
            raise ApiError(422, "text_too_long",
                           f"Text is limited to {settings.max_text_chars} characters.")
        return text

    async def synthesize(ip: str, **kwargs) -> FileResponse:
        st = service.status()
        if st["state"] == "unavailable":
            raise ApiError(503, "model_unavailable", st["detail"] or "Model is not available.")
        if st["state"] == "loading":
            raise ApiError(503, "model_loading", "The model is still loading. Try again shortly.",
                           {"Retry-After": "15"})
        if ip in inflight_ips:
            raise ApiError(409, "duplicate_request", "A generation is already running for you.")
        if counters["pending"] >= settings.max_queue:
            raise ApiError(503, "busy", "The server is busy. Please try again shortly.",
                           {"Retry-After": "10"})
        inflight_ips.add(ip)
        counters["pending"] += 1
        try:
            samples, rate = await run_in_threadpool(service.generate, **kwargs)
            wav = await run_in_threadpool(to_wav_bytes, samples, rate)
        except ModelUnavailable as exc:
            raise ApiError(503, "model_unavailable", str(exc))
        except GenerationFailed:
            raise ApiError(500, "generation_failed", "Speech generation failed. Please try again.")
        except ValueError:
            raise ApiError(500, "generation_failed", "The model returned invalid audio.")
        finally:
            inflight_ips.discard(ip)
            counters["pending"] -= 1
        path = new_temp_path(settings.output_dir, ".wav")
        path.write_bytes(wav)
        return FileResponse(path, media_type="audio/wav", filename="nexvora-voice.wav",
                            headers={"X-Audio-Duration": f"{len(samples) / rate:.2f}"},
                            background=BackgroundTask(remove_quietly, path))

    # ---- routes ------------------------------------------------------------------
    @app.get("/api/health")
    async def health(request: Request):
        enforce_rate_limit(health_limiter, client_ip(request))
        m = service.status()
        return {
            "status": m["state"],  # ready | loading | unavailable | not_loaded
            "service": "nexvora-voice-ai",
            "version": __version__,
            "model": m,
            "limits": {"max_text_chars": settings.max_text_chars, "min_speed": MIN_SPEED,
                       "max_speed": MAX_SPEED, "max_upload_mb": settings.max_upload_mb},
            "capabilities": {"voice_cloning": settings.enable_voice_cloning},
            "design_options": {k: list(v) for k, v in DESIGN_OPTIONS.items()},
        }

    @app.post("/api/generate")
    async def generate(payload: GenerateRequest, request: Request):
        ip = client_ip(request)
        enforce_rate_limit(limiter, ip)
        text = clean_text(payload.text)
        return await synthesize(ip, text=text, instruct=payload.instruct(),
                                speed=payload.speed, num_step=payload.num_step)

    if settings.enable_voice_cloning:
        from fastapi import File, Form, UploadFile  # needs python-multipart

        @app.post("/api/generate-clone")
        async def generate_clone(request: Request,
                                 text: str = Form(...),
                                 consent: bool = Form(False),
                                 speed: float = Form(1.0),
                                 num_step: int = Form(32),
                                 ref_text: Optional[str] = Form(None),
                                 ref_audio: UploadFile = File(...)):
            ip = client_ip(request)
            enforce_rate_limit(limiter, ip)
            if not consent:
                raise ApiError(422, "consent_required",
                               "You must confirm you have permission to use this voice.")
            text = clean_text(text)
            if not (MIN_SPEED <= speed <= MAX_SPEED) or not (8 <= num_step <= 64):
                raise ApiError(422, "validation_error", "speed or num_step out of range.")
            ext = Path(ref_audio.filename or "").suffix.lower()
            if ext not in _CLONE_EXT:
                raise ApiError(422, "invalid_audio", "Use a WAV, MP3, FLAC, OGG or M4A file.")
            ref_path = new_temp_path(settings.output_dir / "ref", ext)  # random name, private dir
            try:
                size = 0
                with open(ref_path, "wb") as fh:
                    while chunk := await ref_audio.read(1024 * 256):
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise ApiError(413, "payload_too_large", "Reference audio is too large.")
                        fh.write(chunk)
                with open(ref_path, "rb") as fh:
                    if size == 0 or not sniff_audio(fh.read(16)):
                        raise ApiError(422, "invalid_audio", "File does not look like valid audio.")
                clean_ref_text = _CTRL.sub("", ref_text).strip()[:500] if ref_text else None
                return await synthesize(ip, text=text, speed=speed, num_step=num_step,
                                        ref_audio=str(ref_path), ref_text=clean_ref_text or None)
            finally:
                remove_quietly(ref_path)  # reference audio never outlives the request

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if settings.serve_frontend and dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
