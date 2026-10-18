"""OmniVoice integration.

API used (verified against https://github.com/k2-fsa/OmniVoice README and docs):
    from omnivoice import OmniVoice
    model = OmniVoice.from_pretrained(model_id, device_map=<device>, dtype=<torch dtype>)
    audio = model.generate(text=..., instruct=..., speed=..., num_step=...,
                           ref_audio=..., ref_text=...)   # -> list[np.ndarray], 24 kHz, shape (T,)

The model is loaded ONCE and reused. One generation runs at a time (a lock), because a
single model instance on one GPU is not safe to drive from several threads at once.
If PyTorch / omnivoice / a compatible device is missing, the service reports
state="unavailable" with a reason. It never fabricates audio.
"""
import logging
import threading
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .config import Settings

logger = logging.getLogger("nexvora.model")
SAMPLE_RATE = 24000  # OmniVoice outputs 24 kHz audio (per its README)


class ModelUnavailable(Exception):
    """Model/hardware missing or failed to load. Message is safe to show to users."""


class GenerationFailed(Exception):
    """Model was ready but inference raised an error (details only in server logs)."""


class ModelService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Any = None
        self._torch: Any = None
        self._state = "not_loaded"      # not_loaded | loading | ready | unavailable
        self._detail: Optional[str] = None
        self._device: Optional[str] = None
        self._load_lock = threading.Lock()
        self._gen_lock = threading.Lock()

    # ---- status -----------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {"id": self.settings.model_id, "state": self._state,
                "device": self._device, "detail": self._detail}

    # ---- loading ----------------------------------------------------------------
    def _resolve_device(self, torch: Any) -> Tuple[Optional[str], Optional[str]]:
        want = self.settings.device.lower()
        has_cuda = torch.cuda.is_available()
        mps = getattr(torch.backends, "mps", None)
        has_mps = bool(mps and mps.is_available())
        xpu = getattr(torch, "xpu", None)
        has_xpu = bool(xpu and xpu.is_available())
        if want == "auto":
            if has_cuda:
                return "cuda:0", None
            if has_mps:
                return "mps", None
            if has_xpu:
                return "xpu", None
            if self.settings.allow_cpu:
                return "cpu", None
            return None, ("No compatible GPU found (CUDA / Apple MPS / Intel XPU). "
                          "Run the model on a GPU machine, or set ALLOW_CPU=true to try CPU (slow).")
        if want.startswith("cuda") and not has_cuda:
            return None, "OMNIVOICE_DEVICE requests CUDA but no CUDA GPU is available."
        if want == "mps" and not has_mps:
            return None, "OMNIVOICE_DEVICE requests MPS but it is not available."
        if want == "xpu" and not has_xpu:
            return None, "OMNIVOICE_DEVICE requests XPU but it is not available."
        if want == "cpu" and not self.settings.allow_cpu:
            return None, "CPU inference is disabled. Set ALLOW_CPU=true to enable it (slow)."
        return want, None

    def _resolve_dtype(self, torch: Any, device: str) -> Any:
        name = self.settings.dtype.lower()
        if name == "auto":
            name = "float16" if device.startswith(("cuda", "xpu")) else "float32"
        mapping = {"float16": torch.float16, "float32": torch.float32, "bfloat16": torch.bfloat16}
        if name not in mapping:
            raise ModelUnavailable("OMNIVOICE_DTYPE must be auto, float16, float32 or bfloat16.")
        return mapping[name]

    def _fail(self, detail: str) -> None:
        self._state, self._detail, self._model = "unavailable", detail, None

    def load(self) -> None:
        """Load the model once. Safe to call repeatedly / from several threads."""
        with self._load_lock:
            if self._state in ("ready", "unavailable"):
                return
            self._state, self._detail = "loading", "Loading model…"
            try:
                import torch  # noqa: WPS433 (lazy: backend still starts without it)
            except ImportError:
                return self._fail("PyTorch is not installed on the model server.")
            try:
                from omnivoice import OmniVoice  # noqa: WPS433
            except ImportError:
                return self._fail("The 'omnivoice' package is not installed on the model server.")
            try:
                device, reason = self._resolve_device(torch)
                if device is None:
                    return self._fail(reason or "No compatible device.")
                dtype = self._resolve_dtype(torch, device)
                logger.info("Loading %s on %s (%s)", self.settings.model_id, device, dtype)
                self._model = OmniVoice.from_pretrained(
                    self.settings.model_id, device_map=device, dtype=dtype)
                self._torch, self._device = torch, device
                self._state, self._detail = "ready", None
                logger.info("OmniVoice ready")
            except ModelUnavailable as exc:
                self._fail(str(exc))
            except Exception as exc:  # noqa: BLE001 - full details go to logs only
                logger.exception("Model load failed")
                self._fail(f"Model failed to load ({type(exc).__name__}). See server logs.")

    # ---- inference --------------------------------------------------------------
    def generate(self, text: str, instruct: Optional[str] = None, speed: float = 1.0,
                 num_step: int = 32, ref_audio: Optional[str] = None,
                 ref_text: Optional[str] = None) -> Tuple[np.ndarray, int]:
        if self._state != "ready":
            self.load()
        if self._state != "ready":
            raise ModelUnavailable(self._detail or "Model is not available.")
        kwargs: Dict[str, Any] = {"text": text, "speed": speed, "num_step": num_step}
        if ref_audio:                      # voice cloning mode
            kwargs["ref_audio"] = ref_audio
            if ref_text:
                kwargs["ref_text"] = ref_text   # omitted -> OmniVoice auto-transcribes (Whisper)
        elif instruct:                     # voice design mode
            kwargs["instruct"] = instruct
        # else: auto voice
        with self._gen_lock:
            try:
                with self._torch.inference_mode():
                    audio = self._model.generate(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Generation failed")
                raise GenerationFailed(type(exc).__name__) from None
        try:
            first = audio[0]
            if hasattr(first, "detach"):   # torch tensor -> numpy
                first = first.detach().cpu().float().numpy()
            return np.asarray(first, dtype=np.float32).reshape(-1), SAMPLE_RATE
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected model output")
            raise GenerationFailed("BadOutput") from None
