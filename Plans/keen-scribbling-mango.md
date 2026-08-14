# Material Creation Tools — Implementation Plan

## Context

The camera system captures 9-angle fabric photos (photometric stereo rig), calibrates color, crops, and generates PBR maps. The missing step is **interactive material refinement** — manual tools that bridge calibrated photos to production-quality tileable materials.

**Design reference:** SEDDI Textura (UI/workflow — clean step-by-step material creation, tiling tools with clone/offset/alignment/gradient removal)
**Functionality reference:** Adobe Substance 3D Sampler (tool parameters — Clone Stamp, Make it Tile, Perspective Correction, Delight, PBR Validate, Tiling)

---

## Architecture

**Frontend:** Add `konva` + `react-konva` + `three` + `@react-three/fiber` + `@react-three/drei` to `web/package.json`
- Konva: interactive canvas (draggable corners, brush painting, overlays)
- Three.js via R3F: 3D material preview (texture on plane/cylinder with lighting)
- No OpenCV.js (8-15MB WASM unnecessary — OpenCV runs server-side)

**Backend:** No new dependencies. OpenCV 4.9+, NumPy, SciPy already installed. All pixel manipulation stays server-side.

**Pattern:** Frontend sends parameters → backend processes → returns preview URL → user confirms → backend applies to all. Same as existing crop tool.

---

## Pipeline Position

```
Capture → Crop → Calibrate → [ TOOLS ] → PBR Generation
                                 │
         ┌───────────────────────┼────────────────────────┐
         ▼                       ▼                        ▼
   1. Equalize            4. Make Seamless          6. PBR Validate
   2. Delight             5. Tiling + 3D Preview    7. Clone Stamp
   3. Perspective
```

Tools are optional, non-destructive, each saves to its own subfolder. Tools can be used in any order; source folder priority chain extended in PBR service.

---

## UI Design (Textura-Inspired)

**Layout:** Full-screen dark slate with clean step-based workflow (Textura pattern)
- Left: large canvas/viewport area (Konva for 2D tools, Three.js for 3D preview toggle)
- Right: slim control panel (~320px) with tool parameters
- Top: breadcrumb (Processing > Tools > [Tool Name]) + batch name
- Bottom: action bar (Preview / Apply / Cancel) — sticky

**Design language:**
- Existing teal palette (`#14B8A6` primary, `#030712` background)
- Card-based parameter groups within sidebar (Textura style)
- Real-time grid view for tiling verification (Textura's grid preview pattern)
- Hover tooltips on each parameter (Textura's icon tutorials pattern)
- Step indicator showing tool pipeline progress

---

## Tool 1: Equalize Images

**Purpose:** Match exposure/color across 9 multi-angle captures for consistent PBR output.

**Backend** — `api/scripts/processing/equalize_service.py`
- CLAHE (adaptive histogram EQ in LAB color space, preserves color)
- Histogram Match (match all to reference via `cv2.calcHist` + LUT)
- Exposure Match (normalize mean brightness)

**Endpoints** — `api/app/routers/processing.py`
```
POST /api/processing/equalize/preview   { batch_name, method, reference_image?, clip_limit? }
POST /api/processing/equalize/apply     { batch_name, method, reference_image?, apply_to_all }
```

**Frontend** — `web/app/processing/tools/equalize/[batchName]/page.tsx`
- 3×3 thumbnail grid of 9 captures with per-image histogram overlays
- Method selector (CLAHE / Histogram Match / Exposure Match)
- Reference image dropdown, CLAHE clip limit slider (1.0–40.0)
- Before/after toggle, Preview + Apply buttons

---

## Tool 2: Delight (De-lighting)

**Reference:** Substance Sampler's Delight — AI-powered, removes lighting from base color. Sampler's version has no parameters (fully automatic). Our version provides manual control.

**Purpose:** Remove residual lighting gradients that color calibration doesn't fully fix. Fabric photos often have center-to-edge brightness falloff.

**Backend** — `api/scripts/processing/delight_service.py`
- Compute low-frequency luminance map (heavy Gaussian blur, configurable radius)
- Divide original by luminance to normalize lighting
- Optional: frequency-domain separation (high-pass for detail, low-pass for lighting)

**Endpoints**
```
POST /api/processing/delight/preview   { batch_name, blur_radius?, strength?, method? }
POST /api/processing/delight/apply     { batch_name, blur_radius, strength, apply_to_all }
```

**Frontend** — `web/app/processing/tools/delight/[batchName]/page.tsx`
- Full image view with lighting gradient visualization overlay
- Strength slider (0–100%)
- Blur radius slider (50–500px, controls frequency cutoff)
- Method toggle: "Gaussian" (simple) / "Frequency Separation" (advanced)
- Before/after slider (draggable vertical divider)

---

## Tool 3: Perspective Transform

**Reference:** Substance Sampler's Perspective Correction — available in left sidebar for fast access, uses handles in 2D view.

**Purpose:** Correct keystone/skew distortion in-place without reducing image area.

**Backend** — `api/scripts/processing/perspective_service.py`
- Line detection: `cv2.HoughLinesP` → cluster by angle → suggest corners
- Transform: `cv2.getPerspectiveTransform` + `cv2.warpPerspective` (reuse from `crop_service.py:473`)

**Endpoints**
```
POST /api/processing/perspective/detect-lines  { batch_name }
POST /api/processing/perspective/preview       { batch_name, source_points, dest_points? }
POST /api/processing/perspective/apply         { batch_name, source_points, apply_to_all }
```

**Frontend** — `web/app/processing/tools/perspective/[batchName]/page.tsx`
- Konva canvas with 4 draggable corner handles (Substance Sampler 2D handle pattern)
- Semi-transparent grid overlay on corrected target
- "Auto-detect" button for line/corner detection
- Manual coordinate inputs (editable)
- Preview + Apply

---

## Tool 4: Make Seamless (Edge/Seam Matching)

**Reference:** Substance Sampler's Make it Tile — overlays multiple copies, adjusts borders of top layer to cover seams. Parameters: Spots Removal (toggle), Color Equalizer (0–50).
**Also:** Textura's tiling workflow (Offset → Clone → Gradient Removal).

**Purpose:** Blend edges so fabric texture tiles without visible seams. Most critical tool for material creation.

**Backend** — `api/scripts/processing/seamless_service.py`
- **Overlay Blend** (Sampler method): overlay shifted copies, blend top layer borders over bottom seams
- **Mirror Blend**: flip + linear gradient blend at edges
- **Poisson Blend**: gradient-domain blending at seam zones (`cv2.seamlessClone`)
- Spots removal: detect and inpaint artifacts near seam line
- Color equalizer: reduce contrast at seam to decrease visibility
- Seam quality metric: L2 distance between opposite edge strips

**Endpoints**
```
POST /api/processing/seamless/analyze   { batch_name, blend_width? }
POST /api/processing/seamless/preview   { batch_name, method, blend_width, spots_removal, color_eq, tile_count }
POST /api/processing/seamless/apply     { batch_name, method, blend_width, spots_removal, color_eq }
```

**Frontend** — `web/app/processing/tools/seamless/[batchName]/page.tsx`
- Image with colored edge strips showing blend zones
- Seam quality score per edge (red/yellow/green indicators)
- Method selector (Overlay Blend / Mirror Blend / Poisson Blend)
- Blend width slider (32–512px)
- Spots Removal toggle (Sampler parameter)
- Color Equalizer slider (0–50, Sampler parameter)
- Tiled preview grid (2×2 / 3×3 / 4×4) to verify seamlessness
- Preview + Apply

---

## Tool 5: Tiling with Adjustment + 3D Preview

**Reference:** Substance Sampler's Tiling tool (Cut Offset, Threshold, Smoothness, Grid Resolution, Transform). Also Textura's Half Drop Repeat tool.

**Purpose:** Preview and export repeating tile patterns. Includes 3D material preview.

**Backend** — `api/scripts/processing/tile_service.py`
- Tiled output generation with offset/rotation/overlap/half-drop
- High-res export at selectable resolution

**Endpoints**
```
POST /api/processing/tile/preview  { batch_name, tile_x, tile_y, offset_x/y, scale, rotation, overlap, half_drop }
POST /api/processing/tile/apply    { batch_name, ..., output_resolution }
```

**Frontend** — `web/app/processing/tools/tiling/[batchName]/page.tsx`

**2D View (Konva — default):**
- Client-side real-time tiled preview (draw image multiple times with transforms)
- Tile count X/Y sliders (1–8)
- Cut Offset X/Y sliders (0–0.5, Sampler parameter)
- Scale slider (25–400%), Rotation slider (-180° to 180°)
- Overlap/Smoothness slider (0–50%)
- Half Drop Repeat toggle (Textura pattern)
- Output resolution selector (1024², 2048², 4096²)

**3D View (Three.js — toggle):**
- `@react-three/fiber` canvas with `@react-three/drei` controls
- Texture mapped onto a plane (flat fabric view) or cylinder (wrapped view)
- Directional + ambient lighting to show how material reacts
- OrbitControls for rotation/zoom
- Material properties: roughness slider, metalness slider (from PBR maps if available)
- Toggle between 2D grid ↔ 3D preview

---

## Tool 6: PBR Validate

**Reference:** Substance Sampler's PBR Validate — Validation Mode (albedo/metallic/both), dark range threshold, overlay map toggle, red-to-green error scale.

**Purpose:** Verify PBR map channel accuracy. Analysis-only, non-destructive.

**Backend** — `api/scripts/processing/validate_service.py`
- Check value ranges per channel (albedo dark threshold, metallic reflectance range)
- Generate overlay heatmap (red=invalid, green=valid, Sampler's scale)
- Compute stats: min/max/mean per channel, % pixels out of range

**Endpoints**
```
POST /api/processing/validate/check    { batch_name, mode, albedo_dark_threshold?, metal_range? }
GET  /api/processing/validate/stats/{batch_name}
```

**Frontend** — `web/app/processing/tools/validate/[batchName]/page.tsx`
- Side-by-side view of all PBR channels (albedo, normal, roughness, height)
- Validation Mode selector: Albedo / Metallic / Both (Sampler parameter)
- Albedo Dark Range Threshold slider (Sampler parameter)
- Metal Reflectance Range slider (Sampler parameter)
- Overlay Map toggle — shows red-green heatmap over base color (Sampler parameter)
- Per-channel histogram with valid range indicators
- Summary: pass/fail badge per channel

---

## Tool 7: Clone Stamp / Inpaint

**Reference:** Substance Sampler's Clone Stamp — Expand mask (0–1), Fade blending (0–1), Blur mask (0–1), Normal intensity (0–2), Source position (x/y). Can scale, rotate, mirror cloned area.

**Purpose:** Remove lint, threads, dust, wrinkles from fabric textures.

**Backend** — `api/scripts/processing/clone_service.py`
- `cv2.inpaint()` with user-painted mask (Navier-Stokes or Telea method)
- Clone stamp: copy source region to target with blending
- Fade blending per channel (Sampler parameter)

**Endpoints**
```
POST /api/processing/clone/inpaint   { batch_name, mask_data (base64), method, radius }
POST /api/processing/clone/stamp     { batch_name, source_pos, target_pos, radius, fade, blur_mask, mirror? }
POST /api/processing/clone/apply     { batch_name, operations[] }
```

**Frontend** — `web/app/processing/tools/clone/[batchName]/page.tsx`
- Konva canvas with brush painting for mask (inpaint mode)
- Source/target crosshair for clone stamp mode
- Mode toggle: Inpaint (paint to remove) / Clone Stamp (copy region)
- Brush radius slider
- Expand Mask slider (0–1, Sampler parameter)
- Fade Blending slider (0–1, Sampler parameter)
- Blur Mask slider (0–1, Sampler parameter)
- Normal Intensity slider (0–2, Sampler parameter)
- Mirror/Rotate source toggles
- Undo stack (multiple operations before final apply)

---

## Shared Components

| Component | Purpose |
|-----------|---------|
| `ToolLayout.tsx` | Full-screen layout: canvas + sidebar + action bar. Textura-inspired step flow |
| `BeforeAfterSlider.tsx` | Draggable vertical divider for before/after comparison |
| `DraggableCorners.tsx` | Konva 4-point corner picker with coordinate display |
| `SeamHighlight.tsx` | Konva colored edge strip overlay with quality scores |
| `TileGrid.tsx` | Konva real-time tile grid renderer |
| `HistogramChart.tsx` | Per-channel histogram with range indicators |
| `BrushCanvas.tsx` | Konva brush painting tool (for clone stamp mask) |
| `ThreePreview.tsx` | R3F 3D material preview (plane/cylinder + orbit controls) |
| `ToolStepIndicator.tsx` | Pipeline step progress indicator (Textura step pattern) |
| `ParameterCard.tsx` | Grouped parameter section with label + slider/toggle |

---

## File Structure

### New Backend Files
```
api/scripts/processing/equalize_service.py
api/scripts/processing/delight_service.py
api/scripts/processing/perspective_service.py
api/scripts/processing/seamless_service.py
api/scripts/processing/tile_service.py
api/scripts/processing/validate_service.py
api/scripts/processing/clone_service.py
```

### New Frontend Files
```
web/app/processing/tools/page.tsx                              — Tool hub (Textura-style card grid)
web/app/processing/tools/equalize/[batchName]/page.tsx
web/app/processing/tools/delight/[batchName]/page.tsx
web/app/processing/tools/perspective/[batchName]/page.tsx
web/app/processing/tools/seamless/[batchName]/page.tsx
web/app/processing/tools/tiling/[batchName]/page.tsx
web/app/processing/tools/validate/[batchName]/page.tsx
web/app/processing/tools/clone/[batchName]/page.tsx
web/app/processing/tools/components/ToolLayout.tsx
web/app/processing/tools/components/BeforeAfterSlider.tsx
web/app/processing/tools/components/DraggableCorners.tsx
web/app/processing/tools/components/SeamHighlight.tsx
web/app/processing/tools/components/TileGrid.tsx
web/app/processing/tools/components/HistogramChart.tsx
web/app/processing/tools/components/BrushCanvas.tsx
web/app/processing/tools/components/ThreePreview.tsx
web/app/processing/tools/components/ToolStepIndicator.tsx
web/app/processing/tools/components/ParameterCard.tsx
```

### Modified Files
```
web/package.json                         — add konva, react-konva, three, @react-three/fiber, @react-three/drei
web/lib/api.ts                           — add 7 tool API function groups
web/app/processing/page.tsx              — add Tools link per batch
api/app/routers/processing.py            — add 7 tool endpoint groups
api/scripts/processing/pbr_service.py    — extend source folder priority chain
```

---

## Implementation Order

1. **Foundation** — install deps, create ToolLayout + ParameterCard + ThreePreview, tool hub page, processing page integration
2. **Equalize** — simplest backend, establishes full frontend↔backend pattern
3. **Delight** — similar pattern to equalize, simple algorithm
4. **Perspective** — reuses existing `getPerspectiveTransform` from crop_service
5. **Make Seamless** — most complex algorithm, core value of toolkit
6. **Tiling + 3D** — depends on seamless output, includes Three.js integration
7. **PBR Validate** — analysis-only, no pixel modification, can run anytime
8. **Clone Stamp** — most complex frontend (brush painting + undo stack)
9. **Integration** — update PBR source folder chain, processing dashboard, Docker build

---

## Verification Plan

1. **Unit test each backend service** — feed known test image, verify output dimensions, value ranges, idempotency
2. **API test each endpoint** — curl against running server, verify JSON + preview URL accessibility
3. **Frontend smoke test** — navigate to each tool page with real batch, verify image loads, sliders respond, preview generates
4. **3D preview test** — verify Three.js canvas renders texture on plane, OrbitControls work, toggle 2D↔3D functions
5. **End-to-end pipeline** — full chain: equalize → delight → perspective → seamless → tiling → PBR → validate
6. **Docker build** — verify `npm run build` with all new deps, container starts cleanly
