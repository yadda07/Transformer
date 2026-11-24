# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
QgsTask wrapper for vector layer transformation.

Runs the heavy feature-iteration loop off the main thread so the UI
stays responsive.  All QGIS map-layer mutations (addMapLayer, etc.)
happen in finished() which runs on the main thread.
"""

from typing import List, Optional, Dict, Any
import copy
from qgis.PyQt.QtCore import QObject

from qgis.core import (
    QgsMessageLog, QgsTask, QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils, QgsProject, QgsVectorLayerFeatureSource,
    QgsExpressionContextScope, QgsExpressionContext, QgsFields, QgsApplication,
)
from ..shared.compat import MsgInfo, MsgWarning, MsgCritical, TaskCanCancel


class DetachedLayerSource:
    """Feature-source snapshot and value metadata, without a GUI layer QObject.

    Construct on the main thread. The native feature source opens iterators
    in the worker without materializing the complete input in a memory layer.
    """

    def __init__(self, layer, base_scopes):
        self._features = QgsVectorLayerFeatureSource(layer)
        self._fields = QgsFields(layer.fields())
        self._count = layer.featureCount()
        self._crs = QgsCoordinateReferenceSystem(layer.crs())
        self._wkb_type = layer.wkbType()
        self._id = layer.id()
        self._name = layer.name()
        self._source = layer.source()
        self._valid = layer.isValid()
        self.expression_scope = self._detached_scope(QgsExpressionContextUtils.layerScope(layer))
        # @layer would retain a live/weak map-layer pointer. The background
        # expression validator rejects it; scalar @layer_id/name remain valid.
        self.expression_scope.removeVariable("layer")
        self._base_scopes = tuple(self._detached_scope(scope) for scope in base_scopes)

    @staticmethod
    def _detached_scope(scope):
        def detached(value):
            if isinstance(value, QObject):
                return None
            if isinstance(value, dict):
                return {key: detached(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [detached(item) for item in value]
            return value
        cloned = QgsExpressionContextScope(scope)
        for name in cloned.variableNames():
            value = cloned.variable(name)
            if name == "layer" or isinstance(value, QObject):
                cloned.removeVariable(name)
            elif isinstance(value, (dict, list, tuple)):
                cloned.setVariable(name, detached(value))
        return cloned

    def fields(self):
        return self._fields

    def getFeatures(self, request=None):
        return self._features.getFeatures() if request is None else self._features.getFeatures(request)

    def featureCount(self):
        return self._count

    def crs(self):
        return self._crs

    def wkbType(self):
        return self._wkb_type

    def id(self):
        return self._id

    def name(self):
        return self._name

    def source(self):
        return self._source

    def isValid(self):
        return self._valid

    def expression_context(self):
        context = QgsExpressionContext()
        for scope in (*self._base_scopes, self.expression_scope):
            context.appendScope(QgsExpressionContextScope(scope))
        context.setFields(self._fields)
        return context


class _TaskProgressFeedback:
    """Adapt QgsTask progress and cancellation for SimpleTransformer."""

    def __init__(self, task: QgsTask, base_pct: float, span_pct: float):
        self._task = task
        self._base = base_pct
        self._span = span_pct

    def isCanceled(self) -> bool:
        return self._task.isCanceled()

    def setProgress(self, value: float) -> None:
        clamped = max(0.0, min(100.0, float(value)))
        self._task.setProgress(self._base + (clamped * self._span / 100.0))

    def pushWarning(self, _message: str) -> None:
        return None


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
        self.target_crs = target_crs
        self.table_filter = table_filter

        # Results populated by run(), consumed by finished()
        self.created_layers: List[QgsVectorLayer] = []
        self.errors: List[str] = []
        self.success_count = 0
        self.fail_count = 0
        self._exception: Optional[Exception] = None
        self.result_summary = {"status": "pending", "recipes": [], "produced_count": 0, "rejected_count": 0, "errors": []}
        self._transform_context = QgsProject.instance().transformContext()
        self._main_thread = QgsApplication.instance().thread()
        # Freeze the recipe catalogue before the background run. Editing the
        # main window cannot alter the recipe used halfway through a task.
        self._worker_transformer = copy.copy(transformer)
        if hasattr(transformer, "config_manager"):
            manager = copy.copy(transformer.config_manager)
            src_data = getattr(transformer.config_manager, "config_data", {}) or {}
            manager.config_data = {
                "version": src_data.get("version"),
                "tables": copy.deepcopy(src_data.get("tables", {})),
            }
            self._worker_transformer.config_manager = manager
        self._worker_transformer._logged_field_errors = set()

        # Copy all expression scopes while the GUI objects are accessible.
        self._prebuilt_scopes = [
            DetachedLayerSource._detached_scope(QgsExpressionContextUtils.globalScope()),
            DetachedLayerSource._detached_scope(QgsExpressionContextUtils.projectScope(QgsProject.instance())),
        ]
        self.items = []
        dependent_layers = []
        snapshots = {}
        for item in items:
            frozen_item = dict(item)
            info = dict(item.get("shapefile_info", {}))
            layer = info.get("layer")
            if layer is not None:
                if layer.id() not in snapshots:
                    snapshots[layer.id()] = DetachedLayerSource(layer, self._prebuilt_scopes)
                    dependent_layers.append(layer)
                # Do not retain the GUI layer, provider or other QObject metadata.
                info = {key: value for key, value in info.items()
                        if key in {"display_name", "name", "path", "is_qgis_layer"}}
                info["layer"] = snapshots[layer.id()]
            frozen_item["shapefile_info"] = info
            if frozen_item.get("table_names") is not None:
                frozen_item["table_names"] = list(frozen_item["table_names"])
            self.items.append(frozen_item)
        self.setDependentLayers(dependent_layers)

    # ------------------------------------------------------------------
    # QgsTask interface
    # ------------------------------------------------------------------

    def run(self) -> bool:
        """Heavy work - runs on a worker thread.

        Rules:
        - No GUI calls.
        - No QgsProject mutations.
        - Read native feature snapshots, never GUI-owned layer QObjects.
        - Move completed memory layers to the GUI thread before publication.
        """
        worker = self._worker_transformer
        worker._current_task = self
        worker._prebuilt_scopes = self._prebuilt_scopes
        worker._transform_context = self._transform_context
        self.result_summary["status"] = "running"
        try:
            total = len(self.items)
            seen = set()
            for idx, item in enumerate(self.items):
                if self.isCanceled():
                    self._cancel_results()
                    return False

                filename = item.get("filename", "")
                shapefile_info = item.get("shapefile_info", {})
                display_name = shapefile_info.get("display_name") or shapefile_info.get("name") or filename
                names = item.get("table_names", self.table_filter)
                if names is not None:
                    names = [name for name in dict.fromkeys(names) if (filename, name) not in seen]
                    if not names:
                        continue
                    seen.update((filename, name) for name in names)
                elif (filename, None) in seen:
                    continue
                else:
                    seen.add((filename, None))

                base_pct = (idx / total) * 100.0 if total > 0 else 0.0
                span_pct = (100.0 / total) if total > 0 else 100.0
                worker._progress_feedback = _TaskProgressFeedback(self, base_pct, span_pct)
                try:
                    if shapefile_info.get("layer") is not None:
                        layer_obj = shapefile_info["layer"]
                        layers = worker.transform_qgis_layer_to_memory_layers(
                            layer_obj, filename, self.target_crs,
                            table_filter=names,
                        )
                    else:
                        shp_path = shapefile_info["path"]
                        layers = worker.transform_shapefile_to_memory_layers(
                            shp_path, self.target_crs,
                            table_filter=names,
                        )

                    if self.isCanceled():
                        self._cancel_results()
                        return False
                    summaries = copy.deepcopy(getattr(worker, "result_summaries", []))
                    self.result_summary["recipes"].extend(summaries)
                    recipe_errors = [error for summary in summaries for error in summary.get("errors", [])]
                    self.errors.extend(recipe_errors)

                    if layers:
                        self.created_layers.extend(layers)
                        self.success_count += 1
                        if any(summary.get("status") != "success" for summary in summaries):
                            self.fail_count += 1
                    else:
                        self.fail_count += 1
                        self.errors.append(f"Aucune sortie produite pour {display_name}.")

                except Exception as exc:
                    self.fail_count += 1
                    self.errors.append(f"{display_name} : {exc}")
                finally:
                    worker._progress_feedback = None

                self.setProgress((idx + 1) / total * 100)

            self.result_summary["produced_count"] = sum(row.get("produced_count", 0) for row in self.result_summary["recipes"])
            self.result_summary["rejected_count"] = sum(row.get("rejected_count", 0) for row in self.result_summary["recipes"])
            self.result_summary["errors"] = self.errors[:20]
            self.result_summary["status"] = "partial" if self.success_count and self.fail_count else ("success" if self.success_count else "failed")
            if self.isCanceled():
                self._cancel_results()
                return False
            # Keep outputs worker-owned until every cancellation point has
            # passed; cancelling an earlier item must not delete GUI-owned
            # QObjects from the worker. finished() handles later cancellations.
            for layer in self.created_layers:
                if layer.parent() is not None:
                    raise RuntimeError("Une sortie de tâche ne doit pas avoir de parent QObject.")
            for layer in self.created_layers:
                layer.moveToThread(self._main_thread)
                if layer.thread() != self._main_thread:
                    raise RuntimeError("La sortie n'a pas rejoint le thread principal.")
            return bool(self.success_count)

        except Exception as exc:
            self._exception = exc
            self.result_summary.update(status="failed", errors=[str(exc)])
            self.created_layers.clear()
            self.success_count = 0
            return False
        finally:
            worker._current_task = None
            worker._progress_feedback = None
            worker._prebuilt_scopes = None
            worker._transform_context = None

    def _cancel_results(self):
        """A cancelled task never presents unpublished memory layers as success."""
        self.created_layers.clear()
        self.success_count = 0
        self.result_summary.update(status="cancelled", produced_count=0, errors=["Exécution annulée ; aucune sortie ajoutée au projet."])
        for summary in self.result_summary["recipes"]:
            summary["published"] = False

    def finished(self, result: bool):
        """Runs on the main thread after run() completes."""
        if self._exception:
            QgsMessageLog.logMessage(
                f"TransformTask exception: {self._exception}",
                "Transformer",
                MsgCritical,
            )
            return

        if self.isCanceled():
            self._cancel_results()
            result = False
        if not result:
            QgsMessageLog.logMessage(
                "TransformTask canceled or failed",
                "Transformer",
                MsgWarning,
            )
            return

        if self.created_layers:
            published = self.transformer.add_layers_to_project(
                self.created_layers, "Transformed Layers"
            )
            if published is False:
                self.result_summary.update(status="failed", errors=["Les résultats calculés n'ont pas tous été ajoutés au projet."])
                self.fail_count += self.success_count
                self.success_count = 0
                return
            for summary in self.result_summary["recipes"]:
                if summary.get("status") == "success":
                    summary["published"] = True

        QgsMessageLog.logMessage(
            f"TransformTask done: {self.success_count} ok, "
            f"{self.fail_count} failed, "
            f"{len(self.created_layers)} layers created",
            "Transformer",
            MsgInfo,
        )
