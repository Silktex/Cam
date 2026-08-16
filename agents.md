# Camera Control System — Agent Guide & Access Reference

This document provides a comprehensive onboarding guide, connectivity details, architecture summary, and tracking guidelines for AI agents working on this project. 

---

## 🔑 Host Connection & Access Information

The development environment and camera hardware are deployed on the remote host **`ind`** (`ESP-PC`).

### Remote Host Details
* **Host Identifier:** `ind`
* **Hostname/IP:** `10.10.2.21`
* **User:** `posh`
* **Default Port:** `22` (SSH)
* **Workspace Path:** `/home/posh/projects/camera_system`

### Configure Local SSH Config
To connect directly, ensure your local `/home/rc/.ssh/config` file is configured as follows:

```ssh
Host ind
  Hostname 10.10.2.21
  User posh
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
```

With this setup, standard commands like `ssh ind` and `scp ind:...` will connect directly.


---

## 🌐 Running Services (Host `ind`)

The system runs inside a multi-process Docker container on `ind`:

| Service | URL | Description |
|:---|:---|:---|
| **Web UI** | http://10.10.2.21:3000 | Next.js 14 frontend |
| **API Docs** | http://10.10.2.21:8000/docs | Swagger UI for FastAPI backend |
| **Meilisearch** | http://10.10.2.21:7700 | Product and fabric search engine |

---

## 🏗️ Project Architecture & Capabilities

The **Camera Control System** is designed to automate high-precision product photography, multi-light capturing, color calibration, and PBR (Physically Based Rendering) texture map generation.

```
 +-----------+     USB/PTP      +------------------+     HTTP     +------------------+
 | Sony      | <--------------> |   FastAPI         | <---------> |   Next.js        |
 | A7R III   |                  |   Backend :8000   |             |   Frontend :3000 |
 +-----------+                  +------------------+             +------------------+
                                       ^    ^                           |
                                       |    |                           |
                                HTTP   |    |  WebSocket                | WebSocket
                                       |    |                           |
                                +------+    +------+                    |
                                |                  |                    |
                          +-----------+     +-------------+      +-------------+
                          |  ESP32    |     | Meilisearch |      |  Browser    |
                          |  Lights   |     |  :7700      |      |  Client     |
                          +-----------+     +-------------+      +-------------+
```

### Core Architecture Components (Remote `ind`)
* **Camera Rig:** Sony A7R III (61MP) controlled over USB PTP using `libgphoto2`.
* **Light Rig:** 9x LED panels (1 Top + 8 Side) controlled via an ESP32 micro-controller on the local network (default: `192.168.0.44`).
* **Backend:** FastAPI (Python 3.12) server handling hardware control, EventBus websocket events, color science (using `colour-science`), boundary detection (SAM/MobileSAM), and database logging (SQLite).
* **Frontend:** Next.js 14 React UI.

---

## 📌 Issue Tracking & Task Workflow (`bd`)

This project uses **`bd` (beads)** for durable task tracking and issue management. Do NOT use markdown TODOs or ad-hoc lists.

### Quick Reference Commands
All issue status is backed by a Dolt database on host `ind`.
* `bd ready` — List unblocked work items.
* `bd show <id>` — View details of a specific issue.
* `bd update <id> --claim` — Claim a task atomically.
* `bd close <id> --reason "Done"` — Close a completed task.
* `bd dolt push` / `bd dolt pull` — Sync issue database to/from the remote git branch `refs/dolt/data`.

### Agent Conduct Rules
* Propose commits/pushes to the user before running them unless in an explicit Team-maintainer profile.
* Never modify `.beads/issues.jsonl` manually; it is a passive export. Always use the `bd` CLI tool.

---

## 🛠️ Current Status & Active Working Tree

A previous session implemented and verified crucial hardware lifecycle and usb-reset bugfixes. The modifications are currently **uncommitted** in the remote working tree on `ind`.

### Uncommitted Files on `ind`
1. **`api/app/services/camera_service.py`**
   * *Fixes:* Rewrote worker thread lifecycle. Thread-safe EventBus publishes transfer loop safely. Camera disconnection/troubleshooting no longer calls `camera.exit()` cross-thread to avoid segfaults.
   * *Troubleshoot Fix:* Removed the destructive USB reset ioctl (`gphoto2 --reset`) from troubleshoot because it wedged the Sony A7R III PTP stack (requiring physical battery pulls). It now performs a clean disconnect -> detect -> reconnect sequence (~2.3 seconds recovery).
2. **`api/tests/test_camera_concurrency.py`**
   * *Fixes:* Concurrency and event bus threading regression tests.
3. **`web/app/all/components/DashboardHeader.tsx`**
   * *Fixes:* Removed the `Ctrl+T` / `Cmd+T` keyboard shortcut that was hijacking browser tabs and firing destructive troubleshoot commands.

---

## 📋 Recommended Follow-Up Actions

If you are picking up work on host `ind`, follow this order of priority:
1. **Commit the changes:** Verify the three modified files on `ind` and commit them.
2. **Fix `kill_ptp_processes` `psmisc` issue:** The current runtime Docker image is missing `psmisc` (causing `killall` to fail with `FileNotFoundError`). Add `psmisc` to `RUN apt-get install` in `Dockerfile`.
3. **Resolve `atexit` logging noise:** `CameraService` singleton registration prints ValueError on closed file descriptors during test tear-downs. Consider module-level registration or a quiet shutdown guard.
4. **⚠️ DO NOT reintroduce USB reset:** Keep the USB reset commented out / disabled. The A7R III cannot recover from `gphoto2 --reset` without physical power cycles.
