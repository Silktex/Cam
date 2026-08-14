# Texturizing Branch — Material Creation Tools

> **Branch:** `texturizing`
> **Base:** `main`
> **Latest Commit:** Flatten tool (9th material creation tool)
> **Scope:** 37 files changed, ~8,700 lines added

---

## Executive Summary

The texturizing branch introduces **9 interactive material creation tools** that transform calibrated multi-angle fabric photographs into production-quality tileable textures with PBR maps. These tools bridge the gap between raw color-calibrated captures and final game/render-ready materials, providing a workflow inspired by Adobe Substance 3D Sampler and SEDDI Textura.

The implementation spans the full stack: 9 Python image processing services built on OpenCV and NumPy, a FastAPI router with 26+ endpoints, 10 reusable React components (including Konva canvas, Three.js 3D preview, and interactive before/after comparison), 8 dedicated tool page UIs with a shared hub interface, and the Yarn Straighten tool integrated directly into the crop page sidebar.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PROCESSING PIPELINE                         │
│                                                                     │
│  RAW → TIFF → Cropped → Color Calibrated → Equalized → Flattened  │
│                                                              │      │
│                                   Delighted ◄────────────────┘      │
│                                       │                             │
│                              Perspective Corrected ◄─────────┘      │
│                                       │                             │
│                                   Straightened                      │
│                                       │                             │
│                                   Seamless → Tiled                  │
│                                       │                             │
│                                   Cleaned (Clone)                   │
│                                       │                             │
│                                PBR Maps → Validate                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Frontend** sends parameters → **Backend** processes the top image → returns preview URL → user confirms → backend applies to all images in the batch. This mirrors the established crop tool pattern.

### Design Decisions

- **All pixel manipulation is server-side.** No OpenCV.js (8–15 MB WASM) in the browser. The frontend handles only parameter input, canvas interaction, and image display.
- **Source folder priority.** Each tool reads from the highest-quality available input folder, forming an implicit dependency chain that allows steps to be skipped.
- **Top image convention.** Previews always process the `_top` image first (the primary capture angle), falling back to alphabetical first.
- **16-bit preservation.** Services detect `uint16` input, downscale to 8-bit for OpenCV processing, then upscale back, preserving the original bit depth in TIFF output.

---

## The Nine Tools

| # | Tool | Purpose | Algorithm(s) |
|---|------|---------|--------------|
| 1 | **Equalize** | Match exposure and color across multi-angle captures | CLAHE, histogram matching, exposure matching |
| 2 | **Delight** | Remove uneven lighting gradients | Gaussian division, frequency separation |
| 3 | **Flatten** | Remove surface wrinkles/folds using PBR normal maps | Normal map cos(θ) shading correction in LAB space |
| 4 | **Perspective** | Correct keystone and skew distortion | Hough line detection, 4-point homography |
| 5 | **Seamless** | Blend edges for seamless tiling | Overlay shift+blend, mirror-fold, Poisson clone |
| 6 | **Tiling** | Preview and export repeating tile patterns | Configurable grid with rotation, overlap, half-drop |
| 7 | **PBR Validate** | Verify PBR map value ranges | Albedo brightness check, metallic binary check |
| 8 | **Clone Stamp** | Remove lint, threads, dust | Telea/Navier-Stokes inpainting, clone stamp |
| 9 | **Yarn Straighten** | Correct yarn skew and bow in woven fabrics | FFT angular projection, strip Hough, cv2.remap bow correction |

---

## Backend Services

The texturizing pipeline is implemented as 9 Python service modules in `api/scripts/processing/`, exposed through a single FastAPI router at `api/app/routers/processing.py`. Each service follows a consistent `preview()` / `apply()` pattern: preview processes only the top image and returns before/after URLs; apply processes all images in the batch and writes to a dedicated output subfolder.

### Source Folder Priority System

Each service reads from the most-processed available folder, creating a cascading dependency chain. If a step is skipped, the next tool automatically falls back to the best available input.

| Service | Source Priority (highest to lowest) |
|---|---|
| **Equalize** | `color_calibrated` > `cropped` > `tiff` |
| **Flatten** | `equalized` > `color_calibrated` > `cropped` > `tiff` |
| **Delight** | `flattened` > `equalized` > `color_calibrated` > `cropped` > `tiff` |
| **Perspective** | `color_calibrated` > `cropped` > `tiff` |
| **Straighten** | `perspective_corrected` > `color_calibrated` > `cropped` > `tiff` |
| **Seamless** | `straightened` > `delighted` > `flattened` > `equalized` > `color_calibrated` > `cropped` > `tiff` |
| **Tile** | `seamless` > `straightened` > `delighted` > `flattened` > `equalized` > `cropped` > `tiff` |
| **Clone** | `seamless` > `straightened` > `delighted` > `flattened` > `equalized` > `cropped` > `tiff` |
| **Validate** | `pbr_grayscale` > `pbr_colored` |

### Bit Depth Handling

All services preserve 16-bit TIFF data through a consistent pattern:

1. **Detection**: Check `image.dtype == np.uint16` at function entry
2. **Downscale for processing**: Convert to 8-bit via `(image / 256).astype(np.uint8)` — most OpenCV algorithms require 8-bit input
3. **Upscale on output**: Convert back via `(result.astype(np.uint16) * 256)`
4. **Full-resolution save**: Output to TIFF preserving the original bit depth
5. **Preview save**: Always converted to 8-bit JPEG for web display

### Output Folder Conventions

| Service | Full Output Folder | Thumbnail Folder |
|---|---|---|
| Equalize | `equalized/` | `equalized_thumbnail/` |
| Delight | `delighted/` | `delighted_thumbnail/` |
| Flatten | `flattened/` | `flattened_thumbnail/` |
| Perspective | `perspective_corrected/` | `perspective_corrected_thumbnail/` |
| Straighten | `straightened/` | `straightened_thumbnail/` |
| Seamless | `seamless/` | `seamless_thumbnail/` |
| Tile | `tiled/` | `tiled_thumbnail/` |
| Clone | `cleaned/` | `cleaned_thumbnail/` |
| Validate | `validate_preview/` | *(analysis only, no batch output)* |

Full outputs are saved as `.tiff` files. Thumbnails are `.jpg` at max 800px. Preview images go to `{tool}_preview/` subfolders as JPEG at max 1200–1600px.

---

### Service Reference

#### 1. Equalize Service

**File**: `api/scripts/processing/equalize_service.py`

Ensures consistent brightness and contrast across all images in a batch. Operates in LAB color space to adjust luminance without shifting color.

| Method | Function | Algorithm |
|---|---|---|
| `clahe` | `equalize_clahe()` | CLAHE (Contrast Limited Adaptive Histogram Equalization) on the L channel. Uses `cv2.createCLAHE(clipLimit, tileGridSize=(8,8))`. |
| `histogram_match` | `equalize_histogram_match()` | Per-channel CDF matching. Builds a 256-entry lookup table by finding the closest CDF value in the reference for each source intensity. |
| `exposure_match` | `equalize_exposure_match()` | Mean-luminance normalization in LAB space. Computes `scale = ref_L_mean / src_L_mean` and applies to the L channel. |

```python
def preview(batch_path, method='clahe', reference_image=None, clip_limit=2.0) -> Dict
# Returns: before_url, after_url, before_histogram, after_histogram, method, source_image, image_count

def apply(batch_path, method='clahe', reference_image=None, clip_limit=2.0) -> Dict
# Returns: success, processed, total, method, output_dir, errors
```

---

#### 2. Delight Service

**File**: `api/scripts/processing/delight_service.py`

Removes uneven lighting from material textures to produce flat, evenly-lit surfaces suitable for tiling and PBR workflows.

| Method | Function | Algorithm |
|---|---|---|
| `gaussian` | `delight_gaussian()` | Divides the L channel by a heavily blurred version of itself, then rescales to preserve mean luminance. Blends with original using `strength` parameter. |
| `frequency_separation` | `delight_frequency_separation()` | Separates image into low-frequency (lighting) and high-frequency (detail). Replaces low-frequency with flat uniform color, then recombines: `result = blended_low + high_freq - 128`. |

```python
def preview(batch_path, blur_radius=200, strength=1.0, method='gaussian') -> Dict
# Returns: before_url, after_url, method, blur_radius, strength, source_image, image_count

def apply(batch_path, blur_radius=200, strength=1.0, method='gaussian') -> Dict
# Returns: success, processed, total, method, output_dir, errors
```

---

#### 3. Flatten Service

**File**: `api/scripts/processing/flatten_service.py`

Removes surface undulation from fabric textures using PBR normal maps. The normal map encodes surface orientation; dividing the L channel by `cos(θ)` (the z-component of the normal) compensates for geometry-induced shading, making the texture appear flat.

Requires PBR maps to be generated first (normal map needed). Automatically locates normals from `pbr_grayscale/normals.png` or `pbr_colored/normals.png`, with fallback between modes.

| Step | Algorithm |
|---|---|
| Load normals | Decode RGB to [-1,1] vectors: `(rgb / max_val) * 2.0 - 1.0` (handles 8-bit and 16-bit) |
| Smooth normals | Optional Gaussian blur on each channel, then re-normalize |
| Compute shading | `cos_theta = normals[:,:,2]`, clamped to [0.05, 1.0] |
| Correct luminance | Convert to LAB, divide L by cos_theta, normalize to preserve mean |
| Blend | `l_result = l_original * (1 - strength) + l_corrected * strength` |

```python
def preview(batch_path, strength=1.0, smoothing_radius=0, pbr_mode='grayscale') -> Dict
# Returns: before_url, after_url, strength, smoothing_radius, pbr_mode, source_image, image_count

def apply(batch_path, strength=1.0, smoothing_radius=0, pbr_mode='grayscale') -> Dict
# Returns: success, processed, total, pbr_mode, output_dir, errors
```

---

#### 4. Perspective Service

**File**: `api/scripts/processing/perspective_service.py`

Detects lines using Hough transform and applies perspective correction via `cv2.getPerspectiveTransform` + `cv2.warpPerspective`.

**Three-step workflow**: `detect_lines()` → `preview()` → `apply()`

- **Line detection**: Canny edge detection (threshold 50/150) followed by probabilistic Hough transform (`cv2.HoughLinesP`, threshold=100, minLineLength=100, maxLineGap=10). Lines classified as horizontal/vertical by angle, then split into top/bottom and left/right groups by position.
- **Perspective transform**: 4-point homography. Source points from user adjustment (or auto-detected). Destination rectangle computed from average of top/bottom widths and left/right heights.

```python
def detect_lines(image_path: Path) -> dict
# Returns: suggested_corners (4 points TL/TR/BR/BL), detected_lines (up to 50), image dimensions
# Fallback: 5% inset rectangle if no lines detected

def preview(batch_path, source_points, dest_points=None) -> dict
def apply(batch_path, source_points, dest_points=None) -> dict
```

---

#### 5. Seamless Service

**File**: `api/scripts/processing/seamless_service.py`

Makes textures tile seamlessly using three blending methods. Includes seam quality analysis via L2 edge distance measurement.

| Method | Function | Algorithm |
|---|---|---|
| `overlay` | `make_seamless_overlay()` | Shifts image by half dimensions (`np.roll`), applies linear feather blending at seam boundaries. Optional `spots_removal` (median filter) and `color_equalizer` (Gaussian blur ratio correction). |
| `mirror` | `make_seamless_mirror()` | Mirror-folds all four edges with linear alpha ramp across the blend zone. |
| `poisson` | `make_seamless_poisson()` | Creates 2x2 tiled version, extracts center crop, uses `cv2.seamlessClone(MIXED_CLONE)` to blend seam regions. Falls back to mirror on failure. |

```python
def analyze_seams(image_path, blend_width=128) -> dict
# Compares opposite edges via L2 distance
# Returns: scores (top, bottom, left, right), overall_score, blend_width

def preview(batch_path, method='overlay', blend_width=128, spots_removal=False,
            color_equalizer=0, tile_count=3) -> dict
# Returns: preview_url, tiled_url, original_url, seam_scores, overall_score

def apply(batch_path, method='overlay', blend_width=128, ...) -> dict
```

---

#### 6. Tile Service

**File**: `api/scripts/processing/tile_service.py`

Generates tiled/repeated texture previews and exports with configurable layout parameters.

The `generate_tiled_preview()` function:
1. Scales tile to `width × scale`
2. Applies rotation with `BORDER_WRAP` for seamless edges
3. Calculates step size with overlap: `step = tile_size × (1 - overlap)`
4. Places tiles on canvas with offset positioning
5. If `half_drop = True`, odd rows shift by `step_x / 2`

```python
def generate_tiled_preview(image, tile_x=3, tile_y=3, offset_x=0.0, offset_y=0.0,
                           scale=1.0, rotation=0.0, overlap=0.0, half_drop=False,
                           output_size=(1200, 1200)) -> np.ndarray

def preview(batch_path, ...) -> Dict
def apply(batch_path, ..., output_resolution=(2048, 2048)) -> Dict
```

Unlike other services, tile operates only on the top image (single tile source).

---

#### 7. Validate Service (PBR)

**File**: `api/scripts/processing/validate_service.py`

Analysis-only service for PBR map validation. Reads from PBR output folders, checks value ranges, generates diagnostic heatmap overlays.

**PBR map detection** uses keyword matching: `albedo` → diffuse/base_color, `normal` → norm/nrm, `roughness` → rough/gloss, `height` → displacement/disp/bump, `metallic` → metal/metalness, `ao` → ambient_occlusion/occlusion.

```python
def validate_albedo(batch_path, dark_threshold=30) -> Dict
# Flags pixels below threshold (dark) and above 240 (bright)
# Pass: both < 5%. Heatmap: green=OK, red=dark, orange=bright

def validate_metallic(batch_path, metal_range=(180, 255)) -> Dict
# Checks binary distribution. Pass: ambiguous_pct < 10%

def get_stats(batch_path) -> Dict
# Returns per-channel min/max/mean and histograms for all detected maps

def generate_overlay(batch_path, mode="albedo", threshold=30) -> Dict
```

---

#### 8. Clone Service

**File**: `api/scripts/processing/clone_service.py`

Inpainting and clone-stamp tool for cleaning textures. Accepts base64-encoded PNG masks.

| Method | Function | Algorithm |
|---|---|---|
| Inpaint (Telea) | `inpaint()` | `cv2.inpaint()` with `INPAINT_TELEA` — fast marching method |
| Inpaint (Navier-Stokes) | `inpaint()` | `cv2.inpaint()` with `INPAINT_NS` — fluid dynamics approach |
| Clone Stamp | `clone_stamp()` | Circular region copy with Gaussian-blurred soft edges, configurable fade and mirror |

```python
def inpaint(image_path, mask_data_b64, method='telea', radius=3) -> Optional[np.ndarray]
def clone_stamp(image_path, source_pos, target_pos, radius=25,
                fade=0.8, blur_mask=0.3, mirror=False) -> Optional[np.ndarray]
def apply(batch_path, operations: List[Dict]) -> Dict
# Operations: [{type: 'inpaint', mask_data, method, radius}, {type: 'stamp', source_pos, target_pos, ...}]
```

`apply()` processes only the top image, applying operations sequentially. Mask decoding handles both raw base64 and data URL prefixed formats.

---

#### 9. Straighten Service (Yarn Straighten)

**File**: `api/scripts/processing/straighten_service.py`

Detects and corrects yarn skew (global rotation) and bow (local curvature) in woven fabric textures. Integrated into the crop page sidebar rather than having its own dedicated tool page.

**Three-step workflow**: `analyze()` → `preview()` → `apply()`

| Component | Algorithm |
|---|---|
| Global skew detection | 2D FFT power spectrum with Hanning window. Angular projection sums power along radial lines at 0.5-degree resolution. Dominant peak deviation from 0/90/180 = skew angle. |
| Local bow detection | Image divided into `grid_divisions` horizontal/vertical strips. Per-strip Canny + HoughLinesP, filtered by near-H/V angle. Median displacement per strip forms the bow profile. |
| Skew correction | `cv2.getRotationMatrix2D` + `cv2.warpAffine` with `BORDER_REFLECT_101`, center-crop back to original size |
| Bow correction | Cubic interpolation of strip displacements via `scipy.interpolate.interp1d`, applied as displacement maps via `cv2.remap` |

```python
def analyze(image_path, grid_divisions=20, direction='both') -> dict
# Returns: skew_angle_deg, max_weft_bow_px, max_warp_bow_px, bow_data, recommendation

def preview(batch_path, mode='auto', strength=1.0, direction='both',
            grid_divisions=20, manual_skew_angle=None) -> dict
# Returns: success, before_url, after_url, analysis data

def apply(batch_path, mode='auto', strength=1.0, direction='both',
          grid_divisions=20, manual_skew_angle=None) -> dict
# Returns: success, processed, total, output_folder
```

Modes: `auto` (skew + bow), `skew` (rotation only), `bow` (curvature only). `strength` parameter (0–1) scales all corrections. `manual_skew_angle` overrides FFT-detected angle.

---

### FastAPI Router

**File**: `api/app/routers/processing.py`

The router defines 26 Pydantic request models and exposes endpoints organized by tool. All endpoints that modify batch state call `sync_batch()` as a background task.

#### Endpoint Inventory

| Method | Endpoint | Service |
|---|---|---|
| `POST` | `/equalize/preview` | `equalize_service.preview()` |
| `POST` | `/equalize/apply` | `equalize_service.apply()` |
| `POST` | `/delight/preview` | `delight_service.preview()` |
| `POST` | `/delight/apply` | `delight_service.apply()` |
| `POST` | `/flatten/preview` | `flatten_service.preview()` |
| `POST` | `/flatten/apply` | `flatten_service.apply()` |
| `POST` | `/perspective/detect-lines` | `perspective_service.detect_lines()` |
| `POST` | `/perspective/preview` | `perspective_service.preview()` |
| `POST` | `/perspective/apply` | `perspective_service.apply()` |
| `POST` | `/seamless/analyze` | `seamless_service.analyze_seams()` |
| `POST` | `/seamless/preview` | `seamless_service.preview()` |
| `POST` | `/seamless/apply` | `seamless_service.apply()` |
| `POST` | `/tile/preview` | `tile_service.preview()` |
| `POST` | `/tile/apply` | `tile_service.apply()` |
| `POST` | `/validate/check` | `validate_service.validate_albedo()` + `validate_metallic()` |
| `GET` | `/validate/stats/{batch_name}` | `validate_service.get_stats()` |
| `POST` | `/clone/inpaint` | `clone_service.preview_inpaint()` |
| `POST` | `/clone/stamp` | `clone_service.preview_stamp()` |
| `POST` | `/clone/apply` | `clone_service.apply()` |
| `POST` | `/straighten/analyze` | `straighten_service.analyze()` |
| `POST` | `/straighten/preview` | `straighten_service.preview()` |
| `POST` | `/straighten/apply` | `straighten_service.apply()` |
| `GET` | `/{tool}/image/{batch_name}` | Shared tool image loader |
| `GET` | `/status/{batch_name}` | Pipeline status |

All 22 tool endpoints are fully wired to their service implementations. A shared helper `_find_top_image_for_tool()` resolves batch → source folder → top image for endpoints that need a specific image path (perspective detect-lines, seamless analyze).

---

## Frontend Components and UI

### Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Framework | Next.js | 14.2.0 | App router, SSR, dynamic imports |
| UI | React | ^18.2.0 | Component model |
| Styling | Tailwind CSS | ^4 | Utility-first dark theme |
| HTTP | Axios | ^1.13.2 | API client with typed wrappers |
| 2D Canvas | Konva + react-konva | ^10.2.0 / ^18.2.14 | Draggable corners, brush painting, seam highlights, tile grids |
| 3D Rendering | Three.js + @react-three/fiber + @react-three/drei | ^0.183.2 / ^8.18.0 / ^9.122.0 | PBR material preview with orbit controls |
| Icons | lucide-react | ^0.562.0 | Tool icons, UI chrome |
| State | @tanstack/react-query | ^5.90.17 | Server state management |
| Testing | Vitest + @testing-library/react + jsdom | ^4.0.18 / ^16.3.2 / ^28.1.0 | Unit and component tests |

### New Dependencies

**Runtime:**

| Package | Version | Used By |
|---------|---------|---------|
| `konva` | ^10.2.0 | DraggableCorners, BrushCanvas, SeamHighlight, TileGrid |
| `react-konva` | ^18.2.14 | React bindings for Konva Stage/Layer/Shape primitives |
| `three` | ^0.183.2 | 3D PBR material preview (ThreePreview) |
| `@react-three/fiber` | ^8.18.0 | React reconciler for Three.js |
| `@react-three/drei` | ^9.122.0 | OrbitControls, Environment presets |
| `@types/three` | ^0.183.1 | TypeScript definitions |

**Dev:**

| Package | Version | Purpose |
|---------|---------|---------|
| `vitest` | ^4.0.18 | Test runner |
| `@testing-library/react` | ^16.3.2 | Component test utilities |
| `@testing-library/jest-dom` | ^6.9.1 | DOM assertion matchers |
| `@testing-library/user-event` | ^14.6.1 | User interaction simulation |
| `@vitejs/plugin-react` | ^5.1.4 | React fast-refresh for Vitest |
| `jsdom` | ^28.1.0 | DOM environment for tests |

---

### Shared Component Library

All shared components live in `web/app/processing/tools/components/`. Every component is a client component (`'use client'` directive) styled for the dark theme (`bg-gray-950` / `slate-*` palette with teal accents).

#### 1. ToolLayout (`ToolLayout.tsx`)

Full-screen layout shell used by every tool page. Provides breadcrumb nav, sidebar, canvas area, and sticky action bar.

```
┌─────────────────────────────────────────────────┐
│  ← Processing / Tools / [icon] ToolName  Batch  │  ← Top bar
├──────────────────────────────┬──────────────────┤
│                              │                  │
│         children             │     sidebar      │  ← Main area
│       (canvas area)          │    (w-80, p-4)   │
│         flex-1               │                  │
│                              │                  │
├──────────────────────────────┴──────────────────┤
│                                   [actionBar]   │  ← Sticky bottom
└─────────────────────────────────────────────────┘
```

Also exports `ActionButton` with variants: `primary` (teal-600), `secondary` (slate-700), `danger` (red-600/20).

#### 2. ParameterCard (`ParameterCard.tsx`)

Collapsible card container for sidebar parameter groups. Exports three form control primitives:

- **SliderControl** — Labeled range input with min/max/step and unit display
- **ToggleControl** — Custom toggle switch (w-9 h-5) with teal-500 active state
- **SelectControl** — Styled `<select>` with slate-700 background and teal focus ring

#### 3. BeforeAfterSlider (`BeforeAfterSlider.tsx`)

Interactive split-screen comparison with a draggable divider. Supports mouse and touch drag. The before image is clipped to the divider position (0–100%). Labels appear as semi-transparent badges in top corners.

#### 4. HistogramChart (`HistogramChart.tsx`)

SVG-based histogram visualization for RGB + luminance channels (256 bins each). Each channel rendered as a semi-transparent filled polygon, normalized to the global maximum. Channel colors: red, green, blue, white (luminance).

#### 5. DraggableCorners (`DraggableCorners.tsx`)

Konva-based interactive quadrilateral editor for perspective correction. Renders a background image with four draggable circle handles, a teal outline, and a 4×4 dashed grid inside the quad. Handles coordinate conversion between image space and display space.

#### 6. BrushCanvas (`BrushCanvas.tsx`)

Konva-based freehand painting canvas for creating inpaint masks. Supports paint/erase modes with undo/redo stack. On mouse up, generates a binary mask (black canvas, white strokes) exported as a base64 PNG data URL.

#### 7. SeamHighlight (`SeamHighlight.tsx`)

Konva overlay that visualizes seam quality with colored edge strips. Score thresholds: green (< 10, good), yellow (< 30, moderate), red (>= 30, poor). Score badges with monospace text at edge centers.

#### 8. TileGrid (`TileGrid.tsx`)

Konva-based tiling preview with configurable grid parameters. Handles scale, rotation, overlap, half-drop offset, and grid line overlays. Uses layer clipping for clean viewport boundaries.

#### 9. ThreePreview (`ThreePreview.tsx`)

Real-time 3D PBR material preview using Three.js and react-three-fiber. Renders texture on `PlaneGeometry` or `CylinderGeometry` with normal, roughness, and height maps. Includes ambient + directional lighting, studio environment preset, and orbit controls with damping.

#### 10. ToolStepIndicator (`ToolStepIndicator.tsx`)

Horizontal step progress indicator with numbered circles, connecting lines, and visual states: completed (teal checkmark), active (teal ring), future (slate).

---

### Tool Hub Page

**File**: `web/app/processing/tools/page.tsx`
**Route**: `/processing/tools`

Entry point for all material tools. Two-column layout: batch selector (left, filterable list) and tool grid (right, 2-column card grid). Tool cards are color-coded and disabled until a batch is selected.

| Tool ID | Name | Icon | Color |
|---------|------|------|-------|
| `equalize` | Equalize | BarChart3 | blue |
| `delight` | Delight | Sun | amber |
| `flatten` | Flatten | Minimize2 | indigo |
| `perspective` | Perspective | Move | violet |
| `seamless` | Make Seamless | Layers | teal |
| `tiling` | Tiling | Grid3x3 | emerald |
| `validate` | PBR Validate | Shield | cyan |
| `clone` | Clone Stamp | Stamp | rose |

---

### Tool Page UIs

All 8 tool pages follow a consistent architecture:

- **Route**: `/processing/tools/{tool}/[batchName]`
- **Layout**: Wrapped in `<ToolLayout>` with sidebar, actionBar, and canvas children
- **Workflow**: Configure → Preview → Review → Apply to All
- **State**: `loading` / `previewing` / `applying` / `result` variables

#### Equalize (`equalize/[batchName]/page.tsx`)

Sidebar: method selector (CLAHE / Histogram Match / Exposure Match), CLAHE clip limit slider (0.5–10), reference image dropdown, before/after histograms. Canvas: BeforeAfterSlider.

#### Delight (`delight/[batchName]/page.tsx`)

Sidebar: method selector (Gaussian / Frequency Separation), strength slider (0–100%), blur radius slider (51–501px). Canvas: BeforeAfterSlider.

#### Flatten (`flatten/[batchName]/page.tsx`)

Sidebar: PBR mode selector (Grayscale / Color), strength slider (0–100%), smoothing radius slider (0–501px). Shows PBR availability warning if normal maps are missing. Canvas: BeforeAfterSlider.

#### Perspective (`perspective/[batchName]/page.tsx`)

Sidebar: auto-detect lines button, corner coordinate display, preview button. Canvas toggles between DraggableCorners editor and BeforeAfterSlider preview. Uses ResizeObserver for responsive container measurement.

#### Seamless (`seamless/[batchName]/page.tsx`)

Sidebar: analyze seams button, overall score badge (color-coded), method selector (Overlay / Mirror / Poisson), blend width slider (32–512px), spots removal toggle, color equalizer slider, tile preview count selector. Canvas: SeamHighlight analysis or seamless preview + tiled grid.

#### Tiling (`tiling/[batchName]/page.tsx`)

Sidebar: 2D/3D view toggle, tile count and offset controls, scale/rotation/overlap/half-drop, grid line toggle, 3D geometry/roughness/metalness, export resolution. Canvas: TileGrid (2D, dynamically imported) or ThreePreview (3D, dynamically imported).

#### PBR Validate (`validate/[batchName]/page.tsx`)

Sidebar: check type selector (Albedo / Metallic / Both), dark threshold and metal range sliders, overlay toggle, per-map pass/fail results with statistics. Canvas: 2×2 grid of PBR map thumbnails with overlay badges.

#### Clone Stamp (`clone/[batchName]/page.tsx`)

Sidebar: inpaint/stamp mode toggle. Inpaint: brush radius, method selector (Telea / Navier-Stokes). Stamp: radius, fade, edge blur sliders, source point indicator, operations counter. Canvas: BrushCanvas (inpaint, dynamically imported) or click-to-clone interaction.

---

### API Client Layer

**File**: `web/lib/api.ts`

Centralized Axios-based HTTP client. Base URL from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

**25 material tool functions:**

| Function | Endpoint |
|----------|----------|
| `getToolImage(batch, tool)` | `GET /processing/{tool}/image/{batch}` |
| `equalizePreview(batch, method, opts?)` | `POST /processing/equalize/preview` |
| `equalizeApply(batch, method, opts?)` | `POST /processing/equalize/apply` |
| `delightPreview(batch, opts?)` | `POST /processing/delight/preview` |
| `delightApply(batch, opts)` | `POST /processing/delight/apply` |
| `flattenPreview(batch, opts?)` | `POST /processing/flatten/preview` |
| `flattenApply(batch, opts)` | `POST /processing/flatten/apply` |
| `perspectiveDetectLines(batch)` | `POST /processing/perspective/detect-lines` |
| `perspectivePreview(batch, srcPts, dstPts?)` | `POST /processing/perspective/preview` |
| `perspectiveApply(batch, srcPts, opts?)` | `POST /processing/perspective/apply` |
| `seamlessAnalyze(batch, blendWidth?)` | `POST /processing/seamless/analyze` |
| `seamlessPreview(batch, opts)` | `POST /processing/seamless/preview` |
| `seamlessApply(batch, opts)` | `POST /processing/seamless/apply` |
| `tilePreview(batch, params)` | `POST /processing/tile/preview` |
| `tileApply(batch, params)` | `POST /processing/tile/apply` |
| `pbrValidateCheck(batch, opts?)` | `POST /processing/validate/check` |
| `pbrValidateStats(batch)` | `GET /processing/validate/stats/{batch}` |
| `cloneInpaint(batch, maskData, opts?)` | `POST /processing/clone/inpaint` |
| `cloneStamp(batch, opts)` | `POST /processing/clone/stamp` |
| `cloneApply(batch, operations)` | `POST /processing/clone/apply` |
| `straightenAnalyze(batch, opts?)` | `POST /processing/straighten/analyze` |
| `straightenPreview(batch, opts)` | `POST /processing/straighten/preview` |
| `straightenApply(batch, opts)` | `POST /processing/straighten/apply` |

**Utility functions**: `getFullUrl()` (resolves relative paths to absolute API URLs), `getMediaUrl()`, `resolveImageUrl()`.

---

## UX Patterns

### Preview → Apply Workflow

Every tool follows a two-phase workflow: configure parameters → generate server-side preview of the top image → review (before/after comparison) → apply to all batch images. The "Apply" button stays disabled until a preview confirms the result.

### Canvas Interaction Patterns

| Pattern | Component | Tools |
|---------|-----------|-------|
| Drag-to-compare | BeforeAfterSlider | Equalize, Delight, Flatten, Perspective |
| Drag-to-position | DraggableCorners | Perspective |
| Paint-to-mask | BrushCanvas | Clone (Inpaint) |
| Click-source-click-target | Custom handler | Clone (Stamp) |
| Visual edge scoring | SeamHighlight | Seamless |
| Repeating tile grid | TileGrid | Tiling (2D) |
| 3D orbit + rotate | ThreePreview | Tiling (3D) |
| Map grid + overlay | Custom grid | PBR Validate |
| Collapsible sidebar panel | Inline controls | Yarn Straighten (crop page) |

### Dynamic Imports

Components depending on browser APIs are loaded via `next/dynamic` with `{ ssr: false }`: TileGrid (Konva canvas), ThreePreview (WebGL), BrushCanvas (Konva).

### Responsive Measurement

Tools rendering Konva stages use `ResizeObserver` to measure container dimensions, passing them as props for proper coordinate transforms.

---

## File Inventory

### New Python Services (9 files)
| File | Lines | Purpose |
|------|-------|---------|
| `api/scripts/processing/equalize_service.py` | 335 | Histogram equalization and exposure matching |
| `api/scripts/processing/delight_service.py` | 269 | Lighting gradient removal |
| `api/scripts/processing/flatten_service.py` | 294 | Normal map-based surface flattening |
| `api/scripts/processing/perspective_service.py` | 338 | Line detection and perspective correction |
| `api/scripts/processing/seamless_service.py` | 480 | Seamless edge blending (3 methods) |
| `api/scripts/processing/tile_service.py` | 265 | Tiling with configurable grid layout |
| `api/scripts/processing/validate_service.py` | 305 | PBR map validation with heatmaps |
| `api/scripts/processing/clone_service.py` | 360 | Inpainting and clone stamp |
| `api/scripts/processing/straighten_service.py` | 552 | Yarn skew/bow detection and correction (FFT + Hough) |

### Modified Python Files (1 file)
| File | Lines Added | Purpose |
|------|-------------|---------|
| `api/app/routers/processing.py` | +530 | 23 new endpoints + Pydantic models |

### New React Components (10 files)
| File | Lines | Purpose |
|------|-------|---------|
| `web/app/processing/tools/components/ToolLayout.tsx` | 134 | Shared layout shell |
| `web/app/processing/tools/components/ParameterCard.tsx` | 116 | Parameter controls |
| `web/app/processing/tools/components/BeforeAfterSlider.tsx` | 114 | Before/after comparison |
| `web/app/processing/tools/components/HistogramChart.tsx` | 78 | RGB histogram |
| `web/app/processing/tools/components/DraggableCorners.tsx` | 194 | Interactive quad editor |
| `web/app/processing/tools/components/BrushCanvas.tsx` | 195 | Freehand mask painting |
| `web/app/processing/tools/components/SeamHighlight.tsx` | 134 | Seam quality overlay |
| `web/app/processing/tools/components/TileGrid.tsx` | 132 | Tiling grid preview |
| `web/app/processing/tools/components/ThreePreview.tsx` | 92 | 3D PBR preview |
| `web/app/processing/tools/components/ToolStepIndicator.tsx` | 52 | Step progress |

### New Tool Pages (9 files)
| File | Lines | Purpose |
|------|-------|---------|
| `web/app/processing/tools/page.tsx` | 241 | Tool hub (batch selector + tool grid) |
| `web/app/processing/tools/equalize/[batchName]/page.tsx` | 256 | Equalize UI |
| `web/app/processing/tools/delight/[batchName]/page.tsx` | 209 | Delight UI |
| `web/app/processing/tools/flatten/[batchName]/page.tsx` | 225 | Flatten UI |
| `web/app/processing/tools/perspective/[batchName]/page.tsx` | 277 | Perspective UI |
| `web/app/processing/tools/seamless/[batchName]/page.tsx` | 337 | Seamless UI |
| `web/app/processing/tools/tiling/[batchName]/page.tsx` | 246 | Tiling UI |
| `web/app/processing/tools/validate/[batchName]/page.tsx` | 279 | PBR Validate UI |
| `web/app/processing/tools/clone/[batchName]/page.tsx` | 372 | Clone Stamp UI |

### Other Changes
| File | Purpose |
|------|---------|
| `web/lib/api.ts` | +175 lines — 25 material tool API functions |
| `web/package.json` | +8 dependencies (6 runtime, 6 dev) |
| `web/app/processing/page.tsx` | +7 lines — tools navigation link |
| `Plans/keen-scribbling-mango.md` | 348 lines — implementation plan |

---

## Test Suite

### Backend (pytest)

**141 tests, 0 skipped** across 9 test files in `api/tests/`:

| File | Tests | Coverage |
|------|-------|----------|
| `test_equalize_service.py` | 14 | CLAHE, histogram match, exposure match, preview/apply, histogram bins |
| `test_delight_service.py` | 11 | Gaussian, frequency separation, bit depth, strength, preview/apply, source priority |
| `test_perspective_service.py` | 14 | Line detection, preview, apply, helpers, source priority, 16-bit |
| `test_seamless_service.py` | 16 | Analyze seams, overlay/mirror/poisson, preview, apply, tiled preview, source priority |
| `test_tile_service.py` | 12 | Tiled preview, scale/rotation/overlap/half-drop, preview, apply, output resolution |
| `test_validate_service.py` | 13 | Albedo/metallic validation, stats, overlay routing, PBR map detection |
| `test_clone_service.py` | 17 | Inpaint (telea/NS), clone stamp, preview, apply, mask decoding, source priority |
| `test_straighten_service.py` | 16 | Analyze (FFT skew, Hough bow), skew/bow correction, dtype preservation, preview/apply |
| `test_processing_api.py` | 21 | HTTP layer: all 7 tool endpoints, shared image endpoint, 422 validation |

Integration tests (`test_processing_api.py`) bootstrap the FastAPI app with mocked hardware modules (`gphoto2`, `aiohttp`, `light_service`) and use `TestClient` to verify endpoint routing and Pydantic validation.

### Frontend (Vitest)

**147 tests, 18 test files** in `web/__tests__/`:

| Category | Files | Tests |
|----------|-------|-------|
| Component tests | 10 | BeforeAfterSlider, BrushCanvas, DraggableCorners, HistogramChart, ParameterCard, SeamHighlight, ThreePreview, TileGrid, ToolLayout, ToolStepIndicator |
| Page tests | 8 | Equalize, Delight, Perspective, Seamless, Tiling, Validate, Clone, ToolHub |

---

## Next Steps

1. **PBR integration.** Connect Validate tool output to the PBR generation pipeline for automated quality gates.
