# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Configuration manager for transformation settings.
Handles JSON config load/save/migrate with filter support.
"""

import json
import os
import copy
import tempfile
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

from qgis.core import QgsMessageLog
from ..shared.compat import MsgInfo, MsgWarning, MsgCritical
from ..shared.helpers import is_filter_enabled, get_filter_expression


class ConfigManager:
    """Manages transformation configurations with filter support."""

    _CONFIG_VERSION = "1.2"
    _MAX_RECIPE_HISTORY = 20
    FIELD_TYPES = {"Text", "Integer", "Integer64", "Real", "Date", "DateTime", "Boolean"}

    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.config_file = os.path.join(plugin_dir, 'calculated_fields_config.json')
        self.config_data = {
            "version": self._CONFIG_VERSION,
            "last_modified": datetime.now().isoformat(),
            "tables": {}
        }
        self.last_import_result = {}
        self.last_export_error = ""
        self.validation_warnings = []
        self._persisted_data = copy.deepcopy(self.config_data)
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
                    "Transformer", MsgInfo,
                )
                return self.save_config()

            if os.path.getsize(self.config_file) == 0:
                QgsMessageLog.logMessage(
                    "Config file is empty, initializing with default structure",
                    "Transformer", MsgInfo,
                )
                return self.save_config()

            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)

            loaded_data = self._migrate_legacy_geometry_aliases(loaded_data)
            legacy = isinstance(loaded_data, dict) and str(loaded_data.get("version", "1.0")) in {"1.0", "1.1"}
            errors = self._validate_document(loaded_data, allow_legacy_geometry=legacy)
            if errors:
                raise ValueError("; ".join(errors))

            self.config_data = loaded_data
            self.validation_warnings = [
                f"{name} : le champ attributaire '{field_name}' utilise un nom réservé. Renommez-le avant d'enregistrer ou d'exécuter cette recette ; sa règle est conservée."
                for name, cfg in loaded_data["tables"].items()
                for field_name in cfg.get("calculated_fields", {})
                if field_name.casefold() == "geometry"
            ]
            for warning in self.validation_warnings:
                QgsMessageLog.logMessage(warning, "Transformer", MsgWarning)
            self._migrate_config_if_needed()
            self._persisted_data = copy.deepcopy(self.config_data)

            QgsMessageLog.logMessage(
                f"Loaded configuration: {len(self.config_data.get('tables', {}))} tables",
                "Transformer", MsgInfo,
            )
            return True

        except Exception as e:
            QgsMessageLog.logMessage(f"Config load error: {e}", "Transformer", MsgWarning)
            return False

    def save_config(self) -> bool:
        """Save configuration to JSON file atomically.

        Writes to a temp file in the same directory, then os.replace.
        Readers either see the old or the new file, never a half-written one.
        """
        try:
            self.config_data["last_modified"] = datetime.now().isoformat()
            self._write_json_atomically(self.config_file, self.config_data)
            QgsMessageLog.logMessage(
                f"Config saved atomically: {len(self.config_data.get('tables', {}))} tables",
                "Transformer", MsgInfo,
            )
            self._persisted_data = copy.deepcopy(self.config_data)
            return True
        except Exception as e:
            self.config_data = copy.deepcopy(self._persisted_data)
            QgsMessageLog.logMessage(f"Config save error: {e}", "Transformer", MsgCritical)
            return False

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _migrate_config_if_needed(self):
        """Add defaults in memory; opening the plugin never rewrites old recipes."""
        for table_config in self.config_data.get("tables", {}).values():
            table_config.setdefault("filter", {"enabled": False, "expression": ""})
            table_config.setdefault("recipe_version", 1)
            table_config.setdefault("field_definitions", {})

    @classmethod
    def _migrate_legacy_geometry_aliases(cls, document):
        """Convert only known legacy geometry aliases, without dropping attributes."""
        result = copy.deepcopy(document)
        if not isinstance(result, dict) or str(result.get("version", "1.0")) not in {"1.0", "1.1"}:
            return result
        tables = result.get("tables")
        if not isinstance(tables, dict):
            return result
        for cfg in tables.values():
            if not isinstance(cfg, dict) or not isinstance(cfg.get("calculated_fields"), dict):
                continue
            fields = cfg["calculated_fields"]
            value = fields.get("geometry")
            if isinstance(value, str) and (value == "$geometry" or value == cfg.get("geometry_expression")):
                cfg["geometry_expression"] = value
                del fields["geometry"]
                if isinstance(cfg.get("field_definitions"), dict):
                    cfg["field_definitions"].pop("geometry", None)
        return result

    @classmethod
    def _secret_metadata_paths(cls, value, path=""):
        """Names of business columns are not connection-secret metadata keys."""
        found = []
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = f"{path}.{key}" if path else str(key)
                if str(key).casefold() in {"secret", "password", "token", "passwd", "api_key", "access_token", "refresh_token"}:
                    found.append(next_path)
                if key in {"tables", "recipe_history", "calculated_fields", "field_definitions"} and isinstance(item, dict):
                    for column, metadata in item.items():
                        found.extend(cls._secret_metadata_paths(metadata, f"{next_path}.{column}"))
                else:
                    found.extend(cls._secret_metadata_paths(item, next_path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found.extend(cls._secret_metadata_paths(item, f"{path}[{index}]"))
        elif isinstance(value, str) and not path.endswith(tuple(f".calculated_fields.{c}" for c in ())):
            lowered = value.casefold()
            if ("postgresql://" in lowered or "postgres://" in lowered) and "@" in lowered and ":" in lowered.split("@", 1)[0].split("://", 1)[-1]:
                found.append(path or "uri")
        return found

    @classmethod
    def _validate_document(cls, document, allow_legacy_geometry=False):
        errors = []
        if not isinstance(document, dict) or not isinstance(document.get("tables"), dict):
            return ["Le document doit contenir un dictionnaire de recettes 'tables'."]
        if str(document.get("version", "1.0")) not in {"1.0", "1.1", cls._CONFIG_VERSION}:
            errors.append("Version de configuration non prise en charge.")
        for path in cls._secret_metadata_paths(document):
            errors.append(f"{path} : les secrets de connexion ne doivent pas être inclus dans une recette partageable. Utilisez le gestionnaire d'authentification QGIS.")
        history = document.get("recipe_history", {})
        if not isinstance(history, dict) or any(not isinstance(rows, list) for rows in history.values()):
            errors.append("Historique des recettes invalide.")
        for name, cfg in document["tables"].items():
            if not isinstance(name, str) or not name.strip() or not isinstance(cfg, dict):
                errors.append("Nom ou contenu de recette invalide.")
                continue
            fields = cfg.get("calculated_fields", {})
            if not isinstance(fields, dict) or any(
                not isinstance(key, str) or not key.strip() or not isinstance(value, str)
                for key, value in fields.items()
            ):
                errors.append(f"{name} : les champs doivent associer un nom à une expression.")
            elif not allow_legacy_geometry:
                for field_name in fields:
                    if field_name.casefold() == "geometry":
                        errors.append(f"{name}.{field_name} : nom réservé à la géométrie. Renommez ce champ attributaire ; placez une règle spatiale dans geometry_expression.")
            for key in ("source_file", "source_id", "target_crs", "geometry_expression"):
                if cfg.get(key) is not None and not isinstance(cfg[key], str):
                    errors.append(f"{name} : {key} doit être du texte.")
            revision = cfg.get("recipe_version", 1)
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                errors.append(f"{name} : version de recette invalide.")
            fc = cfg.get("filter", {})
            if not isinstance(fc, dict) or not isinstance(fc.get("enabled", False), bool) or not isinstance(fc.get("expression", ""), str):
                errors.append(f"{name} : filtre invalide.")
            destination = cfg.get("destination", {})
            if not isinstance(destination, dict):
                errors.append(f"{name}.destination : la destination doit être un objet ou être absente.")
            elif destination:
                kind = destination.get("kind")
                if not isinstance(kind, str) or kind not in {"file", "postgresql"}:
                    errors.append(f"{name}.destination.kind : choisir file ou postgresql.")
                if "replay" in destination and not isinstance(destination["replay"], bool):
                    errors.append(f"{name}.destination.replay : un booléen est attendu.")
                if kind == "file":
                    for key in ("path", "format", "encoding"):
                        if not isinstance(destination.get(key), str) or not destination[key].strip():
                            errors.append(f"{name}.destination.{key} : un texte non vide est attendu.")
                    if "selected_only" in destination and not isinstance(destination["selected_only"], bool):
                        errors.append(f"{name}.destination.selected_only : un booléen est attendu.")
                elif kind == "postgresql":
                    targets = destination.get("targets")
                    if not isinstance(targets, list):
                        errors.append(f"{name}.destination.targets : une liste de tables est attendue.")
                    else:
                        for index, target in enumerate(targets):
                            if not isinstance(target, dict):
                                errors.append(f"{name}.destination.targets[{index}] : un objet est attendu.")
                                continue
                            for key in ("schema", "table", "layer"):
                                if key in target and not isinstance(target[key], str):
                                    errors.append(f"{name}.destination.targets[{index}].{key} : du texte est attendu.")
                            if not all(isinstance(target.get(key), str) and target[key].strip() for key in ("schema", "table")):
                                errors.append(f"{name}.destination.targets[{index}] : renseigner schema et table.")
            definitions = cfg.get("field_definitions", {})
            if not isinstance(definitions, dict):
                errors.append(f"{name} : définitions de champs invalides.")
                continue
            for field_name, definition in definitions.items():
                if not isinstance(definition, dict) or not isinstance(definition.get("type", "Text"), str) or definition.get("type", "Text") not in cls.FIELD_TYPES:
                    errors.append(f"{name}.{field_name} : type de sortie invalide.")
                    continue
                for key in ("length", "precision"):
                    value = definition.get(key, 0)
                    maximum = 65535 if key == "length" else 30
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > maximum:
                        errors.append(f"{name}.{field_name} : {key} doit être un entier compris entre 0 et {maximum}.")
                if not isinstance(definition.get("description", ""), str):
                    errors.append(f"{name}.{field_name} : description invalide.")
        return errors

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
        field_definitions: Optional[Dict[str, Any]] = None,
        source_id: Optional[str] = None,
        source_schema: Optional[Dict[str, Any]] = None,
        destination: Optional[Dict[str, Any]] = None,
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
            QgsMessageLog.logMessage(message, "Transformer", MsgWarning)
            return {
                "success": False,
                "action": "rejected",
                "message": message,
                "replaced_table": None,
            }

        default_filter = {"enabled": False, "expression": ""}
        filter_config = dict(filter_config or default_filter)
        for key, default_value in default_filter.items():
            filter_config.setdefault(key, default_value)

        existing = copy.deepcopy(self.config_data["tables"].get(table_name, {}))
        recipe = copy.deepcopy(existing)
        recipe.update({
            "source_file": source_file,
            "calculated_fields": calculated_fields.copy(),
            "filter": filter_config,
            "target_crs": target_crs,
            "geometry_expression": geometry_expression,
        })
        for key, value in (("field_definitions", field_definitions), ("source_id", source_id), ("source_schema", source_schema), ("destination", destination)):
            if value is not None:
                recipe[key] = copy.deepcopy(value)
        recipe.setdefault("field_definitions", {})
        errors = self._validate_document({"version": self._CONFIG_VERSION, "tables": {table_name: recipe}})
        if errors:
            return {"success": False, "action": "rejected", "message": "; ".join(errors), "replaced_table": None}
        if existing and recipe != existing:
            history = self.config_data.setdefault("recipe_history", {}).setdefault(table_name, [])
            history.append(existing)
            if len(history) > self._MAX_RECIPE_HISTORY:
                del history[:-self._MAX_RECIPE_HISTORY]
            recipe["recipe_version"] = int(existing.get("recipe_version", 1)) + 1
        else:
            recipe.setdefault("recipe_version", 1)
        recipe.setdefault("recipe_id", str(uuid.uuid4()))
        self.config_data["tables"][table_name] = recipe
        self.config_data["version"] = self._CONFIG_VERSION

        filter_info = ""
        if is_filter_enabled(filter_config):
            expr = get_filter_expression(filter_config)
            truncated = f"{expr[:30]}..." if len(expr) > 30 else expr
            filter_info = f" with filter: {truncated}"

        QgsMessageLog.logMessage(
            f"Saved config for {table_name}: {len(calculated_fields)} fields{filter_info}",
            "Transformer", MsgInfo,
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
        result = copy.deepcopy(config)
        if "filter" not in result:
            result["filter"] = {"enabled": False, "expression": ""}
        return result

    def get_all_tables(self) -> Dict[str, Dict]:
        tables = self.config_data.get("tables", {})
        enhanced = {}
        for name, cfg in tables.items():
            entry = copy.deepcopy(cfg)
            entry['field_count'] = len(cfg.get('calculated_fields', {}))
            entry['has_filter'] = cfg.get('filter', {}).get('enabled', False)
            enhanced[name] = entry
        return enhanced

    def remove_table_config(self, table_name: str) -> bool:
        if "tables" in self.config_data and table_name in self.config_data["tables"]:
            del self.config_data["tables"][table_name]
            QgsMessageLog.logMessage(f"Removed config for {table_name}", "Transformer", MsgInfo)
            return True
        return False

    def get_tables_for_source(self, source_file: str, source_id: Optional[str] = None) -> List[str]:
        return [
            name
            for name, cfg in self.config_data.get("tables", {}).items()
            if (cfg.get("source_id") == (source_id or source_file) if cfg.get("source_id")
                else cfg.get("source_file") == source_file)
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
            cfg = self.get_table_config(table_name)
            result = self.add_table_config(table_name, cfg.get("source_file", ""), cfg.get("calculated_fields", {}),
                                           filter_config, cfg.get("target_crs"), cfg.get("geometry_expression"), force_replace=True)
            return bool(result["success"])
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
        self.last_export_error = ""
        try:
            errors = self._validate_document(self.config_data)
            if errors:
                raise ValueError("; ".join(errors))
            self._write_json_atomically(export_path, self.config_data)
            QgsMessageLog.logMessage(
                f"Configuration exported to {export_path}", "Transformer", MsgInfo,
            )
            return True
        except Exception as e:
            self.last_export_error = str(e)
            QgsMessageLog.logMessage(f"Export error: {e}", "Transformer", MsgWarning)
            return False

    def export_single_recipe(self, table_name: str, export_path: str) -> bool:
        """Export one validated recipe to a portable JSON file."""
        self.last_export_error = ""
        recipe = self.get_table_config(table_name)
        if recipe is None:
            self.last_export_error = f"core.config_manager: recette introuvable '{table_name}'."
            QgsMessageLog.logMessage(self.last_export_error, "Transformer", MsgWarning)
            return False
        payload = {
            "version": self._CONFIG_VERSION,
            "last_modified": datetime.now().isoformat(),
            "tables": {table_name: recipe},
        }
        try:
            errors = self._validate_document(payload)
            if errors:
                raise ValueError("; ".join(errors))
            self._write_json_atomically(export_path, payload)
            QgsMessageLog.logMessage(
                f"Single recipe '{table_name}' exported to {export_path}",
                "Transformer", MsgInfo,
            )
            return True
        except Exception as exc:
            self.last_export_error = (
                f"core.config_manager: echec d'export '{table_name}' vers '{export_path}' : {exc}"
            )
            QgsMessageLog.logMessage(self.last_export_error, "Transformer", MsgWarning)
            return False

    @staticmethod
    def _write_json_atomically(dest_path: str, payload: Dict[str, Any]) -> None:
        """Write JSON via temp file and os.replace in destination directory."""
        dest_dir = os.path.dirname(os.path.abspath(dest_path)) or "."
        os.makedirs(dest_dir, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(dest_path) + ".",
            suffix=".tmp",
            dir=dest_dir,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, dest_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError as cleanup_exc:
                QgsMessageLog.logMessage(
                    f"Config temp cleanup warning: {cleanup_exc}", "Transformer", MsgWarning,
                )
            raise

    @classmethod
    def load_recipe_document(cls, recipe_path: str) -> Dict[str, Any]:
        """Load, migrate and validate a standalone recipe or catalogue JSON."""
        if not recipe_path or not os.path.isfile(recipe_path):
            raise FileNotFoundError(
                f"core.config_manager: fichier de recette introuvable : '{recipe_path}'"
            )
        try:
            with open(recipe_path, "r", encoding="utf-8-sig") as stream:
                raw = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"core.config_manager: lecture JSON impossible pour '{recipe_path}' : {exc}"
            ) from exc

        if isinstance(raw, dict) and "tables" not in raw and isinstance(raw.get("calculated_fields"), dict):
            fallback_name = os.path.splitext(os.path.basename(recipe_path))[0] or "recette"
            document = {
                "version": str(raw.get("version", cls._CONFIG_VERSION)),
                "tables": {fallback_name: raw},
            }
        else:
            document = raw

        document = cls._migrate_legacy_geometry_aliases(document)
        legacy = isinstance(document, dict) and str(document.get("version", "1.0")) in {"1.0", "1.1"}
        errors = cls._validate_document(document, allow_legacy_geometry=legacy)
        if errors:
            raise ValueError(
                f"core.config_manager: recette invalide dans '{recipe_path}' : {'; '.join(errors)}"
            )
        for cfg in document["tables"].values():
            cfg.setdefault("filter", {"enabled": False, "expression": ""})
            cfg.setdefault("recipe_version", 1)
            cfg.setdefault("field_definitions", {})
        return document

    @classmethod
    def list_recipe_names(cls, plugin_dir: str, recipe_file: str = "") -> List[str]:
        """Return sorted recipe names from a JSON file or local catalogue."""
        if recipe_file:
            document = cls.load_recipe_document(recipe_file)
            return sorted(document.get("tables", {}).keys())
        config_path = os.path.join(plugin_dir, "calculated_fields_config.json")
        if not os.path.isfile(config_path) or os.path.getsize(config_path) == 0:
            return []
        document = cls.load_recipe_document(config_path)
        return sorted(document.get("tables", {}).keys())

    @classmethod
    def resolve_recipe(
        cls,
        plugin_dir: str,
        recipe_file: str = "",
        recipe_name: str = "",
    ) -> tuple:
        """Resolve one (recipe_name, recipe_dict) from file or local catalogue."""
        clean_file = (recipe_file or "").strip()
        clean_name = (recipe_name or "").strip()
        if not clean_file and not clean_name:
            raise ValueError(
                "core.config_manager: precisez un fichier de recette JSON (RECIPE_FILE) "
                "ou le nom d'une recette du catalogue local (RECIPE_NAME)."
            )

        if clean_file:
            document = cls.load_recipe_document(clean_file)
            tables = document.get("tables", {})
            if not tables:
                raise ValueError(
                    f"core.config_manager: aucune recette dans '{clean_file}'."
                )
            if clean_name:
                if clean_name not in tables:
                    available = ", ".join(sorted(tables.keys()))
                    raise ValueError(
                        f"core.config_manager: recette '{clean_name}' introuvable dans "
                        f"'{clean_file}'. Disponibles : {available}."
                    )
                return clean_name, copy.deepcopy(tables[clean_name])
            if len(tables) == 1:
                only_name = next(iter(tables.keys()))
                return only_name, copy.deepcopy(tables[only_name])
            available = ", ".join(sorted(tables.keys()))
            raise ValueError(
                f"core.config_manager: '{clean_file}' contient {len(tables)} recettes. "
                f"Renseignez RECIPE_NAME parmi : {available}."
            )

        config_path = os.path.join(plugin_dir, "calculated_fields_config.json")
        if not os.path.isfile(config_path):
            raise FileNotFoundError(
                f"core.config_manager: catalogue local absent ('{config_path}'). "
                f"Fournissez RECIPE_FILE ou enregistrez la recette '{clean_name}'."
            )
        document = cls.load_recipe_document(config_path)
        tables = document.get("tables", {})
        if clean_name not in tables:
            available = ", ".join(sorted(tables.keys())) or "aucune"
            raise ValueError(
                f"core.config_manager: recette '{clean_name}' introuvable dans le catalogue "
                f"local '{config_path}'. Disponibles : {available}."
            )
        return clean_name, copy.deepcopy(tables[clean_name])

    def preview_import_config(self, import_path: str) -> Dict[str, Any]:
        """Read and validate an import without changing the active catalogue."""
        try:
            with open(import_path, "r", encoding="utf-8") as stream:
                document = json.load(stream)
            document = self._migrate_legacy_geometry_aliases(document)
            errors = self._validate_document(document)
            names = list(document.get("tables", {})) if isinstance(document, dict) and isinstance(document.get("tables"), dict) else []
            return {
                "valid": not errors,
                "conflicts": [name for name in names if self.has_table_config(name)],
                "new_tables": [name for name in names if not self.has_table_config(name)],
                "errors": errors,
            }
        except Exception as exc:
            return {"valid": False, "conflicts": [], "new_tables": [], "errors": [str(exc)]}

    def import_config(self, import_path: str, conflict_policy: str = "reject") -> bool:
        """Atomically import validated recipes after an explicit conflict decision."""
        before = copy.deepcopy(self.config_data)
        try:
            if conflict_policy not in {"reject", "keep", "replace"}:
                raise ValueError("Politique de conflit inconnue.")
            # Read once for validation and commit: the preview is informative only.
            with open(import_path, "r", encoding="utf-8") as stream:
                imported = json.load(stream)
            imported = self._migrate_legacy_geometry_aliases(imported)
            errors = self._validate_document(imported)
            if errors:
                raise ValueError("; ".join(errors))
            conflicts = [name for name in imported["tables"] if self.has_table_config(name)]
            if conflicts and conflict_policy == "reject":
                self.last_import_result = {"success": False, "conflicts": conflicts, "errors": ["Choisissez de conserver ou remplacer les recettes homonymes."]}
                return False
            staged = copy.deepcopy(before)
            for key, value in imported.items():
                if key not in {"tables", "version", "last_modified", "recipe_history"}:
                    staged.setdefault(key, copy.deepcopy(value))
            for name, snapshots in imported.get("recipe_history", {}).items():
                if isinstance(snapshots, list):
                    staged.setdefault("recipe_history", {}).setdefault(name, []).extend(copy.deepcopy(snapshots))
            count = 0
            for name, cfg in imported["tables"].items():
                previous = staged["tables"].get(name)
                if previous is not None and conflict_policy == "keep":
                    continue
                recipe = copy.deepcopy(cfg)
                if previous is not None:
                    staged.setdefault("recipe_history", {}).setdefault(name, []).append(copy.deepcopy(previous))
                    recipe["recipe_id"] = previous.get("recipe_id", str(uuid.uuid4()))
                    recipe["recipe_version"] = max(previous.get("recipe_version", 1) + 1, recipe.get("recipe_version", 1))
                else:
                    recipe.setdefault("recipe_id", str(uuid.uuid4()))
                staged["tables"][name] = recipe
                count += 1
            staged["version"] = self._CONFIG_VERSION
            self.config_data = staged
            self._migrate_config_if_needed()
            if not self.save_config():
                self.config_data = before
                self.last_import_result = {"success": False, "conflicts": conflicts, "errors": ["L'import n'a pas été enregistré ; le catalogue précédent est conservé."]}
                return False
            self.last_import_result = {"success": True, "conflicts": conflicts, "imported_count": count, "errors": []}
            QgsMessageLog.logMessage(f"{count} recette(s) importée(s) et enregistrée(s)", "Transformer", MsgInfo)
            return True
        except Exception as exc:
            self.config_data = before
            self.last_import_result = {"success": False, "errors": [str(exc)], "conflicts": []}
            QgsMessageLog.logMessage(f"Import error: {exc}", "Transformer", MsgWarning)
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
            elif not cfg.get("source_id") and (os.path.isabs(source) or os.path.dirname(source)) and not os.path.exists(source):
                issues.append(f"Table '{name}': Source file not found: {source}")

            if not cfg.get("calculated_fields"):
                issues.append(f"Table '{name}': No calculated fields defined")

            fc = cfg.get("filter", {})
            if fc.get("enabled", False) and not fc.get("expression", "").strip():
                issues.append(f"Table '{name}': Filter enabled but no expression provided")

        return issues

    def cleanup_missing_sources(self) -> int:
        """Keep orphan recipes: an unavailable input never invalidates the recipe."""
        QgsMessageLog.logMessage(
            "Les recettes sont conservées, même lorsque leur source est indisponible. Reliez une source pour les rejouer.",
            "Transformer", MsgInfo,
        )
        return 0
