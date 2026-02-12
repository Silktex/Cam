"""
Database Service - SQLite with batch/image tracking and processing status
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Database and config paths
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "batches.db"
CONFIG_PATH = DB_DIR / "config.json"

# Default media path
DEFAULT_MEDIA_PATH = Path(__file__).parent.parent.parent / "media" / "captures"


def get_config() -> Dict[str, Any]:
    """Load config from JSON file"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {
        "media_path": str(DEFAULT_MEDIA_PATH),
        "auto_sync_on_startup": True,
    }


def save_config(config: Dict[str, Any]):
    """Save config to JSON file"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


def get_media_path() -> Path:
    """Get current media path from config"""
    config = get_config()
    return Path(config.get("media_path", str(DEFAULT_MEDIA_PATH)))


def set_media_path(path: str) -> bool:
    """Update media path in config"""
    config = get_config()
    config["media_path"] = path
    config["last_path_change"] = datetime.now().isoformat()
    save_config(config)
    return True


@contextmanager
def get_db():
    """Context manager for database connections"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_db():
    """Initialize database schema"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Batches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                folder_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                image_count INTEGER DEFAULT 0,

                -- Phase 1: Cropping
                crop_status TEXT DEFAULT 'pending',
                crop_type TEXT,
                crop_completed_at TIMESTAMP,

                -- Phase 2: Color Calibration
                calibration_status TEXT DEFAULT 'pending',
                calibration_completed_at TIMESTAMP,

                -- Phase 3: PBR Generation
                pbr_status TEXT DEFAULT 'pending',
                pbr_mode TEXT,
                pbr_completed_at TIMESTAMP,

                -- Metadata
                synced_at TIMESTAMP,
                notes TEXT
            )
        """)

        # Images table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                position TEXT,

                -- EXIF metadata
                camera TEXT,
                lens TEXT,
                resolution_w INTEGER,
                resolution_h INTEGER,
                iso INTEGER,
                aperture TEXT,
                shutter TEXT,
                focal_length TEXT,
                captured_at TIMESTAMP,
                file_size INTEGER,

                -- Processing status
                is_cropped INTEGER DEFAULT 0,
                is_calibrated INTEGER DEFAULT 0,

                -- PBR processing (selective)
                pbr_selected INTEGER DEFAULT 1,
                pbr_grayscale_done INTEGER DEFAULT 0,
                pbr_colored_done INTEGER DEFAULT 0,

                FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE,
                UNIQUE(batch_id, filename)
            )
        """)

        # Settings table for key-value storage
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_batch ON images(batch_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(crop_status, calibration_status, pbr_status)")

        logger.info(f"Database initialized at {DB_PATH}")


def extract_exif(raw_path: Path) -> Dict[str, Any]:
    """Extract EXIF metadata from RAW file"""
    metadata = {}
    try:
        import exifread
        with open(raw_path, 'rb') as f:
            tags = exifread.process_file(f, details=False)

        metadata = {
            "camera": f"{tags.get('Image Make', '')} {tags.get('Image Model', '')}".strip(),
            "lens": str(tags.get('EXIF LensModel', '')),
            "resolution_w": int(str(tags.get('EXIF ExifImageWidth', 0))),
            "resolution_h": int(str(tags.get('EXIF ExifImageLength', 0))),
            "iso": int(str(tags.get('EXIF ISOSpeedRatings', 0))) if tags.get('EXIF ISOSpeedRatings') else None,
            "aperture": f"f/{tags.get('EXIF FNumber', '')}" if tags.get('EXIF FNumber') else None,
            "shutter": f"{tags.get('EXIF ExposureTime', '')}s" if tags.get('EXIF ExposureTime') else None,
            "focal_length": f"{tags.get('EXIF FocalLength', '')}mm" if tags.get('EXIF FocalLength') else None,
            "captured_at": str(tags.get('EXIF DateTimeOriginal', '')),
        }
    except ImportError:
        logger.warning("exifread not installed - skipping EXIF extraction")
    except Exception as e:
        logger.warning(f"EXIF extraction failed for {raw_path}: {e}")

    return metadata


def extract_position_from_filename(filename: str) -> str:
    """Extract position (top, side_1, etc.) from filename"""
    name = filename.lower()
    if '_top' in name:
        return 'top'
    for i in range(1, 9):
        if f'_side_{i}' in name or f'side{i}' in name:
            return f'side_{i}'
    return 'unknown'


def sync_batch(batch_name: str) -> Dict[str, Any]:
    """Sync a single batch from filesystem to database"""
    media_path = get_media_path()
    batch_path = media_path / batch_name

    if not batch_path.exists():
        return {"success": False, "error": f"Batch folder not found: {batch_path}"}

    with get_db() as conn:
        cursor = conn.cursor()

        # Check what subfolders exist to determine status
        has_raw = (batch_path / "raw").exists()
        has_cropped = (batch_path / "cropped").exists()
        has_calibrated = (batch_path / "color_calibrated").exists()
        has_pbr_gray = (batch_path / "pbr_grayscale").exists()
        has_pbr_color = (batch_path / "pbr_colored").exists()

        # Determine statuses based on folder presence
        crop_status = 'completed' if has_cropped else 'pending'
        calibration_status = 'completed' if has_calibrated else 'pending'

        if has_pbr_gray and has_pbr_color:
            pbr_status = 'completed'
            pbr_mode = 'both'
        elif has_pbr_gray:
            pbr_status = 'completed'
            pbr_mode = 'grayscale'
        elif has_pbr_color:
            pbr_status = 'completed'
            pbr_mode = 'colored'
        else:
            pbr_status = 'pending'
            pbr_mode = None

        # Insert or update batch
        cursor.execute("""
            INSERT INTO batches (name, folder_path, crop_status, calibration_status, pbr_status, pbr_mode, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                folder_path = excluded.folder_path,
                crop_status = excluded.crop_status,
                calibration_status = excluded.calibration_status,
                pbr_status = excluded.pbr_status,
                pbr_mode = excluded.pbr_mode,
                synced_at = excluded.synced_at
        """, (batch_name, str(batch_path), crop_status, calibration_status, pbr_status, pbr_mode, datetime.now()))

        batch_id = cursor.execute("SELECT id FROM batches WHERE name = ?", (batch_name,)).fetchone()[0]

        # Scan RAW folder for images
        raw_folder = batch_path / "raw"
        image_count = 0

        if raw_folder.exists():
            for raw_file in raw_folder.iterdir():
                if raw_file.suffix.upper() in ['.ARW', '.CR2', '.NEF', '.DNG', '.RAF']:
                    image_count += 1
                    position = extract_position_from_filename(raw_file.name)
                    exif = extract_exif(raw_file)

                    # Check per-image processing status
                    is_cropped = (batch_path / "cropped" / f"{raw_file.stem}.jpg").exists() or \
                                 (batch_path / "cropped" / f"{raw_file.stem}.tiff").exists()
                    is_calibrated = (batch_path / "color_calibrated" / f"{raw_file.stem}.jpg").exists() or \
                                    (batch_path / "color_calibrated" / f"{raw_file.stem}.tiff").exists()
                    pbr_gray_done = (batch_path / "pbr_grayscale" / raw_file.stem).exists()
                    pbr_color_done = (batch_path / "pbr_colored" / raw_file.stem).exists()

                    cursor.execute("""
                        INSERT INTO images (
                            batch_id, filename, position,
                            camera, lens, resolution_w, resolution_h,
                            iso, aperture, shutter, focal_length, captured_at,
                            file_size, is_cropped, is_calibrated,
                            pbr_grayscale_done, pbr_colored_done
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(batch_id, filename) DO UPDATE SET
                            position = excluded.position,
                            camera = excluded.camera,
                            lens = excluded.lens,
                            resolution_w = excluded.resolution_w,
                            resolution_h = excluded.resolution_h,
                            iso = excluded.iso,
                            aperture = excluded.aperture,
                            shutter = excluded.shutter,
                            focal_length = excluded.focal_length,
                            captured_at = excluded.captured_at,
                            file_size = excluded.file_size,
                            is_cropped = excluded.is_cropped,
                            is_calibrated = excluded.is_calibrated,
                            pbr_grayscale_done = excluded.pbr_grayscale_done,
                            pbr_colored_done = excluded.pbr_colored_done
                    """, (
                        batch_id, raw_file.name, position,
                        exif.get('camera'), exif.get('lens'),
                        exif.get('resolution_w'), exif.get('resolution_h'),
                        exif.get('iso'), exif.get('aperture'),
                        exif.get('shutter'), exif.get('focal_length'),
                        exif.get('captured_at'),
                        raw_file.stat().st_size,
                        int(is_cropped), int(is_calibrated),
                        int(pbr_gray_done), int(pbr_color_done)
                    ))

        # Update image count
        cursor.execute("UPDATE batches SET image_count = ? WHERE id = ?", (image_count, batch_id))

        return {
            "success": True,
            "batch": batch_name,
            "image_count": image_count,
            "crop_status": crop_status,
            "calibration_status": calibration_status,
            "pbr_status": pbr_status,
        }


def sync_all_batches() -> Dict[str, Any]:
    """Full sync: scan media folder and sync all batches"""
    media_path = get_media_path()

    if not media_path.exists():
        return {"success": False, "error": f"Media path not found: {media_path}"}

    results = []
    batch_names = []

    for folder in sorted(media_path.iterdir()):
        if folder.is_dir() and not folder.name.startswith('.'):
            result = sync_batch(folder.name)
            results.append(result)
            batch_names.append(folder.name)

    # Remove batches that no longer exist in filesystem
    with get_db() as conn:
        cursor = conn.cursor()
        if batch_names:
            placeholders = ','.join(['?' for _ in batch_names])
            cursor.execute(f"DELETE FROM batches WHERE name NOT IN ({placeholders})", batch_names)
        else:
            cursor.execute("DELETE FROM batches")

    # Update last sync time in config
    config = get_config()
    config["last_sync"] = datetime.now().isoformat()
    save_config(config)

    return {
        "success": True,
        "synced_count": len(results),
        "batches": results,
    }


# ─── Query Functions ───

def get_all_batches() -> List[Dict[str, Any]]:
    """Get all batches with their status"""
    with get_db() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("""
            SELECT * FROM batches ORDER BY created_at DESC
        """).fetchall()
        return [dict(row) for row in rows]


def get_batch(batch_name: str) -> Optional[Dict[str, Any]]:
    """Get a single batch by name"""
    with get_db() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT * FROM batches WHERE name = ?", (batch_name,)).fetchone()
        return dict(row) if row else None


def get_batch_images(batch_name: str) -> List[Dict[str, Any]]:
    """Get all images in a batch"""
    with get_db() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("""
            SELECT i.* FROM images i
            JOIN batches b ON i.batch_id = b.id
            WHERE b.name = ?
            ORDER BY i.position, i.filename
        """, (batch_name,)).fetchall()
        return [dict(row) for row in rows]


def get_batches_by_status(phase: str, status: str) -> List[Dict[str, Any]]:
    """Get batches filtered by phase and status"""
    column_map = {
        'crop': 'crop_status',
        'calibration': 'calibration_status',
        'pbr': 'pbr_status',
    }
    column = column_map.get(phase)
    if not column:
        return []

    with get_db() as conn:
        cursor = conn.cursor()
        rows = cursor.execute(f"""
            SELECT * FROM batches WHERE {column} = ? ORDER BY created_at DESC
        """, (status,)).fetchall()
        return [dict(row) for row in rows]


def update_batch_status(batch_name: str, phase: str, status: str, **kwargs) -> bool:
    """Update batch processing status"""
    column_map = {
        'crop': ('crop_status', 'crop_completed_at', 'crop_type'),
        'calibration': ('calibration_status', 'calibration_completed_at', None),
        'pbr': ('pbr_status', 'pbr_completed_at', 'pbr_mode'),
    }

    if phase not in column_map:
        return False

    status_col, completed_col, type_col = column_map[phase]

    with get_db() as conn:
        cursor = conn.cursor()

        updates = [f"{status_col} = ?"]
        values = [status]

        if status == 'completed':
            updates.append(f"{completed_col} = ?")
            values.append(datetime.now())

        if type_col and type_col.replace('_type', '_mode').replace('crop_type', 'crop_type') in kwargs:
            key = 'crop_type' if phase == 'crop' else 'pbr_mode'
            if key in kwargs:
                updates.append(f"{type_col if phase == 'crop' else 'pbr_mode'} = ?")
                values.append(kwargs[key])

        values.append(batch_name)

        cursor.execute(f"""
            UPDATE batches SET {', '.join(updates)} WHERE name = ?
        """, values)

        return cursor.rowcount > 0


def update_image_pbr_selection(batch_name: str, filename: str, selected: bool) -> bool:
    """Update PBR selection for a specific image"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE images SET pbr_selected = ?
            WHERE filename = ? AND batch_id = (SELECT id FROM batches WHERE name = ?)
        """, (int(selected), filename, batch_name))
        return cursor.rowcount > 0


def get_processing_summary() -> Dict[str, Any]:
    """Get summary of all processing statuses"""
    with get_db() as conn:
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM batches").fetchone()[0]

        summary = {
            "total_batches": total,
            "crop": {
                "pending": cursor.execute("SELECT COUNT(*) FROM batches WHERE crop_status = 'pending'").fetchone()[0],
                "in_progress": cursor.execute("SELECT COUNT(*) FROM batches WHERE crop_status = 'in_progress'").fetchone()[0],
                "completed": cursor.execute("SELECT COUNT(*) FROM batches WHERE crop_status = 'completed'").fetchone()[0],
            },
            "calibration": {
                "pending": cursor.execute("SELECT COUNT(*) FROM batches WHERE calibration_status = 'pending'").fetchone()[0],
                "in_progress": cursor.execute("SELECT COUNT(*) FROM batches WHERE calibration_status = 'in_progress'").fetchone()[0],
                "completed": cursor.execute("SELECT COUNT(*) FROM batches WHERE calibration_status = 'completed'").fetchone()[0],
            },
            "pbr": {
                "pending": cursor.execute("SELECT COUNT(*) FROM batches WHERE pbr_status = 'pending'").fetchone()[0],
                "in_progress": cursor.execute("SELECT COUNT(*) FROM batches WHERE pbr_status = 'in_progress'").fetchone()[0],
                "completed": cursor.execute("SELECT COUNT(*) FROM batches WHERE pbr_status = 'completed'").fetchone()[0],
            },
        }

        return summary


# Initialize on import
init_db()
