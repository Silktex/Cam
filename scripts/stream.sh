#!/usr/bin/env bash
# stream.sh — VA-API hardware-encoded RTSP publish pipeline for camera_system.
#
# Captures MJPEG from /dev/video0, decodes, converts to NV12, uploads to the
# AMD VCN via VA-API (h264_vaapi), and publishes H.264 Constrained Baseline
# over RTSP (TCP) to a local mediamtx server.
#
# Hardware constraints baked in (VCN 1.0 / Vega 11):
#   - constrained_baseline profile + -bf 0 (B-frames unsupported)
#   - CBR rate control via -b:v / -maxrate / -bufsize (NOT -global_quality)
#
# Usage:
#   ./stream.sh                 # defaults (1080p30 @ 4 Mbit)
#   RESOLUTION=1280x720 FPS=25 BITRATE=2M ./stream.sh
#   STREAM_PATH=cam2 ./stream.sh
#
# Env vars (with defaults):
#   VAAPI_DEVICE  VA-API render node            (default: /dev/dri/renderD128)
#   VIDEO_DEVICE  V4L2 capture device           (default: /dev/video0)
#   RESOLUTION    capture/encode resolution     (default: 1920x1080)
#   FPS           capture frame rate            (default: 30)
#   BITRATE       H.264 CBR bitrate             (default: 4M)
#   MAXRATE       peak bitrate (= BITRATE for CBR, default: 4M)
#   BUFSIZE       VBV buffer size               (default: 8M)
#   GOP           keyframe interval in frames   (default: 60)
#   LEVEL         H.264 level                   (default: 4.0)
#   RTSP_URL      publish destination           (default: rtsp://127.0.0.1:8554/stream)
#   VIDEO_SOURCE  'v4l2' (default) or 'lavfi'   (default: v4l2)
#                 lavfi uses a synthetic testsrc pattern — for CI / governor
#                 testing without a physical camera. Encoder stays h264_vaapi.
#   PROGRESS_FILE write ffmpeg -progress key=value stats to this file, updated
#                 periodically (bitrate / fps of the running publish). Empty
#                 disables. Used by scripts/fps_governor.py. (default: empty)
#
# Exit codes:
#   0  clean stop (SIGINT/SIGTERM or explicit kill)
#   1  invalid VA-API device / encoder unavailable
#   2  unused in v4l2 mode (camera absence handled by the internal retry loop)
#   3  ffmpeg exited with an error

set -u

# --- Configuration (env-overridable) -------------------------------------
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"
VIDEO_DEVICE="${VIDEO_DEVICE:-/dev/video0}"
RESOLUTION="${RESOLUTION:-1920x1080}"
FPS="${FPS:-30}"
BITRATE="${BITRATE:-4M}"
MAXRATE="${MAXRATE:-4M}"
BUFSIZE="${BUFSIZE:-8M}"
GOP="${GOP:-60}"
LEVEL="${LEVEL:-4.0}"
RTSP_URL="${RTSP_URL:-rtsp://127.0.0.1:8554/stream}"
VIDEO_SOURCE="${VIDEO_SOURCE:-v4l2}"
PROGRESS_FILE="${PROGRESS_FILE:-}"

# --- Pre-flight checks ----------------------------------------------------
if [ ! -e "${VAAPI_DEVICE}" ]; then
  echo "ERROR: VA-API device ${VAAPI_DEVICE} not found" >&2
  exit 1
fi

if ! ffmpeg -hide_banner -encoders 2>/dev/null | grep -q ' h264_vaapi '; then
  echo "ERROR: ffmpeg build has no h264_vaapi encoder" >&2
  exit 1
fi

# Input selection: real camera (v4l2) or synthetic pattern (lavfi, for tests).
INPUT_ARGS=()
if [ "${VIDEO_SOURCE}" = "v4l2" ]; then
  # Camera presence is NOT fatal: the retry loop below waits for /dev/video0
  # to appear (boot races, unplug/replug) instead of exiting.
  INPUT_ARGS=(-f v4l2 -input_format mjpeg -video_size "${RESOLUTION}" -framerate "${FPS}" -i "${VIDEO_DEVICE}")
  echo "Publishing ${RESOLUTION}@${FPS} ${BITRATE} (CBR) from ${VIDEO_DEVICE} to ${RTSP_URL}" >&2
else
  INPUT_ARGS=(-f lavfi -i "testsrc=size=${RESOLUTION}:rate=${FPS},format=yuv420p")
  echo "Publishing ${RESOLUTION}@${FPS} ${BITRATE} (CBR) from synthetic testsrc to ${RTSP_URL}" >&2
fi
echo "  encoder: h264_vaapi on ${VAAPI_DEVICE} (constrained_baseline, level ${LEVEL}, bf 0)" >&2

# -progress stats file (key=value), truncated each launch.
PROGRESS_ARGS=()
if [ -n "${PROGRESS_FILE}" ]; then
  PROGRESS_ARGS=(-progress "${PROGRESS_FILE}" -nostats)
fi

FFMPEG_ARGS=(
  -hide_banner -loglevel info
  -vaapi_device "${VAAPI_DEVICE}"
  "${INPUT_ARGS[@]}"
  -vf 'format=nv12,hwupload'
  -c:v h264_vaapi -profile:v constrained_baseline -level "${LEVEL}" -bf 0
  -rc_mode CBR -b:v "${BITRATE}" -maxrate "${MAXRATE}" -bufsize "${BUFSIZE}" -g "${GOP}"
  "${PROGRESS_ARGS[@]}"
  -f rtsp -rtsp_transport tcp "${RTSP_URL}"
)

run_ffmpeg() {
  if [ -n "${PROGRESS_FILE}" ]; then
    : > "${PROGRESS_FILE}"
  fi
  ffmpeg "${FFMPEG_ARGS[@]}" &
  FFMPEG_PID=$!
}

case "${VIDEO_SOURCE}" in
  v4l2)
    # Camera unplug/replug resilience: retry opening /dev/video0 with
    # exponential backoff. Handles (a) device absent at startup and (b)
    # ffmpeg dying when the camera is unplugged mid-stream — wait for the
    # device to return, then relaunch. SIGTERM/SIGINT forward to ffmpeg so
    # the governor's graceful-stop path still works (rc 0/130/143 = clean).
    BACKOFF_INIT=2
    BACKOFF_MAX=30
    backoff=${BACKOFF_INIT}
    trap 'echo "stream.sh: signal; stopping ffmpeg" >&2; [ -n "${FFMPEG_PID:-}" ] && kill -TERM "${FFMPEG_PID}" 2>/dev/null; wait 2>/dev/null; exit 0' TERM INT
    while :; do
      if [ ! -e "${VIDEO_DEVICE}" ]; then
        echo "camera ${VIDEO_DEVICE} absent; retrying in ${backoff}s" >&2
        sleep "${backoff}"
        backoff=$((backoff * 2)); [ "${backoff}" -gt "${BACKOFF_MAX}" ] && backoff="${BACKOFF_MAX}"
        continue
      fi
      backoff=${BACKOFF_INIT}
      echo "camera ${VIDEO_DEVICE} present; launching ffmpeg" >&2
      run_ffmpeg
      wait "${FFMPEG_PID}"
      rc=$?
      if [ "${rc}" -eq 0 ] || [ "${rc}" -eq 130 ] || [ "${rc}" -eq 143 ]; then
        echo "stream.sh: ffmpeg stopped cleanly (rc=${rc}); exiting" >&2
        exit 0
      fi
      echo "stream.sh: ffmpeg exited rc=${rc}; camera unplugged? relaunching after ${backoff}s" >&2
      sleep "${backoff}"
      backoff=$((backoff * 2)); [ "${backoff}" -gt "${BACKOFF_MAX}" ] && backoff="${BACKOFF_MAX}"
    done
    ;;
  *)
    exec ffmpeg "${FFMPEG_ARGS[@]}"
    ;;
esac
