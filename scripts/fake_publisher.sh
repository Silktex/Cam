#!/usr/bin/env bash
# fake_publisher.sh — hermetic stand-in for stream.sh used by fps_governor.py
# deterministic tests. It does NOT encode video: it only records the FPS env
# the governor handed it (proof of reconfiguration), then stays alive until
# terminated so the governor's graceful-restart cycle can be exercised.
#
#   FPS_ENV_LOG=<file>  append "FPS=<n> BITRATE=<b> RESOLUTION=<r>" per launch
#
# Without FPS_ENV_LOG the settings are echoed to stderr.

set -u
FPS_ENV_LOG="${FPS_ENV_LOG:-}"

if [ -n "${FPS_ENV_LOG}" ]; then
  printf 'FPS=%s BITRATE=%s RESOLUTION=%s\n' "${FPS:-?}" "${BITRATE:-?}" "${RESOLUTION:-?}" >> "${FPS_ENV_LOG}"
else
  echo "fake_publisher: FPS=${FPS:-?} BITRATE=${BITRATE:-?} RESOLUTION=${RESOLUTION:-?} MAXRATE=${MAXRATE:-?} BUFSIZE=${BUFSIZE:-?} GOP=${GOP:-?}" >&2
fi

trap 'exit 0' TERM INT
while true; do
  sleep 1
done
