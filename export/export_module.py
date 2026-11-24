# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Secure export module for Transformer plugin
QGIS compat across versions
"""

import codecs
import math
import os
import re
import shutil
import sqlite3
import uuid
import zipfile
from pathlib import Path
from contextlib import closing
from enum import Enum

try:
    from osgeo import ogr
except ImportError:
    ogr = None

# Secure imports w/ error handling
EXPORT_AVAILABLE = False
try:
    # QGIS core
    from qgis.core import (QgsProject, QgsVectorLayer, QgsVectorFileWriter,
                           QgsMessageLog, QgsWkbTypes, QgsApplication,
                           QgsTask, QgsVectorFileWriterTask,
                           QgsVectorLayerFeatureSource, QgsFeatureRequest, Qgis, QgsVariantUtils)
    from qgis.gui import QgsMessageBar

    # Qt
    from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, QMetaType
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                                     QTreeWidget, QTreeWidgetItem, QPushButton,
                                     QComboBox, QLabel, QMessageBox, QFileDialog,
                                     QRadioButton, QButtonGroup, QCheckBox, QProgressBar)

    EXPORT_AVAILABLE = True
    from ..shared.compat import UserRole, MsgBoxYes, MsgBoxNo, MultiSelection, MsgInfo, MsgWarning, MsgCritical, MsgSuccess, WriterNoError
    from ..shared.icons import icon as ui_icon

    def _vector_file_action(*names, fallback_int=None):
        """Resolve QgsVectorFileWriter.ActionOnExistingFile across QGIS versions."""
        scoped = getattr(QgsVectorFileWriter, 'ActionOnExistingFile', QgsVectorFileWriter)
        for name in names:
            value = getattr(scoped, name, None)
            if value is not None:
                return value
            value = getattr(QgsVectorFileWriter, name, None)
            if value is not None:
                return value
        if fallback_int is not None:
            return fallback_int
        raise AttributeError(f"QgsVectorFileWriter action not found: {', '.join(names)}")

    GPKG_ACTION_CREATE_FILE = _vector_file_action('CreateOrOverwriteFile', fallback_int=0)
    GPKG_ACTION_ADD_LAYER = _vector_file_action('CreateOrOverwriteLayer', fallback_int=1)

except Exception:
    # Empty classes for compat
    class QObject:
        def __init__(self):
            pass

    class QWidget:
        def __init__(self, parent=None):
            pass

    QgsTask = QObject

    def pyqtSignal(*args, **kwargs):
        return lambda: None


class ExportFormat(Enum):
    """EFs w/ native QGIS API"""
    SHAPEFILE = "ESRI Shapefile"
    GEOPACKAGE = "GeoPackage"
    GEOJSON = "GeoJSON"
    KML = "Keyhole Markup Language"
    CSV = "Comma Separated Values"
    XLSX = "MS Excel (xlsx)"
    DXF = "AutoCAD DXF"
    TAB = "MapInfo TAB"
    GML = "Geography Markup Language"
    SQLITE = "SQLite/SpatiaLite"
    FLATGEOBUF = "FlatGeobuf"


class ExportManager(QObject):
    """Export mgr"""

    def __init__(self):
        super().__init__()

        if not EXPORT_AVAILABLE:
            return

        # File exts for all formats
        self.format_extensions = {
            ExportFormat.SHAPEFILE: ".shp",
            ExportFormat.GEOPACKAGE: ".gpkg",
            ExportFormat.GEOJSON: ".geojson",
            ExportFormat.KML: ".kml",
            ExportFormat.CSV: ".csv",
            ExportFormat.XLSX: ".xlsx",
            ExportFormat.DXF: ".dxf",
            ExportFormat.TAB: ".tab",
            ExportFormat.GML: ".gml",
            ExportFormat.SQLITE: ".sqlite",
            ExportFormat.FLATGEOBUF: ".fgb"
        }

        # Mapping to native QGIS drivers
        self.driver_mapping = {
            ExportFormat.SHAPEFILE: "ESRI Shapefile",
            ExportFormat.GEOPACKAGE: "GPKG",
            ExportFormat.GEOJSON: "GeoJSON",
            ExportFormat.KML: "KML",
            ExportFormat.CSV: "CSV",
            ExportFormat.XLSX: "XLSX",
            ExportFormat.DXF: "DXF",
            ExportFormat.TAB: "MapInfo File",
            ExportFormat.GML: "GML",
            ExportFormat.SQLITE: "SQLite",
            ExportFormat.FLATGEOBUF: "FlatGeobuf"
        }

        # Formats supporting geometry
        self.geometry_formats = {
            ExportFormat.SHAPEFILE, ExportFormat.GEOPACKAGE, ExportFormat.GEOJSON,
            ExportFormat.KML, ExportFormat.DXF, ExportFormat.TAB,
            ExportFormat.GML, ExportFormat.SQLITE, ExportFormat.FLATGEOBUF
        }

        # Formats attribute only
        self.attribute_only_formats = {ExportFormat.CSV, ExportFormat.XLSX}

    def get_transformed_layers(self):
        """Get transformed layers"""
        if not EXPORT_AVAILABLE:
            return []

        layers = []
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                layers.append(layer)
        return sorted(layers, key=lambda x: x.name())

    def export_layer(self, layer, output_path, export_format, selected_features_only=False, encoding="utf-8"):
        """Export layer w/ complete QGIS API"""
        if not EXPORT_AVAILABLE:
            return False, "Module d'export non disponible"

        try:
            # Prep
            if not layer or not layer.isValid():
                return False, "Couche invalide"

            # Get driver for fmt
            driver_name = self.driver_mapping.get(export_format)
            if not driver_name:
                return False, f"Format {export_format.value} not supported"

            # Count features
            if selected_features_only and layer.selectedFeatureCount() > 0:
                feature_count = layer.selectedFeatureCount()
            else:
                feature_count = layer.featureCount()

            if feature_count == 0:
                return False, "No features to export"

            preflight = ExportPreflight(layer, export_format, encoding, driver_name,
                                        selected_features_only and layer.selectedFeatureCount() > 0)
            issues = preflight.check()
            if issues:
                return False, "; ".join(ExportPreflight.messages(issues))

            # Config export opts
            export_options = QgsVectorFileWriter.SaveVectorOptions()
            export_options.driverName = driver_name
            export_options.fileEncoding = encoding  # Use provided enc
            export_options.onlySelectedFeatures = selected_features_only and layer.selectedFeatureCount() > 0

            # Fmt specific opts
            self._configure_format_options(export_format, export_options, layer)

            # Execute export w/ native QGIS API
            if export_format in self.attribute_only_formats:
                # Tabular fmts, export w/o geom
                success, message = self._export_attributes_only(layer, output_path, export_format, export_options)
            else:
                # Std export w/ geom
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), export_options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"

                if error_code == WriterNoError:
                    success, message = True, f"Export réussi : {feature_count} entité(s)"
                else:
                    success, message = False, f"Erreur d'export : {error_message}"

            # Log detail
            if success:
                QgsMessageLog.logMessage(
                    f" Export successful - Layer: {layer.name()}, Format: {export_format.value}, "
                    f"Features: {feature_count}, Size: {self._get_file_size(output_path)} Ko",
                    "Transformer", MsgSuccess
                )
            else:
                QgsMessageLog.logMessage(
                    f" Export failed - Layer: {layer.name()}, Error: {message}",
                    "Transformer", MsgCritical
                )

            return success, message

        except Exception as e:
            error_msg = f"Unexpected error during export : {str(e)}"
            QgsMessageLog.logMessage(f" {error_msg}", "Transformer", MsgCritical)
            return False, error_msg

    def export_layers_to_single_geopackage(self, layers, output_path, encoding="utf-8",
                                           selected_features_only=False):
        """Export several layers into one GeoPackage file."""
        if not EXPORT_AVAILABLE:
            return False, "Module d'export non disponible", 0, 0

        if not layers:
            return False, "Aucune couche à exporter", 0, 0

        exported_count = 0
        failed_count = 0
        total_features = 0
        used_table_names = set()
        errors = []

        # Validate every layer before writing the first table.
        issues = []
        for layer in layers:
            if layer and layer.isValid():
                issues.extend(ExportPreflight(layer, ExportFormat.GEOPACKAGE, encoding, "GPKG").check())
        if issues:
            return False, "; ".join(ExportPreflight.messages(issues)), 0, len(layers)

        for layer in layers:
            if not layer or not layer.isValid():
                failed_count += 1
                layer_label = layer.name() if layer else "Couche"
                errors.append(f"{layer_label} : couche invalide")
                continue

            if selected_features_only and layer.selectedFeatureCount() > 0:
                feature_count = layer.selectedFeatureCount()
            else:
                feature_count = layer.featureCount()

            if feature_count == 0:
                failed_count += 1
                errors.append(f"{layer.name()} : aucune entité à exporter")
                continue

            table_name = self._sanitize_gpkg_table_name(layer.name(), used_table_names)

            export_options = QgsVectorFileWriter.SaveVectorOptions()
            export_options.driverName = "GPKG"
            export_options.fileEncoding = encoding
            export_options.onlySelectedFeatures = (
                selected_features_only and layer.selectedFeatureCount() > 0
            )
            if hasattr(export_options, "layerName"):
                export_options.layerName = table_name
            export_options.layerOptions = [
                f"IDENTIFIER={table_name}",
                f"LAYERNAME={table_name}",
            ]
            export_options.actionOnExistingFile = (
                GPKG_ACTION_ADD_LAYER
                if os.path.exists(output_path)
                else GPKG_ACTION_CREATE_FILE
            )

            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, output_path, QgsProject.instance().transformContext(), export_options
            )
            error_code = result[0]
            error_message = result[1] if len(result) > 1 else "Erreur inconnue"

            if error_code == WriterNoError:
                exported_count += 1
                total_features += feature_count
                QgsMessageLog.logMessage(
                    f" Export GeoPackage - {layer.name()} "
                    f"→ table '{table_name}' ({feature_count} entité(s))",
                    "Transformer", MsgSuccess
                )
            else:
                failed_count += 1
                errors.append(f"{layer.name()} : {error_message}")
                QgsMessageLog.logMessage(
                    f" Export GeoPackage échoué - {layer.name()} : {error_message}",
                    "Transformer", MsgCritical
                )

        if exported_count == 0:
            detail = errors[0] if len(errors) == 1 else "; ".join(errors[:3])
            return False, f"Aucune couche exportée ({detail})", exported_count, failed_count

        if failed_count == 0:
            return (
                True,
                f"{exported_count} couche(s) exportée(s) ({total_features} entité(s)) "
                f"dans {os.path.basename(output_path)}",
                exported_count,
                failed_count,
            )

        return (
            False,
            f"{exported_count} couche(s) exportée(s), {failed_count} échec(s) : "
            f"{'; '.join(errors[:3])}",
            exported_count,
            failed_count,
        )

    @staticmethod
    def _sanitize_gpkg_table_name(name, used_names):
        """Normalize layer names for GeoPackage table identifiers."""
        sanitized = re.sub(r"[^\w]", "_", name, flags=re.UNICODE)
        if not sanitized or sanitized[0].isdigit():
            sanitized = f"layer_{sanitized}"
        sanitized = sanitized[:63]

        base = sanitized
        counter = 1
        while sanitized.lower() in {existing.lower() for existing in used_names}:
            suffix = f"_{counter}"
            sanitized = f"{base[:63 - len(suffix)]}{suffix}"
            counter += 1

        used_names.add(sanitized)
        return sanitized

    def _configure_format_options(self, export_format, options, layer):
        """Config fmt specific opts"""
        if export_format == ExportFormat.SHAPEFILE:
            options.layerOptions = ['ENCODING=' + options.fileEncoding]
        elif export_format == ExportFormat.TAB:
            options.layerOptions = ['ENCODING=' + options.fileEncoding.upper()]
        elif export_format == ExportFormat.GEOPACKAGE:
            options.layerOptions = ['IDENTIFIER=' + layer.name()]
        elif export_format == ExportFormat.GEOJSON:
            options.layerOptions = ['RFC7946=YES', 'WRITE_BBOX=YES', 'AUTODETECT_JSON_STRINGS=NO']
        elif export_format == ExportFormat.KML:
            options.layerOptions = ['NameField=' + (layer.fields().names()[0] if layer.fields().count() > 0 else '')]
        elif export_format == ExportFormat.DXF:
            options.layerOptions = ['MODE=OGR_STYLE']
        elif export_format == ExportFormat.GML:
            options.layerOptions = ['FORMAT=GML3', 'GML3_LONGSRS=YES']
        elif export_format == ExportFormat.SQLITE:
            options.layerOptions = ['SPATIALITE=YES']

    def _export_attributes_only(self, layer, output_path, export_format, options):
        """Export specialized for attr-only fmts (CSV, XLSX)"""
        try:
            if export_format == ExportFormat.CSV:
                # CSV export - config optimized
                options.layerOptions = [
                    'GEOMETRY=AS_WKT',  # Geom in WKT fmt
                    'CREATE_CSVT=YES',  # Create type file
                    'SEPARATOR=COMMA',  # Std comma sep
                    'STRING_QUOTING=IF_NEEDED'  # Quotes if needed
                ]
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
            elif export_format == ExportFormat.XLSX:
                # Excel export - config optimized
                options.layerOptions = [
                    'FIELD_TYPES=AUTO',  # Auto field types
                    'GEOMETRY=AS_WKT'    # Geom in WKT for Excel
                ]
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
            else:
                return False, f"Format attributaire {export_format.value} not implemented"

            if error_code == WriterNoError:
                return True, f"Export tabular successful : {layer.featureCount()} records"
            else:
                return False, f"Export tabular error : {error_message}"

        except Exception as e:
            return False, f"Export tabular error : {str(e)}"

    def _get_file_size(self, file_path):
        """File size in Ko"""
        try:
            return os.path.getsize(file_path) // 1024
        except Exception:
            return 0


class ExportPreflight:
    """Capture schema on the GUI thread; check snapshot values in a worker.

    DBF limits are driver specific, in encoded bytes. Other drivers advertise
    their creation types through GDAL metadata; no DBF limit is applied to them.
    """

    def __init__(self, layer, export_format, encoding, driver_name, selected=False):
        self.layer_name = layer.name()
        self.feature_count = layer.selectedFeatureCount() if selected else layer.featureCount()
        self.export_format = export_format
        self.encoding = encoding
        self.issues = []
        self.fields = list(layer.fields())
        self.string_fields = []
        self.string_limits = {}
        self.real_fields = []
        self.source = None
        self.request = None
        driver = ogr.GetDriverByName(driver_name) if ogr is not None else None
        metadata = driver.GetMetadata() if driver is not None else {}
        supported = set(metadata.get("DMD_CREATIONFIELDDATATYPES", "").split())
        subtypes = set(metadata.get("DMD_CREATIONFIELDDATASUBTYPES", "").split())
        shapefile = export_format == ExportFormat.SHAPEFILE
        mapinfo = export_format == ExportFormat.TAB
        fixed_text = shapefile or mapinfo
        if shapefile:
            supported = supported or {"Integer", "Integer64", "Real", "String", "Date"}
        if fixed_text:
            try:
                codec = codecs.lookup(encoding)
                # DBF stores names as C strings; UTF-16/32 contain zero bytes.
                if b"\0" in "A".encode(codec.name):
                    self._add("", "encoding", f"L'encodage {encoding} contient des octets nuls et ne convient pas à {driver_name}. Choisissez UTF-8 ou un encodage mono-octet.")
            except LookupError:
                self._add("", "encoding", f"Encodage inconnu : {encoding}. Choisissez UTF-8.")
            if mapinfo and encoding.lower() not in {"utf-8", "iso-8859-1", "cp1252"}:
                self._add("", "encoding", f"Le jeu de caractères TAB ne correspond pas à {encoding}. Choisissez UTF-8 ou Windows-1252.")
        names = {}
        type_mapping = {
            "Int": "Integer", "LongLong": "Integer64", "Bool": "Integer",
            "Double": "Real", "QString": "String", "QDate": "Date",
            "QTime": "Time", "QDateTime": "DateTime", "QByteArray": "Binary",
            "QStringList": "StringList",
        }
        for index, field in enumerate(self.fields):
            name = field.name()
            kind = self._kind(field.type())
            target_type = type_mapping.get(kind)
            if kind == "QVariantList":
                target_type = type_mapping.get(self._kind(field.subType()), "") + "List"
            if kind in {"QVariantList", "QVariantMap", "QStringList"} and driver_name == "GPKG":
                self._add(name, "type_conversion", "Ce type complexe serait converti en texte JSON. Choisissez explicitement une représentation avant l'export.")
            elif kind == "QVariantMap" and "JSON" in subtypes:
                pass
            elif (target_type is None or (supported and target_type not in supported)
                  or (kind in {"QStringList", "QVariantList"} and target_type not in supported)
                  or (kind == "LongLong" and driver is not None and "Integer64" not in supported)):
                self._add(name, "unsupported_type", f"Le pilote {driver_name} ne conserve pas le type {field.typeName()} de ce champ. Choisissez un format compatible (GeoPackage pour les types simples) ou définissez une conversion explicite.")
            if driver_name == "SQLite" and name.casefold() == "ogc_fid":
                self._add(name, "reserved_name", "SQLite renommerait le champ réservé ogc_fid. Choisissez un autre nom explicitement ou un autre format.")
            if export_format == ExportFormat.DXF and name.casefold() not in {
                "layer", "paperspace", "subclasses", "linetype", "entityhandle", "text", "blockname",
                "blockscale", "blockangle", "blockocsnormal", "blockocscoords", "blockattributes", "block", "attributetag", "ogr_style",
            }:
                self._add(name, "unsupported_field", "DXF ne conserve que ses attributs graphiques prédéfinis. Choisissez GeoPackage pour conserver ce champ métier.")
            if export_format == ExportFormat.GML and (
                not name or re.sub(r"[^a-zA-Z0-9_.\u0080-\U0010ffff]", "_", name) != name
                or name[0].isdigit() or name[0] == "."
            ):
                self._add(name, "field_name", "Le nom serait modifié ou invalide en GML. Définissez un nom XML compatible explicitement ou choisissez GeoPackage.")
            if not fixed_text:
                continue
            try:
                encoded = name.encode(encoding, errors="strict")
            except (UnicodeError, LookupError):
                self._add(name, "name_encoding", f"Le nom du champ ne peut pas être écrit en {encoding}. Choisissez UTF-8.")
                continue
            # GDAL CPLScanString trims trailing spaces and replaces ':' by '_'.
            limit = 10 if shapefile else 31
            normalized = encoded[:limit]
            if shapefile:
                normalized = normalized.rstrip(b" \t\r\n\v\f").replace(b":", b"_")
            elif not re.fullmatch(rb"[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*", encoded):
                self._add(name, "field_name", "Le nom TAB serait nettoyé par le pilote. Utilisez un nom explicite sans ponctuation ni espace, ou choisissez GeoPackage.")
            if len(encoded) > limit or normalized != encoded or not encoded or b"\0" in encoded:
                self._add(name, "field_name", f"Le nom {driver_name} doit tenir sur {limit} octets sans normalisation. Renommez ce champ explicitement ou choisissez GeoPackage.")
            key = normalized.upper()
            if key in names:
                self._add(name, "name_collision", f"Collision {driver_name} avec le champ '{names[key]}' après limite de {limit} octets, sans distinction de casse.")
            names[key] = name
            if kind == "QString":
                if field.length() > 254:
                    self._add(name, "field_width", f"La largeur déclarée {field.length()} dépasse les 254 octets du texte {driver_name}. Choisissez GeoPackage ou adaptez le schéma explicitement.")
                self.string_fields.append(index)
                self.string_limits[index] = min(field.length(), 254) if mapinfo and field.length() > 0 else 254
            elif kind == "Double" and shapefile:
                width = field.length() + (1 if field.precision() > 0 else 0)
                precision = field.precision()
                if width == 0:
                    width, precision = 24, 15
                if width < 1 or width > 255 or precision < 0 or precision >= width:
                    self._add(name, "numeric_schema", "La largeur et la précision décimales ne définissent pas un nombre DBF fidèle. Choisissez GeoPackage ou adaptez le schéma.")
                else:
                    self.real_fields.append((index, width, precision))
            elif kind == "Double" and mapinfo and (field.length() > 0 or field.precision() > 0):
                width = field.length() + (1 if field.precision() > 0 else 0)
                precision = field.precision()
                if width > 20 or precision > 16 or width - precision < 2:
                    self._add(name, "numeric_schema", "Le pilote TAB ajusterait la largeur ou la précision décimale. Choisissez GeoPackage ou définissez un schéma TAB compatible.")
                else:
                    self.real_fields.append((index, width, precision))
        if fixed_text and not self.issues and (self.string_fields or self.real_fields):
            self.source = QgsVectorLayerFeatureSource(layer)
            req_flag_enum = getattr(Qgis, "FeatureRequestFlag", None)
            no_geom_flag = getattr(req_flag_enum, "NoGeometry", None) if req_flag_enum is not None else None
            if no_geom_flag is None:
                req_flags = getattr(QgsFeatureRequest, "Flag", QgsFeatureRequest)
                no_geom_flag = getattr(req_flags, "NoGeometry", 1)
            self.request = QgsFeatureRequest().setFlags(no_geom_flag)
            self.request.setSubsetOfAttributes(self.string_fields + [item[0] for item in self.real_fields])
            if selected:
                self.request.setFilterFids(layer.selectedFeatureIds())

    @staticmethod
    def _kind(value):
        meta_enum = getattr(QMetaType, "Type", QMetaType)
        for name in ("Int", "LongLong", "Bool", "Double", "QString", "QDate", "QTime", "QDateTime", "QByteArray", "QStringList", "QVariantList", "QVariantMap"):
            candidate = getattr(meta_enum, name, None)
            if candidate is None:
                candidate = getattr(QMetaType, name, None)
            if candidate is not None and value == candidate:
                return name
        return "unknown"

    def _add(self, field, code, message):
        self.issues.append({"layer": self.layer_name, "field": field, "code": code, "message": message})

    @staticmethod
    def messages(issues):
        messages = [f"{item['layer']} / {item['field'] or 'format'} : {item['message']}" for item in issues[:10]]
        if len(issues) > 10:
            messages.append(f"{len(issues) - 10} autre(s) contrainte(s) à résoudre.")
        return messages

    def check(self, task=None):
        if self.source is None or self.issues:
            return self.issues
        iterator = self.source.getFeatures(self.request)
        try:
            for position, feature in enumerate(iterator):
                if task is not None and task.isCanceled():
                    break
                for index in self.string_fields:
                    value = feature[index]
                    if QgsVariantUtils.isNull(value):
                        continue
                    try:
                        encoded = str(value).encode(self.encoding, errors="strict")
                    except UnicodeError:
                        self._add(self.fields[index].name(), "value_encoding", f"Une valeur ne peut pas être écrite en {self.encoding}. Choisissez UTF-8 ou GeoPackage.")
                        break
                    if len(encoded) > self.string_limits[index] or b"\0" in encoded:
                        self._add(self.fields[index].name(), "text_value", f"Une valeur dépasse la largeur de {self.string_limits[index]} octets du texte {self.export_format.value} ou contient un caractère nul. Choisissez GeoPackage pour conserver le texte.")
                        break
                for index, width, precision in self.real_fields:
                    value = feature[index]
                    if QgsVariantUtils.isNull(value):
                        continue
                    number = float(value)
                    rendered = format(number, f".{precision}f")
                    if not math.isfinite(number) or len(rendered) > width or float(rendered) != number:
                        self._add(self.fields[index].name(), "numeric_value", f"Une valeur serait arrondie ou déborde le nombre {self.export_format.value} ({width} positions, {precision} décimales). Choisissez GeoPackage.")
                        break
                if self.issues:
                    break
                if task is not None and position % 256 == 0:
                    task.setProgress(min(99, (position + 1) * 100 / self.feature_count) if self.feature_count > 0 else 0)
        finally:
            iterator.close()
        return self.issues


class ExportFileTask(QgsTask):
    """Prepare or install files without blocking the GUI thread."""

    done = pyqtSignal(dict)

    def __init__(self, description, operation, dependent_layers=None):
        flags = getattr(getattr(QgsTask, "Flag", QgsTask), "CanCancel")
        super().__init__(description, flags)
        self.operation = operation
        self.result_data = {}
        if dependent_layers and hasattr(self, "setDependentLayers"):
            self.setDependentLayers(list(dependent_layers))

    def run(self):
        try:
            self.result_data = self.operation(self)
            return self.result_data.get("status") == "success"
        except Exception as exc:
            self.result_data = {"status": "cancelled" if self.isCanceled() else "failed", "errors": [str(exc)], "outputs": []}
            return False

    def finished(self, result):
        if not self.result_data:
            self.result_data = {"status": "cancelled" if self.isCanceled() else "failed", "outputs": [], "errors": []}
        self.done.emit(self.result_data)


class ExportBatch(QObject):
    """Sequential native writers, staged outputs and recoverable installation."""

    progress_changed = pyqtSignal(int, str)
    finished = pyqtSignal(dict)

    def __init__(self, manager, jobs, export_format, encoding, single_package=False, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.jobs = jobs
        self.export_format = export_format
        self.encoding = encoding
        self.single_package = single_package
        self.groups = []
        self.writer_tasks = []
        self.active_task = None
        self.index = 0
        self.cancelled = False
        self.closed = False
        self.recovery = []
        self.preflights = []

    @staticmethod
    def _fingerprint(path):
        if not path.exists():
            return None
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    def start(self):
        try:
            groups = {}
            used_tables = set()
            for job in self.jobs:
                destination = Path(job["path"]).resolve()
                key = str(destination)
                if key not in groups:
                    # Reserve a name only. No directory or file is created
                    # until every preflight has succeeded.
                    directory = destination.parent / (".transformer-" + uuid.uuid4().hex)
                    group = {
                        "destination": destination, "directory": directory,
                        "stage": directory / destination.name,
                        "before": self._fingerprint(destination), "tables": [],
                        "before_wal": self._fingerprint(Path(str(destination) + "-wal")),
                        "preserve": self.single_package and destination.exists(), "created": False,
                    }
                    groups[key] = group
                    self.groups.append(group)
                group = groups[key]
                job["group"] = group
                layer = job["layer"]
                self.preflights.append(ExportPreflight(
                    layer, self.export_format, self.encoding,
                    self.manager.driver_mapping[self.export_format], job.get("selected", False),
                ))
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = self.manager.driver_mapping[self.export_format]
                options.fileEncoding = self.encoding
                options.onlySelectedFeatures = job.get("selected", False)
                self.manager._configure_format_options(self.export_format, options, layer)
                if self.export_format == ExportFormat.SHAPEFILE:
                    options.layerOptions = ["ENCODING=" + self.encoding]
                elif self.export_format == ExportFormat.CSV:
                    options.layerOptions = ["GEOMETRY=AS_WKT", "CREATE_CSVT=YES", "SEPARATOR=COMMA", "STRING_QUOTING=IF_NEEDED"]
                elif self.export_format == ExportFormat.XLSX:
                    options.layerOptions = ["FIELD_TYPES=AUTO", "GEOMETRY=AS_WKT"]
                if self.single_package:
                    table = self.manager._sanitize_gpkg_table_name(layer.name(), used_tables)
                    options.layerName = table
                    options.layerOptions = ["IDENTIFIER=" + table]
                    options.actionOnExistingFile = GPKG_ACTION_ADD_LAYER if group["tables"] or group["preserve"] else GPKG_ACTION_CREATE_FILE
                    group["tables"].append((table, job["count"]))
                elif self.export_format == ExportFormat.GEOPACKAGE:
                    table = self.manager._sanitize_gpkg_table_name(layer.name(), set())
                    options.layerName = table
                    options.layerOptions = ["IDENTIFIER=" + table]
                    group["tables"].append((table, job["count"]))
                # The native constructor captures its feature source on the
                # GUI thread, before this batch starts any worker.
                task = QgsVectorFileWriterTask(layer, str(group["stage"]), options)
                task.setDependentLayers([layer])
                self.writer_tasks.append(task)
            if any(check.source is not None for check in self.preflights):
                dep_layers = [job["layer"] for job in self.jobs if job.get("layer") is not None]
                self._start_file_task(
                    "Contrôle du format et des valeurs",
                    self._check_formats,
                    self._on_preflight,
                    dependent_layers=dep_layers,
                )
            else:
                self._on_preflight(self._check_formats(None))
        except Exception as exc:
            self._finish({"status": "failed", "outputs": [], "errors": [str(exc)]})

    def _check_formats(self, task):
        issues = []
        for check in self.preflights:
            if task is not None and task.isCanceled():
                return {"status": "cancelled", "outputs": [], "errors": []}
            issues.extend(check.check(task))
        return {
            "status": "failed" if issues else "success", "outputs": [],
            "errors": ExportPreflight.messages(issues), "preflight_issues": issues,
        }

    def _on_preflight(self, result):
        if self.closed:
            return
        if self.cancelled or result.get("status") != "success":
            self._finish({**result, "status": "cancelled" if self.cancelled else result.get("status")})
            return
        try:
            for group in self.groups:
                group["directory"].mkdir()
                group["created"] = True
            if any(group["preserve"] for group in self.groups):
                self._start_file_task("Préparation du GeoPackage", self._prepare_packages, self._on_prepared)
            else:
                self._start_next()
        except Exception as exc:
            self._finish({"status": "failed", "outputs": [], "errors": [str(exc)]})

    def _start_file_task(self, description, operation, callback, dependent_layers=None):
        self.active_task = ExportFileTask(description, operation, dependent_layers=dependent_layers)
        self.active_task.done.connect(callback)
        self.active_task.progressChanged.connect(lambda value: self.progress_changed.emit(int(value), description))
        self.progress_changed.emit(0, description)
        QgsApplication.taskManager().addTask(self.active_task)

    def _prepare_packages(self, task):
        for group in self.groups:
            if not group["preserve"]:
                continue
            if task.isCanceled():
                return {"status": "cancelled", "outputs": [], "errors": []}
            uri = group["destination"].as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(group["stage"])) as target:
                def progress(status, remaining, total):
                    if task.isCanceled():
                        raise RuntimeError("Préparation annulée.")
                    if total:
                        task.setProgress((total - remaining) / total * 100)
                source.backup(target, pages=256, progress=progress)
        return {"status": "success", "outputs": [], "errors": []}

    def _on_prepared(self, result):
        if result.get("status") != "success" or self.cancelled:
            self._finish({**result, "status": "cancelled" if self.cancelled else result.get("status")})
        else:
            self._start_next()

    def _start_next(self):
        if self.closed:
            return
        if self.cancelled:
            self._finish({"status": "cancelled", "outputs": [], "errors": []})
            return
        if self.index == len(self.writer_tasks):
            self._start_file_task("Vérification et installation", self._install_files, self._finish)
            return
        index = self.index
        task = self.writer_tasks[index]
        self.active_task = task
        label = f"Écriture {index + 1}/{len(self.writer_tasks)}"
        self.progress_changed.emit(0, label)
        task.progressChanged.connect(lambda value: self.progress_changed.emit(int(value), label))
        signal = getattr(task, "completed", None)
        if signal is None:
            signal = task.writeComplete
        signal.connect(lambda *args: self._writer_complete(index))
        task.errorOccurred.connect(lambda code, message: self._writer_error(index, message))
        task.taskTerminated.connect(lambda: self._writer_error(index, "Écriture interrompue."))
        QgsApplication.taskManager().addTask(task)

    def _writer_complete(self, index):
        if self.closed or index != self.index:
            return
        self.index += 1
        QTimer.singleShot(0, self._start_next)

    def _writer_error(self, index, message):
        if self.closed or index != self.index:
            return
        self._finish({"status": "cancelled" if self.cancelled else "failed", "outputs": [], "errors": [] if self.cancelled else [str(message)]})

    def cancel(self):
        if self.closed:
            return
        self.cancelled = True
        if self.active_task is not None:
            self.active_task.cancel()

    def _install_files(self, task):
        installed = []
        backups = []
        try:
            for group_index, group in enumerate(self.groups):
                stage = group["stage"]
                destination = group["destination"]
                if task.isCanceled():
                    raise RuntimeError("Export annulé avant installation.")
                if self._fingerprint(destination) != group["before"]:
                    raise RuntimeError(f"La destination '{destination.name}' a changé. Choisissez un autre fichier.")
                if self._fingerprint(Path(str(destination) + "-wal")) != group.get("before_wal"):
                    raise RuntimeError(f"Le GeoPackage '{destination.name}' a changé pendant l'export.")
                if not stage.is_file() or stage.stat().st_size == 0:
                    raise RuntimeError(f"Le fichier '{destination.name}' est absent ou vide.")
                if self.export_format == ExportFormat.SHAPEFILE:
                    for suffix in (".dbf", ".shx"):
                        component = stage.with_suffix(suffix)
                        if not component.is_file() or not component.stat().st_size:
                            raise RuntimeError("Le Shapefile produit est incomplet. Aucun fichier final n'a été remplacé.")
                if self.export_format == ExportFormat.GEOPACKAGE:
                    with closing(sqlite3.connect(stage)) as connection:
                        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise RuntimeError("Le GeoPackage produit est invalide.")
                        for table, _expected in group["tables"]:
                            row = connection.execute(
                                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                                (table,),
                            ).fetchone()
                            if not row:
                                raise RuntimeError(f"La table '{table}' est absente du GeoPackage produit.")
                elif self.export_format == ExportFormat.XLSX:
                    with zipfile.ZipFile(stage) as workbook:
                        if workbook.testzip() is not None:
                            raise RuntimeError("Le fichier Excel produit est invalide.")
                generated = sorted(
                    (path for path in group["directory"].iterdir() if path.is_file()),
                    key=lambda path: (path != stage, path.name),
                )
                backup_dir = group["directory"] / "precedent"
                backup_dir.mkdir()
                # Remove obsolete index sidecars as part of the recoverable
                # group, otherwise an old index could refer to the new data.
                suffixes = {
                    ExportFormat.SHAPEFILE: (".shp", ".shx", ".dbf", ".prj", ".qpj", ".cpg", ".sbn", ".sbx", ".qix", ".fix", ".shp.xml"),
                    ExportFormat.TAB: (".tab", ".dat", ".map", ".id", ".ind"),
                }.get(self.export_format, ())
                generated_names = {path.name.casefold() for path in generated}
                for suffix in suffixes:
                    stale = destination.with_name(destination.stem + suffix)
                    if stale.is_file() and stale.name.casefold() not in generated_names:
                        backup = backup_dir / stale.name
                        shutil.copy2(stale, backup)
                        backups.append((backup, stale))
                        stale.unlink()
                for path in generated:
                    target = destination.parent / path.name
                    if target.exists():
                        backup = backup_dir / path.name
                        shutil.copy2(target, backup)
                        backups.append((backup, target))
                    if task.isCanceled():
                        raise RuntimeError("Installation annulée.")
                    os.replace(path, target)
                    installed.append(target)
                task.setProgress((group_index + 1) / len(self.groups) * 100)
            if not self.recovery:
                for group in self.groups:
                    directory = group["directory"].resolve()
                    parent = group["destination"].parent.resolve()
                    if group.get("created") and directory.parent == parent and directory.name.startswith(".transformer-"):
                        shutil.rmtree(directory, ignore_errors=True)
                        group["created"] = False
            return {"status": "success", "outputs": [str(group["destination"]) for group in self.groups], "errors": []}
        except Exception as exc:
            failures = []
            for path in reversed(installed):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    failures.append(str(path))
            for backup, target in reversed(backups):
                try:
                    os.replace(backup, target)
                except OSError:
                    failures.append(str(target))
            if failures:
                self.recovery = [str(group["directory"]) for group in self.groups]
            return {
                "status": "cancelled" if task.isCanceled() else "failed", "outputs": [],
                "errors": [str(exc)] + (["Restauration à vérifier : " + ", ".join(failures)] if failures else []),
                "recovery_directories": list(self.recovery),
            }

    def _finish(self, result):
        if self.closed:
            return
        self.closed = True
        if not self.recovery:
            for group in self.groups:
                directory = group["directory"].resolve()
                parent = group["destination"].parent.resolve()
                if group.get("created") and directory.parent == parent and directory.name.startswith(".transformer-"):
                    shutil.rmtree(directory, ignore_errors=True)
                    group["created"] = False
        payload = {
            **result, "format": self.export_format.value,
            "features": (sum(job["count"] for job in self.jobs) if all(job["count"] >= 0 for job in self.jobs) else None) if result.get("status") == "success" else 0,
            "layers": [job["name"] for job in self.jobs],
            "atomic": len(self.groups) == 1 and self.export_format not in (ExportFormat.SHAPEFILE, ExportFormat.CSV, ExportFormat.TAB, ExportFormat.GML),
        }
        self.writer_tasks.clear()
        self.active_task = None
        self.preflights.clear()
        self.groups.clear()
        self.finished.emit(payload)


class ExportWidget(QWidget):
    """Widget for simple secure export mgr"""

    export_finished = pyqtSignal(dict)
    request_started = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._export_batch = None
        self._layers_dirty = False

        if not EXPORT_AVAILABLE:
            self.setup_fallback_ui()
        else:
            self.export_manager = ExportManager()
            self.setup_ui()
            self.setup_qgis_signals()
            self.refresh_layers()

    def setup_fallback_ui(self):
        """Fallback interface if the module is not available"""
        layout = QVBoxLayout()

        label = QLabel("Module d'export indisponible")
        label_font = label.font()
        label_font.setBold(True)
        label.setFont(label_font)
        layout.addWidget(label)

        detail_label = QLabel("Le module d'export n'a pas pu être chargé.")
        layout.addWidget(detail_label)

        info_label = QLabel("Les fonctions de préparation et de transformation restent disponibles.")
        layout.addWidget(info_label)

        self.setLayout(layout)

    def setup_ui(self):
        """Configure the main interface"""
        layout = QVBoxLayout()

        # Layers available
        layers_group = QGroupBox("Couches disponibles")
        layers_layout = QVBoxLayout()

        # Tree of layers with enriched columns
        self.layers_tree = QTreeWidget()
        self.layers_tree.setHeaderLabels([
            "Nom de la couche", "Entités", "Type géométrique", "SCR",
            "Source", "Encodage", "Taille (Ko)", "Emprise"
        ])
        self.layers_tree.setSelectionMode(MultiSelection)
        self.layers_tree.setAlternatingRowColors(True)
        self.layers_tree.setSortingEnabled(True)

        # Column widths optimized
        self.layers_tree.setColumnWidth(0, 200)  # Layer name
        self.layers_tree.setColumnWidth(1, 80)   # Features
        self.layers_tree.setColumnWidth(2, 100)  # Type
        self.layers_tree.setColumnWidth(3, 120)  # CRS
        self.layers_tree.setColumnWidth(4, 150)  # Source
        self.layers_tree.setColumnWidth(5, 80)   # Encoding
        self.layers_tree.setColumnWidth(6, 80)   # Size
        self.layers_tree.setColumnWidth(7, 200)  # Extent

        layers_layout.addWidget(self.layers_tree)

        # Management buttons
        buttons_layout = QHBoxLayout()

        refresh_btn = QPushButton("Actualiser")
        refresh_btn.clicked.connect(self.refresh_layers)
        buttons_layout.addWidget(refresh_btn)

        select_all_btn = QPushButton("Tout sélectionner")
        select_all_btn.clicked.connect(lambda: self.layers_tree.selectAll())
        buttons_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Tout désélectionner")
        deselect_all_btn.clicked.connect(lambda: self.layers_tree.clearSelection())
        buttons_layout.addWidget(deselect_all_btn)

        # Remove button
        remove_btn = QPushButton("Retirer du projet")
        remove_btn.clicked.connect(self.remove_selected_layers)
        buttons_layout.addWidget(remove_btn)

        layers_layout.addLayout(buttons_layout)
        layers_group.setLayout(layers_layout)
        layout.addWidget(layers_group)

        # Export format - Single line compact
        format_group = QGroupBox("Format d'export")
        format_layout = QHBoxLayout()  # Single horizontal line

        # File format
        format_layout.addWidget(QLabel("Format :"))

        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(250)  # Slightly wider

        # Group formats by category
        self.format_combo.addItem("=== Formats spatiaux ===", None)
        spatial_formats = [ExportFormat.SHAPEFILE, ExportFormat.GEOPACKAGE, ExportFormat.GEOJSON,
                           ExportFormat.KML, ExportFormat.GML, ExportFormat.FLATGEOBUF]
        for fmt in spatial_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)

        self.format_combo.addItem("=== Formats CAO / DAO ===", None)
        cad_formats = [ExportFormat.DXF, ExportFormat.TAB]
        for fmt in cad_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)

        self.format_combo.addItem("=== Formats tabulaires ===", None)
        table_formats = [ExportFormat.CSV, ExportFormat.XLSX, ExportFormat.SQLITE]
        for fmt in table_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)

        # Select Shapefile by default
        self.format_combo.setCurrentIndex(1)
        self.format_combo.currentIndexChanged.connect(self._on_export_format_changed)
        format_layout.addWidget(self.format_combo)

        # Spacing
        format_layout.addSpacing(20)

        # Encoding on the same line
        format_layout.addWidget(QLabel("Encodage :"))

        self.encoding_combo = QComboBox()
        self.encoding_combo.setMinimumWidth(150)  # More compact

        # Common encodings for export
        encodings = [
            ("UTF-8", "utf-8"),
            ("ISO-8859-1 (Latin-1)", "iso-8859-1"),
            ("Windows-1252", "cp1252"),
            ("ISO-8859-15 (Latin-9)", "iso-8859-15"),
            ("UTF-16", "utf-16"),
            ("ASCII", "ascii")
        ]

        for display_name, encoding_value in encodings:
            self.encoding_combo.addItem(display_name, encoding_value)

        # Load encoding from configuration or default UTF-8
        self._load_encoding_config()

        # Automatically save when encoding changes
        self.encoding_combo.currentTextChanged.connect(self._save_encoding_config)

        format_layout.addWidget(self.encoding_combo)

        # Final spacing to push to the left
        format_layout.addStretch()

        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        # GeoPackage options for multi-layer export
        self.gpkg_options_group = QGroupBox("Options GeoPackage")
        gpkg_layout = QHBoxLayout()

        self.gpkg_mode_group = QButtonGroup(self)
        self.gpkg_per_layer_radio = QRadioButton("Un GeoPackage par couche")
        self.gpkg_single_file_radio = QRadioButton("Un seul GeoPackage contenant toutes les couches")
        self.gpkg_per_layer_radio.setChecked(True)

        self.gpkg_mode_group.addButton(self.gpkg_per_layer_radio, 0)
        self.gpkg_mode_group.addButton(self.gpkg_single_file_radio, 1)

        gpkg_layout.addWidget(self.gpkg_per_layer_radio)
        gpkg_layout.addWidget(self.gpkg_single_file_radio)
        gpkg_layout.addStretch()

        self.gpkg_options_group.setLayout(gpkg_layout)
        self.gpkg_options_group.setVisible(False)
        self.gpkg_mode_group.buttonToggled.connect(self._save_gpkg_mode_config)
        layout.addWidget(self.gpkg_options_group)

        # Export scope + single action (conventional GIS pattern)
        export_group = QGroupBox("Export")
        export_layout = QHBoxLayout()

        self.selected_features_only_cb = QCheckBox("Entités sélectionnées uniquement")
        self.selected_features_only_cb.setToolTip(
            "Exporter uniquement les entités sélectionnées sur la carte (une couche à la fois)"
        )
        export_layout.addWidget(self.selected_features_only_cb)

        export_layout.addStretch()

        export_btn = QPushButton("Exporter…")
        export_btn.setToolTip(
            "Exporter les couches sélectionnées ci-dessus vers le format choisi"
        )
        export_btn.clicked.connect(self.export_layers)
        self.export_btn = export_btn
        export_layout.addWidget(export_btn)

        self.cancel_export_btn = QPushButton("Annuler l'export")
        self.cancel_export_btn.setEnabled(False)
        self.cancel_export_btn.clicked.connect(self.cancel_export)
        export_layout.addWidget(self.cancel_export_btn)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setVisible(False)
        layout.addWidget(self.export_progress)

        self.layers_tree.itemSelectionChanged.connect(self._update_export_scope_state)

        # Message bar
        self.message_bar = QgsMessageBar()
        layout.addWidget(self.message_bar)

        self.setLayout(layout)
        self._load_gpkg_mode_config()
        self._on_export_format_changed()
        self._update_export_scope_state()

    def _update_export_scope_state(self):
        """Disable feature-scope option when several layers are selected."""
        if not hasattr(self, "selected_features_only_cb"):
            return

        multi_layer = len(self.get_selected_layers()) > 1
        self.selected_features_only_cb.setEnabled(not multi_layer)
        if multi_layer:
            self.selected_features_only_cb.setChecked(False)

    def _on_export_format_changed(self):
        """Show GeoPackage options only when GeoPackage is selected."""
        if not hasattr(self, "format_combo"):
            return

        export_format = self.format_combo.currentData()
        is_geopackage = export_format == ExportFormat.GEOPACKAGE
        if hasattr(self, "gpkg_options_group"):
            self.gpkg_options_group.setVisible(is_geopackage)

    def _load_gpkg_mode_config(self):
        """Load GeoPackage multi-export mode from QGIS settings."""
        if not hasattr(self, "gpkg_single_file_radio"):
            return

        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            saved_value = settings.value("Transformer/export_gpkg_single_file", "false")
            single_file = str(saved_value).lower() in ("true", "1", "yes")
            if single_file:
                self.gpkg_single_file_radio.setChecked(True)
            else:
                self.gpkg_per_layer_radio.setChecked(True)
        except (ImportError, Exception):
            self.gpkg_per_layer_radio.setChecked(True)

    def _save_gpkg_mode_config(self):
        """Save GeoPackage multi-export mode in QGIS settings."""
        if not hasattr(self, "gpkg_single_file_radio"):
            return

        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            settings.setValue(
                "Transformer/export_gpkg_single_file",
                self.gpkg_single_file_radio.isChecked(),
            )
        except Exception as exc:
            QgsMessageLog.logMessage(f"GPKG mode setting save skipped: {exc}", "Transformer", MsgWarning)

    def _use_single_geopackage_export(self):
        """Return True when multi-export should produce one combined GeoPackage."""
        return (
            hasattr(self, "gpkg_single_file_radio")
            and self.gpkg_single_file_radio.isChecked()  # noqa: W503
        )

    def setup_qgis_signals(self):
        """Setup QGIS project layer signals for auto-update"""
        if not EXPORT_AVAILABLE:
            return

        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            project.layersAdded.connect(self.on_layers_added)
            project.layersRemoved.connect(self.on_layers_removed)
            project.layerWillBeRemoved.connect(self.on_layer_will_be_removed)
        except Exception as exc:
            QgsMessageLog.logMessage(f"Export signals setup skipped: {exc}", "Transformer", MsgWarning)

    def teardown_qgis_signals(self):
        """Disconnect QGIS project signals and clear layer references before widget destruction."""
        if not EXPORT_AVAILABLE:
            return
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            for name, slot in (
                ("layersAdded", self.on_layers_added),
                ("layersRemoved", self.on_layers_removed),
                ("layerWillBeRemoved", self.on_layer_will_be_removed),
            ):
                try:
                    getattr(project, name).disconnect(slot)
                except (TypeError, RuntimeError, AttributeError):
                    pass
        except (ImportError, RuntimeError, AttributeError):
            pass
        if hasattr(self, 'layers_tree') and self.layers_tree is not None:
            try:
                self.layers_tree.clear()
            except RuntimeError:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_layers_dirty", False):
            self._layers_dirty = False
            self.refresh_layers()

    def teardown_resources(self):
        """Cancel active export batch and disconnect QGIS project signals."""
        batch = getattr(self, "_export_batch", None)
        if batch is not None and not getattr(batch, "closed", True):
            try:
                batch.cancel()
            except Exception as exc:
                QgsMessageLog.logMessage(f"Export batch cancel warning: {exc}", "Transformer", MsgWarning)
        self.teardown_qgis_signals()

    def on_layers_added(self, layers):
        """Handle when new layers are added to QGIS project"""
        if not EXPORT_AVAILABLE:
            return

        vector_layers = [layer for layer in layers if hasattr(layer, 'isValid') and layer.isValid()]
        if vector_layers:
            try:
                from qgis.core import QgsVectorLayer
                vector_layers = [layer for layer in vector_layers if isinstance(layer, QgsVectorLayer)]
                if vector_layers:
                    if not self.isVisible():
                        self._layers_dirty = True
                        return
                    self.refresh_layers()
                    if hasattr(self, 'message_bar') and self.message_bar:
                        self.message_bar.pushInfo("Export", f"{len(vector_layers)} nouvelle(s) couche(s) disponible(s) pour l'export")
            except Exception as exc:
                QgsMessageLog.logMessage(f"Export layers_added refresh skipped: {exc}", "Transformer", MsgWarning)

    def on_layers_removed(self, layer_ids):
        """Handle when layers are removed from QGIS project"""
        if not EXPORT_AVAILABLE:
            return

        if layer_ids:
            if not self.isVisible():
                self._layers_dirty = True
                return
            self.refresh_layers()
            if hasattr(self, 'message_bar') and self.message_bar:
                self.message_bar.pushInfo("Export", "Liste des couches mise à jour après suppression")

    def on_layer_will_be_removed(self, layer_id):
        """Handle when a layer is about to be removed"""
        if not EXPORT_AVAILABLE:
            return

        # Clear selection if the layer being removed is currently selected
        if hasattr(self, 'layers_tree') and self.layers_tree:
            try:
                for item in self.layers_tree.selectedItems():
                    layer = item.data(0, UserRole)
                    if layer and hasattr(layer, 'id') and layer.id() == layer_id:
                        item.setSelected(False)
            except Exception as exc:
                QgsMessageLog.logMessage(f"Export layer selection cleanup skipped: {exc}", "Transformer", MsgWarning)

    def refresh_layers(self):
        """Refresh the list of layers with detailed information"""
        if not EXPORT_AVAILABLE:
            return

        self._layers_dirty = False
        was_sorting = self.layers_tree.isSortingEnabled()
        self.layers_tree.setSortingEnabled(False)
        self.layers_tree.setUpdatesEnabled(False)
        try:
            self.layers_tree.clear()
            layers = self.export_manager.get_transformed_layers()

            for layer in layers:
                item = QTreeWidgetItem(self.layers_tree)
                is_valid = layer.isValid()
                feature_count = layer.featureCount()
                field_count = layer.fields().count()

                item.setText(0, layer.name())
                item.setText(1, str(feature_count))

                geom_type = QgsWkbTypes.displayString(layer.wkbType())
                item.setText(2, geom_type)

                crs = layer.crs()
                if crs.isValid():
                    crs_text = f"{crs.authid()} - {crs.description()}"
                    if len(crs_text) > 50:
                        crs_text = f"{crs.authid()} - {crs.description()[:47]}..."
                else:
                    crs_text = "CRS invalide"
                item.setText(3, crs_text)

                source = layer.source()
                if len(source) > 50:
                    source_text = f"...{source[-47:]}"
                else:
                    source_text = source
                item.setText(4, source_text)

                provider = layer.dataProvider()
                encoding = provider.encoding() if provider is not None else "UTF-8"
                item.setText(5, encoding if encoding else "UTF-8")

                estimated_size = (max(0, feature_count) * field_count * 50) // 1024
                item.setText(6, f"{estimated_size}")

                extent = layer.extent()
                if extent.isNull():
                    extent_text = "Invalid extent"
                else:
                    extent_text = f"X: {extent.xMinimum():.2f} a {extent.xMaximum():.2f}, Y: {extent.yMinimum():.2f} a {extent.yMaximum():.2f}"
                    if len(extent_text) > 80:
                        extent_text = f"X: {extent.xMinimum():.1f}->{extent.xMaximum():.1f}, Y: {extent.yMinimum():.1f}->{extent.yMaximum():.1f}"
                item.setText(7, extent_text)

                item.setData(0, UserRole, layer)

                try:
                    if 'Point' in geom_type:
                        item.setIcon(0, ui_icon("point_layer"))
                    elif 'Line' in geom_type:
                        item.setIcon(0, ui_icon("line_layer"))
                    elif 'Polygon' in geom_type:
                        item.setIcon(0, ui_icon("polygon_layer"))
                    else:
                        item.setIcon(0, ui_icon("layer"))
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Export layer icon skipped: {exc}", "Transformer", MsgInfo)

                if not is_valid:
                    for col in range(8):
                        item.setBackground(col, QColor(255, 0, 0))
                elif feature_count == 0:
                    for col in range(8):
                        item.setBackground(col, QColor(255, 255, 0))
        finally:
            self.layers_tree.setUpdatesEnabled(True)
            self.layers_tree.setSortingEnabled(was_sorting)

    def get_selected_layers(self):
        """Return selected layers"""
        selected_layers = []
        for item in self.layers_tree.selectedItems():
            layer = item.data(0, UserRole)
            if layer and layer.isValid():
                selected_layers.append(layer)
        return selected_layers

    def remove_selected_layers(self):
        """Remove selected layers from QGIS project"""
        if not EXPORT_AVAILABLE:
            return

        selected_layers = self.get_selected_layers()

        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Sélectionnez au moins une couche à retirer")
            return

        # Ask for confirmation
        layer_names = ", ".join([layer.name() for layer in selected_layers])
        reply = QMessageBox.question(
            self,
            "Confirmer le retrait du projet",
            f"Retirer ces {len(selected_layers)} couche(s) du projet QGIS ?\n\n{layer_names}",
            MsgBoxYes | MsgBoxNo,
            MsgBoxNo
        )

        if reply == MsgBoxYes:
            project = QgsProject.instance()
            removed_count = 0

            for layer in selected_layers:
                # Store layer name before deletion to avoid RuntimeError
                layer_name = layer.name()
                layer_id = layer.id()

                try:
                    project.removeMapLayer(layer_id)
                    removed_count += 1
                    QgsMessageLog.logMessage(f"Layer removed: {layer_name}", "Transformer", MsgInfo)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Error removing layer {layer_name}: {str(e)}", "Transformer", MsgWarning)

            # Refresh the list
            self.refresh_layers()

            # Message of success
            self.message_bar.pushSuccess(
                "Retrait effectué",
                f"{removed_count} couche(s) retirée(s) du projet"
            )

    def export_layers(self):
        """Export selected layer(s) using the current format and scope options."""
        if not EXPORT_AVAILABLE:
            return
        if self._export_batch is not None and not self._export_batch.closed:
            self.message_bar.pushWarning("Export en cours", "Terminez ou annulez l'export avant d'en lancer un autre.")
            return

        selected_layers = self.get_selected_layers()
        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Sélectionnez au moins une couche à exporter")
            return

        export_format = self.format_combo.currentData()
        if not export_format:
            self.message_bar.pushWarning("Attention", "Choisissez un format d'export valide")
            return

        selected_features_only = (
            hasattr(self, "selected_features_only_cb")
            and self.selected_features_only_cb.isChecked()  # noqa: W503
        )

        if selected_features_only:
            if len(selected_layers) > 1:
                self.message_bar.pushWarning(
                    "Attention",
                    "Entités sélectionnées uniquement : choisissez une seule couche",
                )
                return
            layer = selected_layers[0]
            if layer.selectedFeatureCount() == 0:
                self.message_bar.pushWarning(
                    "Attention", "Aucune entité n'est sélectionnée sur la carte pour cette couche"
                )
                return
            self._export_single_layer_file(layer, selected_features_only=True)
            return

        if len(selected_layers) == 1:
            self._export_single_layer_file(selected_layers[0], selected_features_only=False)
        else:
            self._export_multiple_layers(selected_layers)

    def _export_single_layer_file(self, layer, selected_features_only=False):
        """Choose the destination, then queue a native writer."""
        export_format = self.format_combo.currentData()
        extension = self.export_manager.format_extensions.get(export_format, ".shp")
        name = self._safe_file_name(layer.name()) + ("_selection" if selected_features_only else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer les entités sélectionnées" if selected_features_only else "Enregistrer la couche",
            name + extension, f"{export_format.value} (*{extension})",
        )
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
        self._start_export_jobs([self._export_job(layer, path, selected_features_only)], overwrite_confirmed=False)

    def _export_multiple_layers(self, selected_layers):
        """Choose one package or a folder while retaining the format options."""
        export_format = self.format_combo.currentData()
        if export_format == ExportFormat.GEOPACKAGE and self._use_single_geopackage_export():
            path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le GeoPackage", "export.gpkg", "GeoPackage (*.gpkg)")
            if not path:
                return
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self._start_export_jobs(
                [self._export_job(layer, path) for layer in selected_layers],
                single_package=True, overwrite_confirmed=False,
            )
            return
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier d'export")
        if not folder:
            return
        extension = self.export_manager.format_extensions.get(export_format, ".shp")
        names = set()
        jobs = []
        for layer in selected_layers:
            name = self._safe_file_name(layer.name())
            candidate = name
            index = 2
            while candidate.casefold() in names:
                candidate = f"{name}_{index}"
                index += 1
            names.add(candidate.casefold())
            jobs.append(self._export_job(layer, os.path.join(folder, candidate + extension)))
        self._start_export_jobs(jobs)

    @staticmethod
    def _safe_file_name(name):
        result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
        if not result or result.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            result = "couche_" + (result or "export")
        return result

    @staticmethod
    def _export_job(layer, path, selected=False):
        if selected and layer.selectedFeatureCount() == 0:
            raise ValueError("Aucune entité sélectionnée : sélectionnez les entités avant l'export.")
        return {
            "layer": layer, "name": layer.name(), "path": os.path.abspath(path),
            "selected": selected, "count": layer.selectedFeatureCount() if selected else layer.featureCount(),
        }

    def _start_export_jobs(self, jobs, single_package=False, overwrite_confirmed=False):
        if not jobs:
            return
        if not overwrite_confirmed:
            existing = sorted({job["path"] for job in jobs if os.path.exists(job["path"])})
            if existing:
                detail = "\n".join(os.path.basename(path) for path in existing[:5])
                answer = QMessageBox.question(
                    self, "Remplacer les fichiers existants",
                    f"{len(existing)} fichier(s) existent déjà :\n{detail}\n\nConfirmer leur remplacement ?",
                    MsgBoxYes | MsgBoxNo,
                )
                if answer != MsgBoxYes:
                    return
        batch = ExportBatch(
            self.export_manager, jobs, self.format_combo.currentData(),
            self.get_selected_encoding(), single_package, self,
        )
        self._export_batch = batch
        batch.progress_changed.connect(self._on_export_progress)
        batch.finished.connect(self._on_export_batch_finished)
        self.export_btn.setEnabled(False)
        self.cancel_export_btn.setEnabled(True)
        self.export_progress.setVisible(True)
        self.request_started.emit({
            "kind": "file_export", "format": batch.export_format.value,
            "layers": [job["name"] for job in jobs],
            "destinations": sorted({job["path"] for job in jobs}),
            "selected_only": any(job["selected"] for job in jobs),
        })
        batch.start()

    def _on_export_progress(self, progress, label):
        self.export_progress.setValue(max(0, min(100, progress)))
        self.export_progress.setFormat(label + " : %p%")

    def cancel_export(self):
        if self._export_batch is not None:
            self._export_batch.cancel()
            self.cancel_export_btn.setEnabled(False)

    def _on_export_batch_finished(self, result):
        self.export_btn.setEnabled(True)
        self.cancel_export_btn.setEnabled(False)
        self.export_progress.setVisible(False)
        self.message_bar.clearWidgets()
        status = result.get("status")
        if status == "success":
            detail = f"{len(result['outputs'])} fichier(s) installé(s)."
            if not result.get("atomic"):
                detail += " Les fichiers du lot sont remplacés avec restauration en cas d'erreur ; l'ensemble n'est pas atomique."
            self.message_bar.pushSuccess("Export terminé", detail)
        elif status == "cancelled":
            detail = "Les fichiers précédents ont été conservés ou restaurés."
            if result.get("recovery_directories"):
                detail = "Restauration à vérifier dans : " + ", ".join(result["recovery_directories"])
            self.message_bar.pushWarning("Export annulé", detail)
        else:
            self.message_bar.pushCritical("Export échoué", "; ".join(result.get("errors", [])))
        self.export_finished.emit(result)

    def _load_encoding_config(self):
        """Load encoding configuration from QGIS settings"""
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()

            # Key for this plugin configuration
            config_key = "Transformer/export_encoding"
            saved_encoding = settings.value(config_key, "utf-8")

            # Find the corresponding index in the combobox
            for i in range(self.encoding_combo.count()):
                if self.encoding_combo.itemData(i) == saved_encoding:
                    self.encoding_combo.setCurrentIndex(i)
                    break
            else:
                # If the saved encoding is not found, use UTF-8 (index 0)
                self.encoding_combo.setCurrentIndex(0)

        except (ImportError, Exception):
            # In case of error, use UTF-8 by default
            self.encoding_combo.setCurrentIndex(0)

    def _save_encoding_config(self):
        """Save encoding configuration in QGIS settings"""
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()

            # Get the selected encoding
            current_encoding = self.encoding_combo.currentData()
            if current_encoding:
                config_key = "Transformer/export_encoding"
                settings.setValue(config_key, current_encoding)

                # Log for debugging
                QgsMessageLog.logMessage(
                    f"Export encoding saved: {current_encoding}",
                    "Transformer", MsgInfo
                )

        except (ImportError, Exception) as e:
            # In case of save error, continue without crashing
            QgsMessageLog.logMessage(
                f"Encoding save error: {str(e)}",
                "Transformer", MsgWarning
            )

    def get_selected_encoding(self):
        """Return the selected encoding by the user"""
        return self.encoding_combo.currentData() or "utf-8"
