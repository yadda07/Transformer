# -*- coding: utf-8 -*-
"""
Non-blocking PostgreSQL connection and schema discovery tasks.

All psycopg2.connect() calls happen in run() (background thread).
finished() runs on main thread for UI feedback.

Thread-safety rules:
- No QgsProject mutations from worker
- No UI calls from worker
- Results stored as instance attributes, read in finished()
"""

from typing import Dict, List, Optional, Any, Tuple

from qgis.core import (
    QgsTask, QgsMessageLog, QgsWkbTypes, QgsVectorLayer,
)
from ..shared.compat import MsgCritical, TaskCanCancel

from ..shared.logger import log_info, log_warning, log_critical
from ..shared.geom_types import get_pg_geom_type

try:
    from psycopg2 import sql as pg_sql
except ImportError:
    pg_sql = None


_DEFAULT_TIMEOUT = 10


class PgConnectionTask(QgsTask):
    """Background task: test a PostgreSQL connection (connect + close).

    Stores ``success`` (bool) and ``message`` (str) for the
    ``finished()`` handler on the main thread.
    """

    def __init__(
        self,
        conn_params: Dict[str, Any],
        description: str = "PostgreSQL connection test",
    ):
        super().__init__(description, TaskCanCancel)
        params = dict(conn_params)
        params.setdefault("connect_timeout", _DEFAULT_TIMEOUT)
        self.conn_params = params
        self.success: bool = False
        self.message: str = ""
        self.elapsed_ms: int = 0

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.conn_params)
            conn.close()
            self.success = True
            self.message = "Connection established"
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_info(
                f"PgConnectionTask: connect OK "
                f"host={self.conn_params.get('host')} "
                f"db={self.conn_params.get('database')} "
                f"elapsed_ms={self.elapsed_ms}"
            )
            return True
        except Exception as exc:
            self.success = False
            self.message = str(exc)
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgConnectionTask: connect FAILED "
                f"host={self.conn_params.get('host')} "
                f"elapsed_ms={self.elapsed_ms} "
                f"error={self.message}"
            )
            return False

    def finished(self, result: bool) -> None:
        if not result:
            QgsMessageLog.logMessage(
                f"PostgreSQL connection test failed: {self.message}",
                "Transformer",
                MsgCritical,
            )


class PgSchemaTask(QgsTask):
    """Background task: discover PostgreSQL schemas and optionally tables.

    When ``fetch_tables_for`` is ``None``, fetches all schema names and
    also loads tables for the ``'public'`` schema (if it exists).

    When ``fetch_tables_for`` is set to a schema name, fetches only the
    tables/views for that schema (schemas list will be empty).

    Results:
        - ``schemas``: list of schema name strings
        - ``tables_by_schema``: dict {schema_name: [table_name, ...]}
        - ``error``: error message string (empty on success)
    """

    def __init__(
        self,
        conn_params: Dict[str, Any],
        fetch_tables_for: Optional[str] = None,
        description: str = "PostgreSQL schema discovery",
    ):
        super().__init__(description, TaskCanCancel)
        params = dict(conn_params)
        params.setdefault("connect_timeout", _DEFAULT_TIMEOUT)
        self.conn_params = params
        self.fetch_tables_for = fetch_tables_for
        self.schemas: List[str] = []
        self.tables_by_schema: Dict[str, List[str]] = {}
        self.error: str = ""
        self.elapsed_ms: int = 0

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        conn = None
        cursor = None
        try:
            import psycopg2

            conn = psycopg2.connect(**self.conn_params)
            cursor = conn.cursor()

            if self.fetch_tables_for is None:
                self._fetch_all_schemas(cursor)
                if "public" in self.schemas:
                    self._fetch_tables_for_schema(cursor, "public")
            else:
                self._fetch_tables_for_schema(cursor, self.fetch_tables_for)

            cursor.close()
            conn.close()
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_info(
                f"PgSchemaTask: discovery OK "
                f"schemas={len(self.schemas)} "
                f"tables_schemas={list(self.tables_by_schema.keys())} "
                f"elapsed_ms={self.elapsed_ms}"
            )
            return True
        except Exception as exc:
            self.error = str(exc)
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgSchemaTask: discovery FAILED "
                f"elapsed_ms={self.elapsed_ms} "
                f"error={self.error}"
            )
            if cursor:
                try:
                    cursor.close()
                except Exception as exc:
                    log_warning(f"PgConnectionTask: cursor close error: {exc}")
            if conn:
                try:
                    conn.close()
                except Exception as exc:
                    log_warning(f"PgConnectionTask: conn close error: {exc}")
            return False

    def _fetch_all_schemas(self, cursor) -> None:
        cursor.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
              AND schema_name NOT LIKE 'pg_temp%'
              AND schema_name NOT LIKE 'pg_toast%'
            ORDER BY schema_name
            """
        )
        self.schemas = [row[0] for row in cursor.fetchall()]

    def _fetch_tables_for_schema(self, cursor, schema: str) -> None:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        tables = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'VIEW'
            ORDER BY table_name
            """,
            (schema,),
        )
        views = [row[0] for row in cursor.fetchall()]
        if views:
            tables.extend([f"[Vue] {view}" for view in views])

        self.tables_by_schema[schema] = tables

    def finished(self, result: bool) -> None:
        if not result:
            QgsMessageLog.logMessage(
                f"PostgreSQL schema discovery failed: {self.error}",
                "Transformer",
                MsgCritical,
            )


class PgCompatibilityTask(QgsTask):
    """Background task: analyze table compatibility for a batch of mappings.

    For each mapping, performs in a single connection:
    - Table existence check
    - Table creation if missing
    - Geometry type detection and compatibility check
    - Table drop+recreate if geometry incompatible
    - CRS comparison
    - Field matching

    Results stored in ``compatibility_info`` (list of dicts matching the
    format expected by callers).  ``errors`` collects per-mapping failures.
    """

    def __init__(
        self,
        conn_params: Dict[str, Any],
        mappings: List[Dict[str, Any]],
        description: str = "PostgreSQL compatibility analysis",
    ):
        super().__init__(description, TaskCanCancel)
        params = dict(conn_params)
        params.setdefault("connect_timeout", _DEFAULT_TIMEOUT)
        self.conn_params = params
        self.mappings = mappings
        self.compatibility_info: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.elapsed_ms: int = 0

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        conn = None
        try:
            import psycopg2

            conn = psycopg2.connect(**self.conn_params)
            cursor = conn.cursor()

            for mapping in self.mappings:
                if self.isCanceled():
                    break
                info = self._analyze_one(cursor, conn, psycopg2, mapping)
                if info:
                    self.compatibility_info.append(info)
                else:
                    self.errors.append(
                        f"Compatibility failed for "
                        f"{mapping.get('schema')}.{mapping.get('table')} "
                        f"(layer: {mapping.get('layer_name')})"
                    )

            cursor.close()
            conn.close()
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_info(
                f"PgCompatibilityTask: analysis OK "
                f"compatible={len(self.compatibility_info)} "
                f"errors={len(self.errors)} "
                f"elapsed_ms={self.elapsed_ms}"
            )
            return True
        except Exception as exc:
            self.errors.append(f"PgCompatibilityTask fatal: {exc}")
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgCompatibilityTask: FAILED "
                f"elapsed_ms={self.elapsed_ms} error={exc}"
            )
            if conn:
                try:
                    conn.close()
                except Exception as exc:
                    log_warning(f"PgCompatibilityTask: conn close error: {exc}")
            return False

    def _analyze_one(
        self, cursor, conn, psycopg2_mod, mapping: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Analyze one mapping. Returns compatibility dict or None."""
        layer_name = mapping["layer_name"]
        schema = mapping["schema"]
        table = mapping["table"]
        source_layer = mapping["layer"]

        if not isinstance(source_layer, QgsVectorLayer):
            log_warning(f"PgCompatibilityTask: '{layer_name}' not a vector layer")
            return None

        table_info = {
            "layer": layer_name,
            "schema": schema,
            "table": table,
            "geometry_compatible": False,
            "crs_compatible": False,
            "geometry_info": "",
            "crs_info": "",
            "matching_fields": 0,
            "total_fields": 0,
            "field_details": [],
            "source_fields": [],
            "dest_fields": [],
            "field_matches": {},
        }

        source_geom_type = source_layer.geometryType()
        source_crs = source_layer.crs()

        target_info = self._get_table_info(cursor, schema, table)

        if not target_info:
            log_info(
                f"PgCompatibilityTask: table {schema}.{table} missing, "
                "auto-creating"
            )
            srid = source_layer.crs().postgisSrid()
            self._create_table(cursor, schema, table, source_layer, srid)
            conn.commit()
            target_info = self._get_table_info(cursor, schema, table)
            if not target_info:
                log_critical(
                    f"PgCompatibilityTask: failed to create {schema}.{table}"
                )
                return None

        target_geom_type = target_info.get("geometry_type", "")
        source_geom_name = QgsWkbTypes.geometryDisplayString(source_geom_type)
        geom_compatible = self._check_geom_compat(source_layer, target_geom_type)

        if not geom_compatible:
            log_warning(
                f"PgCompatibilityTask: geometry mismatch for {schema}.{table}: "
                f"{source_geom_name} vs {target_geom_type}, recreating"
            )
            self._drop_and_recreate(
                cursor, conn, schema, table, source_layer
            )
            target_info = self._get_table_info(cursor, schema, table)
            if target_info:
                target_geom_type = target_info.get("geometry_type", "")
                geom_compatible = True

        table_info["geometry_compatible"] = geom_compatible
        table_info["geometry_info"] = (
            f"Source: {source_geom_name}, Cible: {target_geom_type}"
        )

        target_srid = target_info.get("srid", 0)
        source_srid = source_crs.postgisSrid()
        crs_compatible = (source_srid == target_srid) or target_srid == 0
        table_info["crs_compatible"] = crs_compatible
        table_info["crs_info"] = f"Source SRID: {source_srid}, Cible SRID: {target_srid}"

        source_fields_list = [
            {"name": f.name(), "type": f.typeName()}
            for f in source_layer.fields()
        ]
        target_fields = target_info.get("fields", [])
        table_info["total_fields"] = len(source_fields_list)
        table_info["source_fields"] = source_fields_list
        table_info["dest_fields"] = target_fields

        field_matches = {}
        matching_fields = 0
        field_details = []
        for sf in source_fields_list:
            sfn = sf["name"]
            match = self._find_field_match(sfn, target_fields)
            if match:
                matching_fields += 1
                field_matches[sfn] = match["name"]
                field_details.append({
                    "source_name": sfn,
                    "compatible": True,
                    "status": f"Correspond à '{match['name']}' ({match['type']})",
                })
            else:
                field_details.append({
                    "source_name": sfn,
                    "compatible": False,
                    "status": "Aucune correspondance trouvée",
                })

        table_info["matching_fields"] = matching_fields
        table_info["field_details"] = field_details
        table_info["field_matches"] = field_matches
        return table_info

    def _get_table_info(self, cursor, schema, table):
        """Fetch table info from PostgreSQL (background thread)."""
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        if cursor.fetchone()[0] == 0:
            return None

        cursor.execute(
            "SELECT f_geometry_column, type, srid "
            "FROM geometry_columns "
            "WHERE f_table_schema = %s AND f_table_name = %s",
            (schema, table),
        )
        geom_info = cursor.fetchone()

        geom_column = None
        geom_type = "Unknown"
        srid = 0

        if not geom_info:
            cursor.execute(
                "SELECT column_name, udt_name "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "AND udt_name = 'geometry'",
                (schema, table),
            )
            geom_columns = cursor.fetchall()
            if geom_columns:
                geom_column = geom_columns[0][0]
                try:
                    cursor.execute(
                        f'SELECT ST_GeometryType("{geom_column}"), '
                        f'ST_SRID("{geom_column}") '
                        f'FROM "{schema}"."{table}" '
                        f'WHERE "{geom_column}" IS NOT NULL LIMIT 1'
                    )
                    postgis_result = cursor.fetchone()
                    if postgis_result:
                        st_geom_type = postgis_result[0]
                        if st_geom_type:
                            geom_type = st_geom_type.replace("ST_", "").upper()
                        srid = postgis_result[1] or 0
                except Exception as exc:
                    log_warning(
                        f"PgCompatibilityTask: PostGIS query failed "
                        f"for {schema}.{table}: {exc}"
                    )
        else:
            geom_column = geom_info[0]
            geom_type = geom_info[1]
            srid = geom_info[2]

        cursor.execute(
            "SELECT column_name, data_type, is_nullable, "
            "character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "AND column_name != %s ORDER BY ordinal_position",
            (schema, table, geom_column or "geom"),
        )
        fields_info = cursor.fetchall()

        return {
            "geometry_column": geom_column,
            "geometry_type": geom_type,
            "srid": srid,
            "fields": [
                {
                    "name": f[0],
                    "type": f[1],
                    "nullable": f[2] == "YES",
                    "length": f[3],
                }
                for f in fields_info
                if f[0] not in ("id", "gid")
            ],
        }

    def _check_geom_compat(self, source_layer, target_geom_type):
        """Check geometry compatibility (background thread, pure computation)."""
        wkb_type = source_layer.wkbType()
        wkb_type_map = {
            QgsWkbTypes.Point: "POINT",
            QgsWkbTypes.MultiPoint: "MULTIPOINT",
            QgsWkbTypes.LineString: "LINESTRING",
            QgsWkbTypes.MultiLineString: "MULTILINESTRING",
            QgsWkbTypes.Polygon: "POLYGON",
            QgsWkbTypes.MultiPolygon: "MULTIPOLYGON",
            QgsWkbTypes.Point25D: "POINTZ",
            QgsWkbTypes.MultiPoint25D: "MULTIPOINTZ",
            QgsWkbTypes.LineString25D: "LINESTRINGZ",
            QgsWkbTypes.MultiLineString25D: "MULTILINESTRINGZ",
            QgsWkbTypes.Polygon25D: "POLYGONZ",
            QgsWkbTypes.MultiPolygon25D: "MULTIPOLYGONZ",
        }
        expected = wkb_type_map.get(wkb_type)
        if not expected:
            expected = get_pg_geom_type(source_layer.geometryType())
        return expected.upper() == target_geom_type.upper()

    def _create_table(self, cursor, schema, table_name, source_layer, srid):
        """Create table from source layer structure (background thread)."""
        actual_geom_types = set()
        feature_count = 0
        for feat in source_layer.getFeatures():
            if feature_count >= 10:
                break
            if feat.hasGeometry():
                geom = feat.geometry()
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
            QgsWkbTypes.Point: "POINT",
            QgsWkbTypes.MultiPoint: "MULTIPOINT",
            QgsWkbTypes.LineString: "LINESTRING",
            QgsWkbTypes.MultiLineString: "MULTILINESTRING",
            QgsWkbTypes.Polygon: "POLYGON",
            QgsWkbTypes.MultiPolygon: "MULTIPOLYGON",
            QgsWkbTypes.Point25D: "POINTZ",
            QgsWkbTypes.MultiPoint25D: "MULTIPOINTZ",
            QgsWkbTypes.LineString25D: "LINESTRINGZ",
            QgsWkbTypes.MultiLineString25D: "MULTILINESTRINGZ",
            QgsWkbTypes.Polygon25D: "POLYGONZ",
            QgsWkbTypes.MultiPolygon25D: "MULTIPOLYGONZ",
        }
        pg_geom_type = wkb_type_map.get(wkb_type)
        if not pg_geom_type:
            pg_geom_type = get_pg_geom_type(source_layer.geometryType())

        col_defs = [pg_sql.SQL("id SERIAL PRIMARY KEY")]

        for field in source_layer.fields():
            fn = field.name()
            tn = field.typeName().lower()
            if tn in ("string", "varchar", "text", "char"):
                dl = field.length() if field.length() > 0 else 50
                mrl = 0
                sc = 0
                for feat in source_layer.getFeatures():
                    if sc >= 100:
                        break
                    val = feat[fn]
                    if val and isinstance(val, str):
                        mrl = max(mrl, len(val))
                    sc += 1
                ol = max(dl, mrl, 50)
                if mrl > dl * 2 and mrl > 100:
                    pg_type = "TEXT"
                else:
                    pg_type = f"VARCHAR({ol})"
            elif tn in ("integer", "int", "int4", "int2"):
                pg_type = "INTEGER"
            elif tn in ("integer64", "int8", "longlong"):
                pg_type = "BIGINT"
            elif tn in ("real", "double", "float", "numeric"):
                pg_type = "DOUBLE PRECISION"
            elif tn == "date":
                pg_type = "DATE"
            elif tn in ("datetime", "timestamp"):
                pg_type = "TIMESTAMP"
            elif tn in ("bool", "boolean"):
                pg_type = "BOOLEAN"
            else:
                pg_type = "TEXT"
            col_defs.append(
                pg_sql.SQL("{} " + pg_type).format(pg_sql.Identifier(fn))
            )

        if srid > 0:
            geom_col = pg_sql.SQL(f"geom GEOMETRY({pg_geom_type}, {srid})")
        else:
            geom_col = pg_sql.SQL(f"geom GEOMETRY({pg_geom_type})")
        col_defs.append(geom_col)

        create_sql = pg_sql.SQL(
            "CREATE TABLE IF NOT EXISTS {}.{} (\n{}\n)"
        ).format(
            pg_sql.Identifier(schema),
            pg_sql.Identifier(table_name),
            pg_sql.SQL(",\n").join(col_defs),
        )

        cursor.execute(create_sql)
        index_name = f"idx_{table_name}_geom"
        cursor.execute(
            pg_sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST (geom)"
            ).format(
                pg_sql.Identifier(index_name),
                pg_sql.Identifier(schema),
                pg_sql.Identifier(table_name),
            )
        )
        log_info(
            f"PgCompatibilityTask: created {schema}.{table_name} "
            f"geom={pg_geom_type} srid={srid} fields={len(col_defs) - 2}"
        )

    def _drop_and_recreate(self, cursor, conn, schema, table_name, source_layer):
        """Drop and recreate table (background thread)."""
        cursor.execute(
            pg_sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                pg_sql.Identifier(schema), pg_sql.Identifier(table_name),
            )
        )
        conn.commit()
        srid = source_layer.crs().postgisSrid()
        self._create_table(cursor, schema, table_name, source_layer, srid)
        conn.commit()

    def _find_field_match(self, source_field_name, target_fields):
        """Find a field match (pure computation)."""
        source_lower = source_field_name.lower()
        for tf in target_fields:
            if tf["name"].lower() == source_lower:
                return tf
        for tf in target_fields:
            if source_lower in tf["name"].lower() or tf["name"].lower() in source_lower:
                return tf
        return None

    def finished(self, result: bool) -> None:
        if not result and not self.compatibility_info:
            QgsMessageLog.logMessage(
                f"PostgreSQL compatibility analysis failed: {self.errors}",
                "Transformer",
                MsgCritical,
            )
