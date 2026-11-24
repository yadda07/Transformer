# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""QGIS Processing algorithm: ad-hoc vector transformation using Transformer's strict engine."""

import json

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterExpression,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFieldMapping,
    QgsProperty,
)

from .common import (
    ALGO_FLAG_SUPPORTS_BATCH,
    PARAM_FLAG_ADVANCED,
    PARAM_FLAG_OPTIONAL,
    VECTOR_SOURCE_TYPE,
    field_mapping_to_recipe,
    run_sink_algorithm,
)


class TransformVectorAlgorithm(QgsProcessingAlgorithm):
    """Ad-hoc Transformer algorithm for Modeler / scripts without external JSON file."""

    INPUT = "INPUT"
    FIELDS_MAPPING = "FIELDS_MAPPING"
    FILTER_EXPRESSION = "FILTER_EXPRESSION"
    GEOMETRY_EXPRESSION = "GEOMETRY_EXPRESSION"
    TARGET_CRS = "TARGET_CRS"
    STRICT_SCHEMA_CHECK = "STRICT_SCHEMA_CHECK"
    OUTPUT = "OUTPUT"
    PRODUCED_COUNT = "PRODUCED_COUNT"
    FILTERED_OUT_COUNT = "FILTERED_OUT_COUNT"
    REPORT_JSON = "REPORT_JSON"

    def createInstance(self):
        return TransformVectorAlgorithm()

    def name(self) -> str:
        return "transform_vector"

    def displayName(self) -> str:
        return "Transformer une couche (ad-hoc)"

    def group(self) -> str:
        return "Transformation vectorielle"

    def groupId(self) -> str:
        return "vector_transformation"

    def flags(self):
        return super().flags() | ALGO_FLAG_SUPPORTS_BATCH

    def shortHelpString(self) -> str:
        return (
            "Transforme une couche vectorielle ou tabulaire directement dans le Modeleur "
            "graphique ou un script Python, sans fichier recette externe.\n\n"
            "Combine dans une seule passe :\n"
            "- Renommage, typage strict et expressions attributaires (FIELDS_MAPPING ; si vide, "
            "toutes les colonnes source sont conservees).\n"
            "- Filtre strict sur les lignes (FILTER_EXPRESSION).\n"
            "- Construction ou modification de geometrie dans le SCR source (GEOMETRY_EXPRESSION).\n"
            "- Reprojection finale vers TARGET_CRS."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Couche ou table d'entree",
                [VECTOR_SOURCE_TYPE],
            )
        )

        mapping_param = QgsProcessingParameterFieldMapping(
            self.FIELDS_MAPPING,
            "Correspondance et expressions des champs (vide = conserver les champs source)",
            self.INPUT,
        )
        mapping_param.setFlags(mapping_param.flags() | PARAM_FLAG_OPTIONAL)
        self.addParameter(mapping_param)

        filter_param = QgsProcessingParameterExpression(
            self.FILTER_EXPRESSION,
            "Filtre strict sur les entites",
            defaultValue="",
            parentLayerParameterName=self.INPUT,
            optional=True,
        )
        self.addParameter(filter_param)

        geom_param = QgsProcessingParameterExpression(
            self.GEOMETRY_EXPRESSION,
            "Expression geometrique (evaluee avant reprojection)",
            defaultValue="",
            parentLayerParameterName=self.INPUT,
            optional=True,
        )
        self.addParameter(geom_param)

        crs_param = QgsProcessingParameterCrs(
            self.TARGET_CRS,
            "SCR cible (laisser vide pour conserver le SCR source)",
            defaultValue=None,
            optional=True,
        )
        self.addParameter(crs_param)

        strict_param = QgsProcessingParameterBoolean(
            self.STRICT_SCHEMA_CHECK,
            "Precontrole strict du schema selon le format de sortie",
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
        self.addOutput(QgsProcessingOutputString(self.REPORT_JSON, "Bilan d'execution JSON"))

    @staticmethod
    def _parse_fields_mapping(raw_value, context=None):
        if isinstance(raw_value, QgsProperty):
            expr_ctx = context.expressionContext() if context is not None else None
            evaluated = raw_value.value(expr_ctx) if expr_ctx is not None else (None, False)
            raw_value = evaluated[0] if isinstance(evaluated, tuple) else evaluated
        if raw_value is None or raw_value == "":
            return []
        if isinstance(raw_value, str):
            try:
                parsed = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"transformer:transform_vector : FIELDS_MAPPING JSON invalide : {exc}"
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError(
                    "transformer:transform_vector : FIELDS_MAPPING doit etre une liste d'objets."
                )
            return parsed
        if isinstance(raw_value, (list, tuple)):
            return list(raw_value)
        raise ValueError(
            "transformer:transform_vector : format de FIELDS_MAPPING non pris en charge."
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        filter_text = self.parameterAsExpression(parameters, self.FILTER_EXPRESSION, context)
        geom_text = self.parameterAsExpression(parameters, self.GEOMETRY_EXPRESSION, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        strict_schema = self.parameterAsBoolean(parameters, self.STRICT_SCHEMA_CHECK, context)

        try:
            mapping_entries = self._parse_fields_mapping(
                parameters.get(self.FIELDS_MAPPING), context=context,
            )
            calculated_fields, field_definitions = field_mapping_to_recipe(
                mapping_entries, source.fields(),
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        filter_config = (
            {"enabled": True, "expression": filter_text.strip()}
            if filter_text and filter_text.strip()
            else {"enabled": False, "expression": ""}
        )
        geometry_expression = geom_text.strip() if geom_text and geom_text.strip() else "$geometry"
        resolved_crs = target_crs if (target_crs is not None and target_crs.isValid()) else None
        recipe_label = f"{source.sourceName()}_transformed" if source.sourceName() else "transformed"

        dest_id, summary = run_sink_algorithm(
            algorithm=self,
            alg_id="transformer:transform_vector",
            parameters=parameters,
            context=context,
            feedback=feedback,
            source=source,
            recipe_label=recipe_label,
            calculated_fields=calculated_fields,
            field_definitions=field_definitions,
            filter_config=filter_config,
            geometry_expression=geometry_expression,
            target_crs=resolved_crs,
            strict_schema=strict_schema,
            output_param_name=self.OUTPUT,
        )

        feedback.pushInfo(
            f"Transformation ad-hoc terminee : {summary['produced_count']} entite(s) produite(s), "
            f"{summary['filtered_out_count']} exclue(s)."
        )

        return {
            self.OUTPUT: dest_id,
            self.PRODUCED_COUNT: int(summary["produced_count"]),
            self.FILTERED_OUT_COUNT: int(summary["filtered_out_count"]),
            self.REPORT_JSON: json.dumps(summary, ensure_ascii=False),
        }
