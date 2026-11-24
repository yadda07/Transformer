# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Choisir des objectifs combinables avant d'entrer dans l'atelier de préparation."""

from collections.abc import Mapping

from qgis.PyQt.QtCore import QSize, QSignalBlocker, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core.intentions import build_intentions
from ..shared.compat import (
    AlignCenter,
    AlignTop,
    AlignVCenter,
    EventFocusIn,
    EventPaletteChange,
    FocusNoFocus,
    FocusStrongFocus,
    FrameHLine,
    FrameNoFrame,
    PlainText,
    ScrollBarAlwaysOff,
    SizePolicyExpanding,
    TextSelectableByMouse,
)
from ..shared.icons import icon
from ..widgets.fluent import FluentButton


_ICONS = {"clean": "text", "fields": "fields", "filter": "filter",
          "geometry": "geometry", "compare": "show_all", "deliver": "export", "replay": "history"}
_FAMILIES = (("Préparer les données", ("clean", "fields", "filter", "geometry")),
             ("Vérifier et obtenir le résultat", ("compare", "deliver")),
             ("Réutiliser ce qui existe", ("replay",)))


class _IntentionRow(QFrame):
    changed = pyqtSignal()

    def __init__(self, identifier, parent=None):
        super().__init__(parent)
        self.setObjectName("transformer_intention_" + identifier)
        self.setProperty("role", "intention-row")
        self.setProperty("fluentCard", "row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        self.symbol = QLabel()
        self.symbol.setFixedSize(24, 24)
        self.symbol.setAlignment(AlignCenter)
        self.symbol.setProperty("role", "intention-icon")
        layout.addWidget(self.symbol, 0, AlignTop)
        content = QVBoxLayout()
        content.setSpacing(4)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.choice = QCheckBox()
        self.choice.setObjectName("transformer_intention_choice_" + identifier)
        self.choice.setProperty("role", "intention-choice")
        self.choice.setFocusPolicy(FocusStrongFocus)
        self.choice.toggled.connect(lambda _checked: self.changed.emit())
        heading.addWidget(self.choice, 1)
        self.suggestion = QLabel("Suggestion")
        self.suggestion.setObjectName("transformer_intention_suggestion_" + identifier)
        self.suggestion.setProperty("role", "suggestion")
        self.suggestion.setProperty("fluentRole", "meta")
        suggestion_font = self.suggestion.font()
        suggestion_font.setBold(True)
        self.suggestion.setFont(suggestion_font)
        heading.addWidget(self.suggestion, 0, AlignTop)
        content.addLayout(heading)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(PlainText)
        self.description.setProperty("role", "body")
        self.description.setProperty("fluentRole", "body")
        content.addWidget(self.description)
        self.reason = QLabel()
        self.reason.setObjectName("transformer_intention_reason_" + identifier)
        self.reason.setWordWrap(True)
        self.reason.setTextFormat(PlainText)
        self.reason.setProperty("role", "detail")
        self.reason.setProperty("fluentRole", "meta")
        content.addWidget(self.reason)
        layout.addLayout(content, 1)
        self._identifier = identifier
        self.refresh_icon()

    def refresh_icon(self):
        self.symbol.setPixmap(icon(_ICONS[self._identifier]).pixmap(QSize(24, 24)))

    def update_intention(self, intention, checked):
        with QSignalBlocker(self.choice):
            self.choice.setText(intention["title"])
            self.choice.setEnabled(intention["enabled"])
            self.choice.setChecked(checked and intention["enabled"])
        self.description.setText(intention["description"])
        self.reason.setText(intention["reason"])
        self.suggestion.setVisible(intention["recommended"])
        self.setProperty("available", intention["enabled"])
        self.choice.setAccessibleName(intention["title"])
        self.choice.setAccessibleDescription(intention["description"] + " " + intention["reason"]
            + (" Suggestion pour cette entrée." if intention["recommended"] else ""))
        self.choice.setToolTip(intention["reason"])


class IntentionsPanel(QWidget):
    """Une sélection d'objectifs, sans effet sur les données ni lancement implicite."""

    intentionsChanged = pyqtSignal(object)
    continueRequested = pyqtSignal(object)
    skipRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transformer_intentions_panel")
        self.setProperty("role", "intentions-panel")
        self.setAutoFillBackground(True)
        self._context = {}
        self._intentions = []
        self._rows = {}
        self._last_selection = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        top_bar = QHBoxLayout()
        title = QLabel("Que voulez-vous obtenir ?")
        title.setObjectName("transformer_intentions_title")
        title.setProperty("role", "title")
        title.setProperty("fluentRole", "title")
        title.setWordWrap(True)
        title_font = title.font()
        title_font.setPointSizeF(max(10, title_font.pointSizeF()) * 1.55)
        title_font.setBold(True)
        title.setFont(title_font)
        top_bar.addWidget(title, 1)
        self.skip_button = FluentButton("Revenir à l'atelier", icon_name="layers", compact=True)
        self.skip_button.setObjectName("transformer_intentions_skip")
        self.skip_button.setAutoDefault(False)
        self.skip_button.clicked.connect(self.skipRequested.emit)
        top_bar.addWidget(self.skip_button, 0, AlignVCenter)
        layout.addLayout(top_bar)
        introduction = QLabel("Choisissez un ou plusieurs objectifs. Vous pourrez préciser les réglages dans l'atelier.")
        introduction.setWordWrap(True)
        introduction.setProperty("role", "body")
        introduction.setProperty("fluentRole", "body")
        layout.addWidget(introduction)

        self._source = QLabel()
        self._source.setObjectName("transformer_intentions_source")
        self._source.setTextFormat(PlainText)
        self._source.setWordWrap(True)
        self._source.setProperty("role", "heading")
        self._source.setProperty("fluentRole", "section")
        self._source.setTextInteractionFlags(TextSelectableByMouse)
        layout.addWidget(self._source)
        self._scope = QLabel()
        self._scope.setObjectName("transformer_intentions_context")
        self._scope.setProperty("role", "detail")
        self._scope.setProperty("fluentRole", "meta")
        self._scope.setWordWrap(True)
        layout.addWidget(self._scope)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("transformer_intentions_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(FrameNoFrame)
        self._scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(SizePolicyExpanding, SizePolicyExpanding)
        self._scroll.setFocusPolicy(FocusNoFocus)
        content = QWidget()
        content.setObjectName("transformer_intentions_choices")
        choices = QVBoxLayout(content)
        choices.setContentsMargins(0, 0, 8, 0)
        choices.setSpacing(6)
        for index, (family, identifiers) in enumerate(_FAMILIES):
            if index:
                choices.addSpacing(16)
                separator = QFrame()
                separator.setFrameShape(FrameHLine)
                separator.setProperty("role", "separator")
                choices.addWidget(separator)
                choices.addSpacing(16)
            label = QLabel(family)
            label.setProperty("role", "heading")
            label.setProperty("fluentRole", "section")
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            choices.addWidget(label)
            for identifier in identifiers:
                row = _IntentionRow(identifier)
                self._rows[identifier] = row
                choices.addWidget(row)
                row.changed.connect(self._selection_changed)
                row.choice.installEventFilter(self)
        choices.addStretch(1)
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll, 1)

        footer = QHBoxLayout()
        footer.setSpacing(16)
        self._selection = QLabel()
        self._selection.setObjectName("transformer_intentions_selection")
        self._selection.setProperty("role", "detail")
        self._selection.setProperty("fluentRole", "meta")
        self._selection.setWordWrap(True)
        self._selection.setMinimumHeight(self._selection.fontMetrics().lineSpacing() * 2 + 8)
        footer.addWidget(self._selection, 1)
        self.continue_button = FluentButton("Continuer", variant="primary")
        self.continue_button.setObjectName("transformer_intentions_continue")
        self.continue_button.setProperty("role", "primary")
        self.continue_button.setProperty("variant", "primary")
        self.continue_button.setIcon(icon("play"))
        self.continue_button.setMinimumHeight(42)
        self.continue_button.setAutoDefault(False)
        self.continue_button.clicked.connect(self._continue)
        footer.addWidget(self.continue_button, 0, AlignVCenter)
        layout.addLayout(footer)
        previous = None
        for row in self._rows.values():
            if previous is not None:
                QWidget.setTabOrder(previous, row.choice)
            previous = row.choice
        QWidget.setTabOrder(previous, self.continue_button)
        self.set_context({})

    def set_context(self, context):
        """Mettre à jour les propositions ; ne jamais choisir un objectif à la place de la personne."""
        context = dict(context) if isinstance(context, Mapping) else {}
        previous_source = self._context.get("source_id")
        retained = self.selected_intentions() if previous_source == context.get("source_id") else []
        self._context = context
        self._intentions = build_intentions(context)
        for intention in self._intentions:
            self._rows[intention["id"]].update_intention(intention, intention["id"] in retained)
        has_source = bool(context.get("source_id"))
        name = str(context.get("source_name") or "Entrée sélectionnée")
        self._source.setText("Entrée : " + name if has_source else "Choisissez une entrée pour commencer")
        self._source.setAccessibleName(self._source.text())
        fields = context.get("field_names")
        field_count = len({name for name in fields if isinstance(name, str) and name.strip()}) if isinstance(fields, (list, tuple)) else 0
        count = context.get("feature_count")
        count_text = (format(count, ",").replace(",", " ") + " lignes") if type(count) is int and count >= 0 else "Nombre de lignes non connu"
        access_text = " · Lecture seule (travail en copie)" if context.get("read_only") is True else ""
        self._scope.setText(("Données avec géométrie" if context.get("geometry") is True else "Table sans géométrie")
            + " · " + str(field_count) + " colonnes · " + count_text + access_text if has_source else
            "Sélectionnez une couche ou une table dans les sources. Les propositions suivront son contenu.")
        if previous_source != context.get("source_id"):
            self._scroll.verticalScrollBar().setValue(0)
        self._selection_changed()

    def focus_first_choice(self):
        for intention in self._intentions:
            choice = self._rows[intention["id"]].choice
            if choice.isEnabled() and choice.isChecked():
                choice.setFocus()
                return
        for intention in self._intentions:
            choice = self._rows[intention["id"]].choice
            if choice.isEnabled():
                choice.setFocus()
                return
        self.setFocus()

    def selected_intentions(self):
        return [item["id"] for item in self._intentions
                if item["enabled"] and self._rows[item["id"]].choice.isChecked()]

    def _selection_changed(self):
        selected = self.selected_intentions()
        self.continue_button.setEnabled(bool(selected))
        titles = [item["title"].lower() for item in self._intentions if item["id"] in selected]
        summary = " (" + ", ".join(titles) + ")" if titles else ""
        text = (str(len(selected)) + " objectif" + ("s" if len(selected) > 1 else "")
                + " choisi" + ("s" if len(selected) > 1 else "") + summary
                + ". Continuer ouvre les réglages, sans lancer de traitement.") if selected else \
            "Choisissez au moins un objectif. Votre entrée reste intacte."
        self._selection.setText(text)
        self.continue_button.setAccessibleDescription(text)
        if selected != self._last_selection:
            self._last_selection = list(selected)
            self.intentionsChanged.emit(list(selected))

    def _continue(self):
        selected = self.selected_intentions()
        if selected:
            self.continueRequested.emit(list(selected))

    def eventFilter(self, watched, event):
        if event.type() == EventFocusIn:
            self._scroll.ensureWidgetVisible(watched, 8, 12)
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == EventPaletteChange and hasattr(self, "_rows"):
            for row in self._rows.values():
                row.refresh_icon()
