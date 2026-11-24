# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""QGIS Transformer Plugin

Vector file transformation w/ calculated fields.
"""

import os
import sys

# Plugin dir -> sys.path
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)


def classFactory(iface):
    """
    Factory func for plugin init.

    Args:
        iface: QGIS iface instance

    Returns:
        TransformerPlugin: Plugin instance
    """
    from .main_plugin import TransformerPlugin
    return TransformerPlugin(iface)


# Plugin meta
__version__ = "3.3.0"
__author__ = "yadda"
__email__ = "youcef.geodesien@gmail.com"
__description__ = "Atelier de recettes vectorielles pour QGIS 3.40 - 4.x (Qt 5 / Qt 6)"
