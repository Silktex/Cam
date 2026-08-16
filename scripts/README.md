# scripts — VA-API RTSP pipeline: stream + bandwidth governor

This directory is the operating core for the camera RTSP pipeline (Phase 3:
bandwidth-adaptive frame-rate governor + selectable resolution tiers).

| File | Role |
|---|---|
| `stream.sh` | VA-API hardware-encoded H.264 RTSP publish (existing Phase 2, extended) |
| `fps_governor.py` | Bandwidth-adaptive frame-rate governor (this phase) |
| `stream_state.json` | JSON control/state file: `{resolution, fps, bitrate}` |
| `fake_publisher.sh` | Hermetic stand-in for `stream.sh` (deterministic tests only) |

---

## Quick start

Prerequisites (already on this host): ffmpeg 7.1.5 with h264_vaapi + libzmq,
mediamtx on `:8554` (running, PID ~37964), camera on `/dev/video0`,
`/dev/dri/renderD128` (AMD VCN 1.0).

```bash
# 1. Publish stream only (no governor)
./scripts/stream.sh                                   # 1080p30 @ 4M CBR default
RESOLUTION=1280x720 FPS=25 BITRATE=2M ./scripts/stream.sh

# 2. Run the governor (launches stream.sh, adapts fps to bandwidth)
./scripts/fps_governor.py

# 3. Governor with configurable options
./scripts/fps_governor.py \
  --resolution 1920x1080 --start-fps 30 \
  --sample-interval 5 --interface lo \
  --log-file /var/log/fps_governor.log

# 4. Stop: SIGTERM/SIGINT kills stream and governor cleanly
```

Watch it adapt:

```bash
tail -f /tmp/fps_governor.log    # or wherever --log-file points
cat scripts/stream_state.json    # current {resolution, fps, bitrate}
```

---

## Tier model (approved constants)

| fps tiers | resolution tiers | CBR @ 30fps |
|---|---|---|
| 30, 20, 15, 10, 5 | 1920x1080, 1280x720, 960x540 | 4M, 2.5M, 1.5M |

- **Bitrate scales with fps**: `bitrate(fps) = round(base_kbps * fps / 30)` so
  stepping fps down also frees real bandwidth (CBR target drops).
- **Headroom = 1.3**: a tier is affordable only when
  `bitrate(fps) * 1.3 <= measured bandwidth` (plan's "target × 1.3 must fit
  under measured bandwidth").
- **Hysteresis = 2**: a step fires only after 2 consecutive samples agree on
  the same direction (no flapping on single-sample noise).
- Steps move **one tier at a time**; the governor climbs/descends through every
  intermediate fps.

Example affordability thresholds at 1080p (base 4M):

| fps | bitrate | needs ≥ (×1.3) |
|---|---|---|
| 30 | 4000k | 5.2 Mbit/s |
| 20 | 2667k | 3.5 Mbit/s |
| 15 | 2000k | 2.6 Mbit/s |
| 10 | 1333k | 1.7 Mbit/s |
| 5  | 667k  | 0.9 Mbit/s |

Encoder settings per tier are derived and handed to `stream.sh` via env
(`FPS`, `BITRATE`, `MAXRATE=BITRATE`, `BUFSIZE=2×BITRATE`, `GOP=2×fps`). The
encoder is always `h264_vaapi` constrained_baseline, `-bf 0`, CBR — the VCN 1.0
constraints are preserved. No `-global_quality` anywhere.

---

## Bandwidth measurement (which one and why)

**Default: `/proc/net/dev` egress deltas on the interface carrying the RTSP
publish** (`--interface lo` default; use e.g. `enp1s0f0` for a LAN path).

Why this one:

- `ffmpeg -progress` reports `bitrate=N/A` / `total_size=N/A` for RTSP muxers
  (verified on this build) — the task's *preferred* signal is not available
  for RTSP output. The `fps=` field is present and is logged as a sanity
  signal when `PROGRESS_FILE` is set, but not used for decisions.
- A self-contained loopback TCP probe was built and verified to read the shaped
  rate standalone, but its probe connection stalls on a *fully saturated*
  shaped loopback — unreliable exactly when the link is constrained.
- Egress deltas are robust under congestion: with `tc netem rate 3mbit` on `lo`
  a 4M stream's egress reads ~3.0 Mbit/s (capped); unconstrained it reads
  ~5.6 Mbit/s (CBR + overhead). Both directions of the governor's decision are
  supported, because egress tracks the *current tier's actual* rate — the
  headroom + one-tier-at-a-time hysteresis makes recovery self-correcting.

`--probe-addr` enables the TCP probe variant (kept for environments where
egress counting isn't representative, e.g. remote mediamtx).

---

## Resolution selection (control file)

Resolution is a **user-selectable tier**: edit `scripts/stream_state.json` and
the governor picks up the change within one sample interval, restarts the
publish at the new resolution, and rewrites the file with the derived bitrate.

```json
{
  "resolution": "1280x720",
  "fps": 30,
  "bitrate_kbps": 2500
}
```

Allowed resolutions: `1920x1080`, `1280x720`, `960x540`. `fps`/`bitrate_kbps`
are informational (governor-managed); `resolution` is the control input. The
governor also reads this file at startup and writes it after every step/restart
(UI wiring is deferred to Phase 4+ — this file is that surface).

---

## Live reconfiguration: why graceful restart (not zmq)

The task asked to check zmq first. Findings on this ffmpeg 7.1.5 build:

- zmq **is** compiled in: `--enable-libzmq`, `ffmpeg -hide_banner -h filter=zmq`
  succeeds, filter binds `tcp://*:5555` by default.
- But the `fps` filter does **not** implement `process_command`. Verified
  empirically via the `sendcmd` filter (same `avfilter_graph_send_command`
  machinery zmq uses): `Command reply command #0: ret:Function not
  implemented`. So no live frame-rate option change is possible through zmq on
  this build.

Therefore the governor uses **graceful restart** for every tier change:
SIGTERM the running publish, relaunch `stream.sh` with fresh
`FPS`/`BITRATE`/`MAXRATE`/`BUFSIZE`/`GOP`/`RESOLUTION` env. This path is always
available, and doubles as crash recovery (unexpected publish exit → relaunch at
the current tier). If a future ffmpeg adds fps-command support, the
`_apply_fps` / `_launch_publish` split is the seam for a zmq fast path.

---

## Running the tests

### 1. Deterministic (scripted bandwidth trace — required evidence)

Hermetic; no camera or mediamtx needed. Uses `fake_publisher.sh` which records
the FPS env the governor hands it (proof of reconfiguration).

```bash
# Full down ladder then full recovery:
FPS_ENV_LOG=/tmp/fake_env.log ./scripts/fps_governor.py \
  --publish-cmd scripts/fake_publisher.sh \
  --test-bw 6.0,6.0,6.0,6.0,4.0,4.0,3.0,3.0,2.0,2.0,1.0,1.0,0.6,0.6,0.6,1.8,1.8,2.8,2.8,3.8,3.8,5.6,5.6,5.6 \
  --sample-interval 1 --probe-duration 0.2

cat /tmp/fake_env.log      # FPS=30 FPS=20 FPS=15 FPS=10 FPS=5 FPS=10 FPS=15 FPS=20 FPS=30
```

Expected transitions (logged as `STEP fps X -> Y`):

```
30 -> 20 -> 15 -> 10 -> 5     (bandwidth trace 6.0 → 0.6 Mbit/s)
5 -> 10 -> 15 -> 20 -> 30     (bandwidth trace recovers to 5.6 Mbit/s)
```

`--test-bw` is a comma-separated bandwidth trace in **Mbit/s**; the last value
repeats forever. Any bandwidth source can be substituted — the decision logic
is identical to the real path.

### 2. Real end-to-end with `tc` netem

Real `stream.sh` publish (hardware h264_vaapi, synthetic `testsrc` source via
`--video-source lavfi`, or the real camera with `v4l2`), loopback path shaped
with netem.

> Note: loopback TCP can be unreliable to shape precisely; on this host the
> **egress-based** measurement is shaped cleanly by `tc netem` on `lo`, which
> is what the governor uses by default. (The old TCP-probe variant also reads
> the shaped rate when the link isn't fully saturated.)

```bash
./scripts/fps_governor.py --interface lo --video-source lavfi --sample-interval 3 &
sleep 15                       # stable at 30fps (~19 Mbit/s egress)

sudo tc qdisc add dev lo root netem rate 3mbit     # constrain
sleep 30                      # expect STEP 30 -> 20 -> 15, settle ~15fps

sudo tc qdisc del dev lo root                       # lift
sleep 30                      # expect STEP 15 -> 20 -> 30, back to 30fps

kill %1                       # clean stop
```

Hardware verification after any real run:

```bash
grep -c 'h264_vaapi'  /tmp/gov_real_console.log      # > 0 (encoder is VA-API)
grep -ic 'libx264'     /tmp/gov_real_console.log      # == 0 (no software fallback)
sudo dmesg | grep -icE 'ring.*timeout|gfx.*reset'     # == 0 (no GPU errors)
```

### 3. Resolution switching

```bash
./scripts/fps_governor.py &
python3 - <<'EOF'
import json
d = json.load(open("scripts/stream_state.json"))
d["resolution"] = "1280x720"          # or 960x540
json.dump(d, open("scripts/stream_state.json", "w"), indent=2)
EOF
# within ~1 sample interval the publish restarts at 1280x720/2.5M
```

---

## Environment / CLI reference

`stream.sh` env vars (unchanged interface, two additions):

| Var | Default | Notes |
|---|---|---|
| `VAAPI_DEVICE` | `/dev/dri/renderD128` | |
| `VIDEO_DEVICE` | `/dev/video0` | |
| `RESOLUTION` | `1920x1080` | |
| `FPS` | `30` | |
| `BITRATE` / `MAXRATE` | `4M` | CBR |
| `BUFSIZE` | `8M` | |
| `GOP` | `60` | |
| `LEVEL` | `4.0` | |
| `RTSP_URL` | `rtsp://127.0.0.1:8554/stream` | |
| `VIDEO_SOURCE` | `v4l2` | `lavfi` = synthetic testsrc (tests only) |
| `PROGRESS_FILE` | *(empty)* | `-progress` key=value stats file |

`fps_governor.py` CLI:

| Flag | Default | Notes |
|---|---|---|
| `--resolution` | `1920x1080` | start resolution tier |
| `--start-fps` | `30` | start fps tier |
| `--state-file` | `scripts/stream_state.json` | control/state file |
| `--publish-cmd` | `scripts/stream.sh` | publish command |
| `--sample-interval` | `5.0` | seconds between samples |
| `--interface` | `lo` | `/proc/net/dev` egress interface |
| `--probe-addr` | *(empty)* | enable TCP probe variant on this addr |
| `--probe-port` | `18400` | TCP probe sink port |
| `--probe-duration` | `1.0` | probe blast seconds |
| `--progress-file` | *(empty)* | read achieved publish fps (logging) |
| `--video-source` | `v4l2` | passed through to stream.sh |
| `--log-file` | *(empty)* | append log lines here |
| `--test-bw` | *(empty)* | scripted Mbit/s trace (deterministic tests) |

---

## Verified on this host (evidence summary)

- Deterministic trace: `30→20→15→10→5→10→15→20→30`, each step after 2
  consecutive samples; fake publisher recorded every relaunch's FPS/BITRATE.
- Real e2e (lavfi → h264_vaapi, `tc netem rate 3mbit` on `lo`, then removed):
  `30→20→15→10` under constraint, `10→15→20→30` after recovery.
- Resolution switch via control file: `1920x1080 → 1280x720 → 960x540`, each
  restart picked up by governor with correct CBR (4M/2.5M/1.5M) and confirmed
  by the running ffmpeg `size=...`.
- Encoder always `h264_vaapi` (0 `libx264`), `dmesg` GPU error count 0.
- mediamtx left running (PID ~37964); all test ffmpeg/governor processes
  cleaned up, netem qdiscs removed.

---

# Phase 4: systemd productionization, monitoring, camera resilience

The pipeline now runs as **systemd host services** (no containers). Three units
in `/etc/systemd/system/`:

| Unit | Runs | Restart policy |
|---|---|---|
| `camera-stream-mediamtx.service` | `/usr/local/bin/mediamtx mediamtx.yml` (User=posh) | `Restart=always`, `RestartSec=2` |
| `camera-stream-publish.service` | `fps_governor.py` (launches `stream.sh`; User=posh) | `Restart=always`, `RestartSec=2` |
| `camera-stream-monitor.service` | `monitor.sh --loop --interval 5` (User=posh) | `Restart=always` |

- Publish `Requires=` + `After=` mediamtx (stops with it, starts after it).
  The camera device is **ordered-only** (`After=dev-video0.device`): systemd
  does not track `/dev/video0` as a device unit on this host, and a hard
  `Requires=` would fail boot when the camera enumerates late. Absence is
  handled by the retry loop below — do NOT add `ConditionPathExists=/dev/video0`
  (a unit with that condition will not auto-start when the device reappears).
- Both services run as `posh` (verified non-root access to `/dev/video0` and
  `/dev/dri/renderD128` via `video`/`render` groups + ACLs). Root not needed.
- mediamtx logs to journald (`logLevel: info`, `logDestinations: [stdout]`).

## Operate

```bash
# Status (all three) — expect "active (running)"
systemctl status camera-stream-mediamtx camera-stream-publish camera-stream-monitor

# Start / stop / restart (stop mediamtx stops publish via Requires)
sudo systemctl start  camera-stream-publish     # also starts mediamtx
sudo systemctl stop   camera-stream-publish
sudo systemctl restart camera-stream-publish
sudo systemctl enable --now camera-stream-mediamtx camera-stream-publish camera-stream-monitor

# Boot persistence
systemctl is-enabled camera-stream-mediamtx camera-stream-publish camera-stream-monitor

# Listener check
ss -ltn | grep 8554

# Watch logs (all three units)
journalctl -fu camera-stream-publish
journalctl -fu camera-stream-mediamtx
journalctl -fu camera-stream-monitor        # one CSV sample line per 5 s

# Verify the encode is VA-API (never libx264) and the GPU is clean
journalctl -u camera-stream-publish | grep -c h264_vaapi
journalctl -u camera-stream-publish | grep -ic libx264        # must be 0
sudo dmesg | grep -icE 'ring.*timeout|gfx.*reset'             # must be 0
```

## Monitoring

`scripts/monitor.sh` emits one line per sample:

```
timestamp,gpu_busy_pct,fps,bitrate_kbps,live_fps,live_bitrate_kbps
2026-08-15T08:20:00Z,24.6,30,4000,30.0,n/a
```

- `gpu_busy_pct` is **VCN encoder utilization**: on this APU
  `/sys/class/drm/card0/device/gpu_busy_percent` and `gpu_metrics` both return
  `-EOPNOTSUPP`, so the kernel-native `/proc/<pid>/fdinfo drm-engine-enc`
  counter of the running ffmpeg render-node fd is used (delta / wall-time). At
  1080p30 CBR 4M the VCN block sits around ~25%.
- `fps`/`bitrate_kbps` come from `scripts/stream_state.json` (governor target
  tier). `live_fps` is ffprobe'd from the RTSP stream.
- `live_bitrate_kbps` is always `n/a`: RTSP muxers report `bit_rate=N/A`
  (verified on this ffmpeg build) — the CBR target in `bitrate_kbps` is the
  authoritative figure.
- First sample after startup shows `gpu_busy_pct=n/a` (needs a prior counter
  reading for the delta). Run standalone: `./scripts/monitor.sh --loop --interval 5`.

## Changing resolution

Edit `scripts/stream_state.json` — the governor detects the mtime change within
one sample interval (5 s) and gracefully restarts the publish at the new tier:

```json
{ "resolution": "1280x720", "fps": 30, "bitrate_kbps": 2500 }
```

Allowed resolutions: `1920x1080` (4M base), `1280x720` (2.5M), `960x540`
(1.5M). `fps`/`bitrate_kbps` are informational — the governor rewrites them.
Verify: `systemctl status camera-stream-publish` shows a fresh stream.sh/ffmpeg,
then `journalctl -u camera-stream-monitor -n 3` for the new tier in the CSV.

## Camera unplug/replug resilience (how it works)

`stream.sh` no longer exits when `/dev/video0` is missing (old behavior: `exit 2`).
Instead the v4l2 path runs a **retry loop with exponential backoff** (2 s → 4 s →
8 s → 16 s → 30 s cap) that:

1. Waits for `/dev/video0` to appear (covers boot races and unplugged cameras),
2. Launches ffmpeg, and if ffmpeg dies while the device is gone (unplug
   mid-stream), waits again and relaunches as soon as the device returns.

Signals still propagate: SIGTERM/SIGINT forward to ffmpeg, so the governor's
graceful-stop path (tier change, resolution change, service stop) is unaffected
and exits with a clean rc. While the camera is absent the governor's egress
bandwidth signal collapses (the stream isn't moving bytes), so it steps fps
down and back up on recovery — harmless, self-correcting, and visible as
`STEP fps X -> Y` in the publish journal.

To exercise it without unplugging hardware (all as root):

```bash
# simulate unplug: detach the MS2109 from the USB driver
echo 4-1.1 | sudo tee /sys/bus/usb/drivers/usb/unbind
ls /dev/video0                     # gone; publish logs "camera /dev/video0 absent; retrying in Ns"
# simulate replug
echo 4-1.1 | sudo tee /sys/bus/usb/drivers/usb/bind
ls /dev/video0                     # back; publish logs "camera /dev/video0 present; launching ffmpeg"
journalctl -fu camera-stream-publish
```

Find the camera's USB address (vendor `534d` = MacroSilicon):
`for d in /sys/bus/usb/devices/*/; do [ "$(cat $d/idVendor 2>/dev/null)" = 534d ] && echo $d; done`

## Detecting a problem

| Symptom | Check | Fix |
|---|---|---|
| Stream offline, services fine | `journalctl -u camera-stream-publish -n 50` for `absent`/`exited rc=` | Camera unplugged → replug; loop self-heals |
| Publish in `activating`/`failed` | `systemctl status camera-stream-publish` | `journalctl -u camera-stream-publish -n 50`; config/device access |
| No `:8554` listener | `ss -ltn` + `systemctl status camera-stream-mediamtx` | `sudo systemctl restart camera-stream-mediamtx` |
| `gpu_busy_pct` stays `n/a` | `pgrep -af h264_vaapi` | No publish running → camera absent or publish down |
| Encoding fell back to CPU | `journalctl -u camera-stream-publish \| grep -ic libx264` ≠ 0 | VA-API device issue; check `/dev/dri/renderD128` |
| GPU errors after any change | `sudo dmesg \| grep -icE 'ring.*timeout\|gfx.*reset'` ≠ 0 | Revert recent encoder/DRM changes |

## Boot start

All three units are `systemctl enable`d (`multi-user.target`). On boot the
governor starts even if the camera is still enumerating; `stream.sh` waits in
its retry loop until `/dev/video0` exists, then publishing begins automatically.
