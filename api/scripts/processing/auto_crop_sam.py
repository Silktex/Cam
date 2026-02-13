"""
SAM (Segment Anything Model) Auto-Cropper
Uses MobileSAM for efficient fabric sample detection and cropping.
"""
import logging
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# Check for SAM availability
try:
    import torch
    from segment_anything import sam_model_registry, SamPredictor
    SAM_AVAILABLE = True
except ImportError:
    SAM_AVAILABLE = False
    logger.warning("SAM not installed. Run: pip install segment-anything")


class SAMAutoCropper:
    """Auto-cropper using Segment Anything Model (SAM)."""

    def __init__(self, use_gpu: bool = False):
        if not SAM_AVAILABLE:
            raise ImportError("segment-anything library not installed")

        self.use_gpu = use_gpu
        self.predictor = None
        self._load_model()

    def _load_model(self):
        """Load SAM model."""
        model_path = settings.MODELS_DIR / settings.SAM_MODEL

        if not model_path.exists():
            logger.error(f"SAM model not found: {model_path}")
            raise FileNotFoundError(
                f"SAM model not found at {model_path}. "
                f"Download mobile_sam.pt from https://github.com/ChaoningZhang/MobileSAM"
            )

        # Determine model type from filename
        if 'mobile' in settings.SAM_MODEL.lower():
            model_type = 'vit_t'  # MobileSAM uses tiny ViT
        elif 'vit_h' in settings.SAM_MODEL.lower():
            model_type = 'vit_h'
        elif 'vit_l' in settings.SAM_MODEL.lower():
            model_type = 'vit_l'
        else:
            model_type = 'vit_b'  # default

        logger.info(f"Loading SAM model: {model_path} (type: {model_type})")

        # Set device
        if self.use_gpu and torch.cuda.is_available():
            device = 'cuda'
        elif torch.backends.mps.is_available():
            device = 'mps'  # Apple Silicon
        else:
            device = 'cpu'

        logger.info(f"Using device: {device}")

        # Load model
        sam = sam_model_registry[model_type](checkpoint=str(model_path))
        sam.to(device=device)

        self.predictor = SamPredictor(sam)
        self.device = device

    def crop_image(
        self,
        image_path: str,
        output_folder: str,
        prompt: str = "fabric sample",
        padding: float = 0.05,
    ) -> Dict:
        """
        Crop image using SAM segmentation.

        Args:
            image_path: Path to source image
            output_folder: Output folder path
            prompt: Text prompt (used for center point estimation)
            padding: Padding ratio around detected object

        Returns:
            Dict with success, output_path, bbox, error
        """
        try:
            image_path = Path(image_path)
            output_folder = Path(output_folder)
            output_folder.mkdir(exist_ok=True)

            # Load image
            image = cv2.imread(str(image_path))
            if image is None:
                return {"success": False, "error": "Failed to load image"}

            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            h, w = image.shape[:2]

            # Set image for predictor
            self.predictor.set_image(image_rgb)

            # Use center point as prompt (fabric usually centered)
            center_point = np.array([[w // 2, h // 2]])
            center_label = np.array([1])  # foreground

            # Predict mask
            masks, scores, _ = self.predictor.predict(
                point_coords=center_point,
                point_labels=center_label,
                multimask_output=True,
            )

            # Select best mask (highest score)
            best_mask_idx = np.argmax(scores)
            mask = masks[best_mask_idx]

            # Find bounding box from mask
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)

            if not np.any(rows) or not np.any(cols):
                return {"success": False, "error": "No object detected"}

            y_min, y_max = np.where(rows)[0][[0, -1]]
            x_min, x_max = np.where(cols)[0][[0, -1]]

            # Add padding
            pad_x = int((x_max - x_min) * padding)
            pad_y = int((y_max - y_min) * padding)

            x1 = max(0, x_min - pad_x)
            y1 = max(0, y_min - pad_y)
            x2 = min(w, x_max + pad_x)
            y2 = min(h, y_max + pad_y)

            # Crop image
            cropped = image[y1:y2, x1:x2]

            # Save as TIFF
            output_path = output_folder / f"{image_path.stem}.tiff"
            cv2.imwrite(str(output_path), cropped)

            logger.info(f"SAM cropped: {image_path.name} -> {output_path.name}")

            return {
                "success": True,
                "output_path": str(output_path),
                "bbox": [x1, y1, x2, y2],
                "mask_score": float(scores[best_mask_idx]),
            }

        except Exception as e:
            logger.error(f"SAM crop failed for {image_path}: {e}")
            return {"success": False, "error": str(e)}

    def crop_with_box_prompt(
        self,
        image_path: str,
        output_folder: str,
        box: list,  # [x1, y1, x2, y2]
    ) -> Dict:
        """
        Crop image using SAM with box prompt.
        Useful when approximate bounding box is known.
        """
        try:
            image_path = Path(image_path)
            output_folder = Path(output_folder)
            output_folder.mkdir(exist_ok=True)

            image = cv2.imread(str(image_path))
            if image is None:
                return {"success": False, "error": "Failed to load image"}

            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            self.predictor.set_image(image_rgb)

            # Use box as prompt
            box_array = np.array(box)

            masks, scores, _ = self.predictor.predict(
                box=box_array,
                multimask_output=False,
            )

            mask = masks[0]

            # Find tight bounding box from mask
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)

            if not np.any(rows) or not np.any(cols):
                # Fall back to original box
                x1, y1, x2, y2 = box
            else:
                y1, y2 = np.where(rows)[0][[0, -1]]
                x1, x2 = np.where(cols)[0][[0, -1]]

            cropped = image[y1:y2, x1:x2]

            output_path = output_folder / f"{image_path.stem}.tiff"
            cv2.imwrite(str(output_path), cropped)

            return {
                "success": True,
                "output_path": str(output_path),
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
            }

        except Exception as e:
            logger.error(f"SAM box crop failed: {e}")
            return {"success": False, "error": str(e)}
