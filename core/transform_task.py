# -*- coding: utf-8 -*-
"""
QgsTask wrapper for vector layer transformation.

Runs the heavy feature-iteration loop off the main thread so the UI
stays responsive.  All QGIS map-layer mutations (addMapLayer, etc.)
happen in finished() which runs on the main thread.
"""

from typing import List, Optional, Dict, Any

from qgis.core import (
    QgsMessageLog, QgsTask, QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils, QgsProject,
)
from ..shared.compat import MsgInfo, MsgWarning, MsgCritical, TaskCanCancel


class TransformTask(QgsTask):
    """Background task that delegates to SimpleTransformer."""

    def __init__(
        self,
        transformer,
        items: List[Dict[str, Any]],
        target_crs: Optional[QgsCoordinateReferenceSystem] = None,
        description: str = "Transform layers",
        table_filter: Optional[List[str]] = None,
    ):
        super().__init__(description, TaskCanCancel)
        self.transformer = transformer
        self.items = items
        self.target_crs = target_crs
        self.table_filter = table_filter

        # Results populated by run(), consumed by finished()
        self.created_layers: List[QgsVectorLayer] = []
        self.errors: List[str] = []
        self.success_count = 0
        self.fail_count = 0
        self._exception: Optional[Exception] = None

        # C2: Pre-build global + project scopes on the main thread (thread-safe).
        # The worker thread only builds layer scopes (read-only, safe).
        self._prebuilt_scopes = [
            QgsExpressionContextUtils.globalScope(),
            QgsExpressionContextUtils.projectScope(QgsProject.instance()),
        ]

    # ------------------------------------------------------------------
    # QgsTask interface
    # ------------------------------------------------------------------

    def run(self) -> bool:
        """Heavy work - runs on a worker thread.

        Rules:
        - No GUI calls.
        - No QgsProject mutations.
        - Only read from source layers (safe in QGIS task framework).
        - Memory layers created here will be added to project in finished().
        """
        self.transformer._current_task = self
        self.transformer._prebuilt_scopes = self._prebuilt_scopes
        try:
            total = len(self.items)
            for idx, item in enumerate(self.items):
                if self.isCanceled():
                    return False

                filename = item.get("filename", "")
                shapefile_info = item.get("shapefile_info", {})

                try:
                    if shapefile_info.get("is_qgis_layer", False):
                        layer_obj = shapefile_info["layer"]
                        layers = self.transformer.transform_qgis_layer_to_memory_layers(
                            layer_obj, filename, self.target_crs,
                            table_filter=self.table_filter,
                        )
                    else:
                        shp_path = shapefile_info["path"]
                        layers = self.transformer.transform_shapefile_to_memory_layers(
                            shp_path, self.target_crs,
                            table_filter=self.table_filter,
                        )

                    if layers:
                        self.created_layers.extend(layers)
                        self.success_count += 1
                    else:
                        self.fail_count += 1
                        self.errors.append(f"No layers created from {filename}")

                except Exception as exc:
                    self.fail_count += 1
                    self.errors.append(f"{filename}: {exc}")

                self.setProgress((idx + 1) / total * 100)

            return True

        except Exception as exc:
            self._exception = exc
            return False
        finally:
            self.transformer._current_task = None
            self.transformer._prebuilt_scopes = None

    def finished(self, result: bool):
        """Runs on the main thread after run() completes."""
        if self._exception:
            QgsMessageLog.logMessage(
                f"TransformTask exception: {self._exception}",
                "Transformer",
                MsgCritical,
            )
            return

        if not result:
            QgsMessageLog.logMessage(
                "TransformTask canceled or failed",
                "Transformer",
                MsgWarning,
            )
            return

        if self.created_layers:
            self.transformer.add_layers_to_project(
                self.created_layers, "Transformed Layers"
            )

        QgsMessageLog.logMessage(
            f"TransformTask done: {self.success_count} ok, "
            f"{self.fail_count} failed, "
            f"{len(self.created_layers)} layers created",
            "Transformer",
            MsgInfo,
        )
