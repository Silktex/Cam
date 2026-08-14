# Docker Setup — Camera Control System

## Quick Start

```bash
docker compose up --build
```

- **Web UI:** http://localhost:3000
- **API / Docs:** http://localhost:8000/docs

## Architecture

```
┌─────────────────────────────────┐
│  Single Docker Container        │
│                                 │
│  ┌───────────┐  ┌────────────┐  │
│  │  FastAPI   │  │  Next.js   │  │
│  │  :8000     │  │  :3000     │  │
│  └─────┬─────┘  └────────────┘  │
│        │                        │
│  ┌─────▼─────┐                  │
│  │  gphoto2   │◄── USB Camera   │
│  └───────────┘                  │
│        │                        │
│  ┌─────▼─────────────┐         │
│  │  /app/api/media    │ volume  │
│  │  /app/api/data     │ volume  │
│  └───────────────────┘         │
└─────────────────────────────────┘
```

Both services run in one container. If either process crashes, the container exits and `restart: unless-stopped` brings it back.

## USB Camera Setup by Platform

### Linux (native Docker)

Works out of the box. The `docker-compose.yml` already includes:

```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
privileged: true
```

If your camera is not detected, kill any host PTP daemons first:

```bash
# Check for PTP daemons
sudo killall gvfs-gphoto2-volume-monitor 2>/dev/null
sudo killall gvfsd-gphoto2 2>/dev/null

# Verify camera is visible
lsusb | grep -i sony
docker exec <container> gphoto2 --auto-detect
```

### Windows (Docker Desktop + WSL2)

Docker Desktop on Windows runs Linux containers inside WSL2. USB devices must be forwarded from Windows into WSL2 using **usbipd-win**.

**One-time setup:**

1. Install usbipd on Windows (PowerShell as Administrator):
   ```powershell
   winget install usbipd
   ```

2. Install USB/IP client inside WSL2:
   ```bash
   sudo apt install linux-tools-generic hwdata
   sudo update-alternatives --install /usr/local/bin/usbip usbip /usr/lib/linux-tools/*/usbip 20
   ```

**Each time you connect the camera:**

1. List USB devices (PowerShell as Administrator):
   ```powershell
   usbipd list
   ```
   Find your Sony camera (e.g., `BUSID 2-3, Sony Corporation USB Device`).

2. Bind and attach to WSL2:
   ```powershell
   usbipd bind --busid 2-3
   usbipd attach --wsl --busid 2-3
   ```

3. Verify in WSL2:
   ```bash
   lsusb | grep -i sony
   ```

4. Now `docker compose up` will see the camera via `/dev/bus/usb`.

**To detach:**
```powershell
usbipd detach --busid 2-3
```

### macOS (Docker Desktop)

Docker Desktop for Mac runs containers inside a Linux VM. **USB passthrough is not supported** — the hypervisor does not forward USB devices.

**Options:**
- Run the system natively on macOS (no Docker needed)
- Use a Linux VM (e.g., UTM or Parallels) with USB forwarding, then Docker inside the VM
- Use Docker for the web UI only and connect to a native API instance

## Environment Variables

All variables have sensible defaults. Override as needed:

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `false` | Enable debug logging and hot-reload |
| `ESP32_HOST` | `192.168.0.44` | IP address of the ESP32 light controller |
| `USE_GPU` | `false` | Enable GPU for ML processing (requires NVIDIA setup) |
| `CORS_ORIGINS` | `localhost:3000,8000` | Allowed CORS origins (comma-separated) |
| `CAMERA_TIMEOUT` | `10` | Camera operation timeout in seconds |
| `PREVIEW_FPS` | `15` | Live view frames per second |
| `LIGHT_NAMES` | `Top Light,Side 1...` | Comma-separated light channel names |
| `LIGHT_PINS` | `26,25,5,...` | Comma-separated ESP32 GPIO pin numbers |
| `SAM_MODEL` | `mobile_sam.pt` | Segment Anything model file |
| `DOWNSAMPLE_SCALE` | `1.0` | Image downsample factor (1.0 = full res) |

Build-time variables (set during `docker compose build`):

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API URL baked into the web frontend |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket URL baked into the web frontend |

## Persistent Data

Two named volumes keep data across container rebuilds:

| Volume | Mount Point | Contents |
|---|---|---|
| `media-data` | `/app/api/media` | Captured images, crops, PBR maps |
| `api-data` | `/app/api/data` | SQLite database, color profiles |

To back up:
```bash
docker run --rm -v media-data:/data -v $(pwd):/backup alpine tar czf /backup/media-backup.tar.gz -C /data .
```

To reset all data:
```bash
docker compose down -v
```

## ESP32 Networking

The ESP32 light controller communicates over your local network. In the default bridge networking mode, the container can reach LAN devices at their IP addresses.

If the ESP32 is not reachable from the container, switch to host networking on Linux:

```yaml
# In docker-compose.yml, replace ports: with:
network_mode: host
```

Then access the services directly at `localhost:3000` and `localhost:8000`.

## GPU Support (NVIDIA)

For GPU-accelerated ML processing (SAM, PBR generation), add this to `docker-compose.yml`:

```yaml
services:
  camera-system:
    environment:
      - USE_GPU=true
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Requires:
- NVIDIA GPU with drivers installed
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- Remove `--extra-index-url` CPU-only line from Dockerfile and rebuild

## Troubleshooting

### Camera not detected in container

```bash
# Check if the camera is visible to the host
lsusb | grep -i sony

# Check inside the container
docker exec <container> gphoto2 --auto-detect

# Kill competing PTP daemons on the host
sudo killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2 2>/dev/null
```

### Permission denied on /dev/bus/usb

Ensure `privileged: true` is set in `docker-compose.yml`, or add a udev rule on the host:

```bash
# /etc/udev/rules.d/99-camera.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="054c", MODE="0666"
```

Then reload: `sudo udevadm control --reload-rules && sudo udevadm trigger`

### gphoto2 error: "Could not claim the USB device"

Another process is using the camera. Inside the container:
```bash
# Check for PTP processes
ps aux | grep -i ptp
```

On the host (Linux):
```bash
sudo killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2 2>/dev/null
```

### Build fails on PyTorch install

The Dockerfile uses CPU-only PyTorch to save space. If the index URL is unreachable:
```bash
# Build with full PyTorch (larger image, ~2GB more)
# Edit Dockerfile: remove --extra-index-url line from pip install
docker compose build --no-cache
```

### Container exits immediately

Check logs:
```bash
docker compose logs -f
```

Both the API and web server must start successfully. Common issues:
- Port 3000 or 8000 already in use on the host
- Missing environment variables
- Corrupt node_modules (rebuild with `--no-cache`)
