# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""QGIS Processing provider exposing Transformer algorithms."""

import os

from qgis.PyQt.QtGui import QGuiApplication, QIcon
from qgis.core import QgsProcessingProvider

from .apply_recipe_algorithm import ApplyRecipeAlgorithm
from .publish_postgresql_algorithm import PublishPostgreSQLAlgorithm
from .transform_vector_algorithm import TransformVectorAlgorithm


class TransformerProvider(QgsProcessingProvider):
    """Native QGIS Processing provider for Transformer ETL workflows."""

    def __init__(self, plugin_dir: str = ""):
        super().__init__()
        self.plugin_dir = plugin_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def id(self) -> str:
        return "transformer"

    def name(self) -> str:
        return "Transformer"

    def longName(self) -> str:
        return "Transformer - Recettes vectorielles et publication PostGIS"

    def icon(self) -> QIcon:
        # Guard QIcon creation in pure headless CLI runs without QGuiApplication
        if QGuiApplication.instance() is None:
            return QIcon()
        icon_path = os.path.join(self.plugin_dir, "logo.png")
        if os.path.isfile(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def loadAlgorithms(self):
        self.addAlgorithm(ApplyRecipeAlgorithm(self.plugin_dir))
        self.addAlgorithm(TransformVectorAlgorithm())
        self.addAlgorithm(PublishPostgreSQLAlgorithm(self.plugin_dir))
