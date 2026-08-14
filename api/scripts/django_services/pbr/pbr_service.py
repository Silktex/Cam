"""
PBR service orchestrator.
Creates jobs, calls grayscale/color processors, updates status.
"""
import os
from pathlib import Path

from apps.pbr.models import PBRJob, PBRResult, PBRMode, PBRType
from apps.folders.models import ProcessingFolder
from apps.status.services.status_service import StatusService
from apps.status.models import ProcessingStep, StepStatus

from .pbr_color import PBRMaps, ImageProcessor
from .pbr_grayscale import (
    load_and_pair_images as load_grayscale,
    photometric_stereo as grayscale_stereo,
    compute_roughness as grayscale_roughness,
    integrate_normals as grayscale_height,
    visualize_normals,
    save_map,
)


class PBRService:
    def __init__(self, status_service: StatusService = None):
        self.status_service = status_service or StatusService()

    def generate(
        self,
        folder_id: str,
        mode: str,
        use_gpu: bool = True,
        use_calibrated: bool = True,
        output_base_folder: str = None,
        downsample_scale: float = 0.25,
    ) -> PBRJob:
        """Generate PBR maps for a folder."""
        folder = ProcessingFolder.objects.get(id=folder_id)

        if use_calibrated:
            input_folder = str(Path(folder.path) / "calibrated")
            if not Path(input_folder).exists():
                input_folder = folder.path
        else:
            input_folder = folder.path

        if output_base_folder is None:
            output_base_folder = str(Path(folder.path) / "pbr_maps")

        job = PBRJob.objects.create(
            folder=folder,
            pbr_mode=mode,
            use_gpu=use_gpu,
            use_calibrated_images=use_calibrated,
            input_folder=input_folder,
        )

        try:
            if mode in [PBRMode.GRAYSCALE_ONLY, PBRMode.BOTH]:
                self._generate_grayscale(folder_id, job, input_folder, output_base_folder, downsample_scale)

            if mode in [PBRMode.COLOR_ONLY, PBRMode.BOTH]:
                self._generate_color(folder_id, job, input_folder, output_base_folder, use_gpu, downsample_scale)

            return job

        except Exception as e:
            if mode in [PBRMode.GRAYSCALE_ONLY, PBRMode.BOTH]:
                self.status_service.update_step(
                    folder_id, ProcessingStep.PBR_GRAYSCALE, StepStatus.FAILED, error=str(e),
                )
            if mode in [PBRMode.COLOR_ONLY, PBRMode.BOTH]:
                self.status_service.update_step(
                    folder_id, ProcessingStep.PBR_COLOR, StepStatus.FAILED, error=str(e),
                )
            raise

    def _generate_grayscale(self, folder_id, job, input_folder, output_base, downsample_scale=0.25):
        self.status_service.update_step(
            folder_id, ProcessingStep.PBR_GRAYSCALE, StepStatus.IN_PROGRESS,
        )

        output_folder = str(Path(output_base) / "grayscale")
        Path(output_folder).mkdir(parents=True, exist_ok=True)

        images, light_dirs = load_grayscale(input_folder, downsample_scale=downsample_scale)
        albedo, normals = grayscale_stereo(images, light_dirs)
        roughness = grayscale_roughness(normals)
        height_map = grayscale_height(normals)
        normals_rgb = visualize_normals(normals)

        albedo_path = os.path.join(output_folder, "albedo.tiff")
        normals_path = os.path.join(output_folder, "normals.tiff")
        roughness_path = os.path.join(output_folder, "roughness.tiff")
        height_path = os.path.join(output_folder, "height_map.tiff")

        save_map(albedo, albedo_path)
        save_map(normals_rgb, normals_path)
        save_map(roughness, roughness_path)
        save_map(height_map, height_path)

        result = PBRResult.objects.create(
            job=job,
            pbr_type=PBRType.GRAYSCALE,
            output_folder=output_folder,
            albedo_path=albedo_path,
            normals_path=normals_path,
            roughness_path=roughness_path,
            height_map_path=height_path,
        )

        self.status_service.update_step(
            folder_id,
            ProcessingStep.PBR_GRAYSCALE,
            StepStatus.COMPLETED,
            output_files=[albedo_path, normals_path, roughness_path, height_path],
        )
        return result

    def _generate_color(self, folder_id, job, input_folder, output_base, use_gpu, downsample_scale=0.25):
        self.status_service.update_step(
            folder_id, ProcessingStep.PBR_COLOR, StepStatus.IN_PROGRESS,
        )

        output_folder = str(Path(output_base) / "color")
        Path(output_folder).mkdir(parents=True, exist_ok=True)

        pbr = PBRMaps(input_folder, downsample_scale=downsample_scale, use_gpu=use_gpu)
        albedo, normals = pbr.compute_photometric_stereo()
        roughness = pbr.compute_roughness(normals)
        height_map = pbr.compute_height_map(normals)

        albedo_path = os.path.join(output_folder, "albedo.tiff")
        normals_path = os.path.join(output_folder, "normals.tiff")
        roughness_path = os.path.join(output_folder, "roughness.tiff")
        height_path = os.path.join(output_folder, "height_map.tiff")

        ImageProcessor.save_map(albedo, albedo_path)
        ImageProcessor.save_map(normals, normals_path)
        ImageProcessor.save_map(roughness, roughness_path)
        ImageProcessor.save_map(height_map, height_path)

        result = PBRResult.objects.create(
            job=job,
            pbr_type=PBRType.COLOR,
            output_folder=output_folder,
            albedo_path=albedo_path,
            normals_path=normals_path,
            roughness_path=roughness_path,
            height_map_path=height_path,
        )

        self.status_service.update_step(
            folder_id,
            ProcessingStep.PBR_COLOR,
            StepStatus.COMPLETED,
            output_files=[albedo_path, normals_path, roughness_path, height_path],
        )
        return result
