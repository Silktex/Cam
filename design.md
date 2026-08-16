---
version: alpha
name: Industrial Optical Studio
colors:
  primary: "#121417"
  secondary: "#23272E"
  tertiary: "#E58E26"
  surface: "#1A1D23"
  surface-raised: "#262B34"
  border-subtle: "rgba(255, 255, 255, 0.08)"
  border-strong: "rgba(255, 255, 255, 0.16)"
  text-primary: "#F3F4F6"
  text-secondary: "#9CA3AF"
  text-muted: "#6B7280"
  accent: "#E58E26"
  accent-glow: "rgba(229, 142, 38, 0.15)"
  status-active: "#10B981"
  status-warning: "#F59E0B"
  status-error: "#EF4444"
typography:
  headline-display:
    fontFamily: Space Grotesk
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Space Grotesk
    fontSize: 18px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -0.01em
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: 0.08em
  telemetry-value:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.2
rounded:
  sm: 4px
  md: 6px
  lg: 10px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  canvas-gap: 20px
---

# Design System: Sony A7R III Studio & Photometric Camera System

## 1. Visual Theme & Atmosphere
A high-precision, industrial optical workbench designed for tethered photography, photometric multi-light capture, and color science calibration. The atmosphere is cockpit-dense (Density 8), architectural, and purposeful — drawing inspiration from high-end aerospace instrument clusters and Hasselblad Phocus / Capture One professional tethering suites.

- **Atmosphere Spectrum**: Density 8 (Dense Cockpit), Variance 6 (Asymmetric Studio Layout), Motion 5 (Tactile State Feedback).
- **Core Design Philosophy**: Zero unnecessary decoration. Every pixel serves camera telemetry, optical alignment, or hardware feedback. Real-time controls are tactile, instant, and fail-safe.

---

## 2. Page Reorganization & Architecture

The previous 5 disjointed pages (`home`, `batch`, `gallery`, `lights`, `processing`) have been intelligently synthesized into a cohesive 4-station workflow, eliminating the friction of navigating across separate pages during live photo shoots:

```
+---------------------------------------------------------------------------------------------------+
| GLOBAL STATUS & NAVIGATION HEADER (Hardware Telemetry, EventBus Pulse, Quick Reconnect, Battery)    |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [ STATION 1: UNIFIED CAPTURE STUDIO ]                                                            |
|  * Merges Live View + Full Exposure Controls (ISO/Shutter/Aperture/WB) + Integrated Light Rig   |
|  * Real-time MJPEG Stream, Focus Reticle, Histogram, Zebra Clipping, and Single Capture          |
|                                                                                                   |
|  [ STATION 2: PHOTOMETRIC BATCH SEQUENCING ]                                                      |
|  * Multi-Light Sequential Photography Controller (Top Dome + 8 Radial Side LEDs)                 |
|  * Visual 9-Panel Rig Diagram, Settling Delay Stepper, and Automated Sequence Execution Bar      |
|                                                                                                   |
|  [ STATION 3: COLOR SCIENCE & CALIBRATION ]                                                       |
|  * X-Rite 24-Patch ColorChecker Detection with SAM Segmentation & spectral delta-E analysis       |
|  * Reference vs. Measured Patch Comparison Grid, Color Matrix Profiling, and Batch Persistence    |
|                                                                                                   |
|  [ STATION 4: PBR TEXTURE SYNTHESIS & GALLERY LIGHTBOX ]                                          |
|  * Photometric Stereo Material Generation: Albedo, Tangent Normal, Roughness, Height Maps        |
|  * Deep-Zoom 61MP Inspection Lightbox, Multi-Light Comparison Slider, and glTF PBR Export        |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Color Palette & Roles

- **Chassis Obsidian (#121417)**: Deep neutral canvas background surface providing maximum contrast for high-bitrate live video feeds and color inspection.
- **Instrument Surface (#1A1D23)**: Primary container and card background for telemetry pods and control clusters.
- **Raised Pod (#262B34)**: Elevated hover and active container state for active camera sliders and stepped pickers.
- **Tungsten Amber (#E58E26)**: Single high-contrast interaction accent for capture triggers, active live view states, and armed batch sequences. (Strictly no generic AI purple/neon).
- **Hardware Green (#10B981)**: Verified online states (PTP camera connected, ESP32 WebSocket synced).
- **Subtle Titanium Border (rgba(255, 255, 255, 0.08))**: Clean 1px structural dividers separating control columns without visual clutter.

---

## 4. Typography Hierarchy

- **Technical Display**: `Space Grotesk` (Semi-Bold, track-tight -0.02em) for station titles, modal headers, and mode badges.
- **Telemetry & Numerical Data**: `JetBrains Mono` for all aperture f-stops, shutter speeds, ISO sensitivities, delta-E values, and ESP32 GPIO pin statuses. Numbers never jitter due to tabular spacing.
- **Interface Body**: `Plus Jakarta Sans` for labels, descriptions, and tooltips.
- **Strictly Banned**: Inter, generic un-tracked serif fonts, Comic/Playful typefaces.

---

## 5. Component Stylings & Interaction Specifications

### Unified Live View Viewport
- Low-latency canvas rendering the camera MJPEG stream (`/api/liveview/stream`).
- Interactive focus target reticle with single-click autofocus triggering.
- Floating translucent telemetry chips: Live RGB Histogram, Exposure Clipping Warnings, Current Shutter/Aperture readout.

### Exposure Control Segmented Steppers
- Tactile stepped dials for:
  - **Shutter Speed**: 1/8000s to 30s with 1/3-stop steps.
  - **Aperture**: f/1.4 to f/22 with tactile detents.
  - **ISO**: 50 to 102400 (Native: 100).
  - **White Balance**: Color temperature dial (2500K - 10000K) + Presets (Daylight, Tungsten, Flash).

### Integrated 9-Panel Light Rig Controller
- Embedded radial diagram representing the physical lighting chamber:
  - Center: 1x Top Dome Light.
  - Perimeter: 8x Circumferential Directional LED Panels (45-degree angular spacing).
- Quick master toggle (All ON / All OFF), master dimmer (0-100%), and individual light select for interactive shading preview directly beside the camera live view.

### ColorChecker 24-Patch Matrix
- Automated 4-corner corner-pin detection overlay with manual drag handles.
- Side-by-side split swatch comparison (Measured vs. Reference sRGB).
- Per-patch Delta-E (CIE2000) tolerance metric card.

### PBR 2x2 Material Viewport
- Synchronized quad-viewport displaying:
  1. Albedo (Diffuse Flat Reflection).
  2. Normal Map with interactive 3D virtual light probe sphere.
  3. Roughness Map (Micro-facet distribution).
  4. Height / Displacement Map.
- One-click PBR export package generation (`glTF` + 16-bit PNG maps).

---

## 6. Anti-Patterns & Safety Rules
- **No Destructive USB Resets**: Maintain the verified non-destructive disconnect/reconnect sequence in all troubleshoot actions.
- **No Hidden Controls**: All essential capture parameters must remain visible in the Capture Studio viewport without requiring scroll jumps.
- **No Generic Spinner Loaders**: Use skeletal progress bars with step indicators during batch capture and PBR generation.
- **No Overlapping Dialogs**: All modals and lightboxes occupy dedicated full-screen or slide-out drawer zones.

---

## 7. Google Stitch Project & Generated Screen Catalog

- **Stitch Project ID**: `8012881480995754238`
- **Project Title**: `Sony A7R III Studio & Photometric Camera System`
- **Project URL**: [https://stitch.withgoogle.com/projects/8012881480995754238](https://stitch.withgoogle.com/projects/8012881480995754238)

| Station # | Screen Title | Stitch Screen ID | Local Reference File | Interactive Highlights |
| :--- | :--- | :--- | :--- | :--- |
| **Station 1** | Unified Capture Studio (Live View + Settings + Rig) | `18084586664963604466` | [`.stitch/designs/unified-capture-studio.html`](file:///home/rc/projects/camera_system/.stitch/designs/unified-capture-studio.html) | Live stream overlays (Grid/Zebra/Peaking), interactive dials, 9-LED rig toggle, AF pulse, shutter flash & filmstrip |
| **Station 2** | Photometric Multi-Light Batch Sequencer | `556589096967590868` | [`.stitch/designs/photometric-batch-sequencer.html`](file:///home/rc/projects/camera_system/.stitch/designs/photometric-batch-sequencer.html) | Automated 9-step execution engine (Top + 8 radial spots), countdown timer, live PIP flash, auto batch registration |
| **Station 3** | Color Science & ColorChecker Calibration | `7632233974447837948` | [`.stitch/designs/color-calibration-studio.html`](file:///home/rc/projects/camera_system/.stitch/designs/color-calibration-studio.html) | 24 interactive swatches with CIE2000 Delta-E inspector, 90° rotate / flip canvas, SAM auto-detect, ICC exporter |
| **Station 4** | PBR Texture Synthesis & Normal Map Lab | `3126015793666701376` | [`.stitch/designs/pbr-texture-lab.html`](file:///home/rc/projects/camera_system/.stitch/designs/pbr-texture-lab.html) | Draggable 3D virtual light probe sphere, 2x2 synchronized quad material maps, 4K/8K selector, glTF exporter |
| **Station 5** | Asset Gallery & High-Res Inspection Lightbox | `6210015113962678370` | [`.stitch/designs/asset-inspection-gallery.html`](file:///home/rc/projects/camera_system/.stitch/designs/asset-inspection-gallery.html) | Mouse-tracking 100% 1:1 pixel loupe over 61MP RAW, 9-light directional switcher toolbar, Meilisearch filter bar |


