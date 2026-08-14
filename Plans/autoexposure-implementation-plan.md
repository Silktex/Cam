# Auto Exposure & RAW Exposure QA — Implementation Plan (Grounded)

**PRD:** `autoexposure.md` (1919-line implementation PRD, G1–G20, 7 milestones)
**This file:** Phase-0 codebase-discovery findings + concrete integration points + shared contract for implementation agents.

---

## 1. Phase 0 — Codebase Discovery Findings

The target application is a **Python 3.12 / FastAPI** backend + **Next.js 14** frontend
that controls a **Sony A7R III** over USB PTP and a 9-panel **ESP32** LED rig for
photometric-stereo fabric capture.

| Concern | Finding | File |
|---|---|---|
| Camera control | Singleton `CameraService` using the **`gphoto2` Python binding** (not the CLI). Settings are set/read via generic gphoto config names through `set_setting(name, value)` and `get_settings()`. **No exposure-controller abstraction exists.** | `api/app/services/camera_service.py` (1008 L) |
| RAW capture | `capture_image(folder, prefix, suffix, skip_post_process=...)` captures ARW, downloads to `raw/`, returns filename/filepath. Two-phase variant `capture_only()` + `download_from_camera()` exists. | `camera_service.py` |
| RAW decode | `rawpy` is **already a dependency** and used to produce a **demosaiced 8-bit sRGB JPEG** (`_post_process_image`) and a **16-bit RGB array** (`raw_utils.py::load_raw`). **Neither reads the RAW mosaic/black/white levels — the PRD requires the mosaic path, which must be new.** | `camera_service.py`, `api/scripts/processing/raw_utils.py` |
| LED control | ESP32 over HTTP. `light_service.set_light(id, on, brightness)`, `set_all_lights(on)`. **Top = id 0, Side 1–8 = ids 1–8.** No explicit LED-settle delay concept beyond the batch loop's `light_stabilize_delay`. | `api/app/services/light_service.py` (349 L) |
| Sequence orchestration | `BatchCaptureService.start_batch_capture()` loops 9 lights: light ON → wait → capture → light OFF. **No exposure preflight, no per-frame QA, no exposure lock.** This is the primary integration point. | `api/app/services/batch_capture_service.py` (371 L) |
| Metadata model | `PostCaptureService` writes `output/calibration.json` per batch. No exposure-QA record exists yet. | `api/app/services/post_capture_service.py` (521 L) |
| Config | `Settings(BaseSettings)` in `api/app/config.py`, env-var + `.env` driven (`extra="ignore"`). | `api/app/config.py` (77 L) |
| Models | Pydantic v2 models in `api/app/models/*.py`. | `api/app/models/` |
| Routers | `api/app/routers/*.py`, wired in `api/main.py` with `/api/...` prefixes. | `api/main.py` |
| Events | Simple `EventBus` pub/sub → WebSocket (`EventType` enum). | `api/app/services/event_bus.py` |
| Tests | `pytest` + `pytest-asyncio` (auto mode), synthetic numpy fixtures in `api/tests/conftest.py`. | `api/tests/` |
| Naming trap | `api/scripts/processing/exposure_service.py` is a **post-processing brightness-equalization** service (in-memory preview transforms) — **unrelated** to camera auto-exposure. Do not conflate. | `api/scripts/processing/exposure_service.py` |

### Key architectural consequences

1. **No demosaiced RGB for exposure.** Use rawpy's mosaic accessors:
   `raw.raw_image_visible`, `raw.black_level_per_channel`, `raw.white_level`,
   `raw.raw_pattern` / `raw.raw_colors`, `raw.camera_white_level_per_channel`.
2. **No new camera stack.** The exposure controller wraps the existing `camera_service`
   singleton; do not duplicate PTP capture logic.
3. **Camera-agnostic shutter mapping.** Enumerate via the existing config tree
   (`get_settings()`), never hardcode a shutter table.
4. **Testable without hardware.** Inject the camera controller and light controller as
   constructor dependencies; the RAW analyzer's core operates on a plain numpy mosaic so
   unit tests need only numpy (no rawpy/gphoto2).

---

## 2. New Module Layout (all under `api/app/services/exposure/`)

```
api/app/services/exposure/
  __init__.py          # docstring only (no re-exports — avoids merge conflicts)
  types.py             # domain dataclasses/enums (contract below) — Agent A
  config.py            # AutoExposureConfig (pydantic) + defaults      — Agent A
  raw_analyzer.py      # RawExposureAnalyzer: mosaic -> ExposureAnalysisResult — Agent A
  controller.py        # CameraExposureController (wraps camera_service)      — Agent B
  preflight.py         # ExposurePreflightService (all-lights safe exposure)  — Agent C
  qa.py                # ExposureQaService (PASS/WARNING/RETAKE/FAIL)         — Agent D
  state_machine.py     # AutoExposureStateMachine (G16)                       — Agent D
  report.py            # session + frame metadata serialization (G14)         — Agent E
```

Other files:
- `api/app/models/exposure.py` — Pydantic API request/response models (Agent E)
- `api/app/routers/exposure.py` — `/api/exposure/...` endpoints (Agent E)
- `api/app/config.py` — add `AUTO_EXPOSURE_*` env-backed settings + expose a
  `auto_exposure_config()` builder (Agent E, minimal diff)
- `api/app/services/batch_capture_service.py` — optional preflight + per-frame QA hooks,
  feature-gated (Agent E)
- `api/main.py` — register `exposure.router` (Agent E)
- Tests: `api/tests/test_raw_analyzer.py`, `test_exposure_controller.py`,
  `test_exposure_preflight.py`, `test_exposure_qa.py`, `test_exposure_api.py`

---

## 3. Shared Type Contract (MUST be identical across agents)

`types.py` in `api/app/services/exposure/`. Pure stdlib (`enum`, `dataclasses`, `typing`) —
no numpy at module import time so downstream agents never import numpy transitively.

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict

class QaStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    RETAKE = "RETAKE"
    FAIL = "FAIL"

class RoiType(str, Enum):
    FULL_FRAME = "full_frame"
    CENTER_CROP = "center_crop"
    CONFIGURED_ROI = "configured_roi"
    CAPTURE_AREA_MASK = "capture_area_mask"

@dataclass
class Roi:
    type: RoiType = RoiType.FULL_FRAME
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

@dataclass
class ExposureSettings:
    iso: Optional[int] = None
    aperture: Optional[float] = None
    shutter_seconds: Optional[float] = None
    shutter_label: Optional[str] = None
    camera_mode: Optional[str] = None    # e.g. "Manual"
    raw_format: Optional[str] = None     # e.g. "ARW"

@dataclass
class ShutterOption:
    label: str                 # e.g. "1/40"
    seconds: Optional[float]   # None for bulb / unparseable values

@dataclass
class ChannelMetrics:
    min_norm: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    p999: float = 0.0
    p9999: Optional[float] = None   # None when < 1e4 pixels in channel
    max_norm: float = 0.0
    clipped_count: int = 0
    clipped_fraction: float = 0.0
    near_clipped_fraction: float = 0.0

@dataclass
class ExposureAnalysisResult:
    status: str = "OK"                        # "OK" or an error code string
    raw_width: int = 0
    raw_height: int = 0
    roi: Optional[Roi] = None
    black_levels: List[float] = field(default_factory=list)
    white_levels: List[float] = field(default_factory=list)
    channel_metrics: Dict[str, ChannelMetrics] = field(default_factory=dict)  # {"R","G1","G2","B"}
    limiting_channel: Optional[str] = None
    control_percentile: float = 99.9
    measured_normalized: float = 0.0   # limiting channel value at control percentile
    target_normalized: float = 0.75
    recommended_ev: float = 0.0
    headroom_ev: float = 0.0
    clipped_count: int = 0
    clipped_fraction: float = 0.0
    near_clipped_count: int = 0
    near_clipped_fraction: float = 0.0
    underexposed_fraction: float = 0.0
    metadata_exposure: Optional[ExposureSettings] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

# Pure EV helpers (module-level functions in types.py)
def ev_correction(current: float, target: float) -> float:
    """log2(target/current). current=0.375,target=0.75 -> +1.0"""
def headroom_ev(p: float) -> float:
    """log2(1/p). p=0.5 -> 1.0, p=0.75 -> ~0.415"""
```

### `config.py` — `AutoExposureConfig`

Pydantic `BaseModel` (not BaseSettings — wiring to env is Agent E's job). Defaults are the
PRD §8/§11/§19 values, plus ISO/aperture/strategy/debug flags:

```
enabled: bool = False                      # feature-gated off by default (PRD §46)
mode: str = "fixed_sequence"
adjust: str = "shutter_only"
iso: int = 100
aperture: float = 8.0
roi_mode: str = "full_frame"               # full_frame | center_crop | configured_roi
target_percentile: float = 99.9
target_normalized: float = 0.75
acceptable_low: float = 0.60
acceptable_high: float = 0.85
near_clip_threshold: float = 0.95
hard_clip_threshold: float = 0.995
max_near_clip_fraction: float = 0.001
max_hard_clip_fraction: float = 0.00001
max_ev_error: float = 0.10
convergence_tolerance_ev: float = 0.10
max_adjustment_per_iteration_ev: float = 2.0
max_preflight_iterations: int = 5
retake_limit: int = 2
minimum_p95_normalized: float = 0.05
minimum_median_above_black: float = 0.01
preflight_strategy: str = "all_lights_safe_exposure"
light_settle_ms: int = 250
save_preflight_raws: bool = False
save_metrics_json: bool = True
```

### `controller.py` — `CameraExposureController`

```python
class CameraExposureController:
    def __init__(self, camera_service=None): ...  # injectable for tests (defaults to app singleton)

    def get_current_exposure(self) -> ExposureSettings
    def get_supported_shutter_values(self) -> List[ShutterOption]
    def get_supported_iso_values(self) -> List[int]
    def get_supported_aperture_values(self) -> List[float]
    def set_shutter(self, option: ShutterOption) -> bool
    def set_iso(self, iso: int) -> bool
    def set_aperture(self, aperture: float) -> bool
    def select_shutter(self, desired_seconds: float, prefer_safe: bool = True) -> ShutterOption
    def verify_exposure(self, expected: ExposureSettings) -> bool   # read-back comparison
    def lock_production_settings(self, exposure: ExposureSettings) -> bool  # Manual + ISO + aperture + shutter + auto-ISO off
```

Implementation rules: enumerate config via the injected camera service's `get_settings()`
list; discover shutter/ISO/aperture by matching config names against a small set of
common Sony/libgphoto2 keys (`shutterspeed`/`shutterspeed2`, `iso`, `f-number`/`aperture`)
falling back to parsing any widget whose choices look like shutter speeds / ISO steps /
f-stops. **Never hardcode a shutter table.** Raise/return `False` cleanly when the camera
does not expose a setting.

### `raw_analyzer.py` — `RawExposureAnalyzer`

```python
class RawExposureAnalyzer:
    def __init__(self, config: AutoExposureConfig): ...
    def analyze_mosaic(self, mosaic: np.ndarray, cfa_pattern, black_levels,
                       white_levels, roi: Optional[Roi] = None,
                       metadata_exposure: Optional[ExposureSettings] = None,
                       ) -> ExposureAnalysisResult
    def analyze_file(self, raw_path, roi: Optional[Roi] = None,
                     metadata_exposure: Optional[ExposureSettings] = None,
                     ) -> ExposureAnalysisResult   # rawpy adapter (not unit-tested here)
```

`analyze_mosaic` is the pure-numpy core: split the Bayer mosaic into R/G1/G2/B channels
per `cfa_pattern`, apply `(v - black[c]) / (white[c] - black[c])`, compute percentiles and
clip counts per channel **before any clamping** (PRD §7), pick the limiting channel
(highest P99.9), and compute `recommended_ev = ev_correction(measured, target)` and
`headroom_ev`. `cfa_pattern` accepted as either a `rawpy` pattern or an explicit
`{"R","G1","G2","B"}`→index mapping; non-Bayer layouts raise a clear error.

---

## 4. Orchestration Plan (ordered, parallelized)

### Round 1 — Foundations (parallel, independent)
- **Agent A** — `types.py` + `config.py` + `raw_analyzer.py` + `test_raw_analyzer.py`.
  Covers PRD G1–G5, G15, G18 (no full demosaic; percentile vectorization), G19, G20.
- **Agent B** — `controller.py` + `test_exposure_controller.py` (fake camera service).
  Covers PRD G6, and the read-back/verify half of G8.

### Round 2 — Orchestration (parallel, depend on Round 1 contract only)
- **Agent C** — `preflight.py` + `test_exposure_preflight.py`. `ALL_LIGHTS_SAFE_EXPOSURE`
  per PRD §29/§30, returns `PreflightResult` (status, selected shutter, limiting light/channel,
  predicted peak, headroom, iterations). Detects `FAIL_DYNAMIC_RANGE` (G10). Injects fake
  controller + fake light controller + a `capture_raw` callable.
- **Agent D** — `qa.py` + `state_machine.py` + `test_exposure_qa.py`. QA rules (G9/G10):
  PASS / WARNING / RETAKE / FAIL, exposure-drift detection (G8), bounded retake (retake_limit).

### Round 3 — Integration (parallel after Round 2)
- **Agent E** — `report.py` (G14 session + frame JSON), `models/exposure.py`,
  `routers/exposure.py` (G13/G44 events + endpoints), `api/app/config.py` env wiring,
  `api/main.py` registration, `batch_capture_service.py` feature-gated preflight + QA hook,
  `test_exposure_api.py`. Must keep auto-exposure **disabled by default** so existing
  manual capture is byte-for-byte unchanged (PRD §46).
- **Agent F** — Frontend (Next.js) exposure status UI + API client + preflight progress.

### Verification (orchestrator)
- Run pytest in the isolated venv (`/tmp/opencode/camvenv`): numpy/pydantic/pytest only.
  Confirm all new tests pass and no existing tests regress.

---

## 5. Explicitly Hardware-Dependent (NOT completable in this environment)

These require the physical Sony A7R III + ESP32 rig. They are **follow-ups**, not code
defects: PRD §37 (camera integration), §38 (LED integration), §39 (end-to-end), §40
(external RAW cross-check), §41 (calibration exposure sweep), §42 (photometric-stereo
before/after), and **Milestone 7 (production calibration)**. `rawpy`/`gphoto2` are only
installed inside the Docker image, not in the local dev sandbox.

---

## 6. Non-Negotiable Guardrails (from PRD §49, restated for agents)

1. Inspect the referenced files before editing; extend, do not duplicate, the camera stack.
2. Never use the embedded JPEG / demosaiced RGB for exposure control.
3. Never demosaic solely to compute clipping.
4. Never change ISO/aperture mid-sequence.
5. Never independently auto-expose each directional light in normal mode.
6. Never hide clipping with tone mapping / highlight reconstruction.
7. Never hardcode a camera shutter table.
8. Verify requested-vs-actual settings; never swallow a setting failure.
9. Never silently continue after exposure drift.
10. Keep auto-exposure off by default until validated (feature-gated).
11. Keep auto-exposure separate from color/ICC calibration.
12. Prefer small, testable domain components; no `as any`/`# type: ignore`; typed models, not loose dicts.
