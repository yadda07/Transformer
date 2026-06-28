# -*- coding: utf-8 -*-
"""
Qt5/Qt6 enum compatibility layer for Transformer plugin.

In PyQt6 every enum moved to scoped form:
  Qt.AlignCenter          -> Qt.AlignmentFlag.AlignCenter
  QFont.Bold              -> QFont.Weight.Bold
  QMessageBox.Ok          -> QMessageBox.StandardButton.Ok

The qgis.PyQt shim does NOT always bridge these.
This module provides ready-to-use constants that resolve on both Qt5 and Qt6.

Usage in any plugin file:
    from ..shared.compat import AlignCenter, UserRole, MsgBoxOk, ...
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QKeySequence, QPalette, QColor, QTextCursor
from qgis.PyQt.QtWidgets import (
    QMainWindow, QTabWidget, QDockWidget, QFrame, QFormLayout,
    QSizePolicy, QHeaderView, QAbstractItemView, QMessageBox, QDialog,
    QLineEdit, QPlainTextEdit, QToolButton, QDialogButtonBox
)


def _resolve(scoped_parent, name, flat_parent, flat_name=None):
    """Try scoped_parent.name first (Qt6), then flat_parent.flat_name (Qt5).

    Both lookups are safe: never raises AttributeError.
    """
    val = getattr(scoped_parent, name, None)
    if val is not None:
        return val
    return getattr(flat_parent, flat_name or name, None)


# ======================================================================
# Qt namespace — Alignment
# ======================================================================
_AlignmentFlag = getattr(Qt, 'AlignmentFlag', Qt)
AlignCenter    = _resolve(_AlignmentFlag, 'AlignCenter',  Qt)
AlignLeft      = _resolve(_AlignmentFlag, 'AlignLeft',    Qt)
AlignRight     = _resolve(_AlignmentFlag, 'AlignRight',   Qt)
AlignTop       = _resolve(_AlignmentFlag, 'AlignTop',     Qt)
AlignBottom    = _resolve(_AlignmentFlag, 'AlignBottom',  Qt)
AlignVCenter   = _resolve(_AlignmentFlag, 'AlignVCenter', Qt)
AlignHCenter   = _resolve(_AlignmentFlag, 'AlignHCenter', Qt)

# ======================================================================
# Qt namespace — Orientation
# ======================================================================
_Orientation = getattr(Qt, 'Orientation', Qt)
Horizontal   = _resolve(_Orientation, 'Horizontal', Qt)
Vertical     = _resolve(_Orientation, 'Vertical',   Qt)

# ======================================================================
# Qt namespace — ItemDataRole
# ======================================================================
_ItemDataRole = getattr(Qt, 'ItemDataRole', Qt)
UserRole       = _resolve(_ItemDataRole, 'UserRole',    Qt)
DisplayRole    = _resolve(_ItemDataRole, 'DisplayRole', Qt)

# ======================================================================
# Qt namespace — TextFormat
# ======================================================================
_TextFormat = getattr(Qt, 'TextFormat', Qt)
RichText    = _resolve(_TextFormat, 'RichText',  Qt)
PlainText   = _resolve(_TextFormat, 'PlainText', Qt)

# ======================================================================
# Qt namespace — ScrollBarPolicy
# ======================================================================
_ScrollBarPolicy    = getattr(Qt, 'ScrollBarPolicy', Qt)
ScrollBarAsNeeded   = _resolve(_ScrollBarPolicy, 'ScrollBarAsNeeded',  Qt)
ScrollBarAlwaysOff  = _resolve(_ScrollBarPolicy, 'ScrollBarAlwaysOff', Qt)
ScrollBarAlwaysOn   = _resolve(_ScrollBarPolicy, 'ScrollBarAlwaysOn',  Qt)

# ======================================================================
# Qt namespace — CursorShape
# ======================================================================
_CursorShape       = getattr(Qt, 'CursorShape', Qt)
PointingHandCursor = _resolve(_CursorShape, 'PointingHandCursor', Qt)
WaitCursor         = _resolve(_CursorShape, 'WaitCursor',         Qt)
ArrowCursor        = _resolve(_CursorShape, 'ArrowCursor',        Qt)

# ======================================================================
# Qt namespace — ToolButtonStyle
# ======================================================================
_ToolButtonStyle          = getattr(Qt, 'ToolButtonStyle', Qt)
ToolButtonTextBesideIcon  = _resolve(_ToolButtonStyle, 'ToolButtonTextBesideIcon', Qt)
ToolButtonIconOnly        = _resolve(_ToolButtonStyle, 'ToolButtonIconOnly',       Qt)
ToolButtonTextOnly        = _resolve(_ToolButtonStyle, 'ToolButtonTextOnly',       Qt)

# ======================================================================
# Qt namespace — CheckState, SortOrder, WidgetAttribute
# ======================================================================
_CheckState      = getattr(Qt, 'CheckState', Qt)
_SortOrder       = getattr(Qt, 'SortOrder', Qt)
_WidgetAttribute = getattr(Qt, 'WidgetAttribute', Qt)
_DockWidgetArea  = getattr(Qt, 'DockWidgetArea', Qt)
_ToolBarArea     = getattr(Qt, 'ToolBarArea', Qt)

# ======================================================================
# QFont — Weight
# ======================================================================
_FontWeight = getattr(QFont, 'Weight', QFont)
FontBold    = _resolve(_FontWeight, 'Bold',   QFont)
FontNormal  = _resolve(_FontWeight, 'Normal', QFont)

# ======================================================================
# QTextCursor — MoveOperation & MoveMode
# ======================================================================
_MoveOperation = getattr(QTextCursor, 'MoveOperation', QTextCursor)
_MoveMode = getattr(QTextCursor, 'MoveMode', QTextCursor)
CursorEnd = _resolve(_MoveOperation, 'End', QTextCursor)
CursorUp = _resolve(_MoveOperation, 'Up', QTextCursor)
CursorLineUnder = _resolve(_MoveMode, 'LineUnderCursor', QTextCursor)

# ======================================================================
# Qt namespace — TextInteractionFlag
# ======================================================================
_TextInteractionFlag = getattr(Qt, 'TextInteractionFlag', Qt)
TextSelectableByMouse = _resolve(_TextInteractionFlag, 'TextSelectableByMouse', Qt)

# ======================================================================
# QFrame — Shape & Shadow
# ======================================================================
_FrameShape   = getattr(QFrame, 'Shape', QFrame)
_FrameShadow  = getattr(QFrame, 'Shadow', QFrame)
FrameBox          = _resolve(_FrameShape,  'Box',         QFrame)
FrameStyledPanel  = _resolve(_FrameShape,  'StyledPanel', QFrame)
FrameNoFrame      = _resolve(_FrameShape,  'NoFrame',     QFrame)
FrameHLine        = _resolve(_FrameShape,  'HLine',       QFrame)
FrameRaised       = _resolve(_FrameShadow, 'Raised',      QFrame)
FrameSunken       = _resolve(_FrameShadow, 'Sunken',      QFrame)

# ======================================================================
# QHeaderView — ResizeMode
# ======================================================================
_HeaderResizeMode       = getattr(QHeaderView, 'ResizeMode', QHeaderView)
HeaderStretch           = _resolve(_HeaderResizeMode, 'Stretch',          QHeaderView)
HeaderResizeToContents  = _resolve(_HeaderResizeMode, 'ResizeToContents', QHeaderView)
HeaderFixed             = _resolve(_HeaderResizeMode, 'Fixed',            QHeaderView)
HeaderInteractive       = _resolve(_HeaderResizeMode, 'Interactive',      QHeaderView)

# ======================================================================
# QSizePolicy — Policy
# ======================================================================
_SizePolicy = getattr(QSizePolicy, 'Policy', QSizePolicy)

# ======================================================================
# QAbstractItemView — SelectionMode & Behavior
# ======================================================================
_SelectionMode     = getattr(QAbstractItemView, 'SelectionMode', QAbstractItemView)
_SelectionBehavior = getattr(QAbstractItemView, 'SelectionBehavior', QAbstractItemView)

# ======================================================================
# QMessageBox — StandardButton & Icon
# ======================================================================
_MsgBoxButton = getattr(QMessageBox, 'StandardButton', QMessageBox)
_MsgBoxIcon   = getattr(QMessageBox, 'Icon', QMessageBox)
MsgBoxOk       = _resolve(_MsgBoxButton, 'Ok',        QMessageBox)
MsgBoxYes      = _resolve(_MsgBoxButton, 'Yes',       QMessageBox)
MsgBoxNo       = _resolve(_MsgBoxButton, 'No',        QMessageBox)
MsgBoxCancel   = _resolve(_MsgBoxButton, 'Cancel',    QMessageBox)
MsgBoxSave     = _resolve(_MsgBoxButton, 'Save',      QMessageBox)
MsgBoxDiscard  = _resolve(_MsgBoxButton, 'Discard',   QMessageBox)
MsgBoxIconInfo     = _resolve(_MsgBoxIcon, 'Information', QMessageBox)
MsgBoxIconWarning  = _resolve(_MsgBoxIcon, 'Warning',     QMessageBox)
MsgBoxIconCritical = _resolve(_MsgBoxIcon, 'Critical',    QMessageBox)
MsgBoxIconQuestion = _resolve(_MsgBoxIcon, 'Question',    QMessageBox)

# ======================================================================
# QDialog — DialogCode
# ======================================================================
_DialogCode    = getattr(QDialog, 'DialogCode', QDialog)
DialogAccepted = _resolve(_DialogCode, 'Accepted', QDialog)
DialogRejected = _resolve(_DialogCode, 'Rejected', QDialog)

# ======================================================================
# QMainWindow, QTabWidget, QDockWidget
# ======================================================================
_DockOption        = getattr(QMainWindow, 'DockOption', QMainWindow)
_TabPosition       = getattr(QTabWidget, 'TabPosition', QTabWidget)
_DockWidgetFeature = getattr(QDockWidget, 'DockWidgetFeature', QDockWidget)

# ======================================================================
# QFormLayout — FieldGrowthPolicy
# ======================================================================
_FieldGrowthPolicy  = getattr(QFormLayout, 'FieldGrowthPolicy', QFormLayout)
ExpandingFieldsGrow = _resolve(_FieldGrowthPolicy, 'ExpandingFieldsGrow', QFormLayout)

# ======================================================================
# Qt namespace -- ContextMenuPolicy
# ======================================================================
_ContextMenuPolicy = getattr(Qt, 'ContextMenuPolicy', Qt)
CustomContextMenu  = _resolve(_ContextMenuPolicy, 'CustomContextMenu', Qt)

# ======================================================================
# QAbstractItemView -- SelectionMode values
# ======================================================================
MultiSelection    = _resolve(_SelectionMode, 'MultiSelection',    QAbstractItemView)
SingleSelection   = _resolve(_SelectionMode, 'SingleSelection',   QAbstractItemView)
ExtendedSelection = _resolve(_SelectionMode, 'ExtendedSelection', QAbstractItemView)
NoSelection       = _resolve(_SelectionMode, 'NoSelection',       QAbstractItemView)

# ======================================================================
# QAbstractItemView -- SelectionBehavior values
# ======================================================================
SelectRows  = _resolve(_SelectionBehavior, 'SelectRows',  QAbstractItemView)
SelectItems = _resolve(_SelectionBehavior, 'SelectItems', QAbstractItemView)

# ======================================================================
# QLineEdit -- EchoMode
# ======================================================================
_EchoMode       = getattr(QLineEdit, 'EchoMode', QLineEdit)
PasswordEchoMode = _resolve(_EchoMode, 'Password', QLineEdit)
NormalEchoMode   = _resolve(_EchoMode, 'Normal',   QLineEdit)

# ======================================================================
# QPlainTextEdit -- LineWrapMode
# ======================================================================
_LineWrapMode = getattr(QPlainTextEdit, 'LineWrapMode', QPlainTextEdit)
WrapWidgetWidth = _resolve(_LineWrapMode, 'WidgetWidth', QPlainTextEdit)
WrapNoWrap      = _resolve(_LineWrapMode, 'NoWrap',      QPlainTextEdit)

# ======================================================================
# QToolButton -- ToolButtonPopupMode
# ======================================================================
_PopupMode    = getattr(QToolButton, 'ToolButtonPopupMode', QToolButton)
InstantPopup  = _resolve(_PopupMode, 'InstantPopup',  QToolButton)
MenuButtonPopup = _resolve(_PopupMode, 'MenuButtonPopup', QToolButton)
DelayedPopup  = _resolve(_PopupMode, 'DelayedPopup',  QToolButton)

# ======================================================================
# QKeySequence -- StandardKey
# ======================================================================
_StandardKey    = getattr(QKeySequence, 'StandardKey', QKeySequence)
KeyNew          = _resolve(_StandardKey, 'New',          QKeySequence)
KeyOpen         = _resolve(_StandardKey, 'Open',         QKeySequence)
KeySave         = _resolve(_StandardKey, 'Save',         QKeySequence)
KeyQuit         = _resolve(_StandardKey, 'Quit',         QKeySequence)
KeyUndo         = _resolve(_StandardKey, 'Undo',         QKeySequence)
KeyRedo         = _resolve(_StandardKey, 'Redo',         QKeySequence)
KeyHelpContents = _resolve(_StandardKey, 'HelpContents', QKeySequence)

# ======================================================================
# QDialogButtonBox -- StandardButton
# ======================================================================
_DlgBtnStd        = getattr(QDialogButtonBox, 'StandardButton', QDialogButtonBox)
DlgBtnOk          = _resolve(_DlgBtnStd, 'Ok',              QDialogButtonBox)
DlgBtnCancel      = _resolve(_DlgBtnStd, 'Cancel',          QDialogButtonBox)
DlgBtnClose       = _resolve(_DlgBtnStd, 'Close',           QDialogButtonBox)
DlgBtnSave        = _resolve(_DlgBtnStd, 'Save',            QDialogButtonBox)
DlgBtnDiscard     = _resolve(_DlgBtnStd, 'Discard',         QDialogButtonBox)
DlgBtnApply       = _resolve(_DlgBtnStd, 'Apply',           QDialogButtonBox)
DlgBtnReset       = _resolve(_DlgBtnStd, 'Reset',           QDialogButtonBox)
DlgBtnRestoreDefaults = _resolve(_DlgBtnStd, 'RestoreDefaults', QDialogButtonBox)
DlgBtnHelp        = _resolve(_DlgBtnStd, 'Help',            QDialogButtonBox)
DlgBtnYes         = _resolve(_DlgBtnStd, 'Yes',             QDialogButtonBox)
DlgBtnNo          = _resolve(_DlgBtnStd, 'No',              QDialogButtonBox)

# ======================================================================
# Qt namespace -- ItemDataRole (additional roles)
# ======================================================================
BackgroundRole = _resolve(_ItemDataRole, 'BackgroundRole', Qt)
ForegroundRole = _resolve(_ItemDataRole, 'ForegroundRole', Qt)

# ======================================================================
# Qt namespace -- ItemFlag
# ======================================================================
_ItemFlag       = getattr(Qt, 'ItemFlag', Qt)
ItemIsEnabled    = _resolve(_ItemFlag, 'ItemIsEnabled',    Qt)
ItemIsSelectable = _resolve(_ItemFlag, 'ItemIsSelectable', Qt)
ItemIsEditable   = _resolve(_ItemFlag, 'ItemIsEditable',   Qt)

# ======================================================================
# Qt namespace -- ShortcutContext
# ======================================================================
_ShortcutContext    = getattr(Qt, 'ShortcutContext', Qt)
ApplicationShortcut = _resolve(_ShortcutContext, 'ApplicationShortcut', Qt)
WidgetShortcut      = _resolve(_ShortcutContext, 'WidgetShortcut',      Qt)

# ======================================================================
# Qt namespace -- AspectRatioMode, TransformationMode
# ======================================================================
_AspectRatioMode      = getattr(Qt, 'AspectRatioMode', Qt)
_TransformationMode   = getattr(Qt, 'TransformationMode', Qt)
KeepAspectRatio       = _resolve(_AspectRatioMode,    'KeepAspectRatio',       Qt)
SmoothTransformation  = _resolve(_TransformationMode, 'SmoothTransformation',  Qt)


# ======================================================================
# QFont -- StyleHint (Monospace / SansSerif / Serif / Cursive / Fantasy)
# Qt6: QFont.StyleHint.Monospace ; Qt5: QFont.Monospace
# ======================================================================
_StyleHint        = getattr(QFont, 'StyleHint', QFont)
StyleHintMonospace = _resolve(_StyleHint, 'Monospace', QFont)
StyleHintSansSerif = _resolve(_StyleHint, 'SansSerif', QFont)
StyleHintSerif     = _resolve(_StyleHint, 'Serif',     QFont)


# ======================================================================
# QPalette — ColorRole
# Qt6: QPalette.ColorRole.Link ; Qt5: QPalette.Link
# Never use palette.Link on a QPalette instance — roles are class enums.
# On PyQt6, instance getters (palette.link()) are the reliable fallback.
# ======================================================================
_ROLE_GETTERS = {
    'Text': 'text',
    'Link': 'link',
    'LinkVisited': 'linkVisited',
    'PlaceholderText': 'placeholderText',
    'ToolTipText': 'toolTipText',
    'Mid': 'mid',
    'Window': 'window',
    'Base': 'base',
    'WindowText': 'windowText',
}


def _as_qcolor(value):
    """Normalize palette getter results to QColor (Qt6 getters return QBrush)."""
    if value is None:
        return QColor()
    if hasattr(value, 'lightness'):
        return value
    brush_color = getattr(value, 'color', None)
    if callable(brush_color):
        return brush_color()
    return QColor()


def _resolve_palette_role(name):
    """Resolve a QPalette ColorRole enum across Qt5/Qt6 naming variants."""
    candidates = [name]
    if name and name[0].isupper():
        candidates.append(name[0].lower() + name[1:])

    _ColorRole = getattr(QPalette, 'ColorRole', None)
    if _ColorRole is not None:
        for cand in candidates:
            val = getattr(_ColorRole, cand, None)
            if val is not None:
                return val
        try:
            target = name.lower()
            for member in _ColorRole:
                if member.name.lower() == target:
                    return member
        except TypeError:
            pass

    for cand in candidates:
        val = getattr(QPalette, cand, None)
        if val is not None and not callable(val):
            return val
    return None


def palette_color(palette, role, role_name=None):
    """Return QColor for a palette role. Safe across Qt5/Qt6 bindings.

    role: compat constant (e.g. PaletteLink) — may be None on some bindings.
    role_name: fallback name ('Link', 'Text', ...) for instance getters.
    """
    name = role_name
    if name is None and role is not None:
        name = getattr(role, 'name', None)

    # Instance getters are reliable on Qt6; try before palette.color(enum).
    getter_key = _ROLE_GETTERS.get(name)
    if not getter_key and name:
        getter_key = name[0].lower() + name[1:]
    if getter_key:
        getter = getattr(palette, getter_key, None)
        if callable(getter):
            return _as_qcolor(getter())

    if role is not None:
        try:
            return _as_qcolor(palette.color(role))
        except (TypeError, AttributeError, SystemError):
            pass

    if name:
        resolved = _resolve_palette_role(name)
        if resolved is not None and resolved is not role:
            try:
                return _as_qcolor(palette.color(resolved))
            except (TypeError, AttributeError, SystemError):
                pass

    text_getter = getattr(palette, 'text', None)
    if callable(text_getter):
        return _as_qcolor(text_getter())
    text_role = _resolve_palette_role('Text')
    if text_role is not None:
        try:
            return _as_qcolor(palette.color(text_role))
        except (TypeError, AttributeError, SystemError):
            pass
    return QColor()


PaletteText            = _resolve_palette_role('Text')
PaletteLink            = _resolve_palette_role('Link')
PaletteLinkVisited     = _resolve_palette_role('LinkVisited')
PalettePlaceholderText = _resolve_palette_role('PlaceholderText')
PaletteToolTipText     = _resolve_palette_role('ToolTipText')
PaletteMid             = _resolve_palette_role('Mid')
PaletteWindow          = _resolve_palette_role('Window')
PaletteBase            = _resolve_palette_role('Base')
PaletteWindowText      = _resolve_palette_role('WindowText')


# ======================================================================
# Qt namespace — GlobalColor
# Qt6: Qt.GlobalColor.transparent ; Qt5: Qt.transparent
# ======================================================================
_GlobalColor    = getattr(Qt, 'GlobalColor', Qt)
GlobalTransparent = _resolve(_GlobalColor, 'transparent', Qt)


# ======================================================================
# Runtime version detection (enterprise compat layer)
# ----------------------------------------------------------------------
# Provides explicit runtime knowledge of:
#   - QGIS version (Qgis.QGIS_VERSION_INT, e.g. 34000 for 3.40.0)
#   - Qt major version (5 or 6)
#   - PyQt binding (PyQt5 or PyQt6)
# Plus boolean shortcuts for feature gates.
# ======================================================================

def _detect_qgis_version():
    """Return (major, minor, patch, version_int) or (0,0,0,0) if unavailable."""
    try:
        from qgis.core import Qgis
        version_int = getattr(Qgis, 'QGIS_VERSION_INT', 0)
        if version_int:
            major = version_int // 10000
            minor = (version_int // 100) % 100
            patch = version_int % 100
            return major, minor, patch, version_int
    except ImportError:
        pass
    return 0, 0, 0, 0


def _detect_qt_version():
    """Return (qt_major, binding_name)."""
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR
        qt_major = int(QT_VERSION_STR.split('.')[0])
    except Exception:
        qt_major = 0
    binding = "unknown"
    try:
        import qgis.PyQt
        binding = getattr(qgis.PyQt, 'PYQT_VERSION', None) or "PyQt5/6"
        # More reliable detection
        try:
            import PyQt6  # noqa: F401
            binding = "PyQt6"
        except ImportError:
            try:
                import PyQt5  # noqa: F401
                binding = "PyQt5"
            except ImportError:
                pass
    except Exception:
        pass
    return qt_major, binding


QGIS_MAJOR, QGIS_MINOR, QGIS_PATCH, QGIS_VERSION_INT = _detect_qgis_version()
QT_MAJOR, QT_BINDING = _detect_qt_version()

# Feature gates - use these instead of hardcoded version checks
IS_QT6 = QT_MAJOR >= 6
IS_QT5 = QT_MAJOR == 5
IS_QGIS_3 = QGIS_MAJOR == 3
IS_QGIS_4 = QGIS_MAJOR >= 4
IS_QGIS_3_40_OR_LATER = QGIS_VERSION_INT >= 34000
IS_QGIS_3_44_OR_LATER = QGIS_VERSION_INT >= 34400


def version_summary() -> str:
    """Compact version string for diagnostics. Always safe to call."""
    return (
        f"QGIS {QGIS_MAJOR}.{QGIS_MINOR}.{QGIS_PATCH} "
        f"(int={QGIS_VERSION_INT}) | Qt {QT_MAJOR} | {QT_BINDING}"
    )


def feature_supported(feature: str) -> bool:
    """Boolean check for known feature gates.

    Centralized so callers never inline version comparisons.
    Add new gates here when introducing version-conditional code.
    """
    gates = {
        "qgs_task": True,  # available since 3.0
        "qgs_message_bar_widget": IS_QGIS_3_40_OR_LATER,
        "qgs_proxy_model": IS_QGIS_3_40_OR_LATER,
        "qgs_geometry_engine": True,
        "scoped_enums": IS_QT6,
    }
    return gates.get(feature, False)


def safe_iface():
    """Return qgis.utils.iface or None. Never raises."""
    try:
        from qgis.utils import iface
        return iface
    except Exception:
        return None


def log_environment(logger=None):
    """Log a one-line environment summary to QgsMessageLog and optional logger."""
    summary = version_summary()
    try:
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(f"Transformer environment: {summary}", "Transformer", Qgis.Info)
    except Exception:
        pass
    if logger is not None and hasattr(logger, 'info'):
        logger.info(summary, module="system", code="ENV_DETECT")

