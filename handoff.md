# Handoff — Sony A7R III Studio & Photometric Camera System

## 1. Project Overview & Current State

This project is a high-precision optical studio and photometric stereo acquisition system for the **Sony ILCE-7RM3 (A7R III, 61.0 MP)** combined with a custom **ESP32 9-LED lighting rig** (1 Top Dome Light + 8 radial perimeter spotlights at 45° intervals), hardware-accelerated **MacroSilicon USB 3.0 HDMI Capture Card** streaming via AMD Radeon Vega 11 VA-API H.264 WebRTC/RTSP, and both a unified 5-Station Studio Workbench and a restored classic `/v1` cockpit in Next.js 14.

All legacy MJPEG frame-polling loops have been eliminated in favor of real-time hardware-encoded RTSP (`rtsp://127.0.0.1:8554/stream`) and WebRTC WHEP (`/stream/whep`), reducing CPU usage to near-zero while enabling 100% non-blocking PTP exposure control and 61MP RAW capture.

All test suites and production builds are **100% passing**:
- **Vitest Unit & Component Tests**: **155 passing** across 20 test files (`0` failures).
- **Playwright End-to-End (E2E) UI Tests**: **40 passing** across 6 test files (`0` failures).
- **Backend API Pytest Suite**: **228 passing** inside the Docker container on host `ind` (`0` failures).
- **Next.js Production Build**: `17/17` routes compiled successfully.

---

## 2. Recent Implementation & Fixes Summary

### A. Individual Light Channel Toggles Grid
- **Station 1: Capture Studio (`/`)**: Added a dedicated 9-channel toggle button grid directly beneath the radial lighting visualizer in [`web/app/page.tsx`](file:///home/rc/projects/camera_system/web/app/page.tsx).
  - Individual channels: `TOP DOME` (Center Dome) and `SIDE 1` through `SIDE 8` (45° radial positions).
  - Real-time visual feedback: Glowing active state badge (`ON`/`OFF`), pulse status dot, and keyboard hotkeys (`T`, `1`–`8`).
- **Classic Cockpit (`/all`)**: Modernized [`LightControlPanel.tsx`](file:///home/rc/projects/camera_system/web/app/all/components/LightControlPanel.tsx) with interactive rows and instant ON/OFF status pills.
- **Dedicated Light Station (`/lights`)**: Full individual channel dimmer and toggle cards via [`LightCard.tsx`](file:///home/rc/projects/camera_system/web/components/LightCard.tsx).

### B. Auto-Connect & Auto-Start HDMI Live Streaming
- **Auto-Connect on Page Mount**: Added `useEffect` in [`web/components/StudioHeader.tsx`](file:///home/rc/projects/camera_system/web/components/StudioHeader.tsx) and [`web/app/all/components/DashboardHeader.tsx`](file:///home/rc/projects/camera_system/web/app/all/components/DashboardHeader.tsx) to automatically connect to the camera on load if detected.
- **Auto-Start HDMI WebRTC Stream**: On connection, dispatches `setLiveViewSource('hdmi')` and triggers automatic WHEP WebRTC negotiation with an auto-retry loop in [`web/components/WebRTCStreamViewer.tsx`](file:///home/rc/projects/camera_system/web/components/WebRTCStreamViewer.tsx).

### C. Direct Port 3000 URL & API Routing
- Configured dynamic API URL detection in [`web/lib/urlHelpers.ts`](file:///home/rc/projects/camera_system/web/lib/urlHelpers.ts) and Next.js rewrites in [`web/next.config.js`](file:///home/rc/projects/camera_system/web/next.config.js).
- When users access Next.js directly on port `3000` (bypassing the `cam-gateway` reverse proxy on port `3100`), API (`/api/*`) and stream (`/stream/*`) routes automatically proxy to the FastAPI backend on port `8000`.

### D. Camera Button Styling
- Toggle buttons in [`StudioHeader.tsx`](file:///home/rc/projects/camera_system/web/components/StudioHeader.tsx), [`DashboardHeader.tsx`](file:///home/rc/projects/camera_system/web/app/all/components/DashboardHeader.tsx), and [`camera-control.tsx`](file:///home/rc/projects/camera_system/web/components/camera-control.tsx) display **Green** (`bg-emerald-500/20 text-emerald-400 border-emerald-500/40`) when connected and **Red** (`bg-red-500/20 text-red-400 border-red-500/40`) when disconnected.

### E. Ingress & Reverse Proxy Diagnostics (`cam.silktex.com`)
1. **NetBird SSO Expiration on Host `ind`**: The `ingress-netbird` container experienced an expired SSO session with the management server. A non-expiring Setup Key generated in NetBird (`https://nb.rs74.net`) must be configured as `NB_SETUP_KEY` in the container stack.
2. **Cloudflare 302 Loop**: When Cloudflare SSL is set to Flexible, port 80 traffic enters an infinite 302 redirect loop with `silktex-proxy`. Cloudflare SSL mode should be set to **Full (Strict)** or configured with an Origin Rule routing `cam.silktex.com` directly to port `3100`.

---

## 3. 5-Station Studio Workbench & Classic /v1 Cockpit Routing

| Route | Primary View | Legacy / Direct Aliases | Key Functional & UI Capabilities |
| :--- | :--- | :--- | :--- |
| **`/`** | **Station 1: Capture Studio** | [`/capture`](file:///home/rc/projects/camera_system/web/app/capture/page.tsx) | Sub-100ms WebRTC WHEP live stream (1080p30 H.264 HW Encoded), stream source switcher (`HDMI` MacroSilicon USB 3.0 vs `PTP` Sony ILCE-7RM3, shortcut `S`), canvas freeze-frame snapshot (`L`), visual overlays (Rule-of-Thirds Grid, Zebra clipping, Focus peaking edge-glow), AF lock crosshairs, HUD telemetry, PTP exposure dials, 9-LED individual toggle buttons (`Space`, `T`, `1`–`8`), 61MP RAW capture (`Ctrl+S`), session filmstrip. |
| **`/batch`** | **Station 2: Batch Sequencer** | — | Automated 9-light multi-angle sequence engine, batch folder/prefix configuration, calibration profile selector, light stabilize delay stepper, live stepped progress bar, camera PIP feedback monitor, auto-registration into completed batches table. |
| **`/calibration`** | **Station 3: Color Calibration** | [`/color-calibration`](file:///home/rc/projects/camera_system/web/app/color-calibration/page.tsx) | 24-patch X-Rite ColorChecker Classic interactive grid, deep patch inspector (Reference sRGB D65 vs Measured Camera RGB, CIE2000 $\Delta E$ error), 90° canvas rotation/flip, spectral calibration metrics, $3\times3$ CCM output, ICC profile (.icc) export. |
| **`/processing`** | **Station 4: PBR Synthesis Lab** | [`/pbr`](file:///home/rc/projects/camera_system/web/app/pbr/page.tsx) | 2x2 synchronized material map viewports (Albedo, Normal, Roughness, Displacement), interactive 3D virtual light probe sphere, 4K/8K resolution selector, material presets, glTF 2.0 package (.zip) export. |
| **`/gallery`** | **Station 5: Inspection Lightbox** | — | 61.0 MP RAW image deep-zoom lightbox, view mode toggle (100% 1:1 Pixel View vs Fit to Screen), mouse-following 100% pixel loupe overlay, 9-light directional switcher toolbar, EXIF hardware telemetry card, RAW+TIFF batch download (.zip). |
| **`/v1`** | **Restored Classic UI Cockpit** | [`/all`](file:///home/rc/projects/camera_system/web/app/all/page.tsx) | Restored 2-column classic cockpit (`460px` sidebar + main viewport), `Single` / `Color` / `Batch` tabs, sidebar ESP32 LightControlPanel with individual switches, modern WebRTC live stream with HDMI/PTP source switcher. |
| **Header** | **Studio Header** | [`StudioHeader.tsx`](file:///home/rc/projects/camera_system/web/components/StudioHeader.tsx) | Global station navigation tabs with active badges, camera PTP auto-connect & toggle (`Ctrl+C`), ESP32 light rig status pod, non-destructive Re-Detect button (`troubleshootCamera`), keyboard shortcuts modal (`?`). |
| **Tools** | **Specialized Tools Hub** | [`/processing/tools`](file:///home/rc/projects/camera_system/web/app/processing/tools/page.tsx) | Pipeline tools (Perspective, Equalize, Flatten, Delight, Seamless, Tiling), utility tools (PBR Validate, Clone Stamp), 4-point Crop editor, Cockpit tab switcher, standalone ESP32 Light Controller ([`/lights`](file:///home/rc/projects/camera_system/web/app/lights/page.tsx)). |

---

## 4. Hardware Video Streaming & Transcoding Pipeline

```
                                  +------------------------------------+
                                  | MacroSilicon USB 3.0 HDMI Capture  |
                                  | (/dev/video0, 1080p30 MJPEG raw)  |
                                  +-----------------+------------------+
                                                    |
                                                    v
                                  +------------------------------------+
                                  | AMD Radeon Vega 11 GPU (VCN 1.0)   |
                                  | VA-API Encoder (/dev/dri/renderD128|
                                  | H.264 Constrained Baseline, 4Mbps  |
                                  +-----------------+------------------+
                                                    | (rtsp://127.0.0.1:8554/stream)
                                                    v
                                  +------------------------------------+
                                  | MediaMTX RTSP / WebRTC Server      |
                                  | :8554 (RTSP), :8889 (WHEP)         |
                                  +-----------------+------------------+
                                                    |
                                                    v
                                  +------------------------------------+
                                  | cam-gateway (Nginx :3100)          |
                                  | /stream/ -> :8889 (WHEP Signaling) |
                                  | /api/    -> :8000 (FastAPI)        |
                                  | /        -> :3000 (Next.js)        |
                                  +-----------------+------------------+
                                                    |
                                                    v
                                  +------------------------------------+
                                  | Frontend WebRTCStreamViewer.tsx    |
                                  | Sub-100ms Latency WHEP Player      |
                                  +------------------------------------+
```

---

## 5. Build, Test, and Deployment Commands

```bash
# Run all Vitest unit & component tests
npm --prefix web run test

# Run all Playwright E2E UI tests
npm --prefix web run test:e2e

# Run Next.js production build
npm --prefix web run build

# Sync files to remote host ind (ESP-PC, 10.10.2.21)
rsync -avz --no-owner --no-group --exclude 'node_modules' --exclude '.next' --exclude '.venv' --exclude '__pycache__' /home/rc/projects/camera_system/ ind:/home/posh/projects/camera_system/

# Rebuild and restart Docker container on host ind
ssh ind "cd /home/posh/projects/camera_system && sudo docker compose up -d --build camera-system"
```

---

## 6. Key Files & Artifacts

- [`handoff.md`](file:///home/rc/projects/camera_system/handoff.md) — Master project handoff document.
- [`web/app/page.tsx`](file:///home/rc/projects/camera_system/web/app/page.tsx) — Station 1 Capture Studio with 9-channel individual light toggle buttons grid and dual stream source switcher.
- [`web/components/StudioHeader.tsx`](file:///home/rc/projects/camera_system/web/components/StudioHeader.tsx) — Top studio header with auto-connect on load and green/red status styling.
- [`web/components/WebRTCStreamViewer.tsx`](file:///home/rc/projects/camera_system/web/components/WebRTCStreamViewer.tsx) — Native WebRTC WHEP client with auto-connection and retry mechanisms.
- [`web/app/all/components/LightControlPanel.tsx`](file:///home/rc/projects/camera_system/web/app/all/components/LightControlPanel.tsx) — Interactive individual light switches for `/all` and `/v1`.
- [`web/app/lights/page.tsx`](file:///home/rc/projects/camera_system/web/app/lights/page.tsx) & [`web/components/LightCard.tsx`](file:///home/rc/projects/camera_system/web/components/LightCard.tsx) — Dedicated lighting rig station.
- [`web/lib/urlHelpers.ts`](file:///home/rc/projects/camera_system/web/lib/urlHelpers.ts) & [`web/next.config.js`](file:///home/rc/projects/camera_system/web/next.config.js) — Port 3000 direct access dynamic routing and API rewrites.
- [`api/app/services/video_device_service.py`](file:///home/rc/projects/camera_system/api/app/services/video_device_service.py) — MacroSilicon V4L2 device discovery and VA-API hardware encoder.

---

## 7. Suggested Skills

- `react-doctor` — Run when inspecting React components, state hooks, or performance in `web/app/`.
- `beads` — Track task dependencies and progress (`bd ready`, `bd update`).
- `portainer-skill` / `netbird-portainer` — Monitor Docker container deployments and NetBird proxy routing on host `ind`.
- `graphify` — Query architectural dependencies and god nodes (`graphify update .`).
- `caveman` / `caveman-commit` — Efficient token communication and clean commit generation when staging changes.
