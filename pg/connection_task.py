# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Non-blocking PostgreSQL connection and schema discovery tasks.

All psycopg2.connect() calls happen in run() (background thread).
finished() runs on main thread for UI feedback.

Thread-safety rules:
- No QgsProject mutations from worker
- No UI calls from worker
- Results stored as instance attributes, read in finished()
"""

from typing import Dict, List, Optional, Any
import hashlib
import threading

from qgis.core import (
    QgsTask, QgsMessageLog, QgsWkbTypes, QgsVectorLayer, QgsVectorLayerFeatureSource,
)
from ..shared.compat import MsgCritical, TaskCanCancel

from ..shared.logger import log_info, log_warning, log_critical
from ..shared.geom_types import get_pg_geom_type

try:
    from psycopg2 import sql as pg_sql
    from psycopg2 import pool as pg_pool
except ImportError:
    pg_sql = None
    pg_pool = None


_DEFAULT_TIMEOUT = 10
_DEFAULT_STATEMENT_TIMEOUT_MS = 300000
_DEFAULT_LOCK_TIMEOUT_MS = 30000


class PgConnectionPoolManager:
    """Thread-safe PostgreSQL connection pool manager with bounded concurrency, TTL eviction, and safe rollback."""

    _lock = threading.Lock()
    _pools: Dict[tuple, Any] = {}
    _pool_meta: Dict[int, Dict[str, Any]] = {}
    _POOL_MAX_CONN = 4
    _POOL_IDLE_TTL_S = 60.0

    @classmethod
    def normalize_params(cls, conn_params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(conn_params)
        params.setdefault("connect_timeout", _DEFAULT_TIMEOUT)
        params.setdefault("keepalives", 1)
        params.setdefault("keepalives_idle", 30)
        params.setdefault("keepalives_interval", 10)
        params.setdefault("keepalives_count", 5)
        params.setdefault("sslmode", "prefer")
        params.setdefault(
            "options",
            f"-c statement_timeout={_DEFAULT_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={_DEFAULT_LOCK_TIMEOUT_MS}",
        )
        return params

    @classmethod
    def _pool_key(cls, params: Dict[str, Any]) -> tuple:
        secret = str(params.get("password", ""))
        secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return (
            str(params.get("service", "")),
            str(params.get("host", "localhost")),
            int(params.get("port", 5432) or 5432),
            str(params.get("database", "")),
            str(params.get("user", "")),
            str(params.get("sslmode", "prefer")),
            secret_hash,
        )

    @classmethod
    def can_pool(cls, psycopg2_mod) -> bool:
        if psycopg2_mod is None or pg_pool is None:
            return False
        connect_fn = getattr(psycopg2_mod, "connect", None)
        if connect_fn is None or getattr(connect_fn, "__name__", "") == "deny_network":
            return False
        return hasattr(psycopg2_mod, "pool") or psycopg2_mod.__name__ == "psycopg2"

    @classmethod
    def _evict_idle_pools(cls) -> None:
        import time

        now = time.monotonic()
        expired = []
        with cls._lock:
            for meta_id, meta in list(cls._pool_meta.items()):
                if (
                    not meta["retired"]
                    and meta["in_use"] == 0
                    and (now - meta["last_used"]) > cls._POOL_IDLE_TTL_S
                ):
                    meta["retired"] = True
                    if cls._pools.get(meta["key"]) is meta["pool"]:
                        cls._pools.pop(meta["key"], None)
                    cls._pool_meta.pop(meta_id, None)
                    expired.append(meta["pool"])
        for pool_inst in expired:
            try:
                pool_inst.closeall()
            except Exception as exc:
                log_warning(f"PgConnectionPoolManager: idle TTL closeall error: {exc}")

    @classmethod
    def _release_slot(cls, pool_inst) -> None:
        if pool_inst is None:
            return
        import time

        to_close = None
        sem = None
        with cls._lock:
            meta = cls._pool_meta.get(id(pool_inst))
            if meta is not None:
                meta["in_use"] = max(0, meta["in_use"] - 1)
                meta["last_used"] = time.monotonic()
                sem = meta["sem"]
                if meta["retired"] and meta["in_use"] == 0:
                    cls._pool_meta.pop(id(pool_inst), None)
                    to_close = pool_inst
        if sem is not None:
            try:
                sem.release()
            except ValueError:
                pass
        if to_close is not None:
            try:
                to_close.closeall()
            except Exception as exc:
                log_warning(f"PgConnectionPoolManager: deferred retired closeall error: {exc}")

    @classmethod
    def acquire(cls, conn_params: Dict[str, Any], psycopg2_mod=None):
        import time

        if psycopg2_mod is None:
            import psycopg2 as psycopg2_mod
        if not cls.can_pool(psycopg2_mod):
            params = dict(conn_params)
            params.setdefault("connect_timeout", _DEFAULT_TIMEOUT)
            return psycopg2_mod.connect(**params), None

        cls._evict_idle_pools()
        params = cls.normalize_params(conn_params)
        key = cls._pool_key(params)
        timeout_s = float(params.get("connect_timeout", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT) + 5.0

        pool_inst = None
        meta = None
        for _attempt in range(2):
            with cls._lock:
                pool_inst = cls._pools.get(key)
                if pool_inst is None or getattr(pool_inst, "closed", False):
                    pool_inst = pg_pool.ThreadedConnectionPool(0, cls._POOL_MAX_CONN, **params)
                    meta = {
                        "key": key,
                        "pool": pool_inst,
                        "sem": threading.BoundedSemaphore(cls._POOL_MAX_CONN),
                        "in_use": 0,
                        "last_used": time.monotonic(),
                        "retired": False,
                    }
                    cls._pools[key] = pool_inst
                    cls._pool_meta[id(pool_inst)] = meta
                else:
                    meta = cls._pool_meta.get(id(pool_inst))
                    if meta is None:
                        meta = {
                            "key": key,
                            "pool": pool_inst,
                            "sem": threading.BoundedSemaphore(cls._POOL_MAX_CONN),
                            "in_use": 0,
                            "last_used": time.monotonic(),
                            "retired": False,
                        }
                        cls._pool_meta[id(pool_inst)] = meta
            if not meta["sem"].acquire(timeout=timeout_s):
                raise TimeoutError("pg.connection_task: pool PostgreSQL sature apres attente.")
            with cls._lock:
                if meta["retired"] or getattr(pool_inst, "closed", False):
                    try:
                        meta["sem"].release()
                    except ValueError:
                        pass
                    pool_inst = None
                    continue
                meta["in_use"] += 1
                meta["last_used"] = time.monotonic()
                break
        else:
            raise RuntimeError("pg.connection_task: pool PostgreSQL indisponible apres reessai.")

        try:
            conn = pool_inst.getconn()
        except Exception:
            cls._release_slot(pool_inst)
            raise

        try:
            if getattr(conn, "closed", 0) != 0:
                raise RuntimeError("Pooled connection already closed")
            conn.rollback()
            if hasattr(conn, "set_session"):
                conn.set_session(readonly=False, autocommit=False)
            return conn, pool_inst
        except Exception:
            try:
                pool_inst.putconn(conn, close=True)
            except Exception as put_exc:
                log_warning(f"PgConnectionPoolManager: discard dead conn warning: {put_exc}")
            finally:
                cls._release_slot(pool_inst)
            fresh_conn = psycopg2_mod.connect(**params)
            return fresh_conn, None

    @classmethod
    def release(cls, conn, pool_inst=None, discard: bool = False) -> None:
        try:
            if conn is None:
                return
            broken = bool(discard or getattr(conn, "closed", 0) != 0)
            if not broken:
                try:
                    conn.rollback()
                    if hasattr(conn, "set_session"):
                        conn.set_session(readonly=False, autocommit=False)
                except Exception as exc:
                    broken = True
                    log_warning(f"PgConnectionPoolManager: rollback on release failed: {exc}")
            if pool_inst is not None:
                try:
                    pool_inst.putconn(conn, close=broken)
                    return
                except Exception as exc:
                    log_warning(f"PgConnectionPoolManager: putconn failed: {exc}")
            try:
                conn.close()
            except Exception as exc:
                log_warning(f"PgConnectionPoolManager: conn close failed: {exc}")
        finally:
            if pool_inst is not None:
                cls._release_slot(pool_inst)
            cls._evict_idle_pools()

    @classmethod
    def close_all(cls) -> None:
        retired_idle = []
        with cls._lock:
            cls._pools.clear()
            for meta_id, meta in list(cls._pool_meta.items()):
                meta["retired"] = True
                if meta["in_use"] == 0:
                    cls._pool_meta.pop(meta_id, None)
                    retired_idle.append(meta["pool"])
        for pool_inst in retired_idle:
            try:
                pool_inst.closeall()
            except Exception as exc:
                log_warning(f"PgConnectionPoolManager: closeall error: {exc}")


class PgLayerSnapshot:
    """Thread-safe snapshot of a QgsVectorLayer captured on the GUI thread."""

    def __init__(self, layer):
        self._is_qgis_layer = isinstance(layer, QgsVectorLayer)
        self._feature_source = (
            QgsVectorLayerFeatureSource(layer) if self._is_qgis_layer else None
        )
        self._fallback_layer = None if self._is_qgis_layer else layer
        self._fields = layer.fields()
        self._crs = layer.crs()
        self._wkb_type = layer.wkbType() if hasattr(layer, "wkbType") else 0
        self._geom_type = layer.geometryType() if hasattr(layer, "geometryType") else 0
        self._is_spatial = layer.isSpatial() if hasattr(layer, "isSpatial") else False
        self._id = layer.id() if hasattr(layer, "id") else ""
        self._name = layer.name() if hasattr(layer, "name") else ""
        self._count = layer.featureCount() if hasattr(layer, "featureCount") else -1

    def id(self):
        return self._id

    def name(self):
        return self._name

    def fields(self):
        return self._fields

    def crs(self):
        return self._crs

    def wkbType(self):
        return self._wkb_type

    def geometryType(self):
        return self._geom_type

    def isSpatial(self):
        return self._is_spatial

    def featureCount(self):
        return self._count

    def getFeatures(self, request=None):
        if self._feature_source is not None:
            return (
                self._feature_source.getFeatures()
                if request is None
                else self._feature_source.getFeatures(request)
            )
        if request is None:
            return self._fallback_layer.getFeatures()
        return self._fallback_layer.getFeatures(request)


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
        self._conn_lock = __import__("threading").Lock()
        self._active_conn = None

    def cancel(self) -> None:
        with self._conn_lock:
            conn = self._active_conn
        if conn is not None and hasattr(conn, "cancel"):
            try:
                conn.cancel()
            except Exception as exc:
                log_warning(f"PgConnectionTask: conn.cancel() warning: {exc}")
        if hasattr(super(), "cancel"):
            super().cancel()

    def _sanitize_error(self, exc) -> str:
        msg = str(exc)
        password = self.conn_params.get("password")
        if password:
            msg = msg.replace(str(password), "[secret masqué]")
        return msg

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        conn = None
        pool_inst = None
        try:
            import psycopg2

            if self.isCanceled():
                return False
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                conn, pool_inst = pool_mgr.acquire(self.conn_params, psycopg2)
            else:
                conn = psycopg2.connect(**self.conn_params)
            with self._conn_lock:
                if self.isCanceled():
                    return False
                self._active_conn = conn
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
            self.message = self._sanitize_error(exc)
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgConnectionTask: connect FAILED "
                f"host={self.conn_params.get('host')} "
                f"elapsed_ms={self.elapsed_ms} "
                f"error={self.message}"
            )
            return False
        finally:
            with self._conn_lock:
                self._active_conn = None
            if conn is not None:
                pool_mgr = globals().get("PgConnectionPoolManager")
                if pool_mgr is not None:
                    pool_mgr.release(conn, pool_inst, discard=not self.success)
                else:
                    try:
                        conn.close()
                    except Exception as close_exc:
                        log_warning(f"PgConnectionTask: conn close error: {close_exc}")

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
        self._conn_lock = __import__("threading").Lock()
        self._active_conn = None

    def cancel(self) -> None:
        with self._conn_lock:
            conn = self._active_conn
        if conn is not None and hasattr(conn, "cancel"):
            try:
                conn.cancel()
            except Exception as exc:
                log_warning(f"PgSchemaTask: conn.cancel() warning: {exc}")
        if hasattr(super(), "cancel"):
            super().cancel()

    def _sanitize_error(self, exc) -> str:
        msg = str(exc)
        password = self.conn_params.get("password")
        if password:
            msg = msg.replace(str(password), "[secret masqué]")
        return msg

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        conn = None
        pool_inst = None
        cursor = None
        failed = False
        try:
            import psycopg2

            if self.isCanceled():
                return False
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                conn, pool_inst = pool_mgr.acquire(self.conn_params, psycopg2)
            else:
                conn = psycopg2.connect(**self.conn_params)
            with self._conn_lock:
                if self.isCanceled():
                    return False
                self._active_conn = conn
            conn.set_session(readonly=True)
            cursor = conn.cursor()

            if self.fetch_tables_for is None:
                self._fetch_all_schemas(cursor)
                if not self.isCanceled() and "public" in self.schemas:
                    self._fetch_tables_for_schema(cursor, "public")
            else:
                self._fetch_tables_for_schema(cursor, self.fetch_tables_for)

            if self.isCanceled():
                return False
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_info(
                f"PgSchemaTask: discovery OK "
                f"schemas={len(self.schemas)} "
                f"tables_schemas={list(self.tables_by_schema.keys())} "
                f"elapsed_ms={self.elapsed_ms}"
            )
            return True
        except Exception as exc:
            failed = True
            self.error = self._sanitize_error(exc)
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgSchemaTask: discovery FAILED "
                f"elapsed_ms={self.elapsed_ms} "
                f"error={self.error}"
            )
            return False
        finally:
            with self._conn_lock:
                self._active_conn = None
            if cursor:
                try:
                    cursor.close()
                except Exception as exc:
                    log_warning(f"PgSchemaTask: cursor close error: {exc}")
            if conn:
                pool_mgr = globals().get("PgConnectionPoolManager")
                if pool_mgr is not None:
                    pool_mgr.release(conn, pool_inst, discard=failed)
                else:
                    try:
                        conn.close()
                    except Exception as exc:
                        log_warning(f"PgSchemaTask: conn close error: {exc}")

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
        snapshot_cls = globals().get("PgLayerSnapshot")
        dependent_layers = []
        safe_mappings = []
        for item in mappings:
            entry = dict(item)
            layer = entry.get("layer")
            if layer is not None and isinstance(layer, QgsVectorLayer):
                if hasattr(self, "setDependentLayers"):
                    dependent_layers.append(layer)
                if snapshot_cls is not None:
                    entry["layer"] = snapshot_cls(layer)
            safe_mappings.append(entry)
        if dependent_layers and hasattr(self, "setDependentLayers"):
            self.setDependentLayers(dependent_layers)
        self.mappings = safe_mappings
        self.compatibility_info: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.elapsed_ms: int = 0
        self._conn_lock = __import__("threading").Lock()
        self._active_conn = None

    def cancel(self) -> None:
        with self._conn_lock:
            conn = self._active_conn
        if conn is not None and hasattr(conn, "cancel"):
            try:
                conn.cancel()
            except Exception as exc:
                log_warning(f"PgCompatibilityTask: conn.cancel() warning: {exc}")
        if hasattr(super(), "cancel"):
            super().cancel()

    def _sanitize_error(self, exc) -> str:
        msg = str(exc)
        password = self.conn_params.get("password")
        if password:
            msg = msg.replace(str(password), "[secret masqué]")
        return msg

    def run(self) -> bool:
        import time

        t0 = time.monotonic()
        conn = None
        pool_inst = None
        cursor = None
        failed = False
        try:
            import psycopg2

            if self.isCanceled():
                return False
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                conn, pool_inst = pool_mgr.acquire(self.conn_params, psycopg2)
            else:
                conn = psycopg2.connect(**self.conn_params)
            with self._conn_lock:
                if self.isCanceled():
                    return False
                self._active_conn = conn
            conn.set_session(readonly=True)
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

            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_info(
                f"PgCompatibilityTask: analysis OK "
                f"compatible={len(self.compatibility_info)} "
                f"errors={len(self.errors)} "
                f"elapsed_ms={self.elapsed_ms}"
            )
            return True
        except Exception as exc:
            failed = True
            clean_err = self._sanitize_error(exc)
            self.errors.append(f"PgCompatibilityTask fatal: {clean_err}")
            self.elapsed_ms = int((time.monotonic() - t0) * 1000)
            log_critical(
                f"PgCompatibilityTask: FAILED "
                f"elapsed_ms={self.elapsed_ms} error={clean_err}"
            )
            return False
        finally:
            with self._conn_lock:
                self._active_conn = None
            if cursor:
                try:
                    cursor.close()
                except Exception as exc:
                    log_warning(f"PgCompatibilityTask: cursor close error: {exc}")
            if conn:
                pool_mgr = globals().get("PgConnectionPoolManager")
                if pool_mgr is not None:
                    pool_mgr.release(conn, pool_inst, discard=failed)
                else:
                    try:
                        conn.close()
                    except Exception as exc:
                        log_warning(f"PgCompatibilityTask: conn close error: {exc}")

    def _analyze_one(
        self, cursor, conn, psycopg2_mod, mapping: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Analyze one mapping. Returns compatibility dict or None."""
        layer_name = mapping["layer_name"]
        schema = mapping["schema"]
        table = mapping["table"]
        source_layer = mapping["layer"]

        snapshot_cls = globals().get("PgLayerSnapshot")
        valid_types = (QgsVectorLayer, snapshot_cls) if snapshot_cls is not None else (QgsVectorLayer,)
        if not isinstance(source_layer, valid_types):
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

        table_info["table_exists"] = bool(target_info)
        if not target_info:
            # A proposed table is only a plan here. Creation belongs to the
            # explicitly confirmed export transaction, never to this analysis.
            target_info = {
                "geometry_column": "geom",
                "geometry_type": QgsWkbTypes.geometryDisplayString(source_geom_type),
                "srid": source_crs.postgisSrid(),
                "fields": [
                    {"name": field.name(), "type": field.typeName(), "nullable": True}
                    for field in source_layer.fields()
                ],
            }
            table_info["requires_creation"] = True
            table_info["decision"] = "La table sera créée uniquement après confirmation."

        target_geom_type = target_info.get("geometry_type", "")
        source_geom_name = QgsWkbTypes.geometryDisplayString(source_geom_type)
        geom_compatible = not table_info["table_exists"] or self._check_geom_compat(source_layer, target_geom_type)

        if not geom_compatible:
            table_info["decision"] = (
                "Géométrie incompatible : choisissez une autre table ou "
                "transformez la géométrie source avant de publier. "
                "La table existante est conservée."
            )
            log_warning(f"{schema}.{table} : {table_info['decision']}")

        table_info["geometry_compatible"] = geom_compatible
        table_info["geometry_info"] = (
            f"Source: {source_geom_name}, Cible: {target_geom_type}"
        )

        target_srid = target_info.get("srid", 0)
        source_srid = source_crs.postgisSrid()
        crs_compatible = (source_srid == target_srid) or target_srid == 0
        table_info["crs_compatible"] = crs_compatible
        table_info["crs_info"] = f"Source SRID: {source_srid}, Cible SRID: {target_srid}"
        table_info["geometry_column"] = target_info.get("geometry_column")
        table_info["target_srid"] = target_srid
        table_info["layer_id"] = source_layer.id()

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
                    postgis_query = pg_sql.SQL(
                        'SELECT ST_GeometryType({geom}), ST_SRID({geom}) '
                        'FROM {schema}.{table} '
                        'WHERE {geom} IS NOT NULL LIMIT 1'
                    ).format(
                        geom=pg_sql.Identifier(geom_column),
                        schema=pg_sql.Identifier(schema),
                        table=pg_sql.Identifier(table),
                    )
                    cursor.execute(postgis_query)
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
            ],
        }

    def _check_geom_compat(self, source_layer, target_geom_type):
        """Check geometry compatibility (background thread, pure computation)."""
        wkb_type = source_layer.wkbType()
        wkb_type_map = {
            QgsWkbTypes.Type.Point: "POINT",
            QgsWkbTypes.Type.MultiPoint: "MULTIPOINT",
            QgsWkbTypes.Type.LineString: "LINESTRING",
            QgsWkbTypes.Type.MultiLineString: "MULTILINESTRING",
            QgsWkbTypes.Type.Polygon: "POLYGON",
            QgsWkbTypes.Type.MultiPolygon: "MULTIPOLYGON",
            QgsWkbTypes.Type.Point25D: "POINTZ",
            QgsWkbTypes.Type.MultiPoint25D: "MULTIPOINTZ",
            QgsWkbTypes.Type.LineString25D: "LINESTRINGZ",
            QgsWkbTypes.Type.MultiLineString25D: "MULTILINESTRINGZ",
            QgsWkbTypes.Type.Polygon25D: "POLYGONZ",
            QgsWkbTypes.Type.MultiPolygon25D: "MULTIPOLYGONZ",
        }
        expected = wkb_type_map.get(wkb_type)
        if not expected:
            expected = get_pg_geom_type(source_layer.geometryType())
        return expected.upper() == target_geom_type.upper()

    def _create_table(self, cursor, schema, table_name, source_layer, srid):
        raise RuntimeError("L'analyse est en lecture seule : confirmez la publication pour créer une table.")

    def _drop_and_recreate(self, cursor, conn, schema, table_name, source_layer):
        raise RuntimeError("La suppression automatique de tables est interdite. Choisissez une autre destination.")

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
