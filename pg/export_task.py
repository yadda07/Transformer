# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
QgsTask wrapper for PostgreSQL export.

Runs the heavy INSERT/COPY loop off the main thread.
Uses executemany with batches for efficient network usage.
finished() runs on main thread for UI feedback.
"""

from typing import List, Optional, Dict, Any

from qgis.core import QgsMessageLog, QgsTask, QgsWkbTypes, QgsVectorLayer
from ..shared.compat import MsgInfo, MsgWarning, MsgCritical, TaskCanCancel

try:
    from psycopg2 import sql as pg_sql
except ImportError:
    pg_sql = None

from ..shared.logger import log_info, log_warning
from ..shared.geom_types import get_pg_geom_type, normalize_pg_geom_type
from .connection_task import PgConnectionPoolManager, PgLayerSnapshot  # noqa: F401


BATCH_SIZE = 500


class _ExportCancelled(Exception):
    """Abort the current transaction without reporting committed rows."""


class _ProcessingSourcePgAdapter:
    """Adapt QgsProcessingFeatureSource to the layer interface expected by PgExportTask."""

    def __init__(self, source):
        self._source = source

    def fields(self):
        return self._source.fields()

    def getFeatures(self, *args, **kwargs):
        return self._source.getFeatures(*args, **kwargs)

    def crs(self):
        return self._source.sourceCrs() if hasattr(self._source, "sourceCrs") else self._source.crs()

    def wkbType(self):
        return self._source.wkbType()

    def geometryType(self):
        return QgsWkbTypes.geometryType(self._source.wkbType())

    def isSpatial(self):
        return QgsWkbTypes.flatType(self._source.wkbType()) not in (
            QgsWkbTypes.Type.NoGeometry,
            QgsWkbTypes.Type.Unknown,
        )

    def featureCount(self):
        return self._source.featureCount()


class PgExportTask(QgsTask):
    """Background task for PostgreSQL data export."""

    def __init__(
        self,
        conn_params: Dict[str, Any],
        jobs: List[Dict[str, Any]],
        export_mode: str = "append",
        description: str = "Export to PostgreSQL",
        cancel_callback=None,
        progress_callback=None,
    ):
        """
        Args:
            conn_params: psycopg2 connection parameters (dict)
            jobs: list of resolved jobs, each with:
                - 'schema': str
                - 'table': str
                - 'layer': QgsVectorLayer or QgsProcessingFeatureSource
                - 'srid': int
            export_mode: 'append', 'replace', or 'update'
        """
        super().__init__(description, TaskCanCancel)
        self.conn_params = conn_params
        self._cancel_callback = cancel_callback
        self._progress_callback = progress_callback
        snapshot_cls = globals().get("PgLayerSnapshot")
        dependent_layers = []
        safe_jobs = []
        for item in jobs:
            entry = dict(item)
            layer = entry.get("layer")
            if layer is not None and isinstance(layer, QgsVectorLayer) and hasattr(layer, "dataProvider"):
                if hasattr(self, "setDependentLayers"):
                    dependent_layers.append(layer)
                if snapshot_cls is not None:
                    entry["layer"] = snapshot_cls(layer)
            elif layer is not None and hasattr(layer, "sourceCrs") and not hasattr(layer, "crs"):
                entry["layer"] = _ProcessingSourcePgAdapter(layer)
            safe_jobs.append(entry)
        if dependent_layers and hasattr(self, "setDependentLayers"):
            self.setDependentLayers(dependent_layers)
        self.jobs = safe_jobs
        self.export_mode = export_mode
        self._conn_lock = __import__("threading").Lock()
        self._active_conn = None

        self.success_count = 0
        self.fail_count = 0
        self.errors: List[str] = []
        self.total_inserted = 0
        self._exception: Optional[Exception] = None
        self.status = "pending"
        self.result_summary = {}
        self.table_results = []

    def _is_canceled(self) -> bool:
        if self.isCanceled():
            return True
        if self._cancel_callback is not None and self._cancel_callback():
            return True
        return False

    def _report_progress(self, value: float) -> None:
        self.setProgress(value)
        if self._progress_callback is not None:
            self._progress_callback(value)

    def cancel(self) -> None:
        with self._conn_lock:
            conn = getattr(self, "_active_conn", None)
        if conn is not None and hasattr(conn, "cancel"):
            try:
                conn.cancel()
            except Exception as exc:
                log_warning(f"PgExportTask: conn.cancel() warning: {exc}")
        if hasattr(super(), "cancel"):
            super().cancel()
        else:
            self.cancelled = True

    def run(self) -> bool:
        """Publish jobs, counting only committed transactions."""
        self.status = "running"
        self.table_results = []
        try:
            import psycopg2
            if not self.jobs:
                raise ValueError("Aucune table à publier.")
            destinations = [(job["schema"], job["table"]) for job in self.jobs]
            if len(set(destinations)) != len(destinations):
                raise ValueError("Plusieurs traitements visent la même table : publiez-les séparément.")
            total_jobs = len(self.jobs)
            for index, job in enumerate(self.jobs):
                if self._is_canceled():
                    self.status = "cancelled"
                    break
                inserted = self._export_table(
                    psycopg2, job["schema"], job["table"], job["layer"],
                    job.get("srid", 0), job=job, job_index=index, total_jobs=total_jobs,
                )
                if inserted == -2:
                    self.status = "cancelled"
                    self.table_results.append({
                        "schema": job["schema"], "table": job["table"],
                        "status": "cancelled", "committed": 0,
                    })
                    break
                if inserted >= 0:
                    self.success_count += 1
                    self.total_inserted += inserted
                else:
                    self.fail_count += 1
                self.table_results.append({
                    "schema": job["schema"], "table": job["table"],
                    "status": "success" if inserted >= 0 else "failed",
                    "committed": max(0, inserted),
                })
                self._report_progress((index + 1) / len(self.jobs) * 100)
            if self.status != "cancelled":
                self.status = (
                    "partial" if self.success_count and self.fail_count
                    else "failed" if self.fail_count else "success"
                )
        except Exception as exc:
            self.status = "failed"
            self._exception = exc
            self.errors.append(f"Publication impossible : {self._error_text(exc)}")
        self.result_summary = {
            "status": self.status, "committed": self.total_inserted,
            "success_count": self.success_count, "fail_count": self.fail_count,
            "tables": self.table_results, "errors": list(self.errors),
        }
        return self.status in ("success", "partial")

    def _export_table(
        self,
        psycopg2_mod,
        schema,
        table,
        source_layer,
        srid,
        job=None,
        job_index: int = 0,
        total_jobs: int = 1,
    ) -> int:
        """One atomic transaction; -2 means cancelled, -1 means failed."""
        if job is None:
            matches = [entry for entry in self.jobs
                       if entry.get("schema") == schema and entry.get("table") == table]
            if len(matches) != 1:
                self.errors.append(f"{schema}.{table} : traitement absent ou ambigu.")
                return -1
            job = matches[0]
        conn = None
        pool_inst = None
        cursor = None
        failed = False
        try:
            if self._is_canceled():
                return -2
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                conn, pool_inst = pool_mgr.acquire(self.conn_params, psycopg2_mod)
            else:
                conn = psycopg2_mod.connect(**self.conn_params)
            with self._conn_lock:
                if self._is_canceled():
                    return -2
                self._active_conn = conn
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s", (schema, table),
            )
            if not cursor.fetchone()[0]:
                if not job.get("allow_create", False):
                    raise ValueError("La création de cette table n'a pas été confirmée.")
                self._create_table(
                    cursor, conn, schema, table, source_layer, srid,
                    geometry_column=job.get("geometry_column") or "geom",
                )

            cursor.execute(
                "SELECT column_name, data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, table),
            )
            columns = cursor.fetchall()
            geometry_columns = [row[0] for row in columns if row[2] == "geometry"]
            geometry_column = job.get("geometry_column")
            if geometry_column is None and len(geometry_columns) == 1:
                geometry_column = geometry_columns[0]
            if geometry_column is not None and geometry_column not in geometry_columns:
                raise ValueError("La colonne géométrique confirmée n'existe plus.")
            if len(geometry_columns) > 1 and not geometry_column:
                raise ValueError("Plusieurs colonnes géométriques : précisez la colonne cible.")
            target_fields = {row[0] for row in columns if row[2] != "geometry"}
            mapping = self._validated_mapping(job, source_layer, target_fields)
            source_srid = source_layer.crs().postgisSrid()
            target_srid = job.get("target_srid", source_srid)
            if geometry_column:
                if source_srid <= 0:
                    raise ValueError("SCR source inconnu : définissez-le avant publication.")
                if target_srid and target_srid != source_srid:
                    raise ValueError("SCR incompatibles : reprojetez la source avant publication.")
            elif source_layer.isSpatial():
                raise ValueError("La cible n'a pas de géométrie : choisissez une table spatiale.")

            names = [entry["target"] for entry in mapping]
            placeholders = [
                pg_sql.SQL("CAST(%s AS " + entry["type"] + ")") if entry["type"]
                else pg_sql.Placeholder()
                for entry in mapping
            ]
            if geometry_column:
                names.append(geometry_column)
                placeholders.append(pg_sql.Placeholder())
            statement = pg_sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                pg_sql.Identifier(schema), pg_sql.Identifier(table),
                pg_sql.SQL(", ").join(pg_sql.Identifier(name) for name in names),
                pg_sql.SQL(", ").join(placeholders),
            )
            conflict = None
            if self.export_mode == "update":
                update = job.get("update_config") or {}
                if update.get("join_type", "attribute") != "attribute":
                    raise ValueError("La mise à jour spatiale n'est pas disponible. Choisissez une clé attributaire.")
                source_key = update.get("source_key_field")
                target_key = update.get("target_key_field")
                if not any(entry["source"] == source_key and entry["target"] == target_key
                           for entry in mapping):
                    raise ValueError("La clé source doit être mappée explicitement vers la clé cible.")
                updates = [name for name in names if name != target_key]
                conflict = pg_sql.SQL(" ON CONFLICT ({}) ").format(pg_sql.Identifier(target_key))
                if updates:
                    conflict += pg_sql.SQL("DO UPDATE SET ") + pg_sql.SQL(", ").join(
                        pg_sql.SQL("{} = EXCLUDED.{}").format(
                            pg_sql.Identifier(name), pg_sql.Identifier(name),
                        ) for name in updates
                    )
                else:
                    conflict += pg_sql.SQL("DO NOTHING")
                statement += conflict
            elif self.export_mode not in ("append", "replace"):
                raise ValueError("Mode de publication inconnu.")

            if self._is_canceled():
                raise _ExportCancelled()
            # Validation is complete. DELETE and INSERT share the same commit.
            if self.export_mode == "replace":
                cursor.execute(pg_sql.SQL("DELETE FROM {}.{}").format(
                    pg_sql.Identifier(schema), pg_sql.Identifier(table),
                ))

            source_fields = source_layer.fields()
            src_indices = (
                [source_fields.indexFromName(entry["source"]) for entry in mapping]
                if hasattr(source_fields, "indexFromName")
                else []
            )
            use_idx = bool(src_indices) and all(idx >= 0 for idx in src_indices)
            source_access = src_indices if use_idx else [entry["source"] for entry in mapping]

            execute_values = None
            pg_binary = None
            if type(cursor).__module__.startswith("psycopg2"):
                extras_mod = getattr(psycopg2_mod, "extras", None)
                if extras_mod is None:
                    try:
                        from psycopg2 import extras as extras_mod
                    except ImportError:
                        extras_mod = None
                execute_values = getattr(extras_mod, "execute_values", None)
                pg_binary = getattr(psycopg2_mod, "Binary", None)

            use_wkb_ev = bool(execute_values is not None and (not geometry_column or pg_binary is not None))
            ev_statement = None
            ev_template = None
            if use_wkb_ev:
                ev_sql = pg_sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                    pg_sql.Identifier(schema), pg_sql.Identifier(table),
                    pg_sql.SQL(", ").join(pg_sql.Identifier(name) for name in names),
                )
                if conflict is not None:
                    ev_sql += conflict
                ev_placeholders = [
                    f"CAST(%s AS {entry['type']})" if entry["type"] else "%s"
                    for entry in mapping
                ]
                if geometry_column:
                    ev_placeholders.append(f"ST_SetSRID(ST_GeomFromWKB(%s), {int(source_srid)})")
                ev_template = "(" + ", ".join(ev_placeholders) + ")"
                ev_statement = ev_sql.as_string(cursor) if hasattr(ev_sql, "as_string") else str(ev_sql)

            features_iter = None
            try:
                from qgis.core import QgsFeatureRequest, Qgis
                req = QgsFeatureRequest()
                if use_idx:
                    req.setSubsetOfAttributes(sorted(set(src_indices)))
                if not geometry_column:
                    req_flag = getattr(getattr(Qgis, "FeatureRequestFlag", None), "NoGeometry", None)
                    if req_flag is None:
                        req_flag = getattr(getattr(QgsFeatureRequest, "Flag", QgsFeatureRequest), "NoGeometry", None)
                    if req_flag is not None:
                        req.setFlags(req_flag)
                features_iter = source_layer.getFeatures(req)
            except (ImportError, TypeError, AttributeError):
                features_iter = None
            if features_iter is None:
                features_iter = source_layer.getFeatures()

            total_features = source_layer.featureCount() if hasattr(source_layer, "featureCount") else -1
            batch = []
            inserted = 0
            processed = 0

            def _flush():
                nonlocal inserted, processed
                if not batch:
                    return
                if use_wkb_ev:
                    execute_values(cursor, ev_statement, batch, template=ev_template, page_size=len(batch))
                else:
                    cursor.executemany(statement, batch)
                if cursor.rowcount < 0:
                    raise ValueError("Le nombre d'écritures n'a pas été confirmé par PostgreSQL.")
                inserted += cursor.rowcount
                processed += len(batch)
                batch.clear()
                if total_jobs > 0 and total_features > 0:
                    frac = min(1.0, processed / total_features)
                    self._report_progress((job_index + frac) / total_jobs * 100.0)

            for feature in features_iter:
                if self._is_canceled():
                    raise _ExportCancelled()
                values = [self._python_value(feature[key]) for key in source_access]
                if geometry_column:
                    geometry = feature.geometry()
                    if geometry and not geometry.isNull():
                        if use_wkb_ev:
                            values.append(pg_binary(bytes(geometry.asWkb())))
                        else:
                            values.append(f"SRID={source_srid};{geometry.asWkt()}")
                    else:
                        values.append(None)
                batch.append(tuple(values))
                if len(batch) >= BATCH_SIZE:
                    _flush()
            if self._is_canceled():
                raise _ExportCancelled()
            if batch:
                _flush()
            if self._is_canceled():
                raise _ExportCancelled()
            conn.commit()
            return inserted
        except _ExportCancelled:
            if conn:
                try:
                    conn.rollback()
                except Exception as rb_exc:
                    failed = True
                    log_warning(
                        f"PgExportTask: rollback on cancel failed for {schema}.{table}: "
                        f"{self._error_text(rb_exc)}"
                    )
            return -2
        except Exception as exc:
            failed = True
            if conn:
                try:
                    conn.rollback()
                except Exception as rb_exc:
                    log_warning(
                        f"PgExportTask: rollback on error failed for {schema}.{table}: "
                        f"{self._error_text(rb_exc)}"
                    )
            self.errors.append(f"{schema}.{table} : publication annulée, aucune écriture validée ({self._error_text(exc)}).")
            return -1
        finally:
            with self._conn_lock:
                self._active_conn = None
            if cursor:
                try:
                    cursor.close()
                except Exception as exc:
                    log_warning(f"PgExportTask: cursor close error: {self._error_text(exc)}")
            if conn:
                pool_mgr = globals().get("PgConnectionPoolManager")
                if pool_mgr is not None:
                    pool_mgr.release(conn, pool_inst, discard=failed)
                else:
                    try:
                        conn.close()
                    except Exception as exc:
                        log_warning(f"PgExportTask: conn close error: {self._error_text(exc)}")

    def _validated_mapping(self, job, source_layer, target_fields):
        """Resolve a confirmed mapping without silently dropping bad entries."""
        source_fields = {field.name() for field in source_layer.fields()}
        provided = job.get("field_mapping")
        if provided is None:
            provided = [{"source": name, "target": name} for name in sorted(source_fields & target_fields)]
        elif isinstance(provided, dict):
            provided = [{"source": source, "target": target} for source, target in provided.items()]
        if not isinstance(provided, list) or not provided:
            raise ValueError("Aucune correspondance de champs confirmée.")
        allowed_types = {
            "", "character varying", "text", "integer", "bigint", "double precision",
            "real", "boolean", "date", "timestamp", "uuid",
        }
        resolved = []
        seen_sources = set()
        seen_targets = set()
        forced_types = job.get("forced_types") or {}
        for entry in provided:
            source = entry.get("source", "")
            target = entry.get("target", "")
            conversion = str(entry.get("type") or forced_types.get(source) or "").lower()
            if conversion == "<auto>":
                conversion = ""
            if source not in source_fields or target not in target_fields:
                raise ValueError(f"Correspondance indisponible : {source} vers {target}.")
            if source in seen_sources or target in seen_targets:
                raise ValueError(f"Correspondance ambiguë : {source} vers {target}.")
            if conversion not in allowed_types:
                raise ValueError(f"Conversion non prise en charge : {conversion}.")
            seen_sources.add(source)
            seen_targets.add(target)
            resolved.append({"source": source, "target": target, "type": conversion})
        return resolved

    def _error_text(self, error):
        message = str(error)
        password = self.conn_params.get("password")
        if password:
            message = message.replace(str(password), "[secret masqué]")
        return message

    @staticmethod
    def _python_value(value):
        """Adapt Qt values without replacing false, zero or empty strings by NULL."""
        if value is None or (hasattr(value, "isNull") and value.isNull()):
            return None
        for method in ("toPyDateTime", "toPyDate", "toPyTime"):
            if hasattr(value, method):
                return getattr(value, method)()
        return value

    def _create_table(self, cursor, conn, schema, table_name, source_layer, srid, geometry_column="geom"):
        """Create target table from source layer structure (background thread).

        Reads layer fields and geometry type in a single bounded sample pass,
        builds CREATE TABLE SQL, creates spatial index. Commits are left to caller.
        """
        actual_geom_types = set()
        geom_count = 0
        string_field_names = [
            f.name() for f in source_layer.fields()
            if f.typeName().lower() in ('string', 'varchar', 'text', 'char')
        ]
        max_real_lengths = {name: 0 for name in string_field_names}

        sample_iter = None
        try:
            from qgis.core import QgsFeatureRequest
            sample_iter = source_layer.getFeatures(QgsFeatureRequest().setLimit(100))
        except (ImportError, TypeError, AttributeError):
            sample_iter = None
        if sample_iter is None:
            sample_iter = source_layer.getFeatures()

        for sample_idx, feature in enumerate(sample_iter):
            if sample_idx >= 100:
                break
            if geom_count < 10 and hasattr(feature, "hasGeometry") and feature.hasGeometry():
                geom = feature.geometry()
                if geom and not geom.isNull():
                    actual_geom_types.add(geom.wkbType())
                    geom_count += 1
            if string_field_names:
                for field_name in string_field_names:
                    val = feature[field_name]
                    if val and isinstance(val, str):
                        if len(val) > max_real_lengths[field_name]:
                            max_real_lengths[field_name] = len(val)

        wkb_type = source_layer.wkbType()
        detected = wkb_type

        if (
            QgsWkbTypes.Type.MultiLineString in actual_geom_types
            or QgsWkbTypes.Type.MultiLineString25D in actual_geom_types
        ):
            detected = QgsWkbTypes.Type.MultiLineString
        elif (
            QgsWkbTypes.Type.MultiPoint in actual_geom_types
            or QgsWkbTypes.Type.MultiPoint25D in actual_geom_types
        ):
            detected = QgsWkbTypes.Type.MultiPoint
        elif (
            QgsWkbTypes.Type.MultiPolygon in actual_geom_types
            or QgsWkbTypes.Type.MultiPolygon25D in actual_geom_types
        ):
            detected = QgsWkbTypes.Type.MultiPolygon

        if detected != wkb_type:
            wkb_type = detected

        wkb_type_map = {
            QgsWkbTypes.Type.Point: 'POINT',
            QgsWkbTypes.Type.MultiPoint: 'MULTIPOINT',
            QgsWkbTypes.Type.LineString: 'LINESTRING',
            QgsWkbTypes.Type.MultiLineString: 'MULTILINESTRING',
            QgsWkbTypes.Type.Polygon: 'POLYGON',
            QgsWkbTypes.Type.MultiPolygon: 'MULTIPOLYGON',
            QgsWkbTypes.Type.Point25D: 'POINTZ',
            QgsWkbTypes.Type.MultiPoint25D: 'MULTIPOINTZ',
            QgsWkbTypes.Type.LineString25D: 'LINESTRINGZ',
            QgsWkbTypes.Type.MultiLineString25D: 'MULTILINESTRINGZ',
            QgsWkbTypes.Type.Polygon25D: 'POLYGONZ',
            QgsWkbTypes.Type.MultiPolygon25D: 'MULTIPOLYGONZ',
        }
        pg_geom_type = wkb_type_map.get(wkb_type)
        if not pg_geom_type:
            pg_geom_type = get_pg_geom_type(source_layer.geometryType())

        source_names = {field.name() for field in source_layer.fields()}
        col_defs = [] if "id" in source_names else [pg_sql.SQL("id SERIAL PRIMARY KEY")]

        for field in source_layer.fields():
            field_name = field.name()
            type_name = field.typeName().lower()
            if type_name in ('string', 'varchar', 'text', 'char'):
                declared_length = field.length() if hasattr(field, "length") and field.length() > 0 else 50
                max_real_length = max_real_lengths.get(field_name, 0)
                optimal_length = max(declared_length, max_real_length, 50)
                if max_real_length > declared_length * 2 and max_real_length > 100:
                    pg_type = 'TEXT'
                else:
                    pg_type = f'VARCHAR({optimal_length})'
            elif type_name in ('integer', 'int', 'int4', 'int2'):
                pg_type = 'INTEGER'
            elif type_name in ('integer64', 'int8', 'longlong'):
                pg_type = 'BIGINT'
            elif type_name in ('real', 'double', 'float', 'numeric'):
                pg_type = 'DOUBLE PRECISION'
            elif type_name == 'date':
                pg_type = 'DATE'
            elif type_name in ('datetime', 'timestamp'):
                pg_type = 'TIMESTAMP'
            elif type_name in ('bool', 'boolean'):
                pg_type = 'BOOLEAN'
            else:
                pg_type = 'TEXT'
            col_defs.append(
                pg_sql.SQL("{} " + pg_type).format(pg_sql.Identifier(field_name))
            )

        is_spatial = bool(source_layer.isSpatial()) if hasattr(source_layer, "isSpatial") else True
        geom_col_name = geometry_column or "geom"
        if is_spatial:
            pg_geom_type = normalize_pg_geom_type(pg_geom_type)
            if srid > 0:
                geom_col = pg_sql.SQL("{} GEOMETRY({}, {})").format(
                    pg_sql.Identifier(geom_col_name),
                    pg_sql.SQL(pg_geom_type),
                    pg_sql.Literal(srid),
                )
            else:
                geom_col = pg_sql.SQL("{} GEOMETRY({})").format(
                    pg_sql.Identifier(geom_col_name),
                    pg_sql.SQL(pg_geom_type),
                )
            col_defs.append(geom_col)

        create_sql = pg_sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} (\n{}\n)").format(
            pg_sql.Identifier(schema),
            pg_sql.Identifier(table_name),
            pg_sql.SQL(",\n").join(col_defs),
        )
        cursor.execute(create_sql)

        if is_spatial:
            index_name = f"idx_{table_name}_{geom_col_name}"
            index_sql = pg_sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST ({})"
            ).format(
                pg_sql.Identifier(index_name),
                pg_sql.Identifier(schema),
                pg_sql.Identifier(table_name),
                pg_sql.Identifier(geom_col_name),
            )
            cursor.execute(index_sql)

        log_info(
            f"PgExportTask: table {schema}.{table_name} created "
            f"geom={pg_geom_type if is_spatial else 'NONE'} srid={srid} fields={len(col_defs)}"
        )

    def finished(self, result: bool):
        """Main thread: log results."""
        if self._exception:
            QgsMessageLog.logMessage(
                f"Publication impossible : {self._error_text(self._exception)}",
                "Transformer",
                MsgCritical,
            )
            return

        if not result:
            QgsMessageLog.logMessage(
                "PgExportTask canceled or failed",
                "Transformer",
                MsgWarning,
            )
            return

        QgsMessageLog.logMessage(
            f"PgExportTask done: {self.success_count} tables, "
            f"{self.total_inserted} records inserted, "
            f"{self.fail_count} errors",
            "Transformer",
            MsgInfo,
        )


def publish_source_to_postgresql(
    conn_params: Dict[str, Any],
    schema: str,
    table: str,
    source,
    export_mode: str = "append",
    allow_create: bool = False,
    geometry_column: Optional[str] = None,
    field_mapping=None,
    forced_types: Optional[Dict[str, str]] = None,
    update_config: Optional[Dict[str, Any]] = None,
    target_srid: Optional[int] = None,
    cancel_callback=None,
    progress_callback=None,
    feedback=None,
) -> Dict[str, Any]:
    """Run one transactional PostgreSQL publication synchronously (Processing / API)."""
    clean_schema = (schema or "").strip() or "public"
    clean_table = (table or "").strip()
    if not clean_table:
        raise ValueError("pg.export_task: nom de table PostgreSQL cible requis.")

    adapted = (
        _ProcessingSourcePgAdapter(source)
        if hasattr(source, "sourceCrs") and not hasattr(source, "crs")
        else source
    )
    source_crs = adapted.crs() if hasattr(adapted, "crs") else None
    srid = source_crs.postgisSrid() if source_crs is not None and hasattr(source_crs, "postgisSrid") else 0
    job = {
        "schema": clean_schema,
        "table": clean_table,
        "layer": adapted,
        "srid": srid,
        "allow_create": bool(allow_create),
    }
    if geometry_column:
        job["geometry_column"] = geometry_column.strip()
    if field_mapping is not None:
        job["field_mapping"] = field_mapping
    if forced_types:
        job["forced_types"] = dict(forced_types)
    if update_config:
        job["update_config"] = dict(update_config)
    if target_srid is not None:
        job["target_srid"] = int(target_srid)

    effective_cancel = cancel_callback
    if effective_cancel is None and feedback is not None and hasattr(feedback, "isCanceled"):
        effective_cancel = feedback.isCanceled

    effective_progress = progress_callback
    if effective_progress is None and feedback is not None and hasattr(feedback, "setProgress"):
        def _set_progress(value):
            feedback.setProgress(int(value))

        effective_progress = _set_progress

    task = PgExportTask(
        conn_params=conn_params,
        jobs=[job],
        export_mode=export_mode,
        description=f"Publish {clean_schema}.{clean_table}",
        cancel_callback=effective_cancel,
        progress_callback=effective_progress,
    )
    cancel_signal = getattr(feedback, "canceled", None) if feedback is not None else None
    connected_signal = False
    if cancel_signal is not None and hasattr(cancel_signal, "connect"):
        try:
            cancel_signal.connect(task.cancel)
            connected_signal = True
        except (TypeError, RuntimeError):
            connected_signal = False
    try:
        task.run()
    finally:
        if connected_signal:
            try:
                cancel_signal.disconnect(task.cancel)
            except (TypeError, RuntimeError):
                pass
    return dict(task.result_summary)
