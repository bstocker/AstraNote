"""Logique de notation par étoiles — règles R1 à R9 de la fiche §3.

Le calcul de la note /20 est *dérivé* (jamais stocké). L'unité notée est
l'étudiant (mode individuel) ou le groupe (mode groupe).
"""
from .models import (
    Star, SUBJECT_STUDENT, SUBJECT_GROUP, WORK_MODE_GROUP,
)

# Statuts spéciaux valant 0 étoile (R2) et leur couleur d'affichage.
SPECIAL_STATUSES = {
    "ABS": "red",
    "Pas de PC": "red",
    "Retard": "orange",
    "Non réalisé": "orange",
    "-": "grey",
    "?": "grey",
}

# Jetons sélectionnables dans une cellule : 0..4 étoiles + statuts spéciaux.
STAR_TOKENS = ["0", "1", "2", "3", "4"]
ALL_TOKENS = STAR_TOKENS + list(SPECIAL_STATUSES.keys())


def token_points(value):
    """Points d'une cellule (R1/R2). Les statuts spéciaux valent 0."""
    if value is None:
        return 0
    value = str(value).strip()
    if value in SPECIAL_STATUSES:
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if 0 <= n <= 4 else 0


def display_token(value):
    """Représentation lisible d'une cellule (étoiles ou statut)."""
    value = (str(value).strip() if value is not None else "0")
    if value in SPECIAL_STATUSES:
        return value
    pts = token_points(value)
    return "★" * pts if pts else ""


def status_color(value):
    return SPECIAL_STATUSES.get(str(value).strip() if value is not None else "", None)


def round_half(x):
    """Arrondi au 0,5 le plus proche (R5)."""
    return round(x * 2) / 2.0


def _subject_type_for(module):
    return SUBJECT_GROUP if module.work_mode == WORK_MODE_GROUP else SUBJECT_STUDENT


def _star_column_ids(module):
    ids = []
    for gd in module.grade_dates:
        for sc in gd.star_columns:
            ids.append(sc.id)
    return ids


def compute_module_grades(module, subject_ids):
    """Calcule totaux d'étoiles et notes /20 au prorata pour un module.

    Retourne un dict : subject_id -> {"total": int, "note": float|None,
    "is_reference": bool}. Applique R1, R3, R4, R5, R9 (N/A si max = 0).
    """
    subject_type = _subject_type_for(module)
    column_ids = _star_column_ids(module)

    totals = {sid: 0 for sid in subject_ids}
    if column_ids:
        stars = Star.query.filter(
            Star.star_column_id.in_(column_ids),
            Star.subject_type == subject_type,
            Star.subject_id.in_(subject_ids or [0]),
        ).all()
        for s in stars:
            if s.subject_id in totals:
                totals[s.subject_id] += token_points(s.value)

    max_total = max(totals.values()) if totals else 0

    result = {}
    for sid, total in totals.items():
        if max_total <= 0:  # R9 — pas de division par zéro
            note = None
            is_ref = False
        else:
            note = round_half((total / max_total) * 20)
            is_ref = (total == max_total)
        result[sid] = {"total": total, "note": note, "is_reference": is_ref}
    return result
