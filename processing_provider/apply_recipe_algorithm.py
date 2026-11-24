# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""QGIS Processing algorithm: apply a saved Transformer recipe to a vector source."""

import json
import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterExpression,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
)

from ..core.config_manager import ConfigManager
from .common import (
    ALGO_FLAG_SUPPORTS_BATCH,
    PARAM_FLAG_ADVANCED,
    PARAM_FLAG_OPTIONAL,
    VECTOR_SOURCE_TYPE,
    run_sink_algorithm,
)


_FILE_BEHAVIOR = getattr(
    getattr(QgsProcessingParameterFile, "Behavior", QgsProcessingParameterFile),
    "File",
    0,
)


class ApplyRecipeAlgorithm(QgsProcessingAlgorithm):
    """Apply a Transformer JSON recipe or local catalogue recipe in Processing / Modeler."""

    INPUT = "INPUT"
    RECIPE_FILE = "RECIPE_FILE"
    RECIPE_NAME = "RECIPE_NAME"
    FILTER_OVERRIDE = "FILTER_OVERRIDE"
    GEOMETRY_OVERRIDE = "GEOMETRY_OVERRIDE"
    CRS_OVERRIDE = "CRS_OVERRIDE"
    STRICT_SCHEMA_CHECK = "STRICT_SCHEMA_CHECK"
    OUTPUT = "OUTPUT"
    PRODUCED_COUNT = "PRODUCED_COUNT"
    FILTERED_OUT_COUNT = "FILTERED_OUT_COUNT"
    RECIPE_VERSION = "RECIPE_VERSION"
    REPORT_JSON = "REPORT_JSON"

    def __init__(self, plugin_dir: str = ""):
        super().__init__()
        self.plugin_dir = plugin_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def createInstance(self):
        return ApplyRecipeAlgorithm(self.plugin_dir)

    def name(self) -> str:
        return "apply_recipe"

    def displayName(self) -> str:
        return "Appliquer une recette Transformer"

    def group(self) -> str:
        return "Transformation vectorielle"

    def groupId(self) -> str:
        return "vector_transformation"

    def flags(self):
        return super().flags() | ALGO_FLAG_SUPPORTS_BATCH

    def shortHelpString(self) -> str:
        return (
            "Rejoue une recette Transformer (champs calcules et types, filtre strict, "
            "expression geometrique avant reprojection, SCR cible) sur une couche vectorielle "
            "ou une table sans geometrie.\n\n"
            "Deux modes de reference de recette :\n"
            "- Fichier JSON autonome (RECIPE_FILE) : portable dans un modele .model3 ou qgis_process.\n"
            "- Catalogue local (RECIPE_NAME seul) : selectionne une recette enregistree dans Transformer.\n\n"
            "Les parametres avances permettent de surcharger le filtre, l'expression geometrique "
            "ou le SCR cible sans modifier la recette d'origine."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Couche ou table d'entree",
                [VECTOR_SOURCE_TYPE],
            )
        )

        recipe_file_param = QgsProcessingParameterFile(
            self.RECIPE_FILE,
            "Fichier recette JSON (portable)",
            behavior=_FILE_BEHAVIOR,
            fileFilter="Recettes Transformer JSON (*.json)",
            optional=True,
        )
        self.addParameter(recipe_file_param)

        recipe_name_param = QgsProcessingParameterString(
            self.RECIPE_NAME,
            "Nom de la recette (requis si fichier multi-recettes ou catalogue local)",
            defaultValue="",
            optional=True,
        )
        self.addParameter(recipe_name_param)

        filter_param = QgsProcessingParameterExpression(
            self.FILTER_OVERRIDE,
            "Surcharge du filtre (laisser vide pour conserver celui de la recette)",
            defaultValue="",
            parentLayerParameterName=self.INPUT,
            optional=True,
        )
        filter_param.setFlags(filter_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(filter_param)

        geom_param = QgsProcessingParameterExpression(
            self.GEOMETRY_OVERRIDE,
            "Surcharge de l'expression geometrique (avant reprojection)",
            defaultValue="",
            parentLayerParameterName=self.INPUT,
            optional=True,
        )
        geom_param.setFlags(geom_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(geom_param)

        crs_param = QgsProcessingParameterCrs(
            self.CRS_OVERRIDE,
            "Surcharge du SCR cible",
            defaultValue=None,
            optional=True,
        )
        crs_param.setFlags(crs_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(crs_param)

        strict_param = QgsProcessingParameterBoolean(
            self.STRICT_SCHEMA_CHECK,
            "Precontrole strict du schema selon le format de sortie (ex. limite 10 octets Shapefile)",
            defaultValue=True,
        )
        strict_param.setFlags(strict_param.flags() | PARAM_FLAG_ADVANCED)
        self.addParameter(strict_param)

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                "Couche transformee",
                VECTOR_SOURCE_TYPE,
            )
        )

        self.addOutput(QgsProcessingOutputNumber(self.PRODUCED_COUNT, "Entites produites"))
        self.addOutput(QgsProcessingOutputNumber(self.FILTERED_OUT_COUNT, "Entites filtrees"))
        self.addOutput(QgsProcessingOutputNumber(self.RECIPE_VERSION, "Version de recette"))
        self.addOutput(QgsProcessingOutputString(self.REPORT_JSON, "Bilan d'execution JSON"))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        recipe_file = self.parameterAsFile(parameters, self.RECIPE_FILE, context)
        recipe_name = self.parameterAsString(parameters, self.RECIPE_NAME, context)
        filter_override = self.parameterAsExpression(parameters, self.FILTER_OVERRIDE, context)
        geom_override = self.parameterAsExpression(parameters, self.GEOMETRY_OVERRIDE, context)
        crs_override = self.parameterAsCrs(parameters, self.CRS_OVERRIDE, context)
        strict_schema = self.parameterAsBoolean(parameters, self.STRICT_SCHEMA_CHECK, context)

        try:
            resolved_name, recipe = ConfigManager.resolve_recipe(
                self.plugin_dir,
                recipe_file=recipe_file,
                recipe_name=recipe_name,
            )
        except Exception as exc:
            raise QgsProcessingException(
                f"transformer:apply_recipe : impossible de charger la recette : {exc}"
            ) from exc

        calculated_fields = recipe.get("calculated_fields", {})
        if not calculated_fields:
            raise QgsProcessingException(
                f"transformer:apply_recipe : la recette '{resolved_name}' ne definit aucun champ calcule."
            )

        filter_config = dict(recipe.get("filter") or {"enabled": False, "expression": ""})
        if filter_override and filter_override.strip():
            filter_config = {"enabled": True, "expression": filter_override.strip()}

        geometry_expression = recipe.get("geometry_expression") or "$geometry"
        if geom_override and geom_override.strip():
            geometry_expression = geom_override.strip()

        target_crs = None
        if crs_override is not None and crs_override.isValid():
            target_crs = crs_override
        elif recipe.get("target_crs"):
            target_crs = QgsCoordinateReferenceSystem(recipe["target_crs"])
            if not target_crs.isValid():
                raise QgsProcessingException(
                    f"transformer:apply_recipe : SCR cible invalide dans '{resolved_name}' "
                    f"({recipe['target_crs']})."
                )

        feedback.pushInfo(
            f"Execution de la recette '{resolved_name}' (v{recipe.get('recipe_version', 1)}) "
            f"sur '{source.sourceName()}'."
        )

        dest_id, summary = run_sink_algorithm(
            algorithm=self,
            alg_id="transformer:apply_recipe",
            parameters=parameters,
            context=context,
            feedback=feedback,
            source=source,
            recipe_label=resolved_name,
            calculated_fields=calculated_fields,
            field_definitions=recipe.get("field_definitions") or {},
            filter_config=filter_config,
            geometry_expression=geometry_expression,
            target_crs=target_crs,
            strict_schema=strict_schema,
            output_param_name=self.OUTPUT,
        )

        summary["recipe_version"] = int(recipe.get("recipe_version", 1))
        summary["recipe_id"] = recipe.get("recipe_id")

        # Apply friendly layer name when loading temporary output in QGIS Desktop
        if dest_id and context.willLoadLayerOnCompletion(dest_id):
            details = context.layerToLoadOnCompletionDetails(dest_id)
            if details is not None and (not details.name or details.name == "Couche transformee"):
                details.name = resolved_name

        feedback.pushInfo(
            f"Recette '{resolved_name}' terminee : {summary['produced_count']} entite(s) produite(s), "
            f"{summary['filtered_out_count']} exclue(s)."
        )

        return {
            self.OUTPUT: dest_id,
            self.PRODUCED_COUNT: int(summary["produced_count"]),
            self.FILTERED_OUT_COUNT: int(summary["filtered_out_count"]),
            self.RECIPE_VERSION: int(summary["recipe_version"]),
            self.REPORT_JSON: json.dumps(summary, ensure_ascii=False),
        }
