# -*- coding: utf-8 -*-
"""
Configuration manager for transformation settings.
Handles JSON config load/save/migrate with filter support.
"""

import json
import os
import copy
import tempfile
from typing import Dict, List, Any, Optional
from datetime import datetime

from qgis.core import QgsMessageLog, Qgis
from ..shared.helpers import is_filter_enabled, get_filter_expression


class ConfigManager:
    """Manages transformation configurations with filter support."""

    _CONFIG_VERSION = "1.1"

    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.config_file = os.path.join(plugin_dir, 'calculated_fields_config.json')
        self.config_data = {
            "version": self._CONFIG_VERSION,
            "last_modified": datetime.now().isoformat(),
            "tables": {}
        }
        self.load_config()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_config(self) -> bool:
        """Load configuration from JSON file."""
        try:
            if not os.path.exists(self.config_file):
                QgsMessageLog.logMessage(
                    "Config file doesn't exist, creating with default structure",
                    "Transformer", Qgis.Info,
                )
                self.save_config()
                return True

            if os.path.getsize(self.config_file) == 0:
                QgsMessageLog.logMessage(
                    "Config file is empty, initializing with default structure",
                    "Transformer", Qgis.Info,
                )
                self.save_config()
                return True

            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)

            if not isinstance(loaded_data, dict) or 'tables' not in loaded_data:
                QgsMessageLog.logMessage(
                    "Invalid config structure, reinitializing",
                    "Transformer", Qgis.Warning,
                )
                self.save_config()
                return True

            self.config_data = loaded_data
            self._migrate_config_if_needed()

            QgsMessageLog.logMessage(
                f"Loaded configuration: {len(self.config_data.get('tables', {}))} tables",
                "Transformer", Qgis.Info,
            )
            return True

        except Exception as e:
            QgsMessageLog.logMessage(f"Config load error: {e}", "Transformer", Qgis.Warning)
            return False

    def save_config(self) -> bool:
        """Save configuration to JSON file atomically.

        Writes to a temp file in the same directory, then os.replace.
        Readers either see the old or the new file, never a half-written one.
        """
        try:
            self.config_data["last_modified"] = datetime.now().isoformat()
            dest_dir = os.path.dirname(self.config_file) or "."
            os.makedirs(dest_dir, exist_ok=True)

            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=os.path.basename(self.config_file) + ".",
                suffix=".tmp",
                dir=dest_dir,
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(self.config_data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self.config_file)
            except Exception:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            QgsMessageLog.logMessage(
                f"Config saved atomically: {len(self.config_data.get('tables', {}))} tables",
                "Transformer", Qgis.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Config save error: {e}", "Transformer", Qgis.Critical)
            return False

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _migrate_config_if_needed(self):
        """Migrate config to newer version if needed."""
        current_version = self.config_data.get("version", "1.0")
        if current_version == "1.0":
            for table_config in self.config_data.get("tables", {}).values():
                if "filter" not in table_config:
                    table_config["filter"] = {"enabled": False, "expression": ""}
            self.config_data["version"] = self._CONFIG_VERSION
            QgsMessageLog.logMessage(
                "Migrated configuration to version 1.1", "Transformer", Qgis.Info,
            )
            self.save_config()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_table_config(
        self,
        table_name: str,
        source_file: str,
        calculated_fields: Dict[str, str],
        filter_config: Optional[Dict[str, Any]] = None,
        target_crs: Optional[str] = None,
        geometry_expression: Optional[str] = None,
        force_replace: bool = False,
    ) -> Dict[str, Any]:
        """Add or update a table configuration.

        Returns:
            {"success": bool, "action": str, "message": str, "replaced_table": str|None}
        """
        if "tables" not in self.config_data:
            self.config_data["tables"] = {}

        if table_name in self.config_data["tables"] and not force_replace:
            existing_source = self.config_data["tables"][table_name].get("source_file", "")
            message = (
                f"Configuration already exists for table '{table_name}' "
                f"(source: {existing_source})"
            )
            QgsMessageLog.logMessage(message, "Transformer", Qgis.Warning)
            return {
                "success": False,
                "action": "rejected",
                "message": message,
                "replaced_table": None,
            }

        default_filter = {"enabled": False, "expression": ""}
        if filter_config is None:
            filter_config = default_filter
        else:
            for key, default_value in default_filter.items():
                filter_config.setdefault(key, default_value)

        self.config_data["tables"][table_name] = {
            "source_file": source_file,
            "calculated_fields": calculated_fields.copy(),
            "filter": filter_config,
            "target_crs": target_crs,
            "geometry_expression": geometry_expression,
        }

        filter_info = ""
        if is_filter_enabled(filter_config):
            expr = get_filter_expression(filter_config)
            truncated = f"{expr[:30]}..." if len(expr) > 30 else expr
            filter_info = f" with filter: {truncated}"

        QgsMessageLog.logMessage(
            f"Saved config for {table_name}: {len(calculated_fields)} fields{filter_info}",
            "Transformer", Qgis.Info,
        )
        return {
            "success": True,
            "action": "saved",
            "message": f"Configuration saved for '{table_name}'",
            "replaced_table": None,
        }

    def has_table_config(self, table_name: str) -> bool:
        return table_name in self.config_data.get("tables", {})

    def get_table_config(self, table_name: str) -> Optional[Dict]:
        config = self.config_data.get("tables", {}).get(table_name)
        if config is None:
            return None
        result = copy.copy(config)
        if "filter" not in result:
            result["filter"] = {"enabled": False, "expression": ""}
        return result

    def get_all_tables(self) -> Dict[str, Dict]:
        tables = self.config_data.get("tables", {})
        enhanced = {}
        for name, cfg in tables.items():
            entry = cfg.copy()
            entry['field_count'] = len(cfg.get('calculated_fields', {}))
            entry['has_filter'] = cfg.get('filter', {}).get('enabled', False)
            enhanced[name] = entry
        return enhanced

    def remove_table_config(self, table_name: str) -> bool:
        if "tables" in self.config_data and table_name in self.config_data["tables"]:
            del self.config_data["tables"][table_name]
            QgsMessageLog.logMessage(f"Removed config for {table_name}", "Transformer", Qgis.Info)
            return True
        return False

    def get_tables_for_source(self, source_file: str) -> List[str]:
        return [
            name
            for name, cfg in self.config_data.get("tables", {}).items()
            if cfg.get("source_file") == source_file
        ]

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def get_table_filter_config(self, table_name: str) -> Dict[str, Any]:
        config = self.get_table_config(table_name)
        if config:
            return config.get("filter", {"enabled": False, "expression": ""})
        return {"enabled": False, "expression": ""}

    def update_table_filter(self, table_name: str, filter_config: Dict[str, Any]) -> bool:
        if "tables" in self.config_data and table_name in self.config_data["tables"]:
            self.config_data["tables"][table_name]["filter"] = filter_config
            return True
        return False

    def get_filtered_tables_count(self) -> int:
        count = 0
        for cfg in self.config_data.get("tables", {}).values():
            fc = cfg.get("filter", {})
            if fc.get("enabled", False) and fc.get("expression", "").strip():
                count += 1
        return count

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_config(self, export_path: str) -> bool:
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
            QgsMessageLog.logMessage(
                f"Configuration exported to {export_path}", "Transformer", Qgis.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Export error: {e}", "Transformer", Qgis.Warning)
            return False

    def import_config(self, import_path: str) -> bool:
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)

            if "tables" not in imported_data:
                QgsMessageLog.logMessage(
                    "Invalid configuration format", "Transformer", Qgis.Warning,
                )
                return False

            if "tables" not in self.config_data:
                self.config_data["tables"] = {}

            imported_tables = imported_data.get("tables", {})
            merged_count = 0
            overwritten_count = 0

            for name, cfg in imported_tables.items():
                if name in self.config_data["tables"]:
                    overwritten_count += 1
                else:
                    merged_count += 1
                self.config_data["tables"][name] = cfg

            imported_version = imported_data.get("version", "1.0")
            if imported_version >= self.config_data.get("version", "1.0"):
                self.config_data["version"] = imported_version

            self._migrate_config_if_needed()
            self.save_config()

            QgsMessageLog.logMessage(
                f"Configuration merged: {len(imported_tables)} table(s) "
                f"({merged_count} new, {overwritten_count} updated)",
                "Transformer", Qgis.Info,
            )
            return True

        except Exception as e:
            QgsMessageLog.logMessage(f"Import error: {e}", "Transformer", Qgis.Warning)
            return False

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_config_summary(self) -> Dict[str, Any]:
        tables = self.config_data.get("tables", {})
        source_files = {
            cfg.get("source_file", "")
            for cfg in tables.values()
            if cfg.get("source_file")
        }
        return {
            "version": self.config_data.get("version", "1.0"),
            "last_modified": self.config_data.get("last_modified", ""),
            "total_tables": len(tables),
            "tables_with_filters": self.get_filtered_tables_count(),
            "total_calculated_fields": sum(
                len(cfg.get("calculated_fields", {})) for cfg in tables.values()
            ),
            "unique_source_files": len(source_files),
            "source_files": list(source_files),
        }

    def validate_config(self) -> List[str]:
        issues = []
        tables = self.config_data.get("tables", {})
        if not tables:
            issues.append("No tables configured")
            return issues

        for name, cfg in tables.items():
            source = cfg.get("source_file", "")
            if not source:
                issues.append(f"Table '{name}': No source file specified")
            elif not os.path.exists(source):
                issues.append(f"Table '{name}': Source file not found: {source}")

            if not cfg.get("calculated_fields"):
                issues.append(f"Table '{name}': No calculated fields defined")

            fc = cfg.get("filter", {})
            if fc.get("enabled", False) and not fc.get("expression", "").strip():
                issues.append(f"Table '{name}': Filter enabled but no expression provided")

        return issues

    def cleanup_missing_sources(self) -> int:
        to_remove = [
            name
            for name, cfg in self.config_data.get("tables", {}).items()
            if cfg.get("source_file") and not os.path.exists(cfg["source_file"])
        ]
        for name in to_remove:
            self.remove_table_config(name)

        if to_remove:
            self.save_config()
            QgsMessageLog.logMessage(
                f"Cleaned up {len(to_remove)} configurations with missing source files",
                "Transformer", Qgis.Info,
            )
        return len(to_remove)
