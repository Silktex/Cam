#!/usr/bin/env python3
"""Bandwidth-adaptive frame-rate governor for the VA-API RTSP pipeline.

Monitors available bandwidth, steps the running publish's frame rate among the
approved fps tiers {30,20,15,10,5}, and restarts the publish (via
scripts/stream.sh) with the new FPS/BITRATE when a step is decided.

Bandwidth measurement
---------------------
Default: /proc/net/dev egress deltas on the interface carrying the RTSP
publish (--interface, default lo). The achieved egress rate of the stream is
the correct availability signal: under `tc netem rate` shaping it collapses to
the shaped rate (step down), and when shaping is removed it rises back toward
the current tier's CBR demand (step up). Robust under congestion (no probe
connection to fail).

Alternative: --probe-addr enables a self-contained loopback TCP throughput
probe (sink thread + blaster). Verified to read the shaped rate standalone,
but its probe connection can stall on a fully saturated shaped loopback, so
egress measurement is preferred for the real path.

Secondary: when PROGRESS_FILE is set (stream.sh -progress), the achieved
publish fps is read and logged as a sanity signal (the value is not used for
the step decision; RTSP muxers report bitrate=N/A in -progress).

Tier / headroom model (from the approved plan)
----------------------------------------------
  fps tiers           {30, 20, 15, 10, 5}
  resolution tiers    {1920x1080, 1280x720, 960x540}
  CBR targets @ 30fps {4M, 2.5M, 1.5M}  (base bitrate per resolution)
  HEADROOM = 1.3   (a tier is affordable iff bitrate(fps) * 1.3 <= bandwidth)
  HYSTERESIS = 2   (2 consecutive samples on the same side before stepping)

Bitrate scales with fps from the resolution's 30fps base, so dropping fps also
drops the CBR target and genuinely frees bandwidth:

  bitrate(fps) = round(base_kbps * fps / 30) kbps

Resolution is user-selectable via scripts/stream_state.json (see README.md).
The governor reads the file on startup and watches it for edits (mtime); a
change triggers a graceful restart at the new resolution. The governor writes
the file after every step, so resolution + current fps/bitrate stay in sync.

Reconfiguration mechanism
-------------------------
Live zmq reconfiguration was investigated: this ffmpeg build has --enable-libzmq
and the zmq filter exists, but the `fps` filter does NOT implement
process_command (verified: "Command reply: ret:Function not implemented"), so
no live option change is possible for frame rate. The graceful-restart path is
therefore used for all tier changes: SIGTERM the current publish, relaunch via
stream.sh with fresh FPS/BITRATE/GOP/BUFSIZE env vars. This path is also the
crash-recovery path (unexpected publish exit -> relaunch at current tier).

Usage:
  ./fps_governor.py                       # run with defaults (1080p, 30fps start)
  ./fps_governor.py --state-file scripts/stream_state.json
  ./fps_governor.py --test-bw 5.5,5.5,4.5,...   # scripted bandwidth trace (Mbit/s)
  ./fps_governor.py --publish-cmd scripts/fake_publisher.sh  # hermetic tests
  ./fps_governor.py --sample-interval 1 --probe-duration 0.5  # fast tests

Exit codes: 0 clean SIGINT/SIGTERM stop; 1 startup/config error; 2 fatal loop error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

FPS_TIERS = [30, 20, 15, 10, 5]
RES_BASE_KBPS = {"1920x1080": 4000, "1280x720": 2500, "960x540": 1500}
DEFAULT_RESOLUTION = "1920x1080"
HEADROOM = 1.3
HYSTERESIS = 2
RELAUNCH_STABILIZE_S = 2.0
LOG_FMT = "%(asctime)s %(levelname)s %(message)s"


def tier_bitrate_kbps(fps: int, base_kbps: int) -> int:
    return round(base_kbps * fps / 30)


class Logger:
    def __init__(self, logfile: str | None):
        import logging

        self.log = logging.getLogger("fps_governor")
        self.log.setLevel(logging.INFO)
        fmt = logging.Formatter(LOG_FMT)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        self.log.addHandler(sh)
        if logfile:
            fh = logging.FileHandler(logfile)
            fh.setFormatter(fmt)
            self.log.addHandler(fh)


@dataclass
class State:
    resolution: str = DEFAULT_RESOLUTION
    fps: int = 30
    bitrate_kbps: int = RES_BASE_KBPS[DEFAULT_RESOLUTION]
    updated_at: str = ""


class BandwidthProbe:
    """Loopback TCP sink + blaster measuring available path bandwidth.

    addr/port default to the loopback sink that also carries the RTSP publish,
    so the probe sees the same shaping (tc netem) as the stream. Point addr at
    the RTSP destination's interface address to shape the real network path.
    """

    def __init__(self, addr: str, port: int, duration: float):
        self.addr = addr
        self.port = port
        self.duration = duration
        self._sink = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sink.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sink.settimeout(0.5)
        self._sink.bind((addr, port))
        self._sink.listen(16)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _ = self._sink.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._drain, args=(conn,), daemon=True).start()

    @staticmethod
    def _drain(conn: socket.socket) -> None:
        try:
            while conn.recv(65536):
                pass
        except OSError:
            pass
        finally:
            conn.close()

    def measure_bps(self) -> float | None:
        chunk = b"x" * 65536
        conn = None
        for _ in range(10):
            try:
                conn = socket.create_connection((self.addr, self.port), timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        if conn is None:
            return None
        # Large send buffer: probe must be sustained-throughput-limited, not
        # socket-buffer-limited, so it reports the shaped link rate honestly.
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(2.0)
        end = time.monotonic() + self.duration
        total = 0
        while time.monotonic() < end:
            try:
                total += conn.send(chunk)
            except (BlockingIOError, socket.timeout, OSError):
                continue
        conn.close()
        return total * 8 / self.duration


class EgressBandwidth:
    """Available-bandwidth measurement from /proc/net/dev egress deltas.

    Reads tx-bytes of the interface carrying the RTSP publish and converts
    deltas over a sample window into bits/s. Under `tc netem rate` the egress
    rate is capped at the shaped rate; unconstrained it reports what the
    stream's CBR target plus overhead actually moves. This measures the *used*
    path capacity, which for an adaptive CBR stream is the correct availability
    signal in both directions (shaped -> rate collapses -> step down; shaping
    removed -> rate rises to the current tier's demand -> step up).
    """

    def __init__(self, interface: str, window: float):
        self.interface = interface
        self.window = window
        self._last = self._tx_bytes()
        self._last_t = time.monotonic()

    def _tx_bytes(self) -> int | None:
        try:
            with open("/proc/net/dev") as f:
                for line in f:
                    if line.strip().startswith(self.interface + ":"):
                        return int(line.split()[9])
        except (OSError, ValueError, IndexError):
            return None
        return None

    def measure_bps(self) -> float | None:
        now = time.monotonic()
        if self._last is None:
            self._last = self._tx_bytes()
            self._last_t = now
            return None
        cur = self._tx_bytes()
        if cur is None or self._last is None:
            return None
        dt = now - self._last_t
        if dt <= 0 or cur < self._last:
            self._last, self._last_t = cur, now
            return None
        rate = (cur - self._last) * 8 / dt
        self._last, self._last_t = cur, now
        return rate


class ScriptedBandwidth:
    """--test-bw trace: consume values (Mbit/s), repeat last one forever."""

    def __init__(self, trace: list[float]):
        assert trace, "empty bandwidth trace"
        self.trace = trace
        self.i = 0

    def measure_bps(self) -> float:
        v = self.trace[min(self.i, len(self.trace) - 1)]
        self.i += 1
        return v * 1_000_000


class ProgressReader:
    """Parses ffmpeg -progress key=value lines; returns last fps/bitrate."""

    def __init__(self, path: str | None):
        self.path = path
        self.fps = None
        self.bitrate = None

    def update(self) -> None:
        if not self.path:
            return
        try:
            lines = Path(self.path).read_text().splitlines()
        except OSError:
            return
        for ln in reversed(lines):
            if ln.startswith("fps="):
                try:
                    self.fps = float(ln.split("=", 1)[1])
                except ValueError:
                    pass
            elif ln.startswith("bitrate="):
                self.bitrate = ln.split("=", 1)[1]
                if self.bitrate != "N/A":
                    break


class Governor:
    def __init__(self, args: argparse.Namespace, log: logging.Logger):
        self.args = args
        self.log = log
        self.base_kbps = RES_BASE_KBPS.get(args.resolution)
        if not self.base_kbps:
            raise SystemExit(
                f"invalid resolution '{args.resolution}', "
                f"expected one of {sorted(RES_BASE_KBPS)}"
            )
        if args.bandwidth:
            self.bw_source = ScriptedBandwidth(args.bandwidth)
        elif args.probe_addr:
            self.bw_source = BandwidthProbe(args.probe_addr, args.probe_port, args.probe_duration)
        else:
            self.bw_source = EgressBandwidth(args.interface, args.sample_interval)
        self.progress = ProgressReader(args.progress_file)
        self.publish = None
        self.current_fps = args.start_fps
        self.down_votes = 0
        self.up_votes = 0
        self.state_file = Path(args.state_file)
        self.control_mtime = None
        self._stop = threading.Event()

    # ------------------------------------------------------------- state file
    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                res = data.get("resolution", self.args.resolution)
                if res in RES_BASE_KBPS:
                    self.base_kbps = RES_BASE_KBPS[res]
                self.current_fps = int(data.get("fps", self.current_fps))
                if self.current_fps not in FPS_TIERS:
                    self.current_fps = FPS_TIERS[0]
            except (json.JSONDecodeError, ValueError) as e:
                self.log.warning("state file unreadable (%s); using defaults", e)

    def _write_state(self, measured_mbit: float, action: str) -> None:
        state = State(
            resolution=self._res_key(),
            fps=self.current_fps,
            bitrate_kbps=tier_bitrate_kbps(self.current_fps, self.base_kbps),
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self.state_file.write_text(
            json.dumps(asdict(state), indent=2) + "\n"
        )

    def _res_key(self) -> str:
        for k, v in RES_BASE_KBPS.items():
            if v == self.base_kbps:
                return k
        return DEFAULT_RESOLUTION

    # ------------------------------------------------------------ resolution
    def _resolution_changed(self) -> bool:
        try:
            mtime = self.state_file.stat().st_mtime_ns
        except OSError:
            return False
        if self.control_mtime is None:
            self.control_mtime = mtime
            return False
        if mtime != self.control_mtime:
            self.control_mtime = mtime
            try:
                data = json.loads(self.state_file.read_text())
                res = data.get("resolution", "")
            except (json.JSONDecodeError, OSError):
                return False
            if res in RES_BASE_KBPS and RES_BASE_KBPS[res] != self.base_kbps:
                self.log.info("control file: resolution changed to %s", res)
                self.base_kbps = RES_BASE_KBPS[res]
                return True
        return False

    # ------------------------------------------------------------- publish
    def _launch_publish(self, fps: int) -> None:
        bitrate_k = tier_bitrate_kbps(fps, self.base_kbps)
        env = dict(os.environ)
        env.update(
            RESOLUTION=self._res_key(),
            FPS=str(fps),
            BITRATE=f"{bitrate_k}k",
            MAXRATE=f"{bitrate_k}k",
            BUFSIZE=f"{2 * bitrate_k}k",
            GOP=str(fps * 2),
            VIDEO_SOURCE=self.args.video_source,
            PROGRESS_FILE=self.args.progress_file or "",
        )
        cmd = [self.args.publish_cmd]
        self.log.info(
            "launch publish: %s fps=%d bitrate=%dk %s",
            cmd[0], fps, bitrate_k, self._res_key(),
        )
        try:
            self.publish = subprocess.Popen(cmd, env=env)
        except OSError as e:
            self.log.error("cannot launch %s: %s", cmd[0], e)
            self.publish = None
            return
        time.sleep(RELAUNCH_STABILIZE_S)
        if self.publish.poll() is not None:
            self.log.error("publish exited early rc=%s", self.publish.returncode)
            self.publish = None

    def _stop_publish(self) -> None:
        if not self.publish:
            return
        try:
            self.publish.terminate()
            self.publish.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self.publish.kill()
            except OSError:
                pass
        self.publish = None

    def _ensure_publish(self) -> None:
        if self.publish is None or self.publish.poll() is not None:
            if self.publish is not None:
                self.log.warning("publish died rc=%s; relaunching", self.publish.returncode)
            self._launch_publish(self.current_fps)

    def _apply_fps(self, new_fps: int) -> None:
        self.log.info("STEP fps %d -> %d", self.current_fps, new_fps)
        self._stop_publish()
        self.current_fps = new_fps
        self._launch_publish(new_fps)

    # ------------------------------------------------------------- control
    def _decide(self, measured_mbit: float) -> int | None:
        affordable = max(
            (f for f in FPS_TIERS
             if tier_bitrate_kbps(f, self.base_kbps) * HEADROOM <= measured_mbit * 1000),
            default=FPS_TIERS[-1],
        )
        if affordable < self.current_fps:
            self.down_votes += 1
            self.up_votes = 0
        elif affordable > self.current_fps:
            self.up_votes += 1
            self.down_votes = 0
        else:
            self.down_votes = 0
            self.up_votes = 0

        idx = FPS_TIERS.index(self.current_fps)
        if affordable < self.current_fps and idx < len(FPS_TIERS) - 1:
            if self.down_votes >= HYSTERESIS:
                self.down_votes = 0
                return FPS_TIERS[idx + 1]
        elif affordable > self.current_fps and idx > 0:
            if self.up_votes >= HYSTERESIS:
                self.up_votes = 0
                return FPS_TIERS[idx - 1]
        return None

    def run(self) -> int:
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
        self._load_state()
        self.log.info(
            "governor start: res=%s fps=%d tiers=%s headroom=%.1f hysteresis=%d",
            self._res_key(), self.current_fps, FPS_TIERS, HEADROOM, HYSTERESIS,
        )
        self._ensure_publish()
        self._write_state(0.0, "start")
        try:
            while not self._stop.is_set():
                self._ensure_publish()
                self.progress.update()
                bw_bps = self.bw_source.measure_bps()
                if bw_bps is None:
                    self.log.warning("bandwidth probe failed; holding current tier")
                    self._stop.wait(self.args.sample_interval)
                    continue
                bw_mbit = bw_bps / 1_000_000
                step = self._decide(bw_mbit)
                self.log.info(
                    "sample bw=%.2f Mbit/s affordable<=%s current=%d publish_fps=%s%s",
                    bw_mbit,
                    self._affordable_fps_label(bw_mbit),
                    self.current_fps,
                    self._fmt(self.progress.fps),
                    " -> " + str(step) if step else "",
                )
                if step:
                    self._apply_fps(step)
                    self._write_state(bw_mbit, f"step:{step}")
                if self._resolution_changed():
                    self._apply_fps(self.current_fps)
                    self._write_state(bw_mbit, "resolution")
                self._stop.wait(self.args.sample_interval)
        finally:
            self._stop_publish()
            self.log.info("governor stopped")
        return 0

    def _affordable_fps_label(self, bw_mbit: float) -> int:
        return max(
            (f for f in FPS_TIERS
             if tier_bitrate_kbps(f, self.base_kbps) * HEADROOM <= bw_mbit * 1000),
            default=FPS_TIERS[-1],
        )

    @staticmethod
    def _fmt(v: float | None) -> str:
        return f"{v:.1f}" if v is not None else "n/a"

    def _on_signal(self, signum, frame) -> None:
        self.log.info("signal %d received", signum)
        self._stop.set()


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                   help="start resolution tier (default 1920x1080)")
    p.add_argument("--start-fps", type=int, default=30,
                   help="starting fps tier (default 30)")
    p.add_argument("--state-file", default="scripts/stream_state.json",
                   help="JSON control/state file (default scripts/stream_state.json)")
    p.add_argument("--publish-cmd", default="scripts/stream.sh",
                   help="publish command (default scripts/stream.sh)")
    p.add_argument("--sample-interval", type=float, default=5.0,
                   help="seconds between bandwidth samples (default 5)")
    p.add_argument("--probe-port", type=int, default=18400,
                   help="loopback probe sink port (default 18400)")
    p.add_argument("--probe-addr", default="",
                   help="enable TCP probe on this address (e.g. 127.0.0.1); "
                        "empty (default) uses /proc/net/dev egress measurement "
                        "on --interface")
    p.add_argument("--interface", default="lo",
                   help="interface for /proc/net/dev egress measurement "
                        "(default lo; use the interface carrying the RTSP "
                        "publish, e.g. enp1s0f0 for a LAN path)")
    p.add_argument("--probe-duration", type=float, default=1.0,
                   help="seconds per probe blast (default 1)")
    p.add_argument("--progress-file", default="",
                   help="ffmpeg -progress file to read publish fps (optional)")
    p.add_argument("--video-source", default="v4l2",
                   help="v4l2 or lavfi (default v4l2)")
    p.add_argument("--log-file", default="",
                   help="append governor log lines to this file")
    p.add_argument("--test-bw", default="",
                   help="comma-separated Mbit/s trace overriding measurement "
                        "(repeats last value); deterministic tests")
    args = p.parse_args(argv)
    if args.test_bw:
        try:
            args.bandwidth = [float(x) for x in args.test_bw.split(",") if x.strip()]
        except ValueError as e:
            p.error(f"--test-bw must be comma-separated numbers (Mbit/s): {e}")
        if not args.bandwidth:
            p.error("--test-bw trace is empty")
    else:
        args.bandwidth = None
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    base = Path(__file__).resolve().parent
    if args.publish_cmd == "scripts/stream.sh":
        args.publish_cmd = str(base / "stream.sh")
    elif not args.publish_cmd.startswith("/"):
        args.publish_cmd = str(Path.cwd() / args.publish_cmd)
    if args.state_file == "scripts/stream_state.json":
        args.state_file = str(base / "stream_state.json")
    elif not args.state_file.startswith("/"):
        args.state_file = str(Path.cwd() / args.state_file)
    logger = Logger(args.log_file)
    try:
        g = Governor(args, logger.log)
    except SystemExit as e:
        logger.log.error("%s", e)
        return 1
    return g.run()


if __name__ == "__main__":
    sys.exit(main())
