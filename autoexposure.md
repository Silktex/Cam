# Auto Exposure & RAW Exposure QA for Photometric Stereo

**Document:** `autoexposure.md`  
**Status:** Implementation PRD  
**Target:** Existing photometric-stereo capture application  
**Primary camera control:** `libgphoto2` / `gphoto2`  
**Primary image input:** Camera RAW (Sony ARW currently; implementation must remain camera-agnostic where practical)  
**Primary goal:** Automatically determine and enforce a repeatable, non-clipping, radiometrically useful camera exposure for photometric-stereo fabric capture.

---

## 1. Executive Goal

Add an **Auto Exposure + Exposure QA subsystem** to the existing capture application.

The subsystem must analyze **actual RAW sensor values**, not the embedded JPEG, camera histogram, or rendered preview, and use those values to:

1. determine an appropriate camera exposure before a photometric-stereo capture sequence;
2. select a **single fixed shutter speed** for the entire normal photometric-stereo sequence;
3. verify every captured image for clipping, underexposure, unexpected exposure drift, and capture anomalies;
4. automatically retake or abort when capture quality violates configured limits;
5. record all exposure measurements and decisions as machine-readable metadata;
6. provide enough diagnostics in the UI/logs for an operator to understand why a capture passed or failed.

The system must preserve the relative intensity relationships required by photometric stereo.

> **Critical rule:** In the normal production mode, auto exposure MUST NOT independently change shutter speed between directional-light images. Exposure is solved during preflight, then locked for the sequence.

---

# 2. Why This Feature Exists

The current workflow captures fabric under controlled LED illumination. Fabric can contain:

- bright white yarns;
- dark yarns;
- saturated colored yarns;
- shiny fibers;
- small specular highlights;
- high-frequency weave structures.

Normal camera auto-exposure and camera JPEG histograms are optimized for photographic rendering, not radiometric measurement. They may be affected by JPEG tone curves, white balance, picture styles, highlight processing, and scene composition.

For photometric stereo, the application needs repeatable sensor measurements. The capture system therefore needs exposure decisions based on the linear RAW mosaic values and camera black/white levels.

---

# 3. Success Definition

The feature is complete when an operator can place a fabric sample in the capture rig, start capture, and the application can:

1. perform an exposure preflight;
2. automatically choose a safe shutter speed;
3. lock ISO, aperture, and shutter for the production sequence;
4. capture the full light sequence;
5. detect clipped or invalid frames immediately;
6. retake frames where a retake can solve the problem;
7. reject/abort when a fixed exposure cannot satisfy configured quality limits;
8. store exposure QA measurements beside the capture set;
9. show a clear `PASS`, `RETAKE`, `WARNING`, or `FAIL` status;
10. produce repeatable results without an operator manually reading the camera meter.

---

# 4. Non-Negotiable Photometric-Stereo Constraint

Photometric stereo estimates surface properties using brightness changes caused by different lighting directions.

Changing shutter speed independently for each light changes the measured intensity even when the surface and light are unchanged.

Therefore the default production workflow is:

```text
Configure camera
    ↓
Exposure preflight
    ↓
Find ONE safe exposure
    ↓
Lock exposure
    ↓
Capture all directional lights
    ↓
RAW QA every image
    ↓
Photometric-stereo processing
```

The following workflow is **NOT allowed by default**:

```text
Light 1 → auto expose → 1/30
Light 2 → auto expose → 1/60
Light 3 → auto expose → 1/40
...
```

unless an explicitly enabled calibrated mode normalizes measurements by exposure time and any calibrated light-output factors before the photometric-stereo solver.

---

# 5. Implementation Philosophy

Do not redesign the whole capture application.

The coding agent must first inspect the existing codebase and locate:

- camera abstraction;
- `libgphoto2` integration;
- Sony camera-specific handling, if present;
- capture sequence orchestration;
- LED/light controller;
- RAW download path;
- image metadata model;
- photometric-stereo processing path;
- current UI capture controls;
- logging/error handling;
- existing configuration system;
- existing tests.

The new feature should extend existing abstractions where reasonable rather than creating a parallel capture stack.

---

# 6. Phase 0 — Codebase Discovery Goal

## Goal

Understand the current capture flow before writing implementation code.

## Required investigation

The coding agent must document:

### Camera

- How a camera is discovered.
- How settings are queried.
- How ISO is set.
- How aperture is set.
- How shutter speed is set.
- How RAW/JPEG format is configured.
- Whether the application invokes the `gphoto2` CLI or links `libgphoto2` directly.
- How supported shutter values are enumerated.
- How capture success/failure is detected.
- How camera metadata is retrieved.

### Capture sequence

- How LEDs are selected.
- Whether lights are controlled sequentially.
- Whether the current sequence is 8 sides + top or configurable.
- How filenames correspond to lighting positions.
- Whether all images in one sequence currently share camera settings.

### RAW pipeline

- Where ARW files are saved.
- Whether RAW decoding already exists.
- Whether LibRaw, rawpy, dcraw, darktable, ImageMagick, OpenCV, or another RAW path is already present.
- Whether the application currently converts RAW to RGB before analysis.

### Metadata

- Existing manifest/session file structure.
- Current exposure metadata recorded per frame.
- Whether EXIF shutter/ISO/aperture values are verified after capture.

## Deliverable

Before implementation, add a short codebase-analysis section to the implementation notes or PR describing the discovered architecture and the exact integration points selected.

## Acceptance criteria

- No duplicate camera-control implementation is introduced without justification.
- Existing capture flows continue working with auto exposure disabled.

---

# 7. Functional Goals

## G1 — RAW Sensor Analyzer

### Goal

Create a reusable component that inspects RAW mosaic data without applying photographic rendering.

### Recommended implementation

Prefer, in order:

1. an existing RAW library already used by the application;
2. **LibRaw** for native C/C++ integration;
3. **rawpy** if the relevant service is Python and adding a Python dependency fits the existing architecture.

Do not use the embedded JPEG or a normal demosaiced 8-bit image to make exposure decisions.

### Required inputs

- RAW file path or RAW bytes;
- optional region of interest (ROI);
- exposure-analysis configuration.

### Required RAW metadata

Extract when available:

- visible RAW mosaic;
- CFA/Bayer pattern;
- black level, preferably per channel;
- sensor/camera white or saturation level, preferably per channel when available;
- image dimensions;
- camera make/model;
- ISO;
- shutter/exposure time;
- aperture;
- timestamp.

### Normalization

For a RAW pixel `v` belonging to CFA channel `c`:

```text
normalized(c) = (v - blackLevel[c]) / (whiteLevel[c] - blackLevel[c])
```

Clamp only for presentation/output metrics, not before clipping detection.

### Requirements

- Preserve RAW linear sensor values.
- Do not apply gamma.
- Do not apply tone curves.
- Do not apply automatic brightness.
- Do not use rendered white balance gains for clipping analysis.
- Correctly handle per-channel black/white levels when available.
- Support Bayer sensors first.
- Architect channel mapping so non-Bayer RAW layouts can fail clearly rather than silently produce incorrect results.

---

# 8. G2 — Exposure Metrics

## Goal

Produce robust metrics suitable for automatic decisions.

For the configured analysis ROI, calculate at minimum:

### Global metrics

- minimum normalized value;
- median;
- P90;
- P95;
- P99;
- P99.9;
- P99.99 if enough pixels are present;
- maximum;
- clipped pixel count;
- clipped pixel percentage;
- near-clipped pixel percentage;
- deep-shadow pixel percentage.

### Per-CFA-channel metrics

For Bayer RAW:

- R percentile metrics;
- G1 percentile metrics;
- G2 percentile metrics;
- B percentile metrics;
- clipped percentage per channel;
- highest/limiting channel.

The limiting channel is the channel nearest saturation and is used for safe-exposure decisions.

### Suggested starting thresholds

These are defaults, not immutable constants:

```yaml
exposure:
  target_percentile: 99.9
  target_normalized: 0.75
  acceptable_low: 0.60
  acceptable_high: 0.85
  near_clip_threshold: 0.95
  hard_clip_threshold: 0.995
  max_hard_clip_fraction: 0.00001
  max_near_clip_fraction: 0.001
  max_ev_error: 0.10
```

The application must make these configurable.

### Rationale

A target below sensor saturation leaves headroom for bright white yarns, weave micro-highlights, and small specular peaks.

Do not assume `0.75` is universally ideal. It is a conservative starting value and must be tunable during camera/rig calibration.

---

# 9. G3 — Robust Highlight Estimation

## Goal

Avoid letting a single hot pixel or tiny specular defect control exposure.

### Requirements

Exposure should normally be based on a high percentile, not RAW maximum.

Default:

```text
metric = maximum per-channel P99.9
```

The implementation must also report P99.99 and maximum for QA.

### Hot/dead pixel protection

The agent must evaluate the existing RAW stack for bad-pixel support.

At minimum:

- do not use the single largest pixel as the exposure controller;
- optionally reject isolated extreme pixels using connected-neighborhood or robust-statistics logic;
- never silently remove large highlight regions that may be real clipping.

### Acceptance criteria

A single abnormal pixel must not cause a multi-stop exposure reduction.

A real clipped white-yarn region must still be detected.

---

# 10. G4 — Analysis ROI

## Goal

Make exposure decisions from the fabric/measurement area rather than irrelevant frame elements.

### Modes

Support:

```text
FULL_FRAME
CENTER_CROP
CONFIGURED_ROI
CAPTURE_AREA_MASK
```

If the application already knows the physical fabric/sample capture region, use that as the default ROI.

### Exclusions

Exclude, where appropriate:

- rig edges;
- clamps;
- labels;
- LED fixtures;
- background outside the measurement area;
- permanently masked/dead pixels.

### Requirement

ROI coordinates must be stored with the session metadata so the analysis is reproducible.

---

# 11. G5 — Determine EV Correction

## Goal

Convert RAW measurement into a recommended exposure adjustment.

Given:

```text
current = measured limiting-channel normalized percentile
target  = configured target normalized value
```

Calculate:

```text
EVCorrection = log2(target / current)
```

For shutter-only adjustment:

```text
newExposureTime = oldExposureTime × 2^EVCorrection
```

### Example

```text
Current P99.9 = 0.375
Target        = 0.750

EV = log2(0.750 / 0.375)
   = +1 EV
```

The exposure time should approximately double.

### Safety rules

- If RAW data are saturated, do not infer the unclipped original signal from the clipped measurement.
- For clipping, reduce exposure conservatively and remeasure.
- Limit the maximum adjustment per iteration to a configurable value, e.g. 2 EV.
- Limit the maximum number of preflight iterations.
- Detect non-convergence.

Suggested defaults:

```yaml
max_adjustment_per_iteration_ev: 2.0
max_preflight_iterations: 5
convergence_tolerance_ev: 0.10
```

---

# 12. G6 — Camera Shutter Selection Through libgphoto2

## Goal

Map the desired exposure time to a value actually supported by the connected camera.

### Requirements

The application must query supported camera configuration values rather than assuming a fixed shutter-speed table.

Typical gphoto2 capabilities include:

```text
gphoto2 --list-config
gphoto2 --get-config <name>
gphoto2 --set-config <name>=<value>
```

The exact config key may vary by camera/driver.

### Implementation requirement

Create or extend a camera abstraction such as:

```text
CameraExposureController
  getExposureSettings()
  getSupportedShutterValues()
  setShutter(value)
  verifyShutter(value)
  lockProductionSettings()
```

Do not scatter gphoto config names throughout UI or exposure-analysis code.

### Selection logic

Given the desired exposure time:

1. enumerate supported shutter choices;
2. convert choices into seconds where possible;
3. choose the nearest safe supported value;
4. prefer the value that does not increase clipping risk when choices straddle the target;
5. set the value;
6. read back the setting if supported;
7. confirm the captured file EXIF/metadata matches expected exposure.

### Sony handling

Do not hardcode behavior solely for the Sony A7R III if the existing camera abstraction can remain generic.

Camera-specific adapters are acceptable where libgphoto2 configuration names or behaviors require them.

---

# 13. G7 — Exposure Preflight

## Goal

Automatically determine ONE production exposure before the full photometric-stereo sequence.

### Default preflight strategy

The agent must implement a configurable preflight strategy. Preferred production strategy:

### `ALL_LIGHTS_SAFE_EXPOSURE`

1. Set fixed ISO and aperture.
2. Start from configured/default shutter.
3. For each directional LED used by the sequence:
   - turn on only that light;
   - capture a preflight RAW;
   - analyze exposure;
   - compute the maximum safe shutter time for that lighting condition.
4. Choose the **shortest/safest exposure required by the brightest lighting condition**.
5. Optionally verify representative/darkest lights are not below configured signal thresholds.
6. Lock that exposure for the entire production capture.

This strategy is preferred because LED directions may not deliver identical irradiance at the sample plane.

### Faster optional strategies

Support later if useful:

```text
KNOWN_BRIGHTEST_LIGHT
CALIBRATION_REFERENCE_LIGHT
LAST_KNOWN_GOOD
SINGLE_REFERENCE_LIGHT
```

These should be optimizations, not the first implementation unless the existing application architecture makes an all-lights preflight prohibitively expensive.

### Preflight result

Return:

```json
{
  "status": "PASS",
  "selected_shutter_seconds": 0.025,
  "selected_shutter_label": "1/40",
  "iso": 100,
  "aperture": 8.0,
  "limiting_light": "front_left",
  "limiting_channel": "G1",
  "predicted_peak": 0.76,
  "headroom_ev": 0.40,
  "iterations": 2
}
```

Field names should follow existing project conventions.

---

# 14. G8 — Production Capture Exposure Lock

## Goal

Prevent accidental exposure drift during the photometric-stereo sequence.

Before production capture:

- set Manual mode where supported;
- set configured ISO;
- set configured aperture;
- set selected shutter;
- disable camera auto ISO;
- disable exposure compensation effects where relevant;
- ensure capture is RAW;
- lock software-side exposure changes.

### Important

White balance may remain fixed for preview/color processing, but **RAW clipping analysis must not depend on rendered white balance**.

### Verification

After every captured RAW, compare actual metadata against locked settings.

If exposure time, ISO, or aperture unexpectedly changes:

```text
STATUS = FAIL_EXPOSURE_DRIFT
```

Do not silently accept the frame.

---

# 15. G9 — Per-Capture Exposure QA

## Goal

Validate every frame after download.

### Required output states

```text
PASS
WARNING
RETAKE
FAIL
```

### Example rules

#### PASS

- hard clipping <= configured limit;
- near clipping <= configured limit;
- limiting percentile within acceptable range or known expected range;
- exposure metadata matches sequence lock;
- RAW decode succeeds.

#### WARNING

Examples:

- signal lower than ideal but still usable;
- small near-clip region below failure threshold;
- exposure differs modestly from preflight prediction;
- image statistics differ substantially from calibration but no hard failure exists.

#### RETAKE

Examples:

- capture/download corruption;
- temporary LED failure suspected;
- exposure setting mismatch caused by recoverable camera state;
- image acquired before LED settled;

#### FAIL

Examples:

- hard clipping exceeds threshold under the locked production exposure;
- camera settings drift repeatedly;
- RAW cannot be decoded after retry;
- LED state is invalid;
- sequence cannot satisfy required dynamic range;
- repeated retakes fail.

### Critical production behavior

If one directional frame clips because the scene has changed relative to preflight, do **not** simply shorten shutter for only that frame in normal mode.

Instead:

1. stop/mark the sequence invalid;
2. rerun preflight;
3. select a new single safe exposure;
4. recapture the entire sequence if radiometric comparability requires it.

---

# 16. G10 — Underexposure / Signal Quality

## Goal

Prevent the system from avoiding clipping by selecting an exposure that is too dark to provide useful signal.

Track at minimum:

- median above black level;
- P90/P95 signal;
- channel-specific signal;
- optional estimated signal-to-noise metric.

Suggested configurable thresholds:

```yaml
minimum_p95_normalized: 0.05
minimum_median_above_black: 0.01
```

These are starting values only and should be tuned using real capture data.

### Dynamic-range conflict

If the same fixed exposure cannot simultaneously:

- prevent unacceptable clipping in the brightest required light/frame; and
- provide adequate signal for the darkest required light/frame;

return:

```text
FAIL_DYNAMIC_RANGE
```

with diagnostics identifying the limiting frames/lights.

Do not hide this condition by independently auto-exposing each image.

---

# 17. G11 — Optional Calibrated Variable-Exposure Mode

## Goal

Allow future experiments with per-light shutter adjustment without corrupting radiometric data.

This is **not required for MVP**.

If implemented later, it must be behind an explicit configuration flag such as:

```yaml
photometric_stereo:
  allow_variable_exposure: false
```

When enabled, downstream measurement must normalize at minimum by exposure time:

```text
radiometric_value = (RAW - black) / exposure_seconds
```

and, if light intensity calibration exists:

```text
radiometric_value = (RAW - black) /
                    (exposure_seconds × calibrated_light_scale)
```

Any solver using these values must be verified to consume normalized linear data.

### Acceptance requirement

Variable-exposure mode must not be enabled merely because per-frame auto exposure is easier to implement.

---

# 18. G12 — LED Radiometric Calibration Integration

## Goal

Prepare the exposure subsystem to use existing or future LED calibration data.

If the application has LED intensity calibration, expose:

```text
light_id
commanded_brightness
measured_scale
calibration_date
calibration_version
```

### Preferred long-term system

The rig should use:

- calibrated LED geometry;
- calibrated relative LED intensity;
- fixed camera exposure;
- RAW-linear measurements.

The exposure subsystem should not duplicate LED-calibration responsibilities, but it should consume the calibration results where available.

---

# 19. G13 — UI / Operator Experience

## Goal

Make exposure status obvious without requiring photography expertise.

### Capture screen

Add an `Auto Exposure` / `Exposure QA` area consistent with the existing UI.

Suggested information:

```text
AUTO EXPOSURE
--------------------------------
Mode:            Fixed Sequence
ISO:             100
Aperture:        f/8
Current shutter: 1/40 s
Target P99.9:    75%
Measured:        73.8%
Limiting channel:G1
Near clipping:   0.002%
Hard clipping:   0.000%
Headroom:        0.44 EV
Status:          PASS
```

### Preflight status

Show progress by light:

```text
front        PASS
front_left   PASS
left         PASS
rear_left    PASS
rear         PASS
rear_right   PASS
right        PASS
front_right  PASS
top          PASS
```

### User controls

At minimum:

- Auto Exposure enabled/disabled;
- run exposure preflight;
- configured target/headroom preset if UI architecture supports advanced settings;
- show details / diagnostics;
- manual override.

### Manual override

Allow a knowledgeable operator to select shutter manually.

If manual exposure violates QA thresholds, still warn/fail according to configured policy unless QA itself is explicitly disabled.

---

# 20. G14 — Machine-Readable Session Metadata

## Goal

Make every exposure decision auditable and reproducible.

Store a session-level exposure record, e.g.:

```json
{
  "auto_exposure": {
    "version": 1,
    "mode": "fixed_sequence",
    "analysis_space": "raw_sensor",
    "roi": {
      "type": "configured_roi",
      "x": 100,
      "y": 100,
      "width": 7000,
      "height": 4500
    },
    "target_percentile": 99.9,
    "target_normalized": 0.75,
    "selected_shutter_seconds": 0.025,
    "iso": 100,
    "aperture": 8.0,
    "limiting_light": "front_left",
    "limiting_channel": "G1",
    "preflight_status": "PASS"
  }
}
```

Each frame should record:

```json
{
  "exposure_qa": {
    "status": "PASS",
    "actual_shutter_seconds": 0.025,
    "iso": 100,
    "aperture": 8.0,
    "p99_9": {
      "R": 0.65,
      "G1": 0.74,
      "G2": 0.73,
      "B": 0.58
    },
    "limiting_channel": "G1",
    "hard_clip_fraction": 0.0,
    "near_clip_fraction": 0.00003,
    "headroom_ev": 0.43
  }
}
```

Follow existing metadata naming conventions rather than forcing these exact names.

---

# 21. G15 — Headroom Metric

## Goal

Show how close a capture is to saturation in an intuitive way.

For a limiting normalized signal `p`:

```text
headroomEV = log2(1 / p)
```

Examples:

```text
p = 0.50 → 1.00 EV headroom
p = 0.75 → 0.42 EV headroom
p = 0.80 → 0.32 EV headroom
p = 0.90 → 0.15 EV headroom
```

Also report configured-target headroom separately if useful.

Do not display a misleading positive headroom when actual clipping is already present.

---

# 22. G16 — Auto Exposure State Machine

## Goal

Keep exposure behavior deterministic and testable.

Recommended state machine:

```text
IDLE
 ↓
CONFIGURING_CAMERA
 ↓
PREFLIGHT_CAPTURING
 ↓
PREFLIGHT_ANALYZING
 ↓
ADJUSTING_EXPOSURE
 ↺ until converged / limit reached
 ↓
LOCKED
 ↓
PRODUCTION_CAPTURING
 ↓
FRAME_QA
 ↺ for each light
 ↓
COMPLETE
```

Error states:

```text
FAILED_CAMERA_CONFIG
FAILED_RAW_DECODE
FAILED_NON_CONVERGENCE
FAILED_CLIPPING
FAILED_UNDEREXPOSURE
FAILED_DYNAMIC_RANGE
FAILED_EXPOSURE_DRIFT
FAILED_LED_STATE
FAILED_CAPTURE
```

All transitions must be logged.

---

# 23. G17 — Capture Synchronization

## Goal

Ensure exposure analysis is not confused by LED transition timing.

The existing LED controller must provide or expose a concept equivalent to:

```text
setLight(lightId)
waitUntilStable()
capture()
```

If no LED-settle delay exists, add a configurable value rather than hardcoding sleeps throughout capture code.

Example:

```yaml
lighting:
  settle_ms: 250
```

The appropriate value must be validated on the real rig.

---

# 24. G18 — Performance

## Goal

RAW analysis should not make capture unnecessarily slow.

### Requirements

- Do not demosaic a full-resolution RGB image solely to calculate exposure.
- Operate on RAW mosaic data.
- Use vectorized/native operations where available.
- Permit downsampling/subsampling for percentile calculation only if tests prove decisions remain equivalent within configured tolerance.
- Do not modify/save another full image unless required.

### Target

Exposure analysis should be small relative to camera capture/download time on the production machine.

The agent should benchmark rather than invent a fixed time requirement before seeing existing hardware and code.

---

# 25. G19 — Configuration

Add settings through the application's existing configuration mechanism.

Conceptual configuration:

```yaml
auto_exposure:
  enabled: true
  mode: fixed_sequence

  camera:
    iso: 100
    aperture: 8.0
    adjust: shutter_only

  analysis:
    roi: capture_area
    target_percentile: 99.9
    target_normalized: 0.75
    acceptable_low: 0.60
    acceptable_high: 0.85
    near_clip_threshold: 0.95
    hard_clip_threshold: 0.995
    max_near_clip_fraction: 0.001
    max_hard_clip_fraction: 0.00001

  control:
    convergence_tolerance_ev: 0.10
    max_adjustment_per_iteration_ev: 2.0
    max_preflight_iterations: 5
    retake_limit: 2

  underexposure:
    minimum_p95_normalized: 0.05
    minimum_median_above_black: 0.01

  preflight:
    strategy: all_lights_safe_exposure

  debug:
    save_preflight_raws: false
    save_metrics_json: true
```

Exact schema must match existing project conventions.

---

# 26. G20 — Debug Artifacts

## Goal

Make calibration and field debugging possible.

Optional debug outputs:

- JSON exposure report;
- histogram data;
- per-channel histogram data;
- clipped-pixel mask;
- near-clipped-pixel mask;
- ROI mask;
- preflight RAW files;
- human-readable session summary.

Do not require debug artifacts in normal production if they consume excessive storage.

---

# 27. Exposure Analysis Result Contract

Create a typed/domain object equivalent to:

```text
ExposureAnalysisResult
  status
  rawWidth
  rawHeight
  roi
  blackLevels[]
  whiteLevels[]
  channelMetrics{}
  limitingChannel
  controlPercentile
  measuredNormalized
  targetNormalized
  recommendedEv
  headroomEv
  clippedCount
  clippedFraction
  nearClippedCount
  nearClippedFraction
  underexposedFraction
  metadataExposure
  warnings[]
  errors[]
```

Avoid passing loose dictionaries through core capture orchestration if the project language supports typed models.

---

# 28. Camera Exposure Controller Contract

Create or extend an abstraction equivalent to:

```text
CameraExposureController

getCurrentExposure(): ExposureSettings
getSupportedShutterValues(): ShutterOption[]
setShutter(option): Result
verifyExposure(expected): VerificationResult
captureRaw(...): CaptureResult
```

`ExposureSettings` should include:

```text
ISO
aperture
shutterSeconds
shutterLabel
cameraMode
rawFormat
```

---

# 29. Preflight Algorithm — Reference Pseudocode

```text
function determineFixedSequenceExposure(lights):
    configureManualCamera()
    candidateLimits = []

    for light in lights:
        activateOnly(light)
        waitForLightStable()

        exposure = initialExposureFor(light)

        for iteration in 1..maxIterations:
            raw = captureRaw()
            analysis = analyzeRaw(raw)

            if analysis.hasHardClipping:
                correction = safeNegativeCorrection(analysis)
            else:
                correction = log2(target / analysis.controlValue)

            if abs(correction) <= convergenceTolerance:
                break

            exposure = chooseSupportedShutter(
                exposure * 2^clamp(correction)
            )
            setShutter(exposure)

        candidateLimits.append(
            maximumSafeExposureForThisLight(analysis, exposure)
        )

    selectedExposure = min(candidateLimits)

    setShutter(selectedExposure)
    verifyCameraExposure()

    validation = validateSelectedExposureAcrossLights(lights)

    if validation.dynamicRangeFailure:
        return FAIL_DYNAMIC_RANGE

    return LOCKED(selectedExposure)
```

The implementation can optimize the number of captures, but correctness is more important than minimizing preflight frames in the first release.

---

# 30. Improved Preflight Optimization

After MVP correctness is established, reduce captures by exploiting approximate linearity.

If a non-clipped measurement exists:

```text
predictedSignalNew = signalOld × (tNew / tOld)
```

The controller can calculate the next shutter directly rather than binary searching.

Always verify the calculated setting with an actual RAW capture before locking production exposure.

---

# 31. Sequence Validation

Immediately before starting the full sequence:

1. confirm selected shutter;
2. confirm ISO;
3. confirm aperture;
4. confirm RAW mode;
5. confirm no unsupported auto-exposure mode is active;
6. confirm all required light IDs are available;
7. confirm exposure preflight is current for the active session/sample;
8. start sequence.

If the operator changes camera settings after preflight, invalidate preflight.

---

# 32. Invalidation Rules

Exposure preflight must be considered stale when relevant conditions change.

Invalidate and rerun when any of the following occurs:

- ISO changes;
- aperture changes;
- camera changes;
- lens/aperture configuration changes materially;
- LED brightness configuration changes;
- light calibration changes;
- capture ROI changes materially;
- a new fabric sample is loaded, unless operator/workflow explicitly allows reuse;
- camera reconnect/reset makes exposure state uncertain.

Consider allowing `last known good` as a starting exposure, but not as a substitute for QA.

---

# 33. Error Handling

Every error should state:

```text
what failed
where it failed
whether capture can retry
what the application did
what the operator should check
```

Examples:

### Camera setting rejected

```text
AUTO_EXPOSURE_CAMERA_SET_FAILED
Requested shutter: 1/40
Camera value before: 1/30
Camera value after: 1/30
Action: capture aborted
```

### RAW decode failure

```text
AUTO_EXPOSURE_RAW_DECODE_FAILED
File: session123/front_left.ARW
Retry: 1/2
```

### Dynamic range failure

```text
AUTO_EXPOSURE_DYNAMIC_RANGE_FAILED
Brightest light: top
Darkest light: rear_left
Safe exposure for clipping: <= 1/80
Minimum exposure for signal: >= 1/30
Action: sequence aborted
Suggested check: LED intensity calibration / lighting geometry
```

---

# 34. Logging

Use structured logs.

Log at minimum:

```text
session id
camera identifier
camera model
light id
preflight iteration
requested shutter
actual shutter
ISO
aperture
RAW black levels
RAW white levels
limiting channel
control percentile
normalized control value
hard clipping fraction
near clipping fraction
recommended EV
selected exposure
QA status
failure reason
```

Do not log giant arrays/histograms at normal info level.

---

# 35. Tests — Unit

## RAW normalization

Test:

```text
black = 512
white = 16383
raw = 8447
```

Verify expected normalized value.

Test per-channel black/white values.

## Percentiles

- known synthetic mosaic;
- known outliers;
- one hot pixel;
- real highlight area;
- insufficient pixels for P99.99.

## EV calculation

Test:

```text
current 0.375 target 0.75 => +1 EV
current 0.75  target 0.75 => 0 EV
current 0.90  target 0.75 => negative EV
```

## Shutter mapping

Given a simulated supported shutter list, test:

- exact match;
- nearest safe match;
- minimum/maximum camera limit;
- nonstandard shutter labels;
- bulb/unsupported values.

## QA state

Test all transitions:

```text
PASS
WARNING
RETAKE
FAIL_CLIPPING
FAIL_UNDEREXPOSURE
FAIL_DYNAMIC_RANGE
FAIL_EXPOSURE_DRIFT
```

---

# 36. Tests — RAW Fixtures

Create a small test fixture set using real RAW captures from the production camera.

Include at minimum:

1. intentionally underexposed fabric;
2. good exposure;
3. near-clipped white fabric/yarn;
4. clearly clipped white yarn;
5. dark fabric;
6. saturated colored fabric;
7. shiny/specular fabric;
8. image containing a few hot pixels;
9. representative aqua + white-yarn sample that previously caused visual exposure/color concerns.

Do not commit huge RAW files to the main repository if repository policy discourages them. Use the project's fixture/storage mechanism.

---

# 37. Tests — Camera Integration

With the real libgphoto2-connected camera:

- enumerate shutter values;
- set several shutter values;
- read them back;
- capture RAW;
- verify RAW EXIF exposure matches requested value;
- verify auto ISO is off;
- verify ISO is stable;
- verify aperture is stable;
- disconnect/reconnect and verify clean recovery;
- reject a setting the camera does not support;
- verify no independent exposure changes occur during a production sequence.

---

# 38. Tests — LED Integration

For each configured directional light:

1. activate light;
2. wait for stability;
3. capture reference RAW;
4. calculate metrics;
5. ensure correct light ID is associated with file/metrics;
6. ensure all other controlled lights are off when required.

Test failure where an LED does not activate or its measured signal differs drastically from baseline.

---

# 39. Tests — End-to-End

## E2E-1: Normal fabric

Expected:

```text
preflight → fixed exposure → complete capture → all PASS
```

## E2E-2: White fabric

Expected:

```text
preflight lowers exposure → no unacceptable clipping → capture succeeds
```

## E2E-3: Very dark fabric

Expected:

```text
preflight raises exposure → adequate signal → capture succeeds or reports dynamic-range conflict
```

## E2E-4: Highly reflective textile

Expected:

```text
highlight percentile remains robust
real clipped regions detected
safe exposure selected or clear failure returned
```

## E2E-5: Camera setting changes during sequence

Expected:

```text
exposure drift detected
sequence invalidated
no silent continuation
```

## E2E-6: Brightness changes after preflight

Expected:

```text
frame QA catches discrepancy
normal mode does not independently modify that one frame's shutter
sequence reruns preflight / invalidates as designed
```

---

# 40. Validation Against External RAW Inspection

During development, compare application metrics against an independent RAW-analysis tool or known-good LibRaw/rawpy script.

For selected real ARW fixtures, confirm:

- RAW black level interpretation;
- RAW white level interpretation;
- channel assignment;
- clipping count;
- high-percentile values;
- exposure trend across shutter changes.

The objective is not to match a rendered histogram. It is to verify the sensor-domain analysis.

---

# 41. Calibration Experiment Before Finalizing Defaults

Do not finalize `target_normalized`, clipping limits, and underexposure limits solely from theory.

Run a controlled exposure sweep on the production rig.

Suggested process:

```text
ISO fixed
aperture fixed
LED fixed
sample fixed

capture -2 EV
capture -1.5 EV
capture -1 EV
capture -0.5 EV
capture nominal
capture +0.5 EV
capture +1 EV
```

Use representative samples:

- white;
- black;
- saturated aqua/blue;
- neutral gray;
- shiny fabric;
- normal midtone fabric.

For each exposure, compare:

- RAW clipping;
- noise;
- recovered albedo;
- normal-map stability;
- photometric-stereo residual/error if available;
- color accuracy after the calibrated color pipeline.

Use these results to set production defaults.

---

# 42. Photometric-Stereo Correctness Validation

The feature is not complete merely because images look properly exposed.

Compare before/after datasets using the photometric-stereo solver.

Measure where available:

- solver residual;
- normal stability;
- normal discontinuities;
- recovered albedo stability;
- highlight clipping artifacts;
- repeatability between repeated captures.

A visually attractive exposure is secondary to stable radiometric input.

---

# 43. Color Pipeline Boundary

Auto exposure must remain logically separate from color calibration.

Auto exposure owns:

```text
sensor headroom
clipping
signal level
camera exposure
exposure QA
```

Color calibration owns:

```text
camera spectral/color response
white balance / chromatic adaptation
camera profile / ICC/DCP or equivalent transform
color target calibration
output color space
```

Do not alter RAW RGB channel values with arbitrary color correction before exposure/clipping analysis.

---

# 44. API / Service Integration

If capture is controlled through an API/WebSocket layer, expose status without tying the domain logic to transport.

Possible events:

```text
exposure.preflight.started
exposure.preflight.frame
exposure.preflight.adjusted
exposure.preflight.completed
exposure.locked
exposure.qa.completed
exposure.warning
exposure.failed
```

Example payload:

```json
{
  "event": "exposure.qa.completed",
  "sessionId": "...",
  "lightId": "front_left",
  "status": "PASS",
  "shutterSeconds": 0.025,
  "limitingChannel": "G1",
  "p99_9": 0.738,
  "hardClipFraction": 0.0,
  "headroomEv": 0.44
}
```

Use the application's current event/API conventions.

---

# 45. Security / Safety / Reliability

- Never repeatedly hammer camera configuration without a retry limit.
- Use bounded retries.
- Ensure temporary/preflight files are cleaned according to existing storage rules.
- Preserve originals for failed production captures if debug policy requests them.
- Do not delete an existing valid capture set until a replacement set completes successfully.
- Restore safe light state on abort.
- Turn lights off on unhandled capture failure where existing rig behavior expects this.

---

# 46. Backward Compatibility

Auto exposure must be feature-gated initially.

```yaml
auto_exposure:
  enabled: false
```

or use the project's normal feature-flag/config mechanism.

With auto exposure disabled:

- existing manual capture must behave as it does now;
- existing output formats must remain valid;
- new metadata fields may be absent/null without breaking old readers.

After validation, default can be changed deliberately.

---

# 47. Rollout Plan

## Milestone 1 — RAW Analyzer

Deliver:

- RAW read;
- black/white normalization;
- per-channel statistics;
- clipping metrics;
- CLI/dev diagnostic tool if useful;
- unit tests;
- real ARW fixtures.

**Exit criterion:** exposure metrics are validated against independent RAW inspection.

---

## Milestone 2 — Camera Exposure Controller

Deliver:

- query shutter choices;
- set shutter;
- verify shutter;
- exposure-domain types;
- simulated camera tests;
- real camera integration test.

**Exit criterion:** requested shutter and captured RAW metadata agree reliably.

---

## Milestone 3 — Single-Light Auto Exposure

Deliver:

- capture/analyze/adjust loop;
- convergence;
- retry/error states;
- logging.

**Exit criterion:** system automatically converges to configured RAW target on representative fabrics.

---

## Milestone 4 — All-Light Preflight + Fixed Sequence Lock

Deliver:

- evaluate all production lights;
- select one safe shutter;
- lock production exposure;
- detect dynamic-range conflict.

**Exit criterion:** no directional frame independently changes exposure in normal mode.

---

## Milestone 5 — Per-Frame QA + Retake/Abort

Deliver:

- QA after every capture;
- clipping/underexposure detection;
- exposure drift detection;
- recoverable retakes;
- sequence invalidation when fixed exposure must change.

**Exit criterion:** bad frames cannot silently enter the photometric-stereo dataset.

---

## Milestone 6 — UI + Session Reports

Deliver:

- preflight status;
- selected exposure;
- channel/clip diagnostics;
- session metadata;
- human-readable status.

**Exit criterion:** operator can understand the exposure decision without inspecting logs.

---

## Milestone 7 — Production Calibration

Deliver:

- exposure sweep dataset;
- chosen production thresholds;
- documented camera/rig defaults;
- before/after photometric-stereo comparison.

**Exit criterion:** defaults are based on measured rig behavior rather than arbitrary constants.

---

# 48. Definition of Done

This feature is done only when all of the following are true:

- [ ] Existing camera/capture architecture was inspected before implementation.
- [ ] RAW sensor data, not rendered JPEG data, drives exposure decisions.
- [ ] Black levels are handled correctly.
- [ ] White/saturation levels are handled correctly.
- [ ] Bayer channels are analyzed independently.
- [ ] Robust high-percentile statistics are implemented.
- [ ] Real clipping is measured.
- [ ] Hot-pixel outliers cannot dominate exposure.
- [ ] Exposure correction is expressed in EV.
- [ ] Desired shutter is mapped to camera-supported values.
- [ ] Camera setting is verified after being applied.
- [ ] Preflight selects a single production shutter in normal mode.
- [ ] ISO and aperture are stable throughout the sequence.
- [ ] Shutter is stable throughout the sequence.
- [ ] Actual exposure metadata is verified per frame.
- [ ] Every production RAW receives exposure QA.
- [ ] Clipped frames cannot silently pass.
- [ ] Underexposed frames cannot silently pass when signal is below configured requirements.
- [ ] Dynamic-range conflict is reported explicitly.
- [ ] Per-light variable exposure is disabled by default.
- [ ] Exposure metrics are persisted with the session.
- [ ] Failures use structured error codes/reasons.
- [ ] Unit tests pass.
- [ ] Camera integration tests pass.
- [ ] LED integration tests pass.
- [ ] End-to-end capture tests pass.
- [ ] Representative white, dark, colored, and shiny fabrics were tested.
- [ ] Production thresholds were validated using an exposure sweep.
- [ ] Photometric-stereo output was compared before/after the change.
- [ ] Existing manual workflow still works when feature is disabled.

---

# 49. Coding-Agent Guardrails

The coding agent must follow these rules:

1. **Inspect first, modify second.** Do not invent a new architecture without understanding the existing one.
2. **Do not use JPEG histograms for exposure control.**
3. **Do not demosaic merely to calculate RAW clipping.**
4. **Do not modify ISO during a production sequence.**
5. **Do not modify aperture during a production sequence.**
6. **Do not independently auto-expose each directional image in normal photometric-stereo mode.**
7. **Do not hide clipping by tone mapping or highlight reconstruction.**
8. **Do not treat an image as valid merely because it visually looks good.**
9. **Do not hardcode one camera's shutter list when libgphoto2 can report supported values.**
10. **Do not swallow camera-setting failures.** Verify requested vs actual settings.
11. **Do not silently continue after unexpected exposure drift.**
12. **Do not finalize production thresholds without tests on real rig RAW files.**
13. **Preserve backward compatibility until the new flow is validated.**
14. **Keep auto exposure separate from color-profile/ICC calibration.**
15. **Prefer small, testable domain components over one large capture function.**

---

# 50. Recommended Component Boundaries

A clean implementation will likely have responsibilities similar to:

```text
camera/
  CameraController
  CameraExposureController

raw/
  RawReader
  RawMetadata
  RawExposureAnalyzer

exposure/
  ExposureConfig
  ExposureMetrics
  ExposureDecision
  ExposurePreflightService
  ExposureQaService

capture/
  CaptureSequence
  CaptureFrame
  CaptureSession

lighting/
  LightController
  LightCalibration
```

These names are illustrative.

Use the existing repository's language, folder structure, dependency injection pattern, services, and naming conventions.

---

# 51. Research / Technical References

Use current official documentation during implementation because camera-driver details and RAW-library APIs can change.

### gPhoto2 / libgphoto2

- gPhoto project: https://www.gphoto.org/
- gphoto2 CLI manual: https://gphoto.github.io/doc/manual/ref-gphoto2-cli.html
- libgphoto2 API: https://gphoto.github.io/doc/api/
- Camera API/configuration: https://gphoto.github.io/doc/api/gphoto2-camera_8h.html
- Remote camera control notes: https://gphoto.github.io/doc/remote/
- Source repository: https://github.com/gphoto/libgphoto2

Relevant capabilities include camera capture, listing configuration, reading configuration, setting configuration, and camera-level capture/configuration APIs.

### LibRaw

- Source repository: https://github.com/LibRaw/LibRaw
- LibRaw exposes RAW pixel values and metadata needed for processing, including CFA/geometry and black/white-level information.

### rawpy

- Source repository: https://github.com/letmaik/rawpy
- Documentation: https://letmaik.github.io/rawpy/
- rawpy is a Python wrapper over LibRaw and exposes RAW-visible arrays and RAW metadata suitable for implementing the analyzer in Python.

---

# 52. Final Product Behavior

The desired production experience is:

```text
Operator loads fabric
        ↓
Start capture
        ↓
Application checks camera
        ↓
Application runs RAW exposure preflight
        ↓
Application evaluates all required lights
        ↓
Application chooses one safe shutter
        ↓
ISO + aperture + shutter are locked
        ↓
Photometric-stereo sequence captures
        ↓
Every RAW is validated
        ↓
Any invalid sequence is rejected/retried correctly
        ↓
Only radiometrically valid images reach the solver
```

The goal is not merely "automatic camera exposure."

The goal is a **repeatable radiometric acquisition system** that protects the quality of the albedo, normal, height, roughness, and future material-reconstruction pipeline.
