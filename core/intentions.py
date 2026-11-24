# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Proposer des intentions à partir du contexte fourni, sans Qt ni lecture externe."""

from collections.abc import Mapping


def _names(value):
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(item.strip() for item in value
                              if isinstance(item, str) and item.strip()))


def build_intentions(context):
    """Rendre les sept choix C6 ; proposer ne sélectionne ni n'exécute rien.

    L'absence de géométrie ou de préparation compatible est explicite. Les
    droits d'édition de la source ne conditionnent pas un travail en copie.
    """
    context = context if isinstance(context, Mapping) else {}
    source = bool(context.get("source_id"))
    fields = _names(context.get("field_names"))
    types = context.get("field_types")
    types = types if isinstance(types, Mapping) else {}
    text_fields = [name for name in fields if any(token in str(types.get(name, "")).casefold()
        for token in ("string", "text", "texte", "varchar", "character", "qstring"))]
    geometry = context.get("geometry") is True
    read_only = context.get("read_only") is True
    recipes = _names(context.get("compatible_recipes"))
    missing_source = "Choisissez d'abord une entrée dans la liste des sources."
    missing_fields = "Cette entrée ne contient pas de colonnes à préparer."

    def choice(identifier, title, description, available=True, reason="", recommended=False):
        enabled = source and available
        return {"id": identifier, "title": title, "description": description,
                "enabled": enabled, "reason": reason if source else missing_source,
                "recommended": enabled and recommended}

    text_example = ", ".join(text_fields[:3])
    clean_reason = ("Colonnes de texte disponibles : " + text_example + "." if text_fields else
        "Choisissez les valeurs à préparer ; aucune correction n'est appliquée automatiquement.")
    deliver_reason = (
        "Entrée en lecture seule : votre source reste intacte et le résultat sera créé en copie."
        if read_only else
        "Vous choisirez la destination et confirmerez l'exécution dans l'atelier."
    )
    return [
        choice("clean", "Nettoyer des valeurs",
            "Retirer des espaces inutiles ou harmoniser un texte dans le résultat.",
            bool(fields), clean_reason if fields else missing_fields, bool(text_fields)),
        choice("fields", "Choisir ou compléter les colonnes",
            "Garder les informations utiles, renommer une colonne ou ajouter un calcul.",
            bool(fields), (str(len(fields)) + " colonnes disponibles dans cette entrée.") if fields else missing_fields),
        choice("filter", "Garder certaines lignes",
            "Définir les lignes à conserver, puis vérifier ce qui sera écarté.",
            bool(fields), "Le choix des lignes sera vérifié avant l'exécution." if fields else missing_fields),
        choice("geometry", "Adapter la forme ou les coordonnées",
            "Préparer une autre forme ou des coordonnées adaptées à votre usage.",
            geometry, "Cette entrée possède une géométrie." if geometry else
            "Cette entrée est une table sans géométrie. Ses colonnes restent utilisables."),
        choice("compare", "Comparer avant et après",
            "Examiner les valeurs de départ et le résultat prévu sur un échantillon.",
            True, "L'aperçu ne modifie aucune donnée et reste limité à un échantillon.", True),
        choice("deliver", "Obtenir un fichier ou une table",
            "Préparer un résultat utilisable dans QGIS ou dans un autre logiciel.",
            True, deliver_reason),
        choice("replay", "Reprendre une préparation",
            "Partir de réglages déjà enregistrés et compatibles avec cette entrée.",
            bool(recipes), ("Compatible : " + ", ".join(recipes[:3])
                + (" et " + str(len(recipes) - 3) + " autre(s)" if len(recipes) > 3 else "") + ".") if recipes else
            "Aucune préparation compatible n'est disponible pour cette entrée.", bool(recipes)),
    ]
