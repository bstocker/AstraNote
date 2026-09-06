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


def compute_module_grades(module, subject_ids, active_ids=None):
    """Calcule totaux d'étoiles et notes /20 au prorata pour un module.

    `active_ids` : ensemble des sujets qui **comptent** dans le prorata. Les
    sujets absents (étudiants neutralisés) conservent leur total mais sont
    exclus du max de référence et n'obtiennent pas de note (R7bis / neutralisation).
    Si `active_ids` vaut None, tous les sujets comptent.

    Retourne un dict : subject_id -> {"total": int, "note": float|None,
    "is_reference": bool, "active": bool}. Applique R1, R3, R4, R5, R9.
    """
    subject_type = _subject_type_for(module)
    column_ids = _star_column_ids(module)
    if active_ids is None:
        active_ids = set(subject_ids)

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

    # Le max de référence ne considère que les sujets actifs (R3).
    active_totals = [t for sid, t in totals.items() if sid in active_ids]
    max_total = max(active_totals) if active_totals else 0

    result = {}
    for sid, total in totals.items():
        active = sid in active_ids
        if not active or max_total <= 0:  # neutralisé ou R9 (pas de division par 0)
            note = None
            is_ref = False
        else:
            note = round_half((total / max_total) * 20)
            is_ref = (total == max_total)
        result[sid] = {
            "total": total, "note": note, "is_reference": is_ref, "active": active,
        }
    return result


def compute_member_totals(module, student_ids):
    """Totaux d'étoiles individuels des membres d'un module en groupe (R12).

    Les membres se notent sur **les mêmes colonnes** que leur groupe, mais
    avec `subject_type = student` : leurs étoiles n'interfèrent donc pas avec
    le total du groupe. Aucune note /20 n'en est dérivée — la seule note d'un
    module en groupe reste celle du groupe ; ce total mesure la contribution
    individuelle au sein du travail collectif.
    """
    totals = {sid: 0 for sid in student_ids}
    column_ids = _star_column_ids(module)
    if column_ids and student_ids:
        stars = Star.query.filter(
            Star.star_column_id.in_(column_ids),
            Star.subject_type == SUBJECT_STUDENT,
            Star.subject_id.in_(student_ids),
        ).all()
        for s in stars:
            if s.subject_id in totals:
                totals[s.subject_id] += token_points(s.value)
    return totals


def ranked_places(totals, max_places=5):
    """Classement par places, ex æquo groupés, limité aux `max_places` premières.

    `totals` : dict sujet -> total d'étoiles. Les sujets à 0 étoile sont écartés
    (rien de gagné, et cela éviterait un peloton d'ex æquo à 0 en fin de
    classement). Les places sont **consécutives** : deux premiers ex æquo sont
    suivis d'une 2e place, pas d'une 3e.

    Retourne une liste de dicts ordonnée : {"place", "total", "ids"}.
    """
    scored = {sid: t for sid, t in totals.items() if t > 0}
    places = []
    for place, total in enumerate(sorted(set(scored.values()), reverse=True), start=1):
        if place > max_places:
            break
        places.append({
            "place": place,
            "total": total,
            "ids": [sid for sid, t in scored.items() if t == total],
        })
    return places
