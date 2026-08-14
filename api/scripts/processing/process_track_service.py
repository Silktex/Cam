"""
Process Track Service - JSON-based pipeline state management.

Manages process_track.json for each batch, storing all parameters needed
to reproduce the full photometric PBR pipeline from RAW images.

6-phase pipeline:
  1. crop_align     - Crop, rotate, straighten, perspective
  2. color          - Color calibration + exposure equalization
  3. pbr            - Photometric stereo → normals, albedo, roughness, height
  4. map_refine     - Flatten, delight, roughness scale, clone/inpaint
  5. seamless_tiling - Make seamless + NxN tile check + tiling export
  6. validate_export - PBR range validation + final save
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PHASES = [
    "crop_align",
    "color",
    "pbr",
    "map_refine",
    "seamless_tiling",
    "validate_export",
]

VALID_STATUSES = {"pending", "in_progress", "completed", "skipped"}

TRACK_FILENAME = "process_track.json"


def _default_phases() -> Dict[str, Any]:
    """Return the default 6-phase template with sensible defaults."""
    return {
        "crop_align": {
            "status": "pending",
            "params": {
                "crop_type": None,
                "points": None,
                "rotation": 0,
                "crop_size": 2048,
                "straighten": {
                    "enabled": False,
                    "mode": "auto",
                    "strength": 1.0,
                    "direction": "both",
                },
                "perspective": {
                    "enabled": False,
                    "source_points": None,
                    "dest_points": None,
                },
            },
        },
        "color": {
            "status": "pending",
            "params": {
                "profile_name": None,
                "matrix_3x3": None,
                "checker_wb": None,
                "checker_raw_path": None,
                "exposure_method": "exposure_match",
                "exposure_offset": 0.0,
            },
        },
        "pbr": {
            "status": "pending",
            "params": {
                "mode": "grayscale",
                "selected_images": None,
            },
        },
        "map_refine": {
            "status": "pending",
            "params": {
                "flatten": {"enabled": True, "strength": 1.0, "smoothing": 0},
                "delight": {
                    "enabled": True,
                    "method": "gaussian",
                    "blur_radius": 200,
                    "strength": 1.0,
                },
                "roughness": {"scale_factor": 1.0},
                "clone": {"operations": []},
            },
        },
        "seamless_tiling": {
            "status": "pending",
            "params": {
                "seamless": {
                    "method": "overlay",
                    "blend_width": 64,
                    "spots_removal": False,
                    "color_equalizer": 0,
                },
                "tile_check": 4,
                "tiling": {
                    "tile_x": 2,
                    "tile_y": 2,
                    "scale": 1.0,
                    "rotation": 0,
                    "overlap": 0,
                    "half_drop": False,
                    "output_resolution": [2048, 2048],
                },
            },
        },
        "validate_export": {
            "status": "pending",
            "params": {
                "albedo_dark_threshold": 30,
                "metal_range": [180, 255],
            },
        },
    }


def _track_path(batch_path: Path) -> Path:
    """Return the path to process_track.json inside output/."""
    output_dir = batch_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / TRACK_FILENAME


def create_default_track(batch_name: str) -> dict:
    """Create a new empty track with default 6-phase template."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": 1,
        "batch_name": batch_name,
        "created_at": now,
        "updated_at": now,
        "phases": _default_phases(),
    }


def get_track(batch_path: Path) -> Optional[dict]:
    """Load process_track.json for a batch. Returns None if not found."""
    path = _track_path(batch_path)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load track at {path}: {e}")
        return None


def save_track(batch_path: Path, track: dict) -> None:
    """Write track to process_track.json with updated timestamp."""
    track["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _track_path(batch_path)
    with open(path, "w") as f:
        json.dump(track, f, indent=2)
    logger.info(f"Saved track: {path}")


def update_phase(
    batch_path: Path,
    phase: str,
    status: Optional[str] = None,
    params: Optional[dict] = None,
) -> dict:
    """
    Update a single phase's status and/or params.
    Returns the updated track.
    """
    if phase not in PHASES:
        raise ValueError(f"Unknown phase '{phase}'. Valid: {PHASES}")
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Valid: {VALID_STATUSES}")

    track = get_track(batch_path)
    if track is None:
        raise FileNotFoundError(f"No process_track.json in {batch_path}")

    phase_data = track["phases"][phase]

    if status is not None:
        phase_data["status"] = status

    if params is not None:
        # Merge params (shallow update of top-level keys within params)
        for key, value in params.items():
            phase_data["params"][key] = value

    save_track(batch_path, track)
    return track


def scan_existing_folders(batch_path: Path) -> dict:
    """
    Infer phase statuses from existing output folders on disk.
    Used when initializing a track for a batch that already has some processing done.
    """
    statuses = {}

    # Phase 1: crop_align
    cropped = batch_path / "cropped"
    if cropped.exists() and any(cropped.iterdir()):
        statuses["crop_align"] = "completed"
    else:
        statuses["crop_align"] = "pending"

    # Phase 2: color
    calibrated = batch_path / "color_calibrated"
    if calibrated.exists() and any(calibrated.iterdir()):
        statuses["color"] = "completed"
    else:
        statuses["color"] = "pending"

    # Phase 3: pbr
    pbr_gray = batch_path / "pbr_grayscale"
    pbr_color = batch_path / "pbr_colored"
    if (pbr_gray.exists() and any(pbr_gray.iterdir())) or \
       (pbr_color.exists() and any(pbr_color.iterdir())):
        statuses["pbr"] = "completed"
    else:
        statuses["pbr"] = "pending"

    # Phase 4: map_refine
    flattened = batch_path / "flattened"
    delighted = batch_path / "delighted"
    if (flattened.exists() and any(flattened.iterdir())) or \
       (delighted.exists() and any(delighted.iterdir())):
        statuses["map_refine"] = "completed"
    else:
        statuses["map_refine"] = "pending"

    # Phase 5: seamless_tiling
    seamless = batch_path / "seamless"
    tiled = batch_path / "tiled"
    if (seamless.exists() and any(seamless.iterdir())) or \
       (tiled.exists() and any(tiled.iterdir())):
        statuses["seamless_tiling"] = "completed"
    else:
        statuses["seamless_tiling"] = "pending"

    # Phase 6: validate_export
    validate = batch_path / "validate_preview"
    if validate.exists() and any(validate.iterdir()):
        statuses["validate_export"] = "completed"
    else:
        statuses["validate_export"] = "pending"

    return statuses


def get_phase_index(phase: str) -> int:
    """Return the 0-based index of a phase."""
    return PHASES.index(phase)


def get_current_phase(track: dict) -> int:
    """Return the 1-based phase number of the first non-completed phase."""
    for i, phase_name in enumerate(PHASES):
        status = track["phases"][phase_name]["status"]
        if status not in ("completed", "skipped"):
            return i + 1
    return len(PHASES)  # all completed


def count_completed_phases(track: dict) -> int:
    """Count how many phases are completed or skipped."""
    count = 0
    for phase_name in PHASES:
        status = track["phases"][phase_name]["status"]
        if status in ("completed", "skipped"):
            count += 1
    return count
