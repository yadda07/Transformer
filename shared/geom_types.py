# -*- coding: utf-8 -*-
"""
Centralized QgsWkbTypes geometry type mappings.

Used across transformer.py and postgresql_integration.py to avoid
divergence when new geometry types are introduced.
"""

from qgis.core import QgsWkbTypes


WKB_TO_NAME = {
    QgsWkbTypes.PointGeometry: "Point",
    QgsWkbTypes.LineGeometry: "LineString",
    QgsWkbTypes.PolygonGeometry: "Polygon",
    QgsWkbTypes.UnknownGeometry: "NoGeometry",
    QgsWkbTypes.NullGeometry: "NoGeometry",
}

NAME_TO_WKB = {
    "Point": QgsWkbTypes.PointGeometry,
    "LineString": QgsWkbTypes.LineGeometry,
    "Polygon": QgsWkbTypes.PolygonGeometry,
}

WKB_TO_PG_TYPE = {
    QgsWkbTypes.PointGeometry: "MULTIPOINT",
    QgsWkbTypes.LineGeometry: "MULTILINESTRING",
    QgsWkbTypes.PolygonGeometry: "MULTIPOLYGON",
}


def get_geom_name(wkb_type) -> str:
    """Return the memory-layer URI name for a QgsWkbTypes geometry type.

    Falls back to "Point" for unknown types.
    """
    return WKB_TO_NAME.get(wkb_type, "Point")


def get_wkb_type(name: str):
    """Return the QgsWkbTypes geometry type for a name string.

    Falls back to None if the name is not recognized.
    """
    return NAME_TO_WKB.get(name)


def get_pg_geom_type(wkb_type) -> str:
    """Return the PostgreSQL geometry type name for a QgsWkbTypes geometry type.

    Falls back to "GEOMETRY" for unknown types.
    """
    return WKB_TO_PG_TYPE.get(wkb_type, "GEOMETRY")
