# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Isolated PostgreSQL integrity tests: no QGIS runtime or real connection.

Run: python -B tests/test_pg_integrity.py
Actual source classes are loaded through AST, with transactional database
doubles and a fake authentication manager. Only synthetic temporary files are
written. This is not a PostgreSQL/PostGIS integration receipt.
"""

import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import typing
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class SQL:
    def __init__(self, value):
        self.value = value

    def format(self, *args, **kwargs):
        return SQL(self.value.format(*map(str, args), **{key: str(value) for key, value in kwargs.items()}))

    def join(self, values):
        return SQL(self.value.join(map(str, values)))

    def __add__(self, other):
        return SQL(self.value + str(other))

    def __str__(self):
        return self.value


SQL_MODULE = types.SimpleNamespace(
    SQL=SQL, Identifier=lambda value: SQL('"' + value + '"'),
    Placeholder=lambda: SQL("%s"), Literal=lambda value: SQL(str(value)),
)


class Task:
    def __init__(self, *args):
        self.cancelled = False
        self.progress = []

    def isCanceled(self):
        return self.cancelled

    def setProgress(self, value):
        self.progress.append(value)


class Field:
    def __init__(self, name):
        self.value = name

    def name(self):
        return self.value

    def typeName(self):
        return "text"


class Layer:
    def __init__(self, fields=("source_code",), rows=None):
        self.names = fields
        self.rows = rows if rows is not None else [{"source_code": "001"}]
        self.before_feature = lambda index: None

    def id(self):
        return "synthetic-layer-id"

    def fields(self):
        return [Field(name) for name in self.names]

    def crs(self):
        return types.SimpleNamespace(postgisSrid=lambda: 2154)

    def isSpatial(self):
        return False

    def geometryType(self):
        return 0

    def wkbType(self):
        return 0

    def getFeatures(self):
        for index, row in enumerate(self.rows):
            self.before_feature(index)
            yield row


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0

    def execute(self, query, params=None):
        query = str(query)
        self.connection.trace.append(query)
        if query.startswith("DELETE"):
            self.connection.pending = []

    def fetchone(self):
        return (int(self.connection.exists),)

    def fetchall(self):
        return [(name, "text", "text") for name in self.connection.columns]

    def executemany(self, query, values):
        self.connection.trace.append(str(query))
        if self.connection.fail_insert:
            raise ValueError("Contrainte synthétique")
        self.connection.pending.extend(values)
        self.rowcount = len(values)

    def close(self):
        pass


class Connection:
    def __init__(self, columns=("target_code",), fail_insert=False, exists=True):
        self.columns = columns
        self.fail_insert = fail_insert
        self.exists = exists
        self.durable = [("previous",)]
        self.pending = list(self.durable)
        self.trace = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1
        self.durable = list(self.pending)

    def rollback(self):
        self.rollbacks += 1
        self.pending = list(self.durable)

    def close(self):
        pass


def load_class(relative_path, class_name, namespace, extras=()):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.ClassDef) and node.name in (*extras, class_name)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / relative_path), "exec"), namespace)
    return namespace[class_name]


def base_namespace():
    noop = lambda *args, **kwargs: None
    return {
        **vars(typing), "QgsTask": Task, "TaskCanCancel": 1,
        "QgsVectorLayer": Layer,
        "QgsWkbTypes": types.SimpleNamespace(geometryDisplayString=lambda value: "POINT"),
        "pg_sql": SQL_MODULE, "BATCH_SIZE": 2,
        "log_info": noop, "log_warning": noop, "log_critical": noop,
        "log_success": noop, "QgsMessageLog": types.SimpleNamespace(logMessage=noop),
        "MsgInfo": 0, "MsgWarning": 1, "MsgCritical": 2,
        "_DEFAULT_TIMEOUT": 10, "QWidget": object, "os": os, "json": json,
        "pyqtSignal": lambda *args: types.SimpleNamespace(emit=noop),
    }


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.namespace = base_namespace()
        self.Export = load_class("pg/export_task.py", "PgExportTask", self.namespace, ("_ExportCancelled",))

    def make_task(self, connection=None, mode="replace", mapping=None, layer=None):
        connection = connection or Connection()
        layer = layer or Layer()
        job = {
            "schema": "demo", "table": "destination", "layer": layer, "srid": 2154,
            "field_mapping": mapping if mapping is not None else [
                {"source": "source_code", "target": "target_code", "type": "text"}
            ],
        }
        task = self.Export({}, [job], export_mode=mode)
        fake_db = types.ModuleType("psycopg2")
        fake_db.connect = lambda **kwargs: connection
        return task, fake_db, job, connection

    def test_replace_rolls_back_old_data_when_insert_fails(self):
        task, database, job, connection = self.make_task(Connection(fail_insert=True))
        result = task._export_table(database, "demo", "destination", job["layer"], 2154, job)
        self.assertEqual(result, -1)
        self.assertEqual(connection.durable, [("previous",)])
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_invalid_mapping_is_rejected_before_delete(self):
        task, database, job, connection = self.make_task(mapping=[{"source": "absent", "target": "target_code"}])
        self.assertEqual(task._export_table(database, "demo", "destination", job["layer"], 2154, job), -1)
        self.assertFalse(any(query.startswith("DELETE") for query in connection.trace))
        self.assertEqual(connection.durable, [("previous",)])

    def test_confirmed_renaming_and_cast_are_executed(self):
        task, database, job, connection = self.make_task()
        self.assertEqual(task._export_table(database, "demo", "destination", job["layer"], 2154, job), 1)
        self.assertEqual(connection.durable, [("001",)])
        self.assertEqual(connection.commits, 1)
        statement = next(query for query in connection.trace if query.startswith("INSERT"))
        self.assertIn('"target_code"', statement)
        self.assertIn("CAST(%s AS text)", statement)
        self.assertNotIn('"source_code"', statement)

    def test_duplicate_target_is_rejected(self):
        layer = Layer(("a", "b"), [{"a": 1, "b": 2}])
        task, database, job, connection = self.make_task(layer=layer, mapping=[
            {"source": "a", "target": "target_code"},
            {"source": "b", "target": "target_code"},
        ])
        self.assertEqual(task._export_table(database, "demo", "destination", layer, 2154, job), -1)
        self.assertFalse(any(query.startswith("DELETE") for query in connection.trace))

    def test_cancel_after_batch_rolls_back_and_reports_zero_committed(self):
        layer = Layer(rows=[{"source_code": str(index)} for index in range(3)])
        task, database, job, connection = self.make_task(layer=layer)
        layer.before_feature = lambda index: setattr(task, "cancelled", index == 2)
        with patch.dict(sys.modules, {"psycopg2": database}):
            self.assertFalse(task.run())
        self.assertEqual(task.status, "cancelled")
        self.assertEqual(task.total_inserted, 0)
        self.assertEqual(task.success_count, 0)
        self.assertEqual(connection.durable, [("previous",)])
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(task.result_summary["committed"], 0)

    def test_upsert_can_map_different_key_names(self):
        task, database, job, connection = self.make_task(mode="update")
        job["update_config"] = {
            "join_type": "attribute", "source_key_field": "source_code", "target_key_field": "target_code",
        }
        self.assertEqual(task._export_table(database, "demo", "destination", job["layer"], 2154, job), 1)
        self.assertIn('ON CONFLICT ("target_code") DO NOTHING', connection.trace[-1])

    def test_missing_table_cannot_be_created_without_confirmation(self):
        task, database, job, connection = self.make_task(Connection(exists=False))
        self.assertEqual(task._export_table(database, "demo", "destination", job["layer"], 2154, job), -1)
        self.assertFalse(any(query.startswith(("CREATE", "DELETE")) for query in connection.trace))

    def test_analysis_preserves_incompatible_table_and_plans_missing_table(self):
        compatibility = load_class("pg/connection_task.py", "PgCompatibilityTask", self.namespace)
        task = compatibility({}, [])
        task._get_table_info = lambda *args: {
            "geometry_type": "POLYGON", "srid": 2154,
            "geometry_column": "geom", "fields": [{"name": "source_code", "type": "text"}],
        }
        task._check_geom_compat = lambda *args: False
        task._drop_and_recreate = lambda *args: self.fail("Analyse destructrice")
        task._create_table = lambda *args: self.fail("Création avant confirmation")
        mapping = {"layer_name": "demo", "schema": "demo", "table": "target", "layer": Layer()}
        info = task._analyze_one(None, None, None, mapping)
        self.assertFalse(info["geometry_compatible"])
        self.assertIn("autre table", info["decision"])
        task._get_table_info = lambda *args: None
        task._check_geom_compat = lambda *args: True
        info = task._analyze_one(None, None, None, mapping)
        self.assertFalse(info["table_exists"])
        self.assertTrue(info["requires_creation"])

    def test_false_zero_and_empty_string_are_not_null(self):
        self.assertIs(self.Export._python_value(False), False)
        self.assertEqual(self.Export._python_value(0), 0)
        self.assertEqual(self.Export._python_value(""), "")

    def test_refusing_confirmation_never_dispatches_a_writer(self):
        namespace = base_namespace()
        namespace.update({
            "DialogAccepted": 1,
            "QMessageBox": types.SimpleNamespace(warning=lambda *args: None),
            "IntegrationConfirmationDialog": lambda *args: types.SimpleNamespace(exec=lambda: 0),
        })
        widget_class = load_class("pg/postgresql_integration.py", "PostgreSQLMappingWidget", namespace)
        widget = widget_class.__new__(widget_class)
        widget.available_schemas = []
        widget._dispatch_async_export = lambda *args: self.fail("Écriture sans confirmation")
        widget._dispatch_update_export = lambda *args: self.fail("Écriture sans confirmation")
        task = types.SimpleNamespace(
            isCanceled=lambda: False, errors=[], compatibility_info=[{
                "schema": "demo", "table": "target", "geometry_compatible": True, "crs_compatible": True,
            }],
        )
        widget._active_compat_task = task
        widget._active_export_task = None
        widget._on_export_compatibility_analyzed(task, {})
        self.assertIsNone(widget.confirmation_dialog)

    def test_dialog_plan_preserves_confirmed_names_and_types(self):
        namespace = base_namespace()
        namespace["QDialog"] = object
        dialog_class = load_class("pg/postgresql_integration.py", "IntegrationConfirmationDialog", namespace)
        dialog = dialog_class.__new__(dialog_class)
        destination = types.SimpleNamespace(currentData=lambda: "target_code")
        conversion = types.SimpleNamespace(currentText=lambda: "bigint")
        table = types.SimpleNamespace(
            rowCount=lambda: 1,
            item=lambda row, column: types.SimpleNamespace(text=lambda: "source_code"),
            cellWidget=lambda row, column: destination if column == 2 else conversion,
        )
        dialog.mapping_widgets = {"demo": {"table": table, "info": {"layer": "demo"}}}
        self.assertEqual(dialog.get_execution_plans()[0]["field_mapping"], [
            {"source": "source_code", "target": "target_code", "type": "bigint"}
        ])

    def test_connection_failure_does_not_expose_a_password(self):
        task, database, job, connection = self.make_task()
        task.conn_params = {"password": "synthetic-private"}
        def fail_connection(**kwargs):
            raise ValueError("synthetic-private connection failure")
        database.connect = fail_connection
        with patch.dict(sys.modules, {"psycopg2": database}):
            self.assertFalse(task.run())
        self.assertNotIn("synthetic-private", json.dumps(task.result_summary))
        self.assertEqual(task.status, "failed")

    def test_publication_receipt_has_only_logical_destinations(self):
        namespace = base_namespace()
        widget_class = load_class("pg/postgresql_integration.py", "PostgreSQLMappingWidget", namespace)
        widget = widget_class.__new__(widget_class)
        results = []
        widget.publication_finished = types.SimpleNamespace(emit=results.append)
        task = types.SimpleNamespace(
            status="success", success_count=1, total_inserted=3, fail_count=0, errors=[],
            result_summary={"status": "success", "committed": 3},
            conn_params={"password": "synthetic-private"},
            jobs=[{"schema": "demo", "table": "target", "layer_name": "source"}],
        )
        widget._on_export_finished(task)
        self.assertEqual(results[0]["plan"], [{"schema": "demo", "table": "target", "layer": "source"}])
        self.assertNotIn("synthetic-private", json.dumps(results))


class PublicationCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.namespace = base_namespace()
        self.namespace.update({"DialogAccepted": 1, "QMessageBox": types.SimpleNamespace(warning=lambda *args: None)})
        widget_class = load_class("pg/postgresql_integration.py", "PostgreSQLMappingWidget", self.namespace)
        self.widget = widget_class.__new__(widget_class)
        self.widget._active_export_task = None
        self.widget._compat_generation = 1
        self.widget.available_schemas = []
        self.launches = []
        self.widget._dispatch_async_export = lambda *args: self.launches.append(args)
        self.widget._dispatch_update_export = lambda *args: self.launches.append(args)
        self.task = types.SimpleNamespace(
            _request_generation=1, isCanceled=lambda: False, errors=[], compatibility_info=[{
                "layer": "source", "layer_id": "source-id", "schema": "demo", "table": "target",
                "geometry_compatible": True, "crs_compatible": True,
            }],
        )
        self.widget._active_compat_task = self.task

    def dialog(self, during_exec=lambda: None, before_dispatch=lambda: None):
        def execute():
            during_exec()
            return 1
        def update_config():
            before_dispatch()
            return None
        return types.SimpleNamespace(
            exec=execute,
            get_execution_plans=lambda: [{**self.task.compatibility_info[0], "field_mapping": [{"source": "a", "target": "b"}]}],
            get_selected_export_mode=lambda: "append", get_update_configuration=update_config,
        )

    def test_obsolete_analysis_never_opens_dialog_or_clears_current_analysis(self):
        current = object()
        self.widget._active_compat_task = current
        self.widget._compat_generation = 2
        self.namespace["IntegrationConfirmationDialog"] = lambda *args: self.fail("Dialogue obsolète")
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.assertIs(self.widget._active_compat_task, current)
        self.assertEqual(self.launches, [])

    def test_new_analysis_during_dialog_invalidates_the_old_plan(self):
        current = object()
        def newer_request():
            self.widget._active_compat_task = current
            self.widget._compat_generation = 2
        self.namespace["IntegrationConfirmationDialog"] = lambda *args: self.dialog(during_exec=newer_request)
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.assertEqual(self.launches, [])
        self.assertIs(self.widget._active_compat_task, current)

    def test_export_started_before_dispatch_prevents_another_writer(self):
        current_export = object()
        def another_publication():
            self.widget._active_export_task = current_export
        self.namespace["IntegrationConfirmationDialog"] = lambda *args: self.dialog(before_dispatch=another_publication)
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.assertEqual(self.launches, [])
        self.assertIs(self.widget._active_export_task, current_export)

    def test_current_analysis_dispatches_once_and_releases_its_reference(self):
        self.namespace["IntegrationConfirmationDialog"] = lambda *args: self.dialog()
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.assertEqual(len(self.launches), 1)
        self.assertIsNone(self.widget._active_compat_task)

    def test_old_export_completion_preserves_new_active_export_and_emits_once(self):
        current_export = object()
        self.widget._active_export_task = current_export
        receipts = []
        self.widget.publication_finished = types.SimpleNamespace(emit=receipts.append)
        old = types.SimpleNamespace(status="success", success_count=1, total_inserted=1, fail_count=0, errors=[], jobs=[], result_summary={})
        self.widget._on_export_finished(old)
        self.widget._on_export_finished(old)
        self.assertIs(self.widget._active_export_task, current_export)
        self.assertEqual(len(receipts), 1)

    def test_cancelled_current_analysis_is_released_without_dialog(self):
        self.task.isCanceled = lambda: True
        self.namespace["IntegrationConfirmationDialog"] = lambda *args: self.fail("Analyse annulée")
        self.widget._on_export_compatibility_analyzed(self.task, {})
        self.assertIsNone(self.widget._active_compat_task)
        self.assertEqual(self.launches, [])


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.namespace = base_namespace()
        self.Widget = load_class("pg/postgresql_integration.py", "PostgreSQLConfigWidget", self.namespace)
        self.namespace["CONNECTIONS_FILE_NAME"] = "profiles.json"
        self.widget = self.Widget.__new__(self.Widget)
        self.widget._active_name = "demo"
        self.widget._connections = {
            "demo": self.widget._normalize_profile({"username": "tester", "password": "synthetic-secret"})
        }

    def test_profile_serialization_stores_only_authcfg(self):
        with tempfile.TemporaryDirectory(prefix="transformer-pg-test-") as folder:
            self.widget._config_dir = folder
            self.widget._protect_credentials = lambda *args: "abc1234"
            self.assertTrue(self.widget._write_all_profiles())
            text = Path(folder, "profiles.json").read_text(encoding="utf-8")
            profile = json.loads(text)["connections"]["demo"]
            self.assertNotIn("password", profile)
            self.assertNotIn("_session_password", profile)
            self.assertNotIn("synthetic-secret", text)
            self.assertEqual(profile["authcfg"], "abc1234")

    def test_locked_auth_store_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="transformer-pg-test-") as folder:
            self.widget._config_dir = folder
            target = Path(folder, "profiles.json")
            target.write_text('{"legacy":"synthetic-backup"}', encoding="utf-8")
            before = target.read_bytes()
            self.widget._protect_credentials = lambda *args: ""
            self.assertFalse(self.widget._write_all_profiles())
            self.assertEqual(target.read_bytes(), before)

    def test_qgis_tuple_and_legacy_boolean_returns_are_supported(self):
        config = object()
        self.assertEqual(self.Widget._auth_result((True, config), object()), (True, config))
        self.assertEqual(self.Widget._auth_result(False, config), (False, config))

    def test_legacy_plaintext_file_is_purged_after_successful_migration(self):
        with tempfile.TemporaryDirectory(prefix="transformer-pg-legacy-") as folder:
            self.widget._config_dir = folder
            legacy_file = Path(folder, "legacy.json")
            legacy_file.write_text('{"host":"localhost","password":"old-plaintext-secret"}', encoding="utf-8")
            self.widget._legacy_path = lambda: str(legacy_file)
            self.widget._protect_credentials = lambda *args: "auth123"
            self.assertTrue(self.widget._write_all_profiles())
            self.assertFalse(legacy_file.exists())


class ResourceResilienceTests(unittest.TestCase):
    def setUp(self):
        self.namespace = base_namespace()
        self.namespace["hashlib"] = __import__("hashlib")
        self.namespace["threading"] = __import__("threading")
        self.Export = load_class("pg/export_task.py", "PgExportTask", self.namespace, ("_ExportCancelled",))

    def test_rollback_failure_on_dead_socket_does_not_abort_task_or_leak(self):
        class DeadSocketConnection(Connection):
            def __init__(self):
                super().__init__(fail_insert=True)
                self.closed_calls = 0

            def rollback(self):
                raise RuntimeError("Socket closed by peer during rollback")

            def close(self):
                self.closed_calls += 1

        conn1 = DeadSocketConnection()
        conn2 = Connection()
        conns = [conn1, conn2]
        fake_db = types.ModuleType("psycopg2")
        fake_db.connect = lambda **kwargs: conns.pop(0)

        jobs = [
            {
                "schema": "demo", "table": "t1", "layer": Layer(), "srid": 2154,
                "field_mapping": [{"source": "source_code", "target": "target_code", "type": "text"}],
            },
            {
                "schema": "demo", "table": "t2", "layer": Layer(), "srid": 2154,
                "field_mapping": [{"source": "source_code", "target": "target_code", "type": "text"}],
            },
        ]
        task = self.Export({"password": "secret-val"}, jobs, export_mode="append")
        with patch.dict(sys.modules, {"psycopg2": fake_db}):
            self.assertTrue(task.run())
        self.assertEqual(task.status, "partial")
        self.assertEqual(task.success_count, 1)
        self.assertEqual(task.fail_count, 1)
        self.assertEqual(conn1.closed_calls, 1)

    def test_cancel_invokes_active_connection_cancel(self):
        cancelled_conns = []
        conn = Connection()
        conn.cancel = lambda: cancelled_conns.append(True)
        task = self.Export({}, [], export_mode="append")
        task._active_conn = conn
        task.cancel()
        self.assertEqual(cancelled_conns, [True])
        self.assertTrue(task.isCanceled())

    def test_pool_manager_reuses_and_rolls_back_connections_and_closes_all(self):
        created = []
        put_calls = []
        closed_pools = []

        class FakePooledConn(Connection):
            def __init__(self):
                super().__init__()
                self.closed = 0
                self.session_calls = []

            def set_session(self, **kwargs):
                self.session_calls.append(kwargs)

        class FakePool:
            def __init__(self, minconn, maxconn, **kwargs):
                self.closed = False
                self.kwargs = kwargs
                self._conn = FakePooledConn()
                created.append(self._conn)

            def getconn(self):
                return self._conn

            def putconn(self, conn, close=False):
                put_calls.append((conn, close))

            def closeall(self):
                self.closed = True
                closed_pools.append(True)

        fake_pool_mod = types.SimpleNamespace(ThreadedConnectionPool=FakePool)
        self.namespace["pg_pool"] = fake_pool_mod
        self.namespace["_DEFAULT_STATEMENT_TIMEOUT_MS"] = 300000
        self.namespace["_DEFAULT_LOCK_TIMEOUT_MS"] = 30000
        pool_mgr = load_class("pg/connection_task.py", "PgConnectionPoolManager", self.namespace)
        fake_psycopg2 = types.SimpleNamespace(
            __name__="psycopg2",
            connect=lambda **kw: FakePooledConn(),
            pool=fake_pool_mod,
        )
        params = {"host": "db.local", "port": 5432, "database": "sig", "user": "u", "password": "p"}
        conn, pool_inst = pool_mgr.acquire(params, fake_psycopg2)
        self.assertEqual(len(created), 1)
        self.assertEqual(pool_inst.kwargs["keepalives"], 1)
        self.assertIn("statement_timeout=300000", pool_inst.kwargs["options"])
        pool_mgr.release(conn, pool_inst, discard=False)
        self.assertEqual(conn.rollbacks, 2)
        self.assertEqual(put_calls[-1], (conn, False))
        pool_mgr.close_all()
        self.assertEqual(closed_pools, [True])

    def test_pool_manager_uses_minconn_zero_defers_closeall_and_evicts_idle(self):
        created_args = []
        closed_pools = []

        class FakePooledConn(Connection):
            def __init__(self):
                super().__init__()
                self.closed = 0

            def set_session(self, **kwargs):
                pass

        class FakePool:
            def __init__(self, minconn, maxconn, **kwargs):
                created_args.append((minconn, maxconn))
                self.closed = False
                self._conn = FakePooledConn()

            def getconn(self):
                return self._conn

            def putconn(self, conn, close=False):
                pass

            def closeall(self):
                self.closed = True
                closed_pools.append(True)

        fake_pool_mod = types.SimpleNamespace(ThreadedConnectionPool=FakePool)
        self.namespace["pg_pool"] = fake_pool_mod
        self.namespace["_DEFAULT_STATEMENT_TIMEOUT_MS"] = 300000
        self.namespace["_DEFAULT_LOCK_TIMEOUT_MS"] = 30000
        pool_mgr = load_class("pg/connection_task.py", "PgConnectionPoolManager", self.namespace)
        fake_psycopg2 = types.SimpleNamespace(
            __name__="psycopg2",
            connect=lambda **kw: FakePooledConn(),
            pool=fake_pool_mod,
        )
        params = {"host": "db.ttl", "port": 5432, "database": "sig", "user": "u", "password": "p"}
        conn, pool_inst = pool_mgr.acquire(params, fake_psycopg2)
        self.assertEqual(created_args[0], (0, 4))
        # close_all while checked out defers closeall() until final release
        pool_mgr.close_all()
        self.assertEqual(closed_pools, [])
        pool_mgr.release(conn, pool_inst, discard=False)
        self.assertEqual(closed_pools, [True])

        # Idle TTL eviction closes stale pool on next acquire
        conn2, pool2 = pool_mgr.acquire(params, fake_psycopg2)
        pool_mgr.release(conn2, pool2, discard=False)
        pool_mgr._pool_meta[id(pool2)]["last_used"] -= 120.0
        conn3, pool3 = pool_mgr.acquire(
            {"host": "db.other", "port": 5432, "database": "sig", "user": "u", "password": "p"},
            fake_psycopg2,
        )
        self.assertTrue(pool2.closed)
        pool_mgr.release(conn3, pool3, discard=False)
        pool_mgr.close_all()

    def test_create_table_caps_scan_at_100_rows_without_geometries(self):
        class CountingLayer(Layer):
            def __init__(self, count):
                super().__init__(("source_code",), [{"source_code": f"v{i}"} for i in range(count)])
                self.iterated = 0

            def getFeatures(self):
                for row in self.rows:
                    self.iterated += 1
                    yield row

        self.namespace["normalize_pg_geom_type"] = lambda v: v
        self.namespace["get_pg_geom_type"] = lambda v: "POINT"
        wkb_types = types.SimpleNamespace(
            Point=1, MultiPoint=4, LineString=2, MultiLineString=5,
            Polygon=3, MultiPolygon=6, Point25D=1001, MultiPoint25D=1004,
            LineString25D=1002, MultiLineString25D=1005, Polygon25D=1003, MultiPolygon25D=1006,
            NoGeometry=100, Unknown=0,
        )
        self.namespace["QgsWkbTypes"] = types.SimpleNamespace(
            geometryDisplayString=lambda value: "POINT",
            Type=wkb_types,
            **vars(wkb_types),
        )
        export_cls = load_class("pg/export_task.py", "PgExportTask", self.namespace, ("_ExportCancelled",))
        layer = CountingLayer(300)
        task = export_cls({}, [{"schema": "demo", "table": "t", "layer": layer, "srid": 2154}], export_mode="append")
        conn = Connection()
        task._create_table(conn.cursor(), conn, "demo", "t", layer, 2154)
        self.assertEqual(layer.iterated, 101)


if __name__ == "__main__":
    unittest.main(verbosity=2)
