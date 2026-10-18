# NexVora Voice AI

Original text-to-speech web app (React + TypeScript frontend, FastAPI backend) powered by the
open-source [OmniVoice](https://github.com/k2-fsa/OmniVoice) model (Apache-2.0).
All inference runs on the backend. No Firebase, Supabase, paid TTS or Gemini API is used.

```
frontend/   React + TS + Vite UI (EN / বাংলা, mobile-first, dark cyan/violet theme)
backend/    FastAPI API + OmniVoice model service
```

## Status: what is and is not verified

| Part | Status |
|---|---|
| OmniVoice calls (`from_pretrained`, `generate(text, instruct, speed, num_step, ref_audio, ref_text)`) | Signatures checked against the official README and docs |
| Backend logic: voice-option validation, WAV encoding, rate limiter, temp-file cleanup, config, "model unavailable" behaviour | Unit-tested (`backend/tests/test_core.py`) |
| HTTP tests (`backend/tests/test_api.py`) | Written; run them with `pip install -r requirements-dev.txt && pytest` |
| Real speech generation with OmniVoice | **UNTESTED.** Needs the model + a compatible GPU. Do not treat the system as working until you generate audio yourself (see "Verify end to end") |
| Frontend build in a browser | **UNTESTED** (run `npm install && npm run build`) |

The `StubService` in `test_api.py` is a test double for HTTP plumbing only. The app itself never
returns fake audio: if the model is missing, `/api/health` reports `unavailable` and
`/api/generate` answers `503 model_unavailable`.

## Requirements

- Python 3.10+, Node 18+
- **A compatible GPU is strongly recommended**: NVIDIA CUDA, Apple Silicon (MPS) or Intel Arc (XPU).
  CPU is off by default (`ALLOW_CPU=false`); if you enable it, expect it to be slow, and it is untested here.
- First start downloads the model weights from Hugging Face (not stored in Git).
- Free hosting (free Colab, free Spaces, etc.) usually has no/limited GPU and runtime limits,
  so the model server may stop or be unavailable. Plan for a paid GPU or your own machine.

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Install PyTorch for YOUR hardware first (example: NVIDIA CUDA 12.8), then OmniVoice:
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
pip install omnivoice
# Apple Silicon: pip install torch==2.8.0 torchaudio==2.8.0   then   pip install omnivoice

cp .env.example .env        # optional; defaults work. Export the variables or use a process manager
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check it: `curl http://localhost:8000/api/health` -> `"status": "ready"` once the model has loaded
(`"loading"` for a while on first start, `"unavailable"` with a reason if something is missing).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 ; /api is proxied to localhost:8000
```

Production build: `npm run build` creates `frontend/dist`. If it exists and `SERVE_FRONTEND=true`,
the backend serves it, so one process serves everything on port 8000.

### 3. Verify end to end

1. Open the app; the badge must say "Server ready".
2. Click **Example text** -> **Generate Voice**. Play the result and download the WAV.
3. Try Auto voice, then Voice design (e.g. female + british accent with English text).

Only after this works on your hardware is the AI part verified.

## Using a separate model server

Run the backend on the GPU machine and host the static frontend anywhere:

- Build the frontend with `VITE_API_BASE_URL=https://voice-api.example.com npm run build`.
- On the backend set `CORS_ORIGINS=https://your-frontend.example.com`.
- Put the backend behind HTTPS (Caddy / nginx / a cloud load balancer). Example Caddyfile:
  ```
  voice-api.example.com {
      reverse_proxy localhost:8000
  }
  ```
  and set `TRUST_PROXY=true` so rate limiting sees real client IPs. Only do this behind your own proxy.

## API

| Endpoint | Description |
|---|---|
| `GET /api/health` | Always HTTP 200 while the API is up. `status` is `ready`, `loading`, `unavailable` or `not_loaded`, plus model device/reason, limits, capabilities and the voice-design options |
| `POST /api/generate` | JSON `{text, mode: "auto"\|"design", design: {gender, age, pitch, style, accent}, speed (0.5-2), num_step (8-64)}` -> `audio/wav` (`X-Audio-Duration` header) |
| `POST /api/generate-clone` | Only if `ENABLE_VOICE_CLONING=true`. Multipart: `text`, `ref_audio`, `consent=true`, optional `ref_text`, `speed`, `num_step` |

Errors always look like `{"error": {"code": "...", "message": "..."}}`. Codes: `text_empty`, `text_too_long`,
`validation_error`, `model_unavailable`, `model_loading`, `busy`, `duplicate_request`, `rate_limited`,
`payload_too_large`, `length_required`, `consent_required`, `invalid_audio`, `generation_failed`.

## Safety design

- Model runs only on the server; the browser never loads it. No secrets exist in frontend code.
- The model is loaded once and reused; one generation at a time (lock), bounded queue (`MAX_QUEUE`),
  one in-flight request per client IP, per-IP rate limit (`RATE_LIMIT_PER_MIN`).
- Request bodies are size-limited (64 KB JSON; `MAX_UPLOAD_MB` for reference audio) and must send `Content-Length`.
- Text length limit `MAX_TEXT_CHARS` (default 1000); control characters are stripped.
- Voice-design values are checked against an allow-list. Clients cannot send file paths or arbitrary model arguments.
- Output WAVs are written under `OUTPUT_DIR` with random names, deleted right after the response is sent, and a
  sweeper removes leftovers after `OUTPUT_TTL_SECONDS`. Cleanup only touches files with our own random names.
- Errors never include server paths or stack traces (details go to server logs only).
- **Voice cloning is OFF by default.** When enabled, the user must tick a consent box (also enforced server-side),
  the reference file is type-checked, stored under a random name, and deleted in a `finally` block right after
  generation. Only clone voices you own or have permission to use. OmniVoice's own license text
  prohibits unauthorized cloning, impersonation and fraud; you are responsible for your deployment's compliance.

## Notes and limits

- The progress bar is indeterminate with an elapsed timer; OmniVoice generation is one blocking call and
  gives no percentage.
- Voice design is trained on English and Chinese; English accents only apply to English text. Bangla text
  uses Auto voice (OmniVoice lists 600+ languages; check quality for your text).
- The rate limiter is in-memory and per process. With several workers/replicas, limit at the reverse proxy too.
- Run one uvicorn worker per GPU (the default command does).

## Tests

```bash
cd backend
python -m unittest tests.test_core -v          # no extra dependencies
pip install -r requirements-dev.txt && pytest  # all tests incl. HTTP
```
