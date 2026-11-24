# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""QGIS Processing algorithm: transactional PostgreSQL / PostGIS publication."""

import json
import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDatabaseSchema,
    QgsProcessingParameterDatabaseTable,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterProviderConnection,
    QgsProcessingParameterString,
)

from ..pg.export_task import publish_source_to_postgresql
from .common import (
    ALGO_FLAG_SUPPORTS_BATCH,
    PARAM_FLAG_ADVANCED,
    PARAM_FLAG_OPTIONAL,
    VECTOR_SOURCE_TYPE,
    parse_pg_field_mapping_json,
    resolve_postgres_connection_params,
)


class PublishPostgreSQLAlgorithm(QgsProcessingAlgorithm):
    """Publish a vector layer or table to PostgreSQL/PostGIS in one atomic transaction."""

    INPUT = "INPUT"
    CONNECTION = "CONNECTION"
    SCHEMA = "SCHEMA"
    TABLE = "TABLE"
    MODE = "MODE"
    ALLOW_CREATE = "ALLOW_CREATE"
    GEOMETRY_COLUMN = "GEOMETRY_COLUMN"
    FIELD_MAPPING = "FIELD_MAPPING"
    SOURCE_KEY_FIELD = "SOURCE_KEY_FIELD"
    TARGET_KEY_FIELD = "TARGET_KEY_FIELD"

    COMMITTED_COUNT = "COMMITTED_COUNT"
    STATUS = "STATUS"
    REPORT_JSON = "REPORT_JSON"

    _MODE_CODES = ("append", "replace", "update")
    _MODE_LABELS = (
        "Ajouter (append)",
        "Remplacer atomiquement (replace)",
        "Mettre a jour / inserer (update)",
    )

    def __init__(self, plugin_dir: str = ""):
        super().__init__()
        self.plugin_dir = plugin_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._prepared_conn_name = ""
        self._prepared_conn_params = None
        self._prepared_field_mapping = None
        self._prepare_error = ""

    def createInstance(self):
        return PublishPostgreSQLAlgorithm(self.plugin_dir)

    def name(self) -> str:
        return "publish_postgresql"

    def displayName(self) -> str:
        return "Publier vers PostgreSQL / PostGIS"

    def group(self) -> str:
        return "Base de donnees"

    def groupId(self) -> str:
        return "database"

    def flags(self):
        return super().flags() | ALGO_FLAG_SUPPORTS_BATCH

    def shortHelpString(self) -> str:
        return (
            "Publie une couche vectorielle ou tabulaire dans PostgreSQL / PostGIS via "
            "une connexion QGIS (authcfg pris en charge, aucun mot de passe en clair).\n\n"
            "Modes disponibles :\n"
            "- append : insere les nouvelles entites.\n"
            "- replace : vide puis re-insere dans une seule transaction (rollback complet en cas d'echec).\n"
            "- update : upsert ON CONFLICT sur la cle attributaire (SOURCE_KEY_FIELD / TARGET_KEY_FIELD).\n\n"
            "La creation d'une table absente exige l'option explicite ALLOW_CREATE."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                "Couche ou table a publier",
                [VECTOR_SOURCE_TYPE],
            )
        )

        self.addParameter(
            QgsProcessingParameterProviderConnection(
                self.CONNECTION,
                "Connexion PostgreSQL (QGIS ou profil Transformer)",
                "postgres",
            )
        )

        self.addParameter(
            QgsProcessingParameterDatabaseSchema(
                self.SCHEMA,
                "Schema cible",
                self.CONNECTION,
                defaultValue="public",
                optional=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterDatabaseTable(
                self.TABLE,
                "Table cible",
                self.CONNECTION,
                self.SCHEMA,
                defaultValue="",
                optional=False,
                allowNewTableNames=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                "Mode de publication",
                options=list(self._MODE_LABELS),
                defaultValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLOW_CREATE,
                "Autoriser la creation de la table si absente",
                defaultValue=False,
            )
        )

        geom_col_param = QgsProcessingParameterString(
            self.GEOMETRY_COLUMN,
            "Colonne geometrique cible (vide = detection automatique ou 'geom' a la creation)",
            defaultValue="",
            optional=True,
        )
        geom_col_param.setFlags(geom_col_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(geom_col_param)

        mapping_param = QgsProcessingParameterString(
            self.FIELD_MAPPING,
            "Correspondance des colonnes JSON (ex. {\"code_src\": \"code_pg\"} ; vide = memes noms)",
            defaultValue="",
            multiLine=True,
            optional=True,
        )
        mapping_param.setFlags(mapping_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(mapping_param)

        src_key_param = QgsProcessingParameterField(
            self.SOURCE_KEY_FIELD,
            "Champ cle source (pour mode update / upsert)",
            defaultValue="",
            parentLayerParameterName=self.INPUT,
            optional=True,
        )
        src_key_param.setFlags(src_key_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(src_key_param)

        tgt_key_param = QgsProcessingParameterString(
            self.TARGET_KEY_FIELD,
            "Colonne cle cible PostgreSQL (pour mode update ; vide = meme nom que cle source)",
            defaultValue="",
            optional=True,
        )
        tgt_key_param.setFlags(tgt_key_param.flags() | PARAM_FLAG_ADVANCED | PARAM_FLAG_OPTIONAL)
        self.addParameter(tgt_key_param)

        self.addOutput(QgsProcessingOutputNumber(self.COMMITTED_COUNT, "Lignes validees (commit)"))
        self.addOutput(QgsProcessingOutputString(self.STATUS, "Statut"))
        self.addOutput(QgsProcessingOutputString(self.REPORT_JSON, "Bilan de publication JSON"))

    def prepareAlgorithm(self, parameters, context, feedback):
        """Resolve QGIS connection and authcfg on the main thread before worker execution."""
        self._prepared_conn_name = self.parameterAsConnectionName(parameters, self.CONNECTION, context)
        self._prepared_conn_params = None
        self._prepared_field_mapping = None
        self._prepare_error = ""
        raw_mapping = self.parameterAsString(parameters, self.FIELD_MAPPING, context)
        try:
            self._prepared_conn_params = resolve_postgres_connection_params(
                self._prepared_conn_name, self.plugin_dir,
            )
            self._prepared_field_mapping = parse_pg_field_mapping_json(raw_mapping)
        except Exception as exc:
            self._prepare_error = str(exc)
            feedback.reportError(f"transformer:publish_postgresql : {exc}")
            return False
        return True

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        conn_name = self._prepared_conn_name or self.parameterAsConnectionName(
            parameters, self.CONNECTION, context,
        )
        schema = self.parameterAsSchema(parameters, self.SCHEMA, context) or "public"
        table = self.parameterAsDatabaseTableName(parameters, self.TABLE, context)
        mode_idx = self.parameterAsEnum(parameters, self.MODE, context)
        allow_create = self.parameterAsBoolean(parameters, self.ALLOW_CREATE, context)
        geom_col = self.parameterAsString(parameters, self.GEOMETRY_COLUMN, context).strip()
        raw_mapping = self.parameterAsString(parameters, self.FIELD_MAPPING, context)
        source_key = self.parameterAsString(parameters, self.SOURCE_KEY_FIELD, context).strip()
        target_key = self.parameterAsString(parameters, self.TARGET_KEY_FIELD, context).strip()

        export_mode = self._MODE_CODES[mode_idx] if 0 <= mode_idx < len(self._MODE_CODES) else "append"

        if self._prepare_error:
            raise QgsProcessingException(
                f"transformer:publish_postgresql : {self._prepare_error}"
            )

        if self._prepared_conn_params is not None:
            conn_params = self._prepared_conn_params
            field_mapping = self._prepared_field_mapping
        else:
            try:
                conn_params = resolve_postgres_connection_params(conn_name, self.plugin_dir)
                field_mapping = parse_pg_field_mapping_json(raw_mapping)
            except Exception as exc:
                raise QgsProcessingException(
                    f"transformer:publish_postgresql : {exc}"
                ) from exc

        update_config = None
        if export_mode == "update":
            if not source_key:
                raise QgsProcessingException(
                    "transformer:publish_postgresql : SOURCE_KEY_FIELD est requis en mode update."
                )
            update_config = {
                "join_type": "attribute",
                "source_key_field": source_key,
                "target_key_field": target_key or source_key,
            }

        feedback.pushInfo(
            f"Publication PostgreSQL vers {schema}.{table} (mode={export_mode}, "
            f"connexion='{conn_name}')."
        )

        try:
            summary = publish_source_to_postgresql(
                conn_params=conn_params,
                schema=schema,
                table=table,
                source=source,
                export_mode=export_mode,
                allow_create=allow_create,
                geometry_column=geom_col or None,
                field_mapping=field_mapping,
                update_config=update_config,
                feedback=feedback,
            )
        except Exception as exc:
            raise QgsProcessingException(
                f"transformer:publish_postgresql ({schema}.{table}) : {exc}"
            ) from exc

        status = summary.get("status", "failed")
        if status == "cancelled":
            raise QgsProcessingException(
                f"transformer:publish_postgresql ({schema}.{table}) : publication annulee, transaction annulee."
            )
        if status != "success":
            detail = " ; ".join(summary.get("errors", [])) or "erreur PostgreSQL inconnue."
            raise QgsProcessingException(
                f"transformer:publish_postgresql ({schema}.{table}) : {detail}"
            )

        committed = int(summary.get("committed", 0))
        feedback.pushInfo(
            f"Publication validee : {committed} ligne(s) dans {schema}.{table}."
        )
        return {
            self.COMMITTED_COUNT: committed,
            self.STATUS: status,
            self.REPORT_JSON: json.dumps(summary, ensure_ascii=False),
        }
