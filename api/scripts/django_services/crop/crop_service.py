"""
Crop service - adapted from auto_crop_sam3.py and auto_crop_service.py.
Synchronous Django wrapper with StatusService integration.
"""
import os
import logging
from pathlib import Path

import cv2
import numpy as np

from apps.crop.models import CropResult, CropMethod
from apps.folders.models import ProcessingFolder
from apps.status.services.status_service import StatusService
from apps.status.models import ProcessingStep, StepStatus
from apps.core.utils.image_io import load_image, save_as_tiff
from apps.core.utils.file_utils import list_images, ensure_directory
from apps.core.exceptions import CropError

logger = logging.getLogger(__name__)


class CropService:
    def __init__(self, status_service: StatusService = None):
        self.status_service = status_service or StatusService()

    def _run_cropper(self, image_path, output_dir, prompts):
        """Try SAM3 first, fall back to OpenCV contour detection."""
        try:
            from .auto_crop_sam3 import SAM3AutoCropper, SAM3Config, HAS_SAM3
            if not HAS_SAM3:
                raise ImportError("SAM3 not installed")

            config = SAM3Config()
            if prompts:
                config.use_multi_prompt = False

            cropper = SAM3AutoCropper(config)
            custom_prompt = prompts[0] if prompts else None
            return cropper.process_image(image_path, output_dir, prompt=custom_prompt)

        except (ImportError, Exception) as sam_err:
            logger.info("SAM3 unavailable (%s), using OpenCV fallback", sam_err)
            from .auto_crop_opencv import OpenCVAutoCropper
            cropper = OpenCVAutoCropper()
            return cropper.process_image(image_path, output_dir)

    def auto_crop(
        self,
        folder_id: str,
        image_path: str,
        prompts: list[str] = None,
    ) -> list[CropResult]:
        """Auto-crop an image using SAM3 segmentation (falls back to OpenCV)."""
        try:
            folder = ProcessingFolder.objects.get(id=folder_id)
        except ProcessingFolder.DoesNotExist:
            raise CropError(f"Folder {folder_id} not found")
        self.status_service.update_step(
            folder_id, ProcessingStep.AUTO_CROPPED, StepStatus.IN_PROGRESS,
        )

        try:
            output_dir = ensure_directory(str(Path(folder.path) / "cropped"))
            cropper_result = self._run_cropper(image_path, output_dir, prompts)
            crop_results = []

            if cropper_result.success and cropper_result.metadata:
                for obj in cropper_result.metadata.get("objects", []):
                    crop_path = obj.get("crop_path", "")
                    bbox = obj.get("bbox", [])
                    conf = obj.get("score", 0.0)

                    # Re-save as TIFF if not already
                    if crop_path and not crop_path.lower().endswith(('.tiff', '.tif')):
                        img = load_image(crop_path)
                        tiff_path = os.path.splitext(crop_path)[0] + ".tiff"
                        save_as_tiff(img, tiff_path)
                        crop_path = tiff_path

                    result = CropResult.objects.create(
                        folder=folder,
                        source_image=image_path,
                        output_image=crop_path,
                        method=CropMethod.AUTO,
                        bbox=bbox,
                        confidence=conf,
                    )
                    crop_results.append(result)

            self.status_service.update_step(
                folder_id,
                ProcessingStep.AUTO_CROPPED,
                StepStatus.COMPLETED,
                output_files=[r.output_image for r in crop_results],
            )
            return crop_results

        except Exception as e:
            self.status_service.update_step(
                folder_id, ProcessingStep.AUTO_CROPPED, StepStatus.FAILED,
                error=str(e),
            )
            raise CropError(f"Auto crop failed: {e}")

    def auto_crop_all(self, folder_id: str, prompts: list[str] = None) -> list[CropResult]:
        """Auto-crop all images in a folder using SAM3 segmentation."""
        try:
            folder = ProcessingFolder.objects.get(id=folder_id)
        except ProcessingFolder.DoesNotExist:
            raise CropError(f"Folder {folder_id} not found")
        all_results = []

        for image_path in folder.source_images:
            try:
                results = self.auto_crop(folder_id, image_path, prompts)
                all_results.extend(results)
            except CropError as e:
                logger.warning(f"Auto crop failed for {image_path}: {e}")
                continue

        return all_results

    def manual_crop(
        self,
        folder_id: str,
        image_path: str,
        bbox: list[int],
    ) -> CropResult:
        """Manually crop an image with given bounding box [x1, y1, x2, y2]."""
        try:
            folder = ProcessingFolder.objects.get(id=folder_id)
        except ProcessingFolder.DoesNotExist:
            raise CropError(f"Folder {folder_id} not found")
        self.status_service.update_step(
            folder_id, ProcessingStep.MANUAL_CROPPED, StepStatus.IN_PROGRESS,
        )

        try:
            img = load_image(image_path)
            x1, y1, x2, y2 = bbox

            # Ensure correct ordering and clamp to image dimensions
            h, w = img.shape[:2]
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            x1 = max(0, min(x1, w))
            x2 = max(0, min(x2, w))
            y1 = max(0, min(y1, h))
            y2 = max(0, min(y2, h))

            if x2 - x1 < 1 or y2 - y1 < 1:
                raise CropError("Crop region is too small or outside image bounds")

            cropped = img[y1:y2, x1:x2]

            output_dir = ensure_directory(str(Path(folder.path) / "cropped"))
            basename = os.path.splitext(os.path.basename(image_path))[0]
            output_path = os.path.join(output_dir, f"{basename}_manual.tiff")
            save_as_tiff(cropped, output_path)

            result = CropResult.objects.create(
                folder=folder,
                source_image=image_path,
                output_image=output_path,
                method=CropMethod.MANUAL,
                bbox=bbox,
            )

            self.status_service.update_step(
                folder_id,
                ProcessingStep.MANUAL_CROPPED,
                StepStatus.COMPLETED,
                output_files=[output_path],
            )
            return result

        except Exception as e:
            self.status_service.update_step(
                folder_id, ProcessingStep.MANUAL_CROPPED, StepStatus.FAILED,
                error=str(e),
            )
            raise CropError(f"Manual crop failed: {e}")

    def get_crop_results(self, folder_id: str) -> list[CropResult]:
        """Get all crop results for a folder."""
        return list(CropResult.objects.filter(folder_id=folder_id))
