# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Qt 5 / Qt 6 and QGIS 3.40 - 4.x compatibility layer for Transformer plugin.

Provides cross-version enum constants, moved Qt classes (QAction, QShortcut),
and small runtime adapters for APIs whose signature or return type differs
between Qt 5.15 / QGIS 3.40 and Qt 6.x / QGIS 4.x.
"""

from qgis.core import Qgis as _Qgis
from qgis.core import QgsFeatureRequest as _QgsFeatureRequest
from qgis.core import QgsTask as _QgsTask
from qgis.core import QgsWkbTypes as _QgsWkbTypes
from qgis.PyQt.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QMetaType,
    QSettings,
    QSize,
    Qt,
)
from qgis.PyQt.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QTextCursor,
)
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QToolButton,
)

try:
    from qgis.core import QgsMapLayerType as _QgsMapLayerType
except ImportError:
    _QgsMapLayerType = None

try:
    from qgis.core import QgsVectorFileWriter as _QgsVFW
except ImportError:
    _QgsVFW = None

# QAction and QShortcut moved from QtWidgets (Qt5) to QtGui (Qt6).
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # noqa: F401

try:
    from qgis.PyQt.QtGui import QShortcut
except ImportError:
    from qgis.PyQt.QtWidgets import QShortcut  # noqa: F401


def _resolve(scoped_parent, name, flat_parent, flat_name=None):
    """Try scoped_parent.name first (Qt6), then flat_parent.flat_name (Qt5)."""
    val = getattr(scoped_parent, name, None)
    if val is not None:
        return val
    return getattr(flat_parent, flat_name or name, None)


# ======================================================================
# Runtime version detection
# ======================================================================

def _detect_qgis_version():
    """Return (major, minor, patch, version_int) or (0, 0, 0, 0)."""
    version_int = getattr(_Qgis, 'QGIS_VERSION_INT', 0)
    if version_int:
        major = version_int // 10000
        minor = (version_int // 100) % 100
        patch = version_int % 100
        return major, minor, patch, version_int
    return 0, 0, 0, 0


def _detect_qt_version():
    """Return (qt_major, binding_name) using qgis.PyQt only."""
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR
        qt_major = int(QT_VERSION_STR.split('.')[0])
    except Exception:
        qt_major = 0
    try:
        from qgis.PyQt.QtCore import PYQT_VERSION_STR
        pyqt_major = PYQT_VERSION_STR.split('.')[0]
        binding = f"PyQt{pyqt_major}"
    except Exception:
        binding = f"PyQt{qt_major}" if qt_major else "unknown"
    return qt_major, binding


QGIS_MAJOR, QGIS_MINOR, QGIS_PATCH, QGIS_VERSION_INT = _detect_qgis_version()
QT_MAJOR, QT_BINDING = _detect_qt_version()

IS_QT6 = QT_MAJOR >= 6
IS_QT5 = QT_MAJOR == 5
IS_QGIS_3 = QGIS_MAJOR == 3
IS_QGIS_4 = QGIS_MAJOR >= 4
IS_QGIS_3_40_OR_LATER = QGIS_VERSION_INT >= 34000
IS_QGIS_3_44_OR_LATER = QGIS_VERSION_INT >= 34400


# ======================================================================
# Qt namespace - Alignment
# ======================================================================
_AlignmentFlag = getattr(Qt, 'AlignmentFlag', Qt)
AlignCenter = _resolve(_AlignmentFlag, 'AlignCenter', Qt)
AlignLeft = _resolve(_AlignmentFlag, 'AlignLeft', Qt)
AlignRight = _resolve(_AlignmentFlag, 'AlignRight', Qt)
AlignTop = _resolve(_AlignmentFlag, 'AlignTop', Qt)
AlignBottom = _resolve(_AlignmentFlag, 'AlignBottom', Qt)
AlignVCenter = _resolve(_AlignmentFlag, 'AlignVCenter', Qt)
AlignHCenter = _resolve(_AlignmentFlag, 'AlignHCenter', Qt)

# ======================================================================
# Qt namespace - Orientation
# ======================================================================
_Orientation = getattr(Qt, 'Orientation', Qt)
Horizontal = _resolve(_Orientation, 'Horizontal', Qt)
Vertical = _resolve(_Orientation, 'Vertical', Qt)

# ======================================================================
# Qt namespace - ItemDataRole
# ======================================================================
_ItemDataRole = getattr(Qt, 'ItemDataRole', Qt)
UserRole = _resolve(_ItemDataRole, 'UserRole', Qt)
DisplayRole = _resolve(_ItemDataRole, 'DisplayRole', Qt)
ToolTipRole = _resolve(_ItemDataRole, 'ToolTipRole', Qt)
BackgroundRole = _resolve(_ItemDataRole, 'BackgroundRole', Qt)
ForegroundRole = _resolve(_ItemDataRole, 'ForegroundRole', Qt)
AccessibleDescriptionRole = _resolve(_ItemDataRole, 'AccessibleDescriptionRole', Qt)

# ======================================================================
# Qt namespace - TextFormat, TextFlag, TextElideMode
# ======================================================================
_TextFormat = getattr(Qt, 'TextFormat', Qt)
RichText = _resolve(_TextFormat, 'RichText', Qt)
PlainText = _resolve(_TextFormat, 'PlainText', Qt)

_TextFlag = getattr(Qt, 'TextFlag', Qt)
TextWordWrap = _resolve(_TextFlag, 'TextWordWrap', Qt)

_TextElideMode = getattr(Qt, 'TextElideMode', Qt)
TextElideNone = _resolve(_TextElideMode, 'ElideNone', Qt)

# ======================================================================
# Qt namespace - ScrollBarPolicy
# ======================================================================
_ScrollBarPolicy = getattr(Qt, 'ScrollBarPolicy', Qt)
ScrollBarAsNeeded = _resolve(_ScrollBarPolicy, 'ScrollBarAsNeeded', Qt)
ScrollBarAlwaysOff = _resolve(_ScrollBarPolicy, 'ScrollBarAlwaysOff', Qt)
ScrollBarAlwaysOn = _resolve(_ScrollBarPolicy, 'ScrollBarAlwaysOn', Qt)

# ======================================================================
# Qt namespace - CursorShape
# ======================================================================
_CursorShape = getattr(Qt, 'CursorShape', Qt)
PointingHandCursor = _resolve(_CursorShape, 'PointingHandCursor', Qt)
WaitCursor = _resolve(_CursorShape, 'WaitCursor', Qt)
ArrowCursor = _resolve(_CursorShape, 'ArrowCursor', Qt)

# ======================================================================
# Qt namespace - ToolButtonStyle
# ======================================================================
_ToolButtonStyle = getattr(Qt, 'ToolButtonStyle', Qt)
ToolButtonTextBesideIcon = _resolve(_ToolButtonStyle, 'ToolButtonTextBesideIcon', Qt)
ToolButtonIconOnly = _resolve(_ToolButtonStyle, 'ToolButtonIconOnly', Qt)
ToolButtonTextOnly = _resolve(_ToolButtonStyle, 'ToolButtonTextOnly', Qt)

# ======================================================================
# Qt namespace - FocusPolicy
# ======================================================================
_FocusPolicy = getattr(Qt, 'FocusPolicy', Qt)
FocusStrongFocus = _resolve(_FocusPolicy, 'StrongFocus', Qt)
FocusNoFocus = _resolve(_FocusPolicy, 'NoFocus', Qt)

# ======================================================================
# Qt namespace - CheckState, SortOrder, WidgetAttribute, Dock/ToolBar
# ======================================================================
_CheckState = getattr(Qt, 'CheckState', Qt)
_SortOrder = getattr(Qt, 'SortOrder', Qt)
_WidgetAttribute = getattr(Qt, 'WidgetAttribute', Qt)
WidgetAttrTransparentForMouse = _resolve(
    _WidgetAttribute, 'WA_TransparentForMouseEvents', Qt
)
WidgetAttrNoSystemBackground = _resolve(
    _WidgetAttribute, 'WA_NoSystemBackground', Qt
)

_DockWidgetArea = getattr(Qt, 'DockWidgetArea', Qt)
AllDockAreas = _resolve(_DockWidgetArea, 'AllDockWidgetAreas', Qt)
LeftDockArea = _resolve(_DockWidgetArea, 'LeftDockWidgetArea', Qt)
RightDockArea = _resolve(_DockWidgetArea, 'RightDockWidgetArea', Qt)
TopDockArea = _resolve(_DockWidgetArea, 'TopDockWidgetArea', Qt)
BottomDockArea = _resolve(_DockWidgetArea, 'BottomDockWidgetArea', Qt)

_ToolBarArea = getattr(Qt, 'ToolBarArea', Qt)

# ======================================================================
# Qt namespace - Keys, Modifiers, MouseButtons
# ======================================================================
_Key = getattr(Qt, 'Key', Qt)
KeySpace = _resolve(_Key, 'Key_Space', Qt)
KeyReturn = _resolve(_Key, 'Key_Return', Qt)
KeyEnter = _resolve(_Key, 'Key_Enter', Qt)
KeyF2 = _resolve(_Key, 'Key_F2', Qt)
KeyDelete = _resolve(_Key, 'Key_Delete', Qt)
KeyLeft = _resolve(_Key, 'Key_Left', Qt)
KeyTab = _resolve(_Key, 'Key_Tab', Qt)
KeyEscape = _resolve(_Key, 'Key_Escape', Qt)

_KeyboardModifier = getattr(Qt, 'KeyboardModifier', Qt)
NoModifier = _resolve(_KeyboardModifier, 'NoModifier', Qt)

_MouseButton = getattr(Qt, 'MouseButton', Qt)
MouseLeftButton = _resolve(_MouseButton, 'LeftButton', Qt)

# ======================================================================
# QEvent - Type
# ======================================================================
_EventType = getattr(QEvent, 'Type', QEvent)
EventKeyPress = _resolve(_EventType, 'KeyPress', QEvent)
EventMouseButtonPress = _resolve(_EventType, 'MouseButtonPress', QEvent)
EventMouseMove = _resolve(_EventType, 'MouseMove', QEvent)
EventFocusIn = _resolve(_EventType, 'FocusIn', QEvent)
EventFocusOut = _resolve(_EventType, 'FocusOut', QEvent)
EventFontChange = _resolve(_EventType, 'FontChange', QEvent)
EventPaletteChange = _resolve(_EventType, 'PaletteChange', QEvent)
EventApplicationPaletteChange = _resolve(_EventType, 'ApplicationPaletteChange', QEvent)
EventApplicationFontChange = _resolve(_EventType, 'ApplicationFontChange', QEvent)
EventDynamicPropertyChange = _resolve(_EventType, 'DynamicPropertyChange', QEvent)
EventEnabledChange = _resolve(_EventType, 'EnabledChange', QEvent)
EventToolTip = _resolve(_EventType, 'ToolTip', QEvent)
EventLeave = _resolve(_EventType, 'Leave', QEvent)
EventResize = _resolve(_EventType, 'Resize', QEvent)
EventShow = _resolve(_EventType, 'Show', QEvent)
EventHide = _resolve(_EventType, 'Hide', QEvent)
EventWindowActivate = _resolve(_EventType, 'WindowActivate', QEvent)
EventWindowDeactivate = _resolve(_EventType, 'WindowDeactivate', QEvent)
EventDeferredDelete = _resolve(_EventType, 'DeferredDelete', QEvent)

# ======================================================================
# QFont - Weight & StyleHint
# ======================================================================
_FontWeight = getattr(QFont, 'Weight', QFont)
FontBold = _resolve(_FontWeight, 'Bold', QFont)
FontDemiBold = _resolve(_FontWeight, 'DemiBold', QFont)
FontNormal = _resolve(_FontWeight, 'Normal', QFont)

_StyleHint = getattr(QFont, 'StyleHint', QFont)
StyleHintMonospace = _resolve(_StyleHint, 'Monospace', QFont)
StyleHintSansSerif = _resolve(_StyleHint, 'SansSerif', QFont)
StyleHintSerif = _resolve(_StyleHint, 'Serif', QFont)

# ======================================================================
# QTextCursor - MoveOperation, MoveMode, SelectionType
# ======================================================================
_MoveOperation = getattr(QTextCursor, 'MoveOperation', QTextCursor)
_MoveMode = getattr(QTextCursor, 'MoveMode', QTextCursor)
_SelectionType = getattr(QTextCursor, 'SelectionType', QTextCursor)
CursorEnd = _resolve(_MoveOperation, 'End', QTextCursor)
CursorUp = _resolve(_MoveOperation, 'Up', QTextCursor)
CursorStartOfLine = _resolve(_MoveOperation, 'StartOfLine', QTextCursor)
CursorKeepAnchor = _resolve(_MoveMode, 'KeepAnchor', QTextCursor)
CursorLineUnder = _resolve(_SelectionType, 'LineUnderCursor', QTextCursor)

# ======================================================================
# Qt namespace - TextInteractionFlag
# ======================================================================
_TextInteractionFlag = getattr(Qt, 'TextInteractionFlag', Qt)
TextSelectableByMouse = _resolve(_TextInteractionFlag, 'TextSelectableByMouse', Qt)

# ======================================================================
# QFrame - Shape & Shadow
# ======================================================================
_FrameShape = getattr(QFrame, 'Shape', QFrame)
_FrameShadow = getattr(QFrame, 'Shadow', QFrame)
FrameBox = _resolve(_FrameShape, 'Box', QFrame)
FrameStyledPanel = _resolve(_FrameShape, 'StyledPanel', QFrame)
FrameNoFrame = _resolve(_FrameShape, 'NoFrame', QFrame)
FrameHLine = _resolve(_FrameShape, 'HLine', QFrame)
FrameRaised = _resolve(_FrameShadow, 'Raised', QFrame)
FrameSunken = _resolve(_FrameShadow, 'Sunken', QFrame)

# ======================================================================
# QHeaderView - ResizeMode
# ======================================================================
_HeaderResizeMode = getattr(QHeaderView, 'ResizeMode', QHeaderView)
HeaderStretch = _resolve(_HeaderResizeMode, 'Stretch', QHeaderView)
HeaderResizeToContents = _resolve(_HeaderResizeMode, 'ResizeToContents', QHeaderView)
HeaderFixed = _resolve(_HeaderResizeMode, 'Fixed', QHeaderView)
HeaderInteractive = _resolve(_HeaderResizeMode, 'Interactive', QHeaderView)

# ======================================================================
# QSizePolicy - Policy
# ======================================================================
_SizePolicy = getattr(QSizePolicy, 'Policy', QSizePolicy)
SizePolicyFixed = _resolve(_SizePolicy, 'Fixed', QSizePolicy)
SizePolicyMinimum = _resolve(_SizePolicy, 'Minimum', QSizePolicy)
SizePolicyMaximum = _resolve(_SizePolicy, 'Maximum', QSizePolicy)
SizePolicyPreferred = _resolve(_SizePolicy, 'Preferred', QSizePolicy)
SizePolicyExpanding = _resolve(_SizePolicy, 'Expanding', QSizePolicy)
SizePolicyIgnored = _resolve(_SizePolicy, 'Ignored', QSizePolicy)

# ======================================================================
# QAbstractItemView - SelectionMode, SelectionBehavior, EditTrigger
# ======================================================================
_SelectionMode = getattr(QAbstractItemView, 'SelectionMode', QAbstractItemView)
_SelectionBehavior = getattr(QAbstractItemView, 'SelectionBehavior', QAbstractItemView)
_EditTrigger = getattr(QAbstractItemView, 'EditTrigger', QAbstractItemView)
MultiSelection = _resolve(_SelectionMode, 'MultiSelection', QAbstractItemView)
SingleSelection = _resolve(_SelectionMode, 'SingleSelection', QAbstractItemView)
ExtendedSelection = _resolve(_SelectionMode, 'ExtendedSelection', QAbstractItemView)
NoSelection = _resolve(_SelectionMode, 'NoSelection', QAbstractItemView)
SelectRows = _resolve(_SelectionBehavior, 'SelectRows', QAbstractItemView)
SelectItems = _resolve(_SelectionBehavior, 'SelectItems', QAbstractItemView)
NoEditTriggers = _resolve(_EditTrigger, 'NoEditTriggers', QAbstractItemView)

# ======================================================================
# QMessageBox - StandardButton & Icon
# ======================================================================
_MsgBoxButton = getattr(QMessageBox, 'StandardButton', QMessageBox)
_MsgBoxIcon = getattr(QMessageBox, 'Icon', QMessageBox)
MsgBoxOk = _resolve(_MsgBoxButton, 'Ok', QMessageBox)
MsgBoxYes = _resolve(_MsgBoxButton, 'Yes', QMessageBox)
MsgBoxNo = _resolve(_MsgBoxButton, 'No', QMessageBox)
MsgBoxCancel = _resolve(_MsgBoxButton, 'Cancel', QMessageBox)
MsgBoxSave = _resolve(_MsgBoxButton, 'Save', QMessageBox)
MsgBoxDiscard = _resolve(_MsgBoxButton, 'Discard', QMessageBox)
MsgBoxIconInfo = _resolve(_MsgBoxIcon, 'Information', QMessageBox)
MsgBoxIconWarning = _resolve(_MsgBoxIcon, 'Warning', QMessageBox)
MsgBoxIconCritical = _resolve(_MsgBoxIcon, 'Critical', QMessageBox)
MsgBoxIconQuestion = _resolve(_MsgBoxIcon, 'Question', QMessageBox)

# ======================================================================
# QDialog - DialogCode
# ======================================================================
_DialogCode = getattr(QDialog, 'DialogCode', QDialog)
DialogAccepted = _resolve(_DialogCode, 'Accepted', QDialog)
DialogRejected = _resolve(_DialogCode, 'Rejected', QDialog)

# ======================================================================
# QMainWindow, QTabWidget, QDockWidget
# ======================================================================
_DockOption = getattr(QMainWindow, 'DockOption', QMainWindow)
DockAllowNestedDocks = _resolve(_DockOption, 'AllowNestedDocks', QMainWindow)
DockAllowTabbedDocks = _resolve(_DockOption, 'AllowTabbedDocks', QMainWindow)

_TabPosition = getattr(QTabWidget, 'TabPosition', QTabWidget)
TabNorth = _resolve(_TabPosition, 'North', QTabWidget)
TabSouth = _resolve(_TabPosition, 'South', QTabWidget)

_DockWidgetFeature = getattr(QDockWidget, 'DockWidgetFeature', QDockWidget)
DockMovable = _resolve(_DockWidgetFeature, 'DockWidgetMovable', QDockWidget)
DockFloatable = _resolve(_DockWidgetFeature, 'DockWidgetFloatable', QDockWidget)
DockClosable = _resolve(_DockWidgetFeature, 'DockWidgetClosable', QDockWidget)

# ======================================================================
# QFormLayout, QComboBox, QFileDialog
# ======================================================================
_FieldGrowthPolicy = getattr(QFormLayout, 'FieldGrowthPolicy', QFormLayout)
ExpandingFieldsGrow = _resolve(_FieldGrowthPolicy, 'ExpandingFieldsGrow', QFormLayout)
FormAllNonFixedFieldsGrow = _resolve(_FieldGrowthPolicy, 'AllNonFixedFieldsGrow', QFormLayout)

_RowWrapPolicy = getattr(QFormLayout, 'RowWrapPolicy', QFormLayout)
FormWrapLongRows = _resolve(_RowWrapPolicy, 'WrapLongRows', QFormLayout)

_ComboSizeAdjust = getattr(QComboBox, 'SizeAdjustPolicy', QComboBox)
ComboAdjustMinContentsIcon = _resolve(
    _ComboSizeAdjust, 'AdjustToMinimumContentsLengthWithIcon', QComboBox
)

_FileDialogOption = getattr(QFileDialog, 'Option', QFileDialog)
FileDialogDontConfirmOverwrite = _resolve(
    _FileDialogOption, 'DontConfirmOverwrite', QFileDialog
)

# ======================================================================
# Qt namespace - ContextMenuPolicy
# ======================================================================
_ContextMenuPolicy = getattr(Qt, 'ContextMenuPolicy', Qt)
CustomContextMenu = _resolve(_ContextMenuPolicy, 'CustomContextMenu', Qt)

# ======================================================================
# QLineEdit, QPlainTextEdit, QToolButton
# ======================================================================
_EchoMode = getattr(QLineEdit, 'EchoMode', QLineEdit)
PasswordEchoMode = _resolve(_EchoMode, 'Password', QLineEdit)
NormalEchoMode = _resolve(_EchoMode, 'Normal', QLineEdit)

_LineWrapMode = getattr(QPlainTextEdit, 'LineWrapMode', QPlainTextEdit)
WrapWidgetWidth = _resolve(_LineWrapMode, 'WidgetWidth', QPlainTextEdit)
WrapNoWrap = _resolve(_LineWrapMode, 'NoWrap', QPlainTextEdit)

_PopupMode = getattr(QToolButton, 'ToolButtonPopupMode', QToolButton)
InstantPopup = _resolve(_PopupMode, 'InstantPopup', QToolButton)
MenuButtonPopup = _resolve(_PopupMode, 'MenuButtonPopup', QToolButton)
DelayedPopup = _resolve(_PopupMode, 'DelayedPopup', QToolButton)

# ======================================================================
# QKeySequence - StandardKey
# ======================================================================
_StandardKey = getattr(QKeySequence, 'StandardKey', QKeySequence)
KeyNew = _resolve(_StandardKey, 'New', QKeySequence)
KeyOpen = _resolve(_StandardKey, 'Open', QKeySequence)
KeySave = _resolve(_StandardKey, 'Save', QKeySequence)
KeyQuit = _resolve(_StandardKey, 'Quit', QKeySequence)
KeyUndo = _resolve(_StandardKey, 'Undo', QKeySequence)
KeyRedo = _resolve(_StandardKey, 'Redo', QKeySequence)
KeyHelpContents = _resolve(_StandardKey, 'HelpContents', QKeySequence)

# ======================================================================
# QDialogButtonBox - StandardButton
# ======================================================================
_DlgBtnStd = getattr(QDialogButtonBox, 'StandardButton', QDialogButtonBox)
DlgBtnOk = _resolve(_DlgBtnStd, 'Ok', QDialogButtonBox)
DlgBtnCancel = _resolve(_DlgBtnStd, 'Cancel', QDialogButtonBox)
DlgBtnClose = _resolve(_DlgBtnStd, 'Close', QDialogButtonBox)
DlgBtnSave = _resolve(_DlgBtnStd, 'Save', QDialogButtonBox)
DlgBtnDiscard = _resolve(_DlgBtnStd, 'Discard', QDialogButtonBox)
DlgBtnApply = _resolve(_DlgBtnStd, 'Apply', QDialogButtonBox)
DlgBtnReset = _resolve(_DlgBtnStd, 'Reset', QDialogButtonBox)
DlgBtnRestoreDefaults = _resolve(_DlgBtnStd, 'RestoreDefaults', QDialogButtonBox)
DlgBtnHelp = _resolve(_DlgBtnStd, 'Help', QDialogButtonBox)
DlgBtnYes = _resolve(_DlgBtnStd, 'Yes', QDialogButtonBox)
DlgBtnNo = _resolve(_DlgBtnStd, 'No', QDialogButtonBox)

# ======================================================================
# Qt namespace - ItemFlag, ShortcutContext, AspectRatioMode, TransformationMode
# ======================================================================
_ItemFlag = getattr(Qt, 'ItemFlag', Qt)
ItemIsEnabled = _resolve(_ItemFlag, 'ItemIsEnabled', Qt)
ItemIsSelectable = _resolve(_ItemFlag, 'ItemIsSelectable', Qt)
ItemIsEditable = _resolve(_ItemFlag, 'ItemIsEditable', Qt)

_ShortcutContext = getattr(Qt, 'ShortcutContext', Qt)
ApplicationShortcut = _resolve(_ShortcutContext, 'ApplicationShortcut', Qt)
WidgetShortcut = _resolve(_ShortcutContext, 'WidgetShortcut', Qt)

_AspectRatioMode = getattr(Qt, 'AspectRatioMode', Qt)
_TransformationMode = getattr(Qt, 'TransformationMode', Qt)
KeepAspectRatio = _resolve(_AspectRatioMode, 'KeepAspectRatio', Qt)
SmoothTransformation = _resolve(_TransformationMode, 'SmoothTransformation', Qt)

# ======================================================================
# QIcon, QStyle, QImage, QPainter, QEasingCurve, QAbstractAnimation, QSettings
# ======================================================================
_IconMode = getattr(QIcon, 'Mode', QIcon)
_IconState = getattr(QIcon, 'State', QIcon)
IconModeNormal = _resolve(_IconMode, 'Normal', QIcon)
IconModeDisabled = _resolve(_IconMode, 'Disabled', QIcon)
IconStateOff = _resolve(_IconState, 'Off', QIcon)
IconStateOn = _resolve(_IconState, 'On', QIcon)

_StyleState = getattr(QStyle, 'StateFlag', QStyle)
_StyleCE = getattr(QStyle, 'ControlElement', QStyle)
StyleStateEnabled = _resolve(_StyleState, 'State_Enabled', QStyle)
StyleCEPushButtonLabel = _resolve(_StyleCE, 'CE_PushButtonLabel', QStyle)

_ImageFormat = getattr(QImage, 'Format', QImage)
ImageFormatARGB32Premultiplied = _resolve(
    _ImageFormat, 'Format_ARGB32_Premultiplied', QImage
)

_RenderHint = getattr(QPainter, 'RenderHint', QPainter)
Antialias = _resolve(_RenderHint, 'Antialiasing', QPainter)

_CompositionMode = getattr(QPainter, 'CompositionMode', QPainter)
CompositionSourceIn = _resolve(_CompositionMode, 'CompositionMode_SourceIn', QPainter)

_PenStyle = getattr(Qt, 'PenStyle', Qt)
NoPen = _resolve(_PenStyle, 'NoPen', Qt)
PenSolidLine = _resolve(_PenStyle, 'SolidLine', Qt)

_PenCapStyle = getattr(Qt, 'PenCapStyle', Qt)
PenCapRound = _resolve(_PenCapStyle, 'RoundCap', Qt)

_BrushStyle = getattr(Qt, 'BrushStyle', Qt)
BrushNoBrush = _resolve(_BrushStyle, 'NoBrush', Qt)

_GlobalColor = getattr(Qt, 'GlobalColor', Qt)
GlobalTransparent = _resolve(_GlobalColor, 'transparent', Qt)

_EasingType = getattr(QEasingCurve, 'Type', QEasingCurve)
EaseInOutQuad = _resolve(_EasingType, 'InOutQuad', QEasingCurve)
EaseOutCubic = _resolve(_EasingType, 'OutCubic', QEasingCurve)

_AnimState = getattr(QAbstractAnimation, 'State', QAbstractAnimation)
AnimationStopped = _resolve(_AnimState, 'Stopped', QAbstractAnimation)

_SettingsFormat = getattr(QSettings, 'Format', QSettings)
_SettingsScope = getattr(QSettings, 'Scope', QSettings)
SettingsIniFormat = _resolve(_SettingsFormat, 'IniFormat', QSettings)
SettingsNativeFormat = _resolve(_SettingsFormat, 'NativeFormat', QSettings)
SettingsUserScope = _resolve(_SettingsScope, 'UserScope', QSettings)
SettingsSystemScope = _resolve(_SettingsScope, 'SystemScope', QSettings)


# ======================================================================
# QPalette - ColorGroup & ColorRole
# ======================================================================
_PaletteGroup = getattr(QPalette, 'ColorGroup', QPalette)
PaletteGroupActive = _resolve(_PaletteGroup, 'Active', QPalette)
PaletteGroupInactive = _resolve(_PaletteGroup, 'Inactive', QPalette)
PaletteGroupDisabled = _resolve(_PaletteGroup, 'Disabled', QPalette)

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
    'Button': 'button',
    'ButtonText': 'buttonText',
    'Highlight': 'highlight',
    'HighlightedText': 'highlightedText',
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

    color_role = getattr(QPalette, 'ColorRole', None)
    if color_role is not None:
        for cand in candidates:
            val = getattr(color_role, cand, None)
            if val is not None:
                return val
        try:
            target = name.lower()
            for member in color_role:
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
    """Return QColor for a palette role safely across Qt5/Qt6 bindings."""
    name = role_name
    if name is None and role is not None:
        name = getattr(role, 'name', None)

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


PaletteText = _resolve_palette_role('Text')
PaletteLink = _resolve_palette_role('Link')
PaletteLinkVisited = _resolve_palette_role('LinkVisited')
PalettePlaceholderText = _resolve_palette_role('PlaceholderText')
PaletteToolTipText = _resolve_palette_role('ToolTipText')
PaletteMid = _resolve_palette_role('Mid')
PaletteWindow = _resolve_palette_role('Window')
PaletteBase = _resolve_palette_role('Base')
PaletteWindowText = _resolve_palette_role('WindowText')
PaletteButton = _resolve_palette_role('Button')
PaletteButtonText = _resolve_palette_role('ButtonText')
PaletteHighlight = _resolve_palette_role('Highlight')
PaletteHighlightedText = _resolve_palette_role('HighlightedText')


# ======================================================================
# QGIS core enums - cross-version 3.40 to 4.x
# ======================================================================
_MessageLevel = getattr(_Qgis, 'MessageLevel', _Qgis)
MsgInfo = _resolve(_MessageLevel, 'Info', _Qgis)
MsgWarning = _resolve(_MessageLevel, 'Warning', _Qgis)
MsgCritical = _resolve(_MessageLevel, 'Critical', _Qgis)
MsgSuccess = _resolve(_MessageLevel, 'Success', _Qgis)

_GeometryType = getattr(_QgsWkbTypes, 'GeometryType', _QgsWkbTypes)
GeomNull = _resolve(_GeometryType, 'Null', _QgsWkbTypes, 'NullGeometry')
GeomPoint = _resolve(_GeometryType, 'Point', _QgsWkbTypes, 'PointGeometry')
GeomLine = _resolve(_GeometryType, 'Line', _QgsWkbTypes, 'LineGeometry')
GeomPolygon = _resolve(_GeometryType, 'Polygon', _QgsWkbTypes, 'PolygonGeometry')
GeomUnknown = _resolve(_GeometryType, 'Unknown', _QgsWkbTypes, 'UnknownGeometry')

_TaskFlag = getattr(_QgsTask, 'Flag', _QgsTask)
TaskCanCancel = _resolve(_TaskFlag, 'CanCancel', _QgsTask)

if _QgsVFW is not None:
    _WriterError = getattr(_QgsVFW, 'WriterError', _QgsVFW)
    WriterNoError = _resolve(_WriterError, 'NoError', _QgsVFW)
else:
    WriterNoError = 0

_LayerType = getattr(_Qgis, 'LayerType', None)
LayerTypeVector = _resolve(
    _LayerType if _LayerType is not None else _QgsMapLayerType,
    'Vector',
    _QgsMapLayerType,
    'VectorLayer',
)

_FeatureRequestFlag = getattr(_Qgis, 'FeatureRequestFlag', None)
if _FeatureRequestFlag is not None and hasattr(_FeatureRequestFlag, 'NoGeometry'):
    FeatureRequestNoGeometry = _FeatureRequestFlag.NoGeometry
else:
    _ReqFlags = getattr(_QgsFeatureRequest, 'Flag', _QgsFeatureRequest)
    FeatureRequestNoGeometry = _resolve(_ReqFlags, 'NoGeometry', _QgsFeatureRequest)


# ======================================================================
# Qt 5 / Qt 6 runtime adapters (fonts, HiDPI pixmaps, QMetaType, geometry)
# ======================================================================

_FONT_FAMILIES_CACHE = None


def font_database_families():
    """Return installed font families on both Qt 5 (instance) and Qt 6 (static)."""
    global _FONT_FAMILIES_CACHE
    if _FONT_FAMILIES_CACHE is not None:
        return list(_FONT_FAMILIES_CACHE)
    if IS_QT6:
        families = list(QFontDatabase.families())
    else:
        try:
            families = list(QFontDatabase().families())
        except TypeError:
            families = list(QFontDatabase.families())
    from qgis.PyQt.QtWidgets import QApplication
    if families and QApplication.instance() is not None:
        _FONT_FAMILIES_CACHE = tuple(families)
    return families


def fixed_system_font():
    """Return the platform monospace system font on both Qt 5 and Qt 6."""
    sys_font = getattr(QFontDatabase, 'SystemFont', QFontDatabase)
    fixed = _resolve(sys_font, 'FixedFont', QFontDatabase)
    return QFontDatabase.systemFont(fixed)


def icon_pixmap(qicon, size, dpr=1.0, mode=None, state=None):
    """Return a HiDPI-aware QPixmap for a QIcon on both Qt 5 and Qt 6."""
    if mode is None:
        mode = IconModeNormal
    if state is None:
        state = IconStateOff
    scale = float(dpr) if dpr and dpr > 0 else 1.0
    if IS_QT6:
        return qicon.pixmap(size, scale, mode, state)
    if scale > 1.0:
        physical = QSize(
            max(1, round(size.width() * scale)),
            max(1, round(size.height() * scale)),
        )
        pixmap = qicon.pixmap(physical, mode, state)
        if not pixmap.isNull():
            pixmap.setDevicePixelRatio(scale)
            return pixmap
    return qicon.pixmap(size, mode, state)


_METATYPE_CANONICAL_CODES = {
    1: 'Bool',
    2: 'Int',
    3: 'UInt',
    4: 'LongLong',
    5: 'ULongLong',
    6: 'Double',
    8: 'QVariantMap',
    9: 'QVariantList',
    10: 'QString',
    11: 'QStringList',
    12: 'QByteArray',
    14: 'QDate',
    15: 'QTime',
    16: 'QDateTime',
    33: 'Short',
    36: 'UShort',
    38: 'Float',
}

_METATYPE_NAME_TO_CODE = {v: k for k, v in _METATYPE_CANONICAL_CODES.items()}


def meta_type_enum(name):
    """Resolve a Qt MetaType value by canonical name across Qt 5 and Qt 6."""
    scoped = getattr(QMetaType, 'Type', None)
    if scoped is not None:
        val = getattr(scoped, name, None)
        if val is not None:
            return val
    val = getattr(QMetaType, name, None)
    if val is not None:
        return val
    return _METATYPE_NAME_TO_CODE.get(name)


def meta_type_name(field_type) -> str:
    """Return canonical Qt MetaType name for a QgsField.type() on Qt 5 and Qt 6."""
    if field_type is None:
        return ''
    enum_name = getattr(field_type, 'name', None)
    if isinstance(enum_name, str) and enum_name:
        return enum_name
    try:
        code = int(field_type)
    except (TypeError, ValueError):
        return ''
    resolved = _METATYPE_CANONICAL_CODES.get(code)
    if resolved:
        return resolved
    scoped = getattr(QMetaType, 'Type', QMetaType)
    for name in _METATYPE_NAME_TO_CODE:
        candidate = getattr(scoped, name, None)
        if candidate is not None and field_type == candidate:
            return name
    return ''


def wkb_type_name(wkb_type) -> str:
    """Return a stable string name for a WKB type across QGIS 3.40 - 4.x."""
    enum_name = getattr(wkb_type, 'name', None)
    if isinstance(enum_name, str) and enum_name:
        return enum_name
    return _QgsWkbTypes.displayString(wkb_type)


def geometry_equals(first, second) -> bool:
    """Compare two QgsGeometry instances without triggering QGIS 4.2 deprecation."""
    if hasattr(first, 'isExactlyEqual'):
        return bool(first.isExactlyEqual(second))
    return bool(first.equals(second))


def version_summary() -> str:
    """Compact version string for diagnostics. Always safe to call."""
    return (
        f"QGIS {QGIS_MAJOR}.{QGIS_MINOR}.{QGIS_PATCH} "
        f"(int={QGIS_VERSION_INT}) | Qt {QT_MAJOR} | {QT_BINDING}"
    )


def feature_supported(feature: str) -> bool:
    """Boolean check for known feature gates."""
    gates = {
        "qgs_task": True,
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
        from qgis.core import QgsMessageLog
        QgsMessageLog.logMessage(
            f"Transformer environment: {summary}", "Transformer", MsgInfo
        )
    except Exception as exc:
        summary = f"{summary} ({type(exc).__name__})"
    if logger is not None and hasattr(logger, 'info'):
        logger.info(summary, module="system", code="ENV_DETECT")
