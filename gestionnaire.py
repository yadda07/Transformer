# -*- coding: utf-8 -*-
"""
Config mgr for shapefile transform settings
Filter support for transforms
"""

import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime

from qgis.core import QgsMessageLog, Qgis


class SimpleConfigManager:
    """Transform configs for shapefiles w/ filter support"""
    
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.config_file = os.path.join(plugin_dir, 'calculated_fields_config.json')
        self.config_data = {
            "version": "1.1",  # Version w/ filters
            "last_modified": datetime.now().isoformat(),
            "tables": {}
        }
        self.load_config()
    
    def load_config(self) -> bool:
        """Config from JSON file"""
        try:
            if os.path.exists(self.config_file):
                # Check if file is empty
                if os.path.getsize(self.config_file) == 0:
                    QgsMessageLog.logMessage("Config file is empty, initializing with default structure", "Transformer", Qgis.Info)
                    self.save_config()
                    return True
                
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                
                # Validate loaded data structure
                if not isinstance(loaded_data, dict) or 'tables' not in loaded_data:
                    QgsMessageLog.logMessage("Invalid config structure, reinitializing", "Transformer", Qgis.Warning)
                    self.save_config()
                    return True
                
                self.config_data = loaded_data
                
                # Migration from old ver if needed
                self._migrate_config_if_needed()
                
                QgsMessageLog.logMessage(
                    f"Loaded configuration: {len(self.config_data.get('tables', {}))} tables", 
                    "Transformer", Qgis.Info
                )
                return True
            else:
                QgsMessageLog.logMessage("Config file doesn't exist, creating with default structure", "Transformer", Qgis.Info)
                self.save_config()
                return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Config load error: {str(e)}", "Transformer", Qgis.Warning)
            return False
    
    def _migrate_config_if_needed(self):
        """Migrate config to newer ver if needed"""
        current_version = self.config_data.get("version", "1.0")
        
        if current_version == "1.0":
            # Migration to v1.1 - add filter support
            for table_name, table_config in self.config_data.get("tables", {}).items():
                if "filter" not in table_config:
                    table_config["filter"] = {
                        "enabled": False,
                        "expression": ""
                    }
            
            self.config_data["version"] = "1.1"
            QgsMessageLog.logMessage("Migrated configuration to version 1.1", "Transformer", Qgis.Info)
            self.save_config()
    
    def save_config(self) -> bool:
        """Config to JSON file"""
        try:
            self.config_data["last_modified"] = datetime.now().isoformat()
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Config save error: {str(e)}", "Transformer", Qgis.Warning)
            return False
    
    def add_table_config(self, table_name: str, source_file: str, calculated_fields: Dict[str, str], 
                        filter_config: Optional[Dict[str, Any]] = None, target_crs: Optional[str] = None, 
                        geometry_expression: Optional[str] = None, force_replace: bool = False):
        """Add or update table configuration with filter support
        
        Args:
            table_name: Name of the table
            source_file: Source shapefile path
            calculated_fields: Dictionary of calculated fields
            filter_config: Filter configuration (optional)
            target_crs: Target CRS for reprojection (optional)
            force_replace: If True, replace existing configuration without warning
            
        Returns:
            dict: {"success": bool, "action": str, "message": str, "replaced_table": str or None}
        """
        if "tables" not in self.config_data:
            self.config_data["tables"] = {}
        
        # Check if configuration already exists for this table name
        if table_name in self.config_data["tables"] and not force_replace:
            existing_config = self.config_data["tables"][table_name]
            existing_source = existing_config.get("source_file", "")
            
            message = f"Configuration already exists for table '{table_name}' (source: {existing_source})"
            QgsMessageLog.logMessage(message, "Transformer", Qgis.Warning)
            return {"success": False, "action": "rejected", "message": message, "replaced_table": None}
        
        # Allow multiple configurations per source_file - uniqueness is based on (source_file, table_name) tuple
        # No need to remove existing configurations for the same source_file
        existing_table_for_source = None  # No replacement since we allow multiple configs per source
        
        # Configuration par défaut du filtre
        default_filter = {
            "enabled": False,
            "expression": ""
        }
        
        # Utiliser la configuration de filtre fournie ou la valeur par défaut
        if filter_config is None:
            filter_config = default_filter
        else:
            # S'assurer que toutes les clés nécessaires sont présentes
            for key, default_value in default_filter.items():
                if key not in filter_config:
                    filter_config[key] = default_value
            
        self.config_data["tables"][table_name] = {
            "source_file": source_file,
            "calculated_fields": calculated_fields.copy(),
            "filter": filter_config,
            "target_crs": target_crs,
            "geometry_expression": geometry_expression
        }
        
        filter_info = ""
        if filter_config.get("enabled", False):
            filter_expr = filter_config.get("expression", "")
            filter_info = f" with filter: {filter_expr[:30]}..." if len(filter_expr) > 30 else f" with filter: {filter_expr}"
        
        action = "Updated" if existing_table_for_source or table_name in self.config_data.get("tables", {}) else "Added"
        replaced_info = f" (replaced '{existing_table_for_source}')" if existing_table_for_source else ""
        
        QgsMessageLog.logMessage(
            f"{action} config for {table_name}: {len(calculated_fields)} fields{filter_info}{replaced_info}", 
            "Transformer", Qgis.Info
        )
        
        return {
            "success": True, 
            "action": action.lower(), 
            "message": f"Configuration {action.lower()} successfully for '{table_name}'",
            "replaced_table": existing_table_for_source
        }
    
    def has_table_config(self, table_name: str) -> bool:
        """Config exists for table name"""
        return table_name in self.config_data.get("tables", {})
    
    def replace_table_config(self, table_name: str, source_file: str, calculated_fields: Dict[str, str], 
                           filter_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Replace existing table config (force replace)
        
        Args:
            table_name: Name of the table
            source_file: Source shapefile path
            calculated_fields: Dictionary of calculated fields
            filter_config: Filter configuration (optional)
            
        Returns:
            dict: {"success": bool, "action": str, "message": str, "replaced_table": str or None}
        """
        return self.add_table_config(table_name, source_file, calculated_fields, filter_config, force_replace=True)
    
    def get_table_config(self, table_name: str) -> Optional[Dict]:
        """Config for specific table"""
        config = self.config_data.get("tables", {}).get(table_name)
        
        if config:
            # Ensure filter config exists
            if "filter" not in config:
                config["filter"] = {
                    "enabled": False,
                    "expression": ""
                }
        
        return config
    
    def get_all_tables(self) -> Dict[str, Dict]:
        """All table configs"""
        tables = self.config_data.get("tables", {})
        
        # Add CRS info and field count to each table config for display
        enhanced_tables = {}
        for table_name, config in tables.items():
            enhanced_config = config.copy()
            enhanced_config['field_count'] = len(config.get('calculated_fields', {}))
            enhanced_config['has_filter'] = config.get('filter', {}).get('enabled', False)
            enhanced_tables[table_name] = enhanced_config
        
        return enhanced_tables
    
    def get_all_table_configs(self) -> Dict[str, Dict]:
        """Alias for get_all_tables for compatibility"""
        return self.get_all_tables()
    
    def remove_table_config(self, table_name: str) -> bool:
        """Remove table config"""
        if "tables" in self.config_data and table_name in self.config_data["tables"]:
            del self.config_data["tables"][table_name]
            QgsMessageLog.logMessage(f"Removed config for {table_name}", "Transformer", Qgis.Info)
            return True
        return False
    
    def get_tables_for_source(self, source_file: str) -> List[str]:
        """Tables for specific source file"""
        tables = []
        for table_name, config in self.config_data.get("tables", {}).items():
            if config.get("source_file") == source_file:
                tables.append(table_name)
        return tables
    
    def get_table_filter_config(self, table_name: str) -> Dict[str, Any]:
        """Filter config for specific table"""
        config = self.get_table_config(table_name)
        if config:
            return config.get("filter", {"enabled": False, "expression": ""})
        return {"enabled": False, "expression": ""}
    
    def update_table_filter(self, table_name: str, filter_config: Dict[str, Any]) -> bool:
        """Update filter config for table"""
        if "tables" in self.config_data and table_name in self.config_data["tables"]:
            self.config_data["tables"][table_name]["filter"] = filter_config
            
            filter_info = "disabled"
            if filter_config.get("enabled", False):
                filter_expr = filter_config.get("expression", "")
                filter_info = f"enabled: {filter_expr[:30]}..." if len(filter_expr) > 30 else f"enabled: {filter_expr}"
            
            QgsMessageLog.logMessage(
                f"Updated filter for {table_name}: {filter_info}", 
                "Transformer", Qgis.Info
            )
            return True
        return False
    
    def get_filtered_tables_count(self) -> int:
        """Count of tables w/ enabled filters"""
        count = 0
        for table_name, config in self.config_data.get("tables", {}).items():
            filter_config = config.get("filter", {})
            if filter_config.get("enabled", False) and filter_config.get("expression", "").strip():
                count += 1
        return count
    
    def export_config(self, export_path: str) -> bool:
        """Export config to file"""
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
            QgsMessageLog.logMessage(f"Configuration exported to {export_path}", "Transformer", Qgis.Info)
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Export error: {str(e)}", "Transformer", Qgis.Warning)
            return False
    
    def import_config(self, import_path: str) -> bool:
        """Import config from file and merge with existing calculated_fields_config.json"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
            
            if "tables" in imported_data:
                # Initialize tables dict if not exists
                if "tables" not in self.config_data:
                    self.config_data["tables"] = {}
                
                # Merge imported tables with existing ones in calculated_fields_config.json
                imported_tables = imported_data.get("tables", {})
                merged_count = 0
                overwritten_count = 0
                
                for table_name, table_config in imported_tables.items():
                    if table_name in self.config_data["tables"]:
                        overwritten_count += 1
                        QgsMessageLog.logMessage(f"Overwriting existing config for table '{table_name}'", "Transformer", Qgis.Info)
                    else:
                        merged_count += 1
                    
                    # Merge the table config into calculated_fields_config.json
                    self.config_data["tables"][table_name] = table_config
                
                # Update version and timestamp from imported file if newer
                imported_version = imported_data.get("version", "1.0")
                if imported_version >= self.config_data.get("version", "1.0"):
                    self.config_data["version"] = imported_version
                
                # Migration if needed after import
                self._migrate_config_if_needed()
                
                self.save_config()
                
                # Log summary of import operation
                total_imported = len(imported_tables)
                QgsMessageLog.logMessage(
                    f"Configuration merged from {import_path}: {total_imported} table(s) imported "
                    f"({merged_count} new, {overwritten_count} updated)", 
                    "Transformer", Qgis.Info
                )
                return True
            else:
                QgsMessageLog.logMessage("Invalid configuration format", "Transformer", Qgis.Warning)
                return False
        except Exception as e:
            QgsMessageLog.logMessage(f"Import error: {str(e)}", "Transformer", Qgis.Warning)
            return False
    
    def get_config_summary(self) -> Dict[str, Any]:
        """Summary of current config"""
        tables = self.config_data.get("tables", {})
        
        total_tables = len(tables)
        filtered_tables = self.get_filtered_tables_count()
        total_fields = sum(len(config.get("calculated_fields", {})) for config in tables.values())
        
        source_files = set()
        for config in tables.values():
            source_file = config.get("source_file", "")
            if source_file:
                source_files.add(source_file)
        
        return {
            "version": self.config_data.get("version", "1.0"),
            "last_modified": self.config_data.get("last_modified", ""),
            "total_tables": total_tables,
            "tables_with_filters": filtered_tables,
            "total_calculated_fields": total_fields,
            "unique_source_files": len(source_files),
            "source_files": list(source_files)
        }
    
    def validate_config(self) -> List[str]:
        """Validate config & return issues list"""
        issues = []
        
        tables = self.config_data.get("tables", {})
        if not tables:
            issues.append("No tables configured")
            return issues
        
        for table_name, config in tables.items():
            # Check source file
            source_file = config.get("source_file", "")
            if not source_file:
                issues.append(f"Table '{table_name}': No source file specified")
            elif not os.path.exists(source_file):
                issues.append(f"Table '{table_name}': Source file not found: {source_file}")
            
            # Check calc fields
            calculated_fields = config.get("calculated_fields", {})
            if not calculated_fields:
                issues.append(f"Table '{table_name}': No calculated fields defined")
            
            # Check filter config
            filter_config = config.get("filter", {})
            if filter_config.get("enabled", False):
                filter_expr = filter_config.get("expression", "").strip()
                if not filter_expr:
                    issues.append(f"Table '{table_name}': Filter enabled but no expression provided")
        
        return issues
    
    def cleanup_missing_sources(self) -> int:
        """Remove configs for missing source files"""
        removed_count = 0
        tables_to_remove = []
        
        for table_name, config in self.config_data.get("tables", {}).items():
            source_file = config.get("source_file", "")
            if source_file and not os.path.exists(source_file):
                tables_to_remove.append(table_name)
        
        for table_name in tables_to_remove:
            if self.remove_table_config(table_name):
                removed_count += 1
        
        if removed_count > 0:
            self.save_config()
            QgsMessageLog.logMessage(
                f"Cleaned up {removed_count} configurations with missing source files", 
                "Transformer", Qgis.Info
            )
        
        return removed_count
    
    def cleanup_duplicate_source_files(self) -> int:
        """Remove duplicate configurations for the same source_file, keeping only the most recent"""
        source_file_mapping = {}  # source_file -> [(table_name, config)]
        tables_to_remove = []
        
        # Group configurations by source_file
        for table_name, config in self.config_data.get("tables", {}).items():
            source_file = config.get("source_file", "")
            if source_file:
                if source_file not in source_file_mapping:
                    source_file_mapping[source_file] = []
                source_file_mapping[source_file].append((table_name, config))
        
        # Find duplicates and mark for removal (keep the last one)
        removed_count = 0
        for source_file, configs in source_file_mapping.items():
            if len(configs) > 1:
                # Sort by table_name to have consistent behavior
                configs.sort(key=lambda x: x[0])
                # Keep the last one, remove the others
                for table_name, _ in configs[:-1]:
                    tables_to_remove.append(table_name)
                    QgsMessageLog.logMessage(
                        f"Marking duplicate configuration '{table_name}' for removal (source: {source_file})", 
                        "Transformer", Qgis.Info
                    )
        
        # Remove duplicates
        for table_name in tables_to_remove:
            if self.remove_table_config(table_name):
                removed_count += 1
        
        if removed_count > 0:
            self.save_config()
            QgsMessageLog.logMessage(
                f"Cleaned up {removed_count} duplicate source_file configurations", 
                "Transformer", Qgis.Info
            )
        
        return removed_count