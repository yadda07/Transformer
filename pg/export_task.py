# -*- coding: utf-8 -*-
"""
QgsTask wrapper for PostgreSQL export.

Runs the heavy INSERT/COPY loop off the main thread.
Uses executemany with batches for efficient network usage.
finished() runs on main thread for UI feedback.
"""

from typing import List, Optional, Dict, Any

from qgis.core import QgsMessageLog, QgsTask, QgsWkbTypes
from ..shared.compat import MsgInfo, MsgWarning, MsgCritical, TaskCanCancel

from psycopg2 import sql as pg_sql

from ..shared.logger import log_info, log_warning, log_critical
from ..shared.geom_types import get_pg_geom_type


BATCH_SIZE = 500


class PgExportTask(QgsTask):
    """Background task for PostgreSQL data export."""

    def __init__(
        self,
        conn_params: Dict[str, Any],
        jobs: List[Dict[str, Any]],
        export_mode: str = "append",
        description: str = "Export to PostgreSQL",
    ):
        """
        Args:
            conn_params: psycopg2 connection parameters (dict)
            jobs: list of resolved jobs, each with:
                - 'schema': str
                - 'table': str
                - 'layer': QgsVectorLayer (resolved on main thread)
                - 'srid': int (resolved on main thread)
            export_mode: 'append' or 'replace'
        """
        super().__init__(description, TaskCanCancel)
        self.conn_params = conn_params
        self.jobs = jobs
        self.export_mode = export_mode

        self.success_count = 0
        self.fail_count = 0
        self.errors: List[str] = []
        self.total_inserted = 0
        self._exception: Optional[Exception] = None

    def run(self) -> bool:
        """Worker thread: insert features into PostgreSQL using batched executemany.

        Thread-safety rules respected:
        - Layer references resolved on main thread before run()
        - Only layer.getFeatures() (documented thread-safe for reading)
        - No QgsProject mutations from worker
        - No UI calls
        """
        try:
            import psycopg2
        except ImportError:
            self.errors.append("psycopg2 not installed")
            return False

        total = len(self.jobs)
        for idx, job in enumerate(self.jobs):
            if self.isCanceled():
                return False

            schema = job["schema"]
            table = job["table"]
            source_layer = job["layer"]
            srid = job["srid"]

            try:
                inserted = self._export_table(
                    psycopg2, schema, table, source_layer, srid
                )
                if inserted >= 0:
                    self.success_count += 1
                    self.total_inserted += inserted
                else:
                    self.fail_count += 1
            except Exception as exc:
                self.fail_count += 1
                self.errors.append(f"{schema}.{table}: {exc}")

            self.setProgress((idx + 1) / total * 100)

        return True

    def _export_table(self, psycopg2_mod, schema, table, source_layer, srid) -> int:
        """Export one table. Returns inserted count or -1 on failure.

        For 'append' and 'replace': uses executemany with batches.
        For 'update': uses INSERT ... ON CONFLICT (key) DO UPDATE (attribute UPSERT).
        """
        conn = psycopg2_mod.connect(**self.conn_params)
        try:
            cursor = conn.cursor()

            # Ensure table exists
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, table),
            )
            table_exists = cursor.fetchone()[0] > 0

            if not table_exists:
                log_info(
                    f"PgExportTask: table {schema}.{table} missing, "
                    "auto-creating from source layer"
                )
                self._create_table(cursor, conn, schema, table, source_layer, srid)
                conn.commit()

            # Replace mode: truncate
            if self.export_mode == "replace":
                cursor.execute(
                    pg_sql.SQL("DELETE FROM {}.{}").format(
                        pg_sql.Identifier(schema), pg_sql.Identifier(table),
                    )
                )
                conn.commit()

            # Get valid fields
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "AND column_name != 'geom' ORDER BY ordinal_position",
                (schema, table),
            )
            pg_fields = [r[0] for r in cursor.fetchall()]
            source_fields = [f.name() for f in source_layer.fields()]
            valid_fields = [f for f in source_fields if f in pg_fields]

            if not valid_fields:
                self.errors.append(f"No matching fields for {schema}.{table}")
                cursor.close()
                conn.close()
                return -1

            field_list = pg_sql.SQL(", ").join(
                [pg_sql.Identifier(f) for f in valid_fields]
            )
            srid = source_layer.crs().postgisSrid()

            if self.export_mode == "update":
                return self._upsert_table(
                    cursor, conn, schema, table, source_layer, srid,
                    valid_fields, field_list,
                )

            placeholders = pg_sql.SQL(", ").join(
                [pg_sql.Placeholder()] * (len(valid_fields) + 1)
            )
            insert_sql = pg_sql.SQL(
                "INSERT INTO {}.{} ({}, geom) VALUES ({})"
            ).format(
                pg_sql.Identifier(schema), pg_sql.Identifier(table),
                field_list, placeholders,
            )

            batch: list = []
            inserted = 0

            for feat in source_layer.getFeatures():
                if self.isCanceled():
                    conn.rollback()
                    cursor.close()
                    conn.close()
                    return inserted

                geom = feat.geometry()
                if not geom or geom.isNull():
                    continue

                values = []
                for f in valid_fields:
                    val = feat[f]
                    if val is None:
                        values.append(None)
                    elif isinstance(val, (int, float, str, bool)):
                        values.append(val)
                    else:
                        try:
                            values.append(val if val else None)
                        except Exception:
                            values.append(str(val) if val else None)

                values.append(f"SRID={srid};{geom.asWkt()}")
                batch.append(tuple(values))

                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(insert_sql, batch)
                    inserted += len(batch)
                    batch.clear()

            # Flush remaining
            if batch:
                cursor.executemany(insert_sql, batch)
                inserted += len(batch)

            conn.commit()
            cursor.close()
            conn.close()
            return inserted

        except Exception as exc:
            try:
                conn.rollback()
                conn.close()
            except Exception as cleanup_exc:
                log_warning(f"PgExportTask: cleanup error after failure: {cleanup_exc}")
            self.errors.append(f"{schema}.{table}: {exc}")
            return -1

    def _upsert_table(
        self, cursor, conn, schema, table, source_layer, srid,
        valid_fields, field_list,
    ) -> int:
        """Perform attribute-based UPSERT in background thread.

        Uses INSERT ... ON CONFLICT (target_key) DO UPDATE SET ...
        Requires update_config with join_type='attribute' and
        source_key_field + target_key_field.
        """
        update_config = None
        for job in self.jobs:
            if job.get("schema") == schema and job.get("table") == table:
                update_config = job.get("update_config")
                break

        if not update_config:
            self.errors.append(
                f"UPSERT {schema}.{table}: no update_config provided"
            )
            return -1

        join_type = update_config.get("join_type", "attribute")
        if join_type != "attribute":
            self.errors.append(
                f"UPSERT {schema}.{table}: spatial join not yet supported in async mode"
            )
            return -1

        source_key = update_config.get("source_key_field", "")
        target_key = update_config.get("target_key_field", "")

        if not source_key or not target_key:
            self.errors.append(
                f"UPSERT {schema}.{table}: missing key fields "
                f"(source='{source_key}', target='{target_key}')"
            )
            return -1

        if source_key not in valid_fields:
            self.errors.append(
                f"UPSERT {schema}.{table}: source key '{source_key}' "
                "not in valid fields"
            )
            return -1

        if target_key not in valid_fields:
            self.errors.append(
                f"UPSERT {schema}.{table}: target key '{target_key}' "
                "not in valid fields"
            )
            return -1

        non_key_fields = [f for f in valid_fields if f != target_key]
        update_set = pg_sql.SQL(", ").join([
            pg_sql.SQL("{} = EXCLUDED.{}").format(
                pg_sql.Identifier(f), pg_sql.Identifier(f),
            )
            for f in non_key_fields
        ])

        placeholders = pg_sql.SQL(", ").join(
            [pg_sql.Placeholder()] * (len(valid_fields) + 1)
        )
        upsert_sql = pg_sql.SQL(
            "INSERT INTO {}.{} ({}, geom) VALUES ({}) "
            "ON CONFLICT ({}) DO UPDATE SET {}, geom = EXCLUDED.geom"
        ).format(
            pg_sql.Identifier(schema), pg_sql.Identifier(table),
            field_list, placeholders,
            pg_sql.Identifier(target_key),
            update_set,
        )

        batch: list = []
        upserted = 0

        for feat in source_layer.getFeatures():
            if self.isCanceled():
                conn.rollback()
                cursor.close()
                conn.close()
                return upserted

            geom = feat.geometry()
            if not geom or geom.isNull():
                continue

            values = []
            for f in valid_fields:
                val = feat[f]
                if val is None:
                    values.append(None)
                elif isinstance(val, (int, float, str, bool)):
                    values.append(val)
                else:
                    try:
                        values.append(val if val else None)
                    except Exception:
                        values.append(str(val) if val else None)

            values.append(f"SRID={srid};{geom.asWkt()}")
            batch.append(tuple(values))

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(upsert_sql, batch)
                upserted += len(batch)
                batch.clear()

        if batch:
            cursor.executemany(upsert_sql, batch)
            upserted += len(batch)

        conn.commit()
        cursor.close()
        conn.close()
        log_info(
            f"PgExportTask: UPSERT {schema}.{table} "
            f"upserted={upserted} key={target_key}"
        )
        return upserted

    def _create_table(self, cursor, conn, schema, table_name, source_layer, srid):
        """Create target table from source layer structure (background thread).

        Reads layer fields and geometry type, builds CREATE TABLE SQL,
        creates spatial index. Commits are left to the caller.
        """
        actual_geom_types = set()
        feature_count = 0
        for feature in source_layer.getFeatures():
            if feature_count >= 10:
                break
            if feature.hasGeometry():
                geom = feature.geometry()
                if geom and not geom.isNull():
                    actual_geom_types.add(geom.wkbType())
                    feature_count += 1

        wkb_type = source_layer.wkbType()
        detected = wkb_type

        if QgsWkbTypes.MultiLineString in actual_geom_types or QgsWkbTypes.MultiLineString25D in actual_geom_types:
            detected = QgsWkbTypes.MultiLineString
        elif QgsWkbTypes.MultiPoint in actual_geom_types or QgsWkbTypes.MultiPoint25D in actual_geom_types:
            detected = QgsWkbTypes.MultiPoint
        elif QgsWkbTypes.MultiPolygon in actual_geom_types or QgsWkbTypes.MultiPolygon25D in actual_geom_types:
            detected = QgsWkbTypes.MultiPolygon

        if detected != wkb_type:
            wkb_type = detected

        wkb_type_map = {
            QgsWkbTypes.Point: 'POINT',
            QgsWkbTypes.MultiPoint: 'MULTIPOINT',
            QgsWkbTypes.LineString: 'LINESTRING',
            QgsWkbTypes.MultiLineString: 'MULTILINESTRING',
            QgsWkbTypes.Polygon: 'POLYGON',
            QgsWkbTypes.MultiPolygon: 'MULTIPOLYGON',
            QgsWkbTypes.Point25D: 'POINTZ',
            QgsWkbTypes.MultiPoint25D: 'MULTIPOINTZ',
            QgsWkbTypes.LineString25D: 'LINESTRINGZ',
            QgsWkbTypes.MultiLineString25D: 'MULTILINESTRINGZ',
            QgsWkbTypes.Polygon25D: 'POLYGONZ',
            QgsWkbTypes.MultiPolygon25D: 'MULTIPOLYGONZ',
        }
        pg_geom_type = wkb_type_map.get(wkb_type)
        if not pg_geom_type:
            pg_geom_type = get_pg_geom_type(source_layer.geometryType())

        col_defs = [pg_sql.SQL("id SERIAL PRIMARY KEY")]

        for field in source_layer.fields():
            field_name = field.name()
            type_name = field.typeName().lower()
            if type_name in ('string', 'varchar', 'text', 'char'):
                declared_length = field.length() if field.length() > 0 else 50
                max_real_length = 0
                sample_count = 0
                for feat in source_layer.getFeatures():
                    if sample_count >= 100:
                        break
                    val = feat[field_name]
                    if val and isinstance(val, str):
                        max_real_length = max(max_real_length, len(val))
                    sample_count += 1
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

        if srid > 0:
            geom_col = pg_sql.SQL(f"geom GEOMETRY({pg_geom_type}, {srid})")
        else:
            geom_col = pg_sql.SQL(f"geom GEOMETRY({pg_geom_type})")
        col_defs.append(geom_col)

        create_sql = pg_sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} (\n{}\n)").format(
            pg_sql.Identifier(schema),
            pg_sql.Identifier(table_name),
            pg_sql.SQL(",\n").join(col_defs),
        )
        cursor.execute(create_sql)

        index_name = f"idx_{table_name}_geom"
        index_sql = pg_sql.SQL(
            "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST (geom)"
        ).format(
            pg_sql.Identifier(index_name),
            pg_sql.Identifier(schema),
            pg_sql.Identifier(table_name),
        )
        cursor.execute(index_sql)

        log_info(
            f"PgExportTask: table {schema}.{table_name} created "
            f"geom={pg_geom_type} srid={srid} fields={len(col_defs) - 2}"
        )

    def finished(self, result: bool):
        """Main thread: log results."""
        if self._exception:
            QgsMessageLog.logMessage(
                f"PgExportTask exception: {self._exception}",
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
