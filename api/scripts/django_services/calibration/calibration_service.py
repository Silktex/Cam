"""
Calibration service - color correction using color checker data.
Extracted from color_calibration.ipynb.
"""
import os
import logging
from pathlib import Path

import cv2
import numpy as np

from apps.calibration.models import CalibrationJob, CalibrationMode
from apps.colorchecker.models import SavedColorChecker
from apps.folders.models import ProcessingFolder
from apps.status.services.status_service import StatusService
from apps.status.models import ProcessingStep, StepStatus
from apps.core.utils.image_io import save_as_tiff
from apps.core.utils.file_utils import list_images, ensure_directory
from apps.core.exceptions import CalibrationError

logger = logging.getLogger(__name__)

try:
    import colour
    COLOUR_AVAILABLE = True
except ImportError:
    COLOUR_AVAILABLE = False


class CalibrationService:
    def __init__(self, status_service: StatusService = None):
        self.status_service = status_service or StatusService()

    def calibrate(
        self,
        folder_id: str,
        colorchecker_id: str,
        mode: str = "all",
        source_image: str = None,
    ) -> CalibrationJob:
        """Apply color calibration to images in a folder."""
        if not COLOUR_AVAILABLE:
            raise CalibrationError("colour-science library not installed")

        folder = ProcessingFolder.objects.get(id=folder_id)
        checker = SavedColorChecker.objects.get(id=colorchecker_id)

        self.status_service.update_step(
            folder_id, ProcessingStep.CALIBRATION_APPLIED, StepStatus.IN_PROGRESS,
        )

        # Get reference swatches from checker's correction matrix
        if not checker.correction_matrix:
            raise CalibrationError("Color checker has no correction matrix. Save the checker first.")

        detected_swatches = np.array(checker.correction_matrix["detected_swatches"])
        reference_swatches = np.array(checker.correction_matrix["reference_swatches"])

        output_folder = ensure_directory(str(Path(folder.path) / "calibrated"))

        job = CalibrationJob.objects.create(
            folder=folder,
            colorchecker=checker,
            calibration_mode=mode,
            source_image_for_calibration=source_image or "",
            output_folder=output_folder,
        )

        try:
            calibrated_images = []

            if mode == CalibrationMode.SINGLE and source_image:
                output_path = self._calibrate_image(
                    source_image, detected_swatches, reference_swatches, output_folder,
                )
                calibrated_images.append(output_path)
            else:
                # Calibrate all images in folder
                images = list_images(folder.path)
                for img_path in images:
                    try:
                        output_path = self._calibrate_image(
                            img_path, detected_swatches, reference_swatches, output_folder,
                        )
                        calibrated_images.append(output_path)
                    except Exception as e:
                        logger.error(f"Failed to calibrate {img_path}: {e}")

            job.calibrated_images = calibrated_images
            job.save()

            self.status_service.update_step(
                folder_id,
                ProcessingStep.CALIBRATION_APPLIED,
                StepStatus.COMPLETED,
                output_files=calibrated_images,
            )

            return job

        except Exception as e:
            self.status_service.update_step(
                folder_id, ProcessingStep.CALIBRATION_APPLIED, StepStatus.FAILED,
                error=str(e),
            )
            raise CalibrationError(f"Calibration failed: {e}")

    def _calibrate_image(
        self,
        image_path: str,
        detected_swatches: np.ndarray,
        reference_swatches: np.ndarray,
        output_folder: str,
    ) -> str:
        """Calibrate a single image using colour.colour_correction."""
        # Read image as float for colour-science
        image = colour.io.read_image(image_path)

        # Apply colour correction
        corrected = colour.colour_correction(
            image, detected_swatches, reference_swatches,
        )

        # Convert to 16-bit TIFF
        corrected_16bit = np.clip(colour.cctf_encoding(corrected), 0, 1)
        corrected_16bit = (corrected_16bit * 65535).astype(np.uint16)

        # Convert RGB to BGR for cv2
        corrected_bgr = cv2.cvtColor(corrected_16bit, cv2.COLOR_RGB2BGR)

        # Save as TIFF
        basename = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_folder, f"{basename}_calibrated.tiff")
        save_as_tiff(corrected_bgr, output_path)

        return output_path

    def get_jobs(self, folder_id: str) -> list[CalibrationJob]:
        """Get calibration jobs for a folder."""
        return list(CalibrationJob.objects.filter(folder_id=folder_id))
