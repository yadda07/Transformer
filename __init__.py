# -*- coding: utf-8 -*-
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
__version__ = "2.1.0"
__author__ = "yadda"
__email__ = "youcef.geodesien@gmail.com"
__description__ = "Vector file transformation w/ calculated fields"