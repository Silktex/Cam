#!/usr/bin/env bash
# monitor.sh - compact camera-stream health sampler.
#
# Emits one CSV line per sample:
#   timestamp,gpu_busy_pct,fps,bitrate_kbps,live_fps,live_bitrate_kbps
#   (live_* are ffprobe'd from the RTSP stream; "n/a" when unavailable)
#
# gpu_busy_pct measures VCN hardware-encode utilization: on this APU the
# amdgpu gpu_busy_percent/gpu_metrics sysfs files return -EOPNOTSUPP, so the
# kernel-native /proc/<pid>/fdinfo drm-engine-enc counter of the running
# ffmpeg render-node fd is used instead (delta / wall-time, i.e. what fraction
# of the sample window the H.264 encoder block was busy).
#
# Sources:
#   gpu_busy_pct  ffmpeg fdinfo drm-engine-enc delta (VCN encode busy %)
#   fps/bitrate   scripts/stream_state.json (governor target tier)
#   live_*        ffprobe of the RTSP stream (actual achieved values)
#
# Usage:
#   ./scripts/monitor.sh                       # one sample (~interval s)
#   ./scripts/monitor.sh --loop                # sample every --interval seconds
#   ./scripts/monitor.sh --loop --interval 5   # (systemd: default 5s)
#   ./scripts/monitor.sh --journal             # also forward lines to journald
#
# Under systemd stdout already lands in journald; --journal is for manual runs.

set -u

STATE_FILE="${STATE_FILE:-/home/posh/Desktop/camera_system/scripts/stream_state.json}"
RTSP_URL="${RTSP_URL:-rtsp://127.0.0.1:8554/stream}"
INTERVAL=5
LOOP=0
JOURNAL=0
prev_enc=""
prev_now=""

usage() {
  sed -n '2,24p' "$0" | sed 's/^# //'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --loop) LOOP=1 ;;
    --journal) JOURNAL=1 ;;
    --interval) INTERVAL="$2"; shift ;;
    --rtsp) RTSP_URL="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

# Encoder busy ns of the running publish (max across its render-node fds).
# Empty when no ffmpeg publish is alive. The bracketed pgrep pattern
# (h264_vaap[i]) prevents the pattern itself from matching this process.
enc_read() {
  local pid v maxns
  pid=$(pgrep -f 'h264_vaap[i].*-f rtsp' | head -1)
  [ -z "${pid}" ] && { echo ""; return; }
  maxns=0
  for f in /proc/${pid}/fdinfo/*; do
    v=$(awk '/^drm-engine-enc:/{print $2}' "$f" 2>/dev/null)
    [ -n "${v}" ] && [ "${v}" -gt "${maxns}" ] && maxns="${v}"
  done
  echo "${maxns}"
}

sample() {
  local ts gpu fps bitrate live_fps live_kbps probe rate bits now cur
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  now=$(date +%s%N)
  cur=$(enc_read)
  gpu="n/a"
  if [ -n "${prev_enc}" ] && [ -n "${cur}" ] && [ "${cur}" -ge "${prev_enc}" ] && [ "${now}" -gt "${prev_now}" ]; then
    gpu=$(awk -v d="$((cur - prev_enc))" -v t="$((now - prev_now))" 'BEGIN{printf "%.1f", d * 100 / t}')
  fi
  prev_enc="${cur}"
  prev_now="${now}"

  fps="n/a"; bitrate="n/a"
  if [ -r "${STATE_FILE}" ]; then
    read -r fps bitrate < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("fps","n/a"), d.get("bitrate_kbps","n/a"))' "${STATE_FILE}" 2>/dev/null)
  fi
  live_fps="n/a"; live_kbps="n/a"
  probe=$(timeout 4 ffprobe -v error -select_streams v:0 \
    -show_entries stream=r_frame_rate,bit_rate \
    -of default=noprint_wrappers=1:nokey=1 "${RTSP_URL}" 2>/dev/null)
  if [ -n "${probe}" ]; then
    rate=$(echo "${probe}" | sed -n 1p)
    bits=$(echo "${probe}" | sed -n 2p)
    case "${rate}" in
      */*) live_fps=$(awk -v r="${rate}" 'BEGIN{split(r,a,"/"); printf "%.1f", a[1]/a[2]}') ;;
      *) [ -n "${rate}" ] && live_fps="${rate}" ;;
    esac
    case "${bits}" in
      *[0-9]*) live_kbps=$((bits / 1000)) ;;
    esac
  fi
  LINE="${ts},${gpu},${fps},${bitrate},${live_fps},${live_kbps}"
}

echo "timestamp,gpu_busy_pct,fps,bitrate_kbps,live_fps,live_bitrate_kbps"
sample_once() {
  sample
  echo "${LINE}"
  [ "${JOURNAL}" -eq 1 ] && logger -t camera-stream-monitor "${LINE}"
}

if [ "${LOOP}" -eq 1 ]; then
  while :; do
    sample_once
    sleep "${INTERVAL}"
  done
else
  prev_enc=$(enc_read)
  prev_now=$(date +%s%N)
  sleep "${INTERVAL}"
  sample_once
fi
