# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Headless helpers shared by Transformer QGIS Processing algorithms."""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsDataSourceUri,
    QgsFields,
    QgsMessageLog,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputLayerDefinition,
    QgsProcessingParameterDefinition,
    QgsProviderRegistry,
)

from ..core.field_types import definition_from_processing_mapping
from ..core.transformer import SimpleTransformer
from ..shared.compat import MsgWarning, meta_type_name

try:
    from osgeo import ogr
except ImportError:
    ogr = None


# QGIS 4 / Qt 6 scoped enum resolution
_SOURCE_TYPE_ENUM = getattr(QgsProcessing, "SourceType", QgsProcessing)
VECTOR_SOURCE_TYPE = getattr(
    _SOURCE_TYPE_ENUM,
    "TypeVector",
    getattr(_SOURCE_TYPE_ENUM, "Vector", getattr(QgsProcessing, "TypeVector", 5)),
)

_ALGO_FLAG_ENUM = getattr(QgsProcessingAlgorithm, "Flag", QgsProcessingAlgorithm)
ALGO_FLAG_SUPPORTS_BATCH = getattr(_ALGO_FLAG_ENUM, "FlagSupportsBatch", 0)

_PARAM_FLAG_ENUM = getattr(QgsProcessingParameterDefinition, "Flag", QgsProcessingParameterDefinition)
PARAM_FLAG_OPTIONAL = getattr(_PARAM_FLAG_ENUM, "FlagOptional", 0)
PARAM_FLAG_ADVANCED = getattr(_PARAM_FLAG_ENUM, "FlagAdvanced", 0)

_EXT_TO_DRIVER = {
    ".shp": "ESRI Shapefile",
    ".gpkg": "GPKG",
    ".geojson": "GeoJSON",
    ".json": "GeoJSON",
    ".kml": "KML",
    ".csv": "CSV",
    ".xlsx": "XLSX",
    ".dxf": "DXF",
    ".tab": "MapInfo File",
    ".gml": "GML",
    ".sqlite": "SQLite",
    ".fgb": "FlatGeobuf",
}

_METATYPE_TO_OGR = {
    "Int": "Integer",
    "LongLong": "Integer64",
    "Bool": "Integer",
    "Double": "Real",
    "QString": "String",
    "QDate": "Date",
    "QTime": "Time",
    "QDateTime": "DateTime",
    "QByteArray": "Binary",
    "QStringList": "StringList",
}

_DXF_ALLOWED_FIELDS = frozenset({
    "layer", "paperspace", "subclasses", "linetype", "entityhandle", "text",
    "blockname", "blockscale", "blockangle", "blockocsnormal", "blockocscoords",
    "blockattributes", "block", "attributetag", "ogr_style",
})

_OGR_DBNAME_RE = re.compile(r"dbname\s*=\s*(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))", re.IGNORECASE)
_SHP_SIDECAR_EXTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".sbn", ".sbx", ".qix")
_SQLITE_WAL_SUFFIXES = ("-wal", "-shm", "-journal")


def _metatype_kind(value) -> str:
    return meta_type_name(value) or "unknown"


def extract_output_destination_path(raw_output) -> str:
    """Return local file path for a Processing sink parameter, or '' for memory/DB."""
    if raw_output is None:
        return ""
    if isinstance(raw_output, QgsProcessingOutputLayerDefinition):
        sink = getattr(raw_output, "sink", None)
        if sink is not None and hasattr(sink, "staticValue"):
            raw_output = sink.staticValue()
        else:
            return ""
    if isinstance(raw_output, os.PathLike):
        raw_output = os.fspath(raw_output)
    if not isinstance(raw_output, str):
        return ""
    value = raw_output.strip()
    if not value:
        return ""
    lowered = value.lower()
    if (
        value == QgsProcessing.TEMPORARY_OUTPUT
        or lowered == "temporary_output"
        or lowered.startswith("memory:")
        or lowered.startswith("postgres:")
        or lowered.startswith("postgis:")
    ):
        return ""
    # Extract file path from QGIS Processing "Save to GeoPackage..." ogr:dbname=... URI
    if lowered.startswith("ogr:"):
        match = _OGR_DBNAME_RE.search(value)
        if match:
            return (match.group(1) or match.group(2) or match.group(3) or "").strip()
        return ""
    # Strip OGR layer suffix syntax ("path.gpkg|layername=foo")
    if "|" in value:
        value = value.split("|", 1)[0].strip()
    return value


def cleanup_partial_output_file(dest_path: str, existed_before: bool) -> None:
    """Delete a newly created partial output file (and sidecars) after failure or cancel."""
    if not dest_path or existed_before:
        return
    base, ext = os.path.splitext(dest_path)
    candidates = [dest_path]
    ext_lower = ext.lower()
    if ext_lower == ".shp":
        candidates.extend(base + side for side in _SHP_SIDECAR_EXTS)
    elif ext_lower in (".gpkg", ".sqlite"):
        candidates.extend(dest_path + suffix for suffix in _SQLITE_WAL_SUFFIXES)

    seen = set()
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(path):
            try:
                os.unlink(path)
            except OSError as exc:
                QgsMessageLog.logMessage(
                    f"processing_provider.common: nettoyage partiel impossible pour '{path}' : {exc}",
                    "Transformer",
                    MsgWarning,
                )


def check_sink_schema_preflight(
    fields: QgsFields,
    output_destination,
    encoding: str = "utf-8",
) -> List[str]:
    """Validate output fields against target GDAL/OGR driver constraints before writing."""
    dest_path = extract_output_destination_path(output_destination)
    if not dest_path:
        return []
    ext = os.path.splitext(dest_path)[1].lower()
    driver_name = _EXT_TO_DRIVER.get(ext)
    if not driver_name:
        return []

    driver = ogr.GetDriverByName(driver_name) if ogr is not None else None
    metadata = driver.GetMetadata() if driver is not None else {}
    supported = set(metadata.get("DMD_CREATIONFIELDDATATYPES", "").split())
    subtypes = set(metadata.get("DMD_CREATIONFIELDDATASUBTYPES", "").split())
    is_shp = driver_name == "ESRI Shapefile"
    is_tab = driver_name == "MapInfo File"
    if is_shp:
        supported = supported or {"Integer", "Integer64", "Real", "String", "Date"}

    issues: List[str] = []
    seen_short: Dict[bytes, str] = {}

    for idx in range(fields.count()):
        field = fields.at(idx)
        name = field.name()
        kind = _metatype_kind(field.type())
        target_type = _METATYPE_TO_OGR.get(kind)
        if kind == "QVariantList":
            sub_target = _METATYPE_TO_OGR.get(_metatype_kind(field.subType()), "")
            target_type = (sub_target + "List") if sub_target else None

        if kind in {"QVariantList", "QVariantMap", "QStringList"} and driver_name == "GPKG":
            issues.append(
                f"Champ '{name}' : type complexe non conserve tel quel en GeoPackage."
            )
        elif kind == "QVariantMap" and "JSON" in subtypes:
            pass
        elif (
            target_type is None
            or (supported and target_type not in supported)
            or (kind == "LongLong" and driver is not None and "Integer64" not in supported)
        ):
            issues.append(
                f"Champ '{name}' : le pilote {driver_name} ne conserve pas le type "
                f"{field.typeName()}. Choisissez GeoPackage (.gpkg) ou convertissez ce champ."
            )

        if driver_name == "SQLite" and name.casefold() == "ogc_fid":
            issues.append(
                "Champ 'ogc_fid' : nom reserve SQLite qui serait renomme. Renommez ce champ ou choisissez GeoPackage."
            )

        if driver_name == "DXF" and name.casefold() not in _DXF_ALLOWED_FIELDS:
            issues.append(
                f"Champ '{name}' : DXF ne conserve pas les attributs metier. Choisissez GeoPackage (.gpkg)."
            )

        if driver_name == "GML" and (
            not name
            or re.sub(r"[^a-zA-Z0-9_.\u0080-\U0010ffff]", "_", name) != name
            or name[0].isdigit()
            or name[0] == "."
        ):
            issues.append(
                f"Champ '{name}' : nom incompatible XML/GML. Renommez ce champ ou choisissez GeoPackage."
            )

        if not (is_shp or is_tab):
            continue

        try:
            encoded = name.encode(encoding, errors="strict")
        except (UnicodeError, LookupError):
            issues.append(
                f"Champ '{name}' : impossible a encoder en {encoding} pour {driver_name}."
            )
            continue

        limit = 10 if is_shp else 31
        normalized = encoded[:limit]
        if is_shp:
            normalized = normalized.rstrip(b" \t\r\n\v\f").replace(b":", b"_")
        elif not re.fullmatch(rb"[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*", encoded):
            issues.append(
                f"Champ '{name}' : nom incompatible MapInfo TAB. Utilisez un identifiant sans espace ni ponctuation."
            )

        if len(encoded) > limit or normalized != encoded or not encoded or b"\0" in encoded:
            issues.append(
                f"Champ '{name}' : {driver_name} limite les noms a {limit} octets sans normalisation. "
                "Renommez ce champ, choisissez GeoPackage (.gpkg) ou desactivez STRICT_SCHEMA_CHECK."
            )

        key = normalized.upper()
        if key in seen_short:
            issues.append(
                f"Champ '{name}' : collision {driver_name} avec '{seen_short[key]}' apres troncature a {limit} octets."
            )
        seen_short[key] = name

        if kind == "QString" and field.length() > 254:
            issues.append(
                f"Champ '{name}' : largeur {field.length()} superieure a 254 octets pour {driver_name}. "
                "Choisissez GeoPackage (.gpkg)."
            )

    return issues


def run_sink_algorithm(
    algorithm: QgsProcessingAlgorithm,
    alg_id: str,
    parameters: Dict[str, Any],
    context,
    feedback,
    source,
    recipe_label: str,
    calculated_fields: Dict[str, str],
    field_definitions: Optional[Dict[str, Any]],
    filter_config: Dict[str, Any],
    geometry_expression: str,
    target_crs,
    strict_schema: bool,
    output_param_name: str,
) -> Tuple[Any, Dict[str, Any]]:
    """Shared streaming execution path for sink-based Transformer Processing algorithms."""
    raw_output = parameters.get(output_param_name)
    dest_path = extract_output_destination_path(raw_output)
    existed_before = bool(dest_path and os.path.exists(dest_path))

    def _validate_schema(fields, _wkb_type, _dest_crs):
        if not strict_schema:
            return
        issues = check_sink_schema_preflight(fields, raw_output)
        if issues:
            raise ValueError(
                "Precontrole schema de sortie echoue : " + " ; ".join(issues[:5])
            )

    def _create_sink(fields, wkb_type, dest_crs):
        sink, dest_id = algorithm.parameterAsSink(
            parameters, output_param_name, context, fields, wkb_type, dest_crs,
        )
        if sink is None:
            raise ValueError(algorithm.invalidSinkError(parameters, output_param_name))
        return sink, dest_id

    def _cleanup():
        cleanup_partial_output_file(dest_path, existed_before)

    engine = SimpleTransformer(None)
    try:
        return engine.execute_to_sink(
            source=source,
            table_name=recipe_label,
            calculated_fields=calculated_fields,
            sink_factory=_create_sink,
            filter_config=filter_config,
            target_crs=target_crs,
            geometry_expression=geometry_expression,
            field_definitions=field_definitions or {},
            expression_context=context.expressionContext(),
            transform_context=context.transformContext(),
            feedback=feedback,
            schema_validator=_validate_schema,
            cleanup_on_failure=_cleanup,
            raise_on_error=True,
        )
    except InterruptedError as exc:
        raise QgsProcessingException(f"{alg_id} : execution annulee ({exc})") from exc
    except Exception as exc:
        raise QgsProcessingException(f"{alg_id} ({recipe_label}) : {exc}") from exc


def field_mapping_to_recipe(
    mapping_entries: Optional[List[Dict[str, Any]]],
    source_fields: QgsFields,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """Translate QgsProcessingParameterFieldMapping entries into recipe fields and definitions."""
    calculated_fields: Dict[str, str] = {}
    field_definitions: Dict[str, Dict[str, Any]] = {}

    if not mapping_entries:
        # Leave field_definitions empty so direct quoted refs clone exact native QgsField
        # (including QTime, QByteArray, JSON, StringList, lengths and comments).
        for idx in range(source_fields.count()):
            fld = source_fields.at(idx)
            name = fld.name()
            escaped = name.replace('"', '""')
            calculated_fields[name] = f'"{escaped}"'
        return calculated_fields, field_definitions

    for index, entry in enumerate(mapping_entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"processing_provider.common: entree FIELDS_MAPPING[{index}] invalide."
            )
        name = str(entry.get("name") or "").strip()
        expr = str(entry.get("expression") or "").strip()
        if not name:
            raise ValueError(
                f"processing_provider.common: nom de champ vide a FIELDS_MAPPING[{index}]."
            )
        if name.casefold() == "geometry":
            raise ValueError(
                "processing_provider.common: 'geometry' est reserve ; utilisez GEOMETRY_EXPRESSION."
            )
        if not expr:
            raise ValueError(
                f"processing_provider.common: expression vide pour le champ '{name}'."
            )
        calculated_fields[name] = expr
        if entry.get("type") is not None or entry.get("type_name"):
            # For unchanged native passthrough types (e.g. QTime/JSON), allow direct clone
            quoted = expr.strip()
            is_direct_ref = len(quoted) >= 2 and quoted[0] == quoted[-1] == '"'
            try:
                field_definitions[name] = definition_from_processing_mapping(entry)
            except ValueError:
                if is_direct_ref and source_fields.indexFromName(quoted[1:-1].replace('""', '"')) >= 0:
                    continue
                raise

    return calculated_fields, field_definitions


def _auth_load_result(result, config: QgsAuthMethodConfig) -> Tuple[bool, QgsAuthMethodConfig]:
    if isinstance(result, tuple):
        return bool(result[0]), result[1]
    return bool(result), config


def _expand_authcfg_credentials(authcfg: str) -> Tuple[str, str]:
    """Resolve username and password from QGIS Authentication Manager without logging."""
    if not authcfg:
        return "", ""
    manager = QgsApplication.authManager()
    if manager is None or manager.isDisabled():
        raise ValueError(
            f"processing_provider.common: gestionnaire d'authentification QGIS verrouille "
            f"pour authcfg='{authcfg}'."
        )
    cfg = QgsAuthMethodConfig()
    ok, cfg = _auth_load_result(manager.loadAuthenticationConfig(authcfg, cfg, True), cfg)
    if not ok:
        raise ValueError(
            f"processing_provider.common: configuration d'authentification authcfg='{authcfg}' introuvable."
        )
    return str(cfg.config("username") or ""), str(cfg.config("password") or "")


def _sslmode_name(uri: QgsDataSourceUri) -> str:
    ssl_mode = uri.sslMode()
    mapping = {
        getattr(QgsDataSourceUri, "SslDisable", -1): "disable",
        getattr(QgsDataSourceUri, "SslAllow", -1): "allow",
        getattr(QgsDataSourceUri, "SslPrefer", -1): "prefer",
        getattr(QgsDataSourceUri, "SslRequire", -1): "require",
        getattr(QgsDataSourceUri, "SslVerifyCa", -1): "verify-ca",
        getattr(QgsDataSourceUri, "SslVerifyFull", -1): "verify-full",
    }
    return mapping.get(ssl_mode, "prefer")


def _parse_port(raw_port, conn_name: str) -> int:
    if raw_port is None or raw_port == "":
        return 5432
    if isinstance(raw_port, bool):
        raise ValueError(
            f"processing_provider.common: port booleen invalide pour la connexion '{conn_name}'."
        )
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"processing_provider.common: port invalide ({raw_port!r}) pour la connexion '{conn_name}'."
        ) from exc
    if not 1 <= port <= 65535:
        raise ValueError(
            f"processing_provider.common: port hors plage ({port}) pour la connexion '{conn_name}'."
        )
    return port


def resolve_postgres_connection_params(
    connection_name: str,
    plugin_dir: str = "",
) -> Dict[str, Any]:
    """Resolve psycopg2 connection params from a QGIS Postgres connection or Transformer profile.

    Must be called on the main thread when QGIS authentication DB may prompt.
    """
    clean_name = (connection_name or "").strip()
    if not clean_name:
        raise ValueError(
            "processing_provider.common: nom de connexion PostgreSQL manquant."
        )

    # Primary source: QGIS native PostgreSQL provider connection
    registry = QgsProviderRegistry.instance()
    pg_meta = registry.providerMetadata("postgres") if registry is not None else None
    conn_obj = pg_meta.findConnection(clean_name) if pg_meta is not None else None

    if conn_obj is not None:
        uri = QgsDataSourceUri(conn_obj.uri())
        params: Dict[str, Any] = {}
        if uri.service():
            params["service"] = uri.service()
        if uri.host():
            params["host"] = uri.host()
        if uri.port():
            params["port"] = _parse_port(uri.port(), clean_name)
        if uri.database():
            params["database"] = uri.database()
        user = uri.username()
        password = uri.password()
        authcfg = uri.authConfigId()
        if authcfg:
            auth_user, auth_pass = _expand_authcfg_credentials(authcfg)
            user = auth_user or user
            password = auth_pass or password
        if user:
            params["user"] = user
        if password:
            params["password"] = password
        params["sslmode"] = _sslmode_name(uri)
        return params

    # Fallback: Transformer saved PostgreSQL profile (authcfg protected)
    if plugin_dir:
        profile_path = os.path.join(plugin_dir, "pg", "transformer_postgresql_connections.json")
        if os.path.isfile(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as stream:
                    profiles = json.load(stream)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"processing_provider.common: lecture du profil '{profile_path}' impossible : {exc}"
                ) from exc
            container = (
                profiles.get("connections")
                if isinstance(profiles, dict) and isinstance(profiles.get("connections"), dict)
                else profiles
            )
            if isinstance(container, dict) and clean_name in container:
                prof = container[clean_name]
                if not isinstance(prof, dict):
                    raise ValueError(
                        f"processing_provider.common: profil '{clean_name}' corrompu dans '{profile_path}'."
                    )
                user = str(prof.get("username") or prof.get("user") or "")
                auth_credential = None
                authcfg = str(prof.get("authcfg") or "")
                if authcfg:
                    auth_user, auth_credential = _expand_authcfg_credentials(authcfg)
                    user = auth_user or user
                params = {
                    "host": str(prof.get("host") or "localhost"),
                    "port": _parse_port(prof.get("port", 5432), clean_name),
                    "database": str(prof.get("database") or ""),
                    "user": user,
                    "sslmode": str(prof.get("sslmode") or "prefer"),
                }
                if auth_credential:
                    params["password"] = auth_credential
                return params

    raise ValueError(
        f"processing_provider.common: connexion PostgreSQL '{clean_name}' introuvable "
        "dans les connexions QGIS ni dans les profils Transformer."
    )


def parse_pg_field_mapping_json(raw_json: str):
    """Parse optional PostgreSQL field mapping JSON into dict/list or None."""
    cleaned = (raw_json or "").strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"processing_provider.common: FIELD_MAPPING JSON invalide : {exc}"
        ) from exc
    if not isinstance(parsed, (dict, list)):
        raise ValueError(
            "processing_provider.common: FIELD_MAPPING doit etre un objet {\"src\": \"dst\"} "
            "ou une liste [{\"source\": ..., \"target\": ..., \"type\": ...}]."
        )
    return parsed


def build_processing_python_snippet(
    recipe_name: str,
    recipe_file: str = "",
    input_ref: str = "ma_couche",
) -> str:
    """Build a ready-to-paste PyQGIS processing.run() and qgis_process snippet."""
    lines = [
        "import processing",
        "",
        'result = processing.run("transformer:apply_recipe", {',
        f'    "INPUT": {input_ref!r},',
    ]
    if recipe_file:
        lines.append(f'    "RECIPE_FILE": {recipe_file!r},')
    if recipe_name:
        lines.append(f'    "RECIPE_NAME": {recipe_name!r},')
    lines.extend([
        '    "OUTPUT": "TEMPORARY_OUTPUT",',
        "})",
        'output_layer = result["OUTPUT"]',
    ])
    cli_parts = [
        "# CLI headless : qgis_process run transformer:apply_recipe",
        f"#   --INPUT={input_ref}",
    ]
    if recipe_file:
        cli_parts.append(f"#   --RECIPE_FILE={recipe_file}")
    if recipe_name:
        cli_parts.append(f"#   --RECIPE_NAME={recipe_name}")
    cli_parts.append("#   --OUTPUT=sortie.gpkg")
    return "\n".join(lines + [""] + cli_parts)
