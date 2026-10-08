"""Modules : grille de notation, dates, colonnes, groupes, saisie des étoiles.

C'est le cœur de l'application (fiche §5.3 à §5.7). La vue module affiche un
tableau unique de consultation + saisie ; les étoiles / notes / URL sont
enregistrées immédiatement via des endpoints AJAX avec recalcul du prorata.
"""
from io import BytesIO
import re

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify,
    send_file,
)
from flask_login import login_required, current_user

from .models import (
    db, Class, Module, GradeDate, StarColumn, UrlColumn, TextColumn,
    PresenceColumn, NoteColumn, Student, Enrollment, Group, GroupMember,
    Star, UrlValue, TextValue, PresenceValue, NoteValue,
    SubjectColor, SUBJECT_COLORS,
    SUBJECT_STUDENT, SUBJECT_GROUP, WORK_MODE_INDIVIDUAL, WORK_MODE_GROUP,
)
from . import grading
from .main import get_class_or_403, purge_subject_data, clean_url, URL_ERROR

modules_bp = Blueprint("modules", __name__)

# Moyens de transmission des notes à l'établissement (valeur -> libellé).
NOTES_METHODS = {
    "mail": "Mail",
    "institutional": "Outil institutionnel de l'école",
    "other": "Autre",
}


# Durée maximale acceptée pour une séance : au-delà, c'est une faute de frappe
# (« 20 » pour « 2.0 ») plutôt qu'une journée de cours de 25 heures.
MAX_DURATION_HOURS = 24


# Libellés des couleurs de cellule (infobulles de la palette).
SUBJECT_COLOR_LABELS = {
    "green": "Vert", "yellow": "Jaune", "red": "Rouge", "grey": "Gris",
}


@modules_bp.app_context_processor
def _inject_module_constants():
    """Constantes dont les gabarits ont besoin (libellés d'envoi, borne de durée).

    La borne passe par ici pour que le `max` du champ de saisie et le contrôle
    serveur ne puissent pas diverger.
    """
    return {"notes_methods": NOTES_METHODS, "max_duration": MAX_DURATION_HOURS}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def get_module_or_403(module_id):
    module = db.session.get(Module, module_id) or abort(404)
    get_class_or_403(module.class_id)  # applique le cloisonnement des droits
    return module


def _next_position(items):
    return (max((i.position or 0) for i in items) + 1) if items else 0


def _module_redirect(module, anchor=None):
    """Retour à la grille, ancré sur l'élément qui vient d'être touché.

    Sans ancre, le navigateur réaffiche la page tout en haut : après l'ajout
    d'une colonne à la dernière séance, l'enseignant devait re-parcourir toute
    la grille pour retrouver sa saisie. `grid.js` reprend le fragment pour
    recentrer aussi le défilement **horizontal**, que l'ancre HTML seule ne
    déplacerait pas.
    """
    return redirect(url_for("modules.view_module", module_id=module.id,
                            _anchor=anchor))


def parse_duration(raw):
    """Durée d'une séance en heures, ou None si le champ est vide.

    Accepte la virgule décimale (« 2,5 »), comme le taux horaire d'une classe :
    un clavier français la produit naturellement. Lève ValueError sur une
    saisie illisible ou hors bornes, à charge de l'appelant de le signaler —
    une durée fautive ne doit pas empêcher la séance d'exister.
    """
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None
    hours = float(text)   # ValueError si illisible
    if not (0 < hours <= MAX_DURATION_HOURS):
        raise ValueError(f"durée hors de 0–{MAX_DURATION_HOURS} h")
    return hours


def module_total_hours(module):
    """Cumul des heures des séances du module (None si aucune durée saisie).

    Renvoyer None plutôt que 0 distingue « aucune durée renseignée » de
    « des séances de durée nulle » — la seconde n'existe pas (cf. parse_duration).
    """
    hours = [gd.duration_hours for gd in module.grade_dates if gd.duration_hours]
    return round(sum(hours), 2) if hours else None


def module_dates_sorted(module, recent_first=False):
    """Séances triées par date, de la plus ancienne à la plus récente.

    C'est l'ordre des colonnes de la grille, quel que soit l'ordre de création :
    une séance ajoutée après coup avec une date antérieure vient se ranger à sa
    place. `recent_first` donne l'ordre du menu d'ajout de colonne : on travaille
    presque toujours sur la séance du jour, qui doit y venir en tête. Par
    défaut c'est l'ordre chronologique de lecture de la grille, celui du
    bandeau de saut entre séances.

    Dans les deux cas une séance sans date est reléguée en fin de liste :
    elle n'a pas de place dans une chronologie.
    """
    dated = sorted((gd for gd in module.grade_dates if gd.date),
                   key=lambda gd: (gd.date, gd.position or 0),
                   reverse=recent_first)
    return dated + [gd for gd in module.grade_dates if not gd.date]


def valid_subjects(module):
    """Couples (subject_type, subject_id) réellement notables dans le module.

    Garde-fou des endpoints AJAX : en mode groupe, les groupes **et** leurs
    membres sont notables ; en mode individuel, seuls les étudiants inscrits.
    """
    subjects = {(s["type"], s["id"]) for s in module_subjects(module)}
    for members in module_members(module).values():
        subjects |= {(m["type"], m["id"]) for m in members}
    return subjects


def module_subjects(module):
    """Liste ordonnée des unités notées : (subject_type, id, label, enrollment?).

    En mode individuel : les étudiants inscrits. En mode groupe : les groupes.
    """
    if module.is_group_mode:
        groups = sorted(module.groups, key=lambda g: g.name.lower())
        return [
            {"type": SUBJECT_GROUP, "id": g.id, "label": g.name,
             "comment": g.comment, "obj": g, "active": True,
             "discord": None}
            for g in groups
        ]
    # Actifs d'abord (ordre alphabétique), puis les neutralisés en fin de liste.
    enrollments = sorted(
        module.klass.enrollments,
        key=lambda e: (not e.student.active, e.student.full_name.lower()),
    )
    return [
        {"type": SUBJECT_STUDENT, "id": e.student.id, "label": e.student.full_name,
         "comment": e.general_comment, "obj": e.student, "enrollment": e,
         "active": e.student.active, "discord": e.student.discord_alias}
        for e in enrollments
    ]


def module_members(module):
    """Membres de chaque groupe : {group_id: [ligne membre, …]} (mode groupe).

    Une ligne membre a la même forme qu'une ligne étudiant de `module_subjects`
    et se note sur les mêmes colonnes, avec `subject_type = student`. Le
    commentaire est celui de l'inscription — le « commentaire général » de
    l'étudiant dans la classe, partagé avec les autres modules (cf. fiche §5.4).

    Les étudiants neutralisés après leur affectation restent affichés, grisés
    et verrouillés, comme dans un module individuel.
    """
    if not module.is_group_mode:
        return {}
    comments = {
        e.student_id: e.general_comment
        for e in Enrollment.query.filter_by(class_id=module.class_id).all()
    }
    members = {}
    for group in module.groups:
        # `m.student` peut être None sur une base antérieure à la cascade des
        # affectations (cf. réparation dans _run_migrations) : on l'ignore
        # plutôt que de faire tomber toute la grille.
        rows = sorted((m.student for m in group.members if m.student),
                      key=lambda st: (not st.active, st.full_name.lower()))
        members[group.id] = [
            {"type": SUBJECT_STUDENT, "id": st.id, "label": st.full_name,
             "comment": comments.get(st.id), "obj": st, "active": st.active,
             "discord": st.discord_alias, "group_id": group.id}
            for st in rows
        ]
    return members


# --------------------------------------------------------------------------- #
# CRUD Module
# --------------------------------------------------------------------------- #
@modules_bp.route("/classes/<int:class_id>/modules/new", methods=["POST"])
@login_required
def create_module(class_id):
    klass = get_class_or_403(class_id)
    name = request.form.get("name", "").strip()
    work_mode = request.form.get("work_mode", WORK_MODE_INDIVIDUAL)
    if work_mode not in (WORK_MODE_INDIVIDUAL, WORK_MODE_GROUP):
        work_mode = WORK_MODE_INDIVIDUAL
    if not name:
        flash("Le nom du module est requis.", "error")
        return redirect(url_for("main.view_class", class_id=class_id))

    try:
        discord_url = clean_url(request.form.get("discord_url"))
        discord_ref_url = clean_url(request.form.get("discord_ref_url"))
    except ValueError:
        flash(URL_ERROR, "error")
        return redirect(url_for("main.view_class", class_id=class_id))

    module = Module(
        name=name, class_id=klass.id, work_mode=work_mode,
        discord_url=discord_url, discord_ref_url=discord_ref_url,
    )
    db.session.add(module)
    db.session.commit()
    flash("Module créé.", "success")
    return redirect(url_for("modules.view_module", module_id=module.id))


@modules_bp.route("/modules/<int:module_id>/edit", methods=["POST"])
@login_required
def edit_module(module_id):
    """Édite un module : nom et liens Discord (salon du module + référence).

    Le mode de travail (individuel/groupe) n'est PAS modifiable après création
    (il conditionne groupes et notes déjà saisis — cf. fiche §2).
    """
    module = get_module_or_403(module_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Le nom du module est requis.", "error")
        return redirect(url_for("modules.view_module", module_id=module.id))

    try:
        discord_url = clean_url(request.form.get("discord_url"))
        discord_ref_url = clean_url(request.form.get("discord_ref_url"))
    except ValueError:
        flash(URL_ERROR, "error")
        return redirect(url_for("modules.view_module", module_id=module.id))

    module.name = name
    module.discord_url = discord_url
    module.discord_ref_url = discord_ref_url
    db.session.commit()
    flash("Module mis à jour.", "success")
    return redirect(url_for("modules.view_module", module_id=module.id))


@modules_bp.route("/modules/<int:module_id>/notes-sent", methods=["POST"])
@login_required
def set_notes_sent(module_id):
    """Enregistre si/quand/comment les notes du module ont été envoyées à
    l'établissement (fiche §5.7)."""
    from datetime import datetime

    module = get_module_or_403(module_id)
    sent = "notes_sent" in request.form
    module.notes_sent = sent

    if sent:
        raw = request.form.get("notes_sent_date", "").strip()
        parsed = None
        if raw:
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                parsed = None
        # Si envoyé sans date précisée, on retient la date du jour.
        if parsed is None:
            parsed = datetime.today().date()
        method = request.form.get("notes_sent_method", "").strip()
        module.notes_sent_date = parsed
        module.notes_sent_method = method if method in NOTES_METHODS else None
        module.notes_sent_detail = request.form.get("notes_sent_detail", "").strip() or None
    else:
        module.notes_sent_date = None
        module.notes_sent_method = None
        module.notes_sent_detail = None

    db.session.commit()
    flash("Statut d'envoi des notes mis à jour.", "success")
    return redirect(url_for("modules.view_module", module_id=module.id))


@modules_bp.route("/modules/<int:module_id>/delete", methods=["POST"])
@login_required
def delete_module(module_id):
    module = get_module_or_403(module_id)
    class_id = module.class_id
    db.session.delete(module)
    db.session.commit()
    flash("Module supprimé.", "success")
    return redirect(url_for("main.view_class", class_id=class_id))


# --------------------------------------------------------------------------- #
# Vue module : la grille
# --------------------------------------------------------------------------- #
@modules_bp.route("/modules/<int:module_id>")
@login_required
def view_module(module_id):
    module = get_module_or_403(module_id)

    # La grille ne montre que les étudiants actifs : un étudiant neutralisé a
    # quitté l'école, il encombrerait la saisie sans jamais pouvoir être noté.
    # Ses étoiles restent en base, et il reste visible (et réactivable) sur la
    # fiche de la classe. Le filtrage est **volontairement local à l'affichage** :
    # `module_subjects` / `module_members` continuent de le connaître, ce qui
    # permet aux endpoints AJAX de refuser sa saisie avec un message explicite
    # plutôt qu'un « sujet inconnu ».
    all_subjects = module_subjects(module)
    subjects = [s for s in all_subjects if s["active"]]
    hidden_inactive = len(all_subjects) - len(subjects)
    subject_ids = [s["id"] for s in subjects]
    grades = grading.compute_module_grades(module, subject_ids, set(subject_ids))

    # Membres dépliables et leur total d'étoiles (mode groupe uniquement).
    all_members = module_members(module)
    members = {gid: [m for m in rows if m["active"]]
               for gid, rows in all_members.items()}
    hidden_inactive += (sum(len(r) for r in all_members.values())
                        - sum(len(r) for r in members.values()))
    member_ids = [m["id"] for rows in members.values() for m in rows]
    member_totals = grading.compute_member_totals(module, member_ids)

    # Index des valeurs pour un accès O(1) dans le template, clé
    # (subject_type, subject_id, column_id) : une grille de module en groupe
    # porte à la fois les lignes du groupe et celles de ses membres. Le filtre
    # sur les colonnes du module suffit à borner la requête, plus besoin de
    # filtrer sur le type.
    star_map, url_map, text_map, note_map = {}, {}, {}, {}
    presence_map = {}

    star_col_ids, url_col_ids, text_col_ids, presence_col_ids = [], [], [], []
    for gd in module.grade_dates:
        star_col_ids += [c.id for c in gd.star_columns]
        url_col_ids += [c.id for c in gd.url_columns]
        text_col_ids += [c.id for c in gd.text_columns]
        presence_col_ids += [c.id for c in gd.presence_columns]
    note_col_ids = [c.id for c in module.note_columns]

    if star_col_ids:
        for s in Star.query.filter(Star.star_column_id.in_(star_col_ids)).all():
            star_map[(s.subject_type, s.subject_id, s.star_column_id)] = s.value
    if url_col_ids:
        for u in UrlValue.query.filter(UrlValue.url_column_id.in_(url_col_ids)).all():
            url_map[(u.subject_type, u.subject_id, u.url_column_id)] = u.url
    if text_col_ids:
        for t in TextValue.query.filter(
                TextValue.text_column_id.in_(text_col_ids)).all():
            text_map[(t.subject_type, t.subject_id, t.text_column_id)] = t.content
    if presence_col_ids:
        for p in PresenceValue.query.filter(
                PresenceValue.presence_column_id.in_(presence_col_ids)).all():
            presence_map[(p.subject_type, p.subject_id, p.presence_column_id)] = p.status
    if note_col_ids:
        for n in NoteValue.query.filter(
                NoteValue.note_column_id.in_(note_col_ids)).all():
            note_map[(n.subject_type, n.subject_id, n.note_column_id)] = n.score

    color_map = {
        (c.subject_type, c.subject_id): c.color
        for c in SubjectColor.query.filter_by(module_id=module.id).all()
    }

    # Étudiants actifs encore non affectés à un groupe (mode groupe). Les
    # étudiants neutralisés (partis) n'ont pas besoin d'être affectés.
    unassigned_active = []
    if module.is_group_mode:
        assigned = {
            m.student_id for g in module.groups for m in g.members
        }
        unassigned_active = sorted(
            (e.student for e in module.klass.enrollments
             if e.student.id not in assigned and e.student.active),
            key=lambda s: s.full_name.lower(),
        )

    # Deux ordres, pour deux usages : le bandeau des séances suit la chronologie
    # de la grille, le menu d'ajout de colonne ouvre sur la séance du jour.
    dates_asc = module_dates_sorted(module)
    dates_desc = module_dates_sorted(module, recent_first=True)
    # Séance la plus récente *datée* : c'est elle que le bandeau étoile et que
    # la grille met en avant.
    latest_date = next((gd for gd in dates_desc if gd.date), None)

    return render_template(
        "modules/module_detail.html",
        module=module, subjects=subjects, grades=grades,
        members=members, member_totals=member_totals,
        star_map=star_map, url_map=url_map, text_map=text_map, note_map=note_map,
        presence_map=presence_map, presence_statuses=grading.PRESENCE_STATUSES,
        color_map=color_map, subject_colors=SUBJECT_COLORS,
        color_labels=SUBJECT_COLOR_LABELS,
        all_tokens=grading.ALL_TOKENS, special_statuses=grading.SPECIAL_STATUSES,
        unassigned_active=unassigned_active,
        dates_asc=dates_asc, dates_desc=dates_desc, latest_date=latest_date,
        hidden_inactive=hidden_inactive, total_hours=module_total_hours(module),
    )


# --------------------------------------------------------------------------- #
# Classement du module (podium général + podium par séance)
# --------------------------------------------------------------------------- #
@modules_bp.route("/modules/<int:module_id>/ranking")
@login_required
def module_ranking(module_id):
    """Dashboard de classement : les 5 premières places, ex æquo groupés.

    Un classement général (toutes séances confondues) et un classement par
    séance. Les étudiants neutralisés en sont exclus, comme du prorata (R10).
    """
    module = get_module_or_403(module_id)
    subjects = [s for s in module_subjects(module) if s["active"]]
    labels = {s["id"]: s["label"] for s in subjects}
    stype = _subject_type(module)

    # Colonne d'étoiles -> séance, pour ventiler les points en une seule passe.
    col_date = {sc.id: gd.id for gd in module.grade_dates for sc in gd.star_columns}
    overall = {sid: 0 for sid in labels}
    per_date = {gd.id: {sid: 0 for sid in labels} for gd in module.grade_dates}

    if col_date:
        for st in Star.query.filter(
            Star.subject_type == stype,
            Star.star_column_id.in_(col_date)).all():
            if st.subject_id in overall:
                pts = grading.token_points(st.value)
                overall[st.subject_id] += pts
                per_date[col_date[st.star_column_id]][st.subject_id] += pts

    sessions = [
        {"date": gd, "places": grading.ranked_places(per_date[gd.id])}
        for gd in module_dates_sorted(module)
    ]
    return render_template(
        "modules/ranking.html",
        module=module, labels=labels,
        general=grading.ranked_places(overall),
        sessions=sessions,
        ranked_count=sum(1 for t in overall.values() if t > 0),
        subject_count=len(subjects),
    )


# --------------------------------------------------------------------------- #
# Synthèse de séance (Excel) : effectifs par élément des listes
# --------------------------------------------------------------------------- #
PRESENCE_UNSET = "Non renseigné"


def picked_dates(module, raw_ids):
    """Séances du module désignées par `raw_ids`, dans l'ordre chronologique.

    Les identifiants illisibles ou étrangers au module sont ignorés.
    """
    wanted = set()
    for raw in raw_ids:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    return [gd for gd in module_dates_sorted(module) if gd.id in wanted]


def synthesis_dates(module, raw_ids):
    """Séances retenues pour la synthèse, dans l'ordre chronologique.

    Les identifiants étrangers au module sont ignorés. Sans sélection valable,
    on retient la séance datée la plus récente (à défaut, la dernière créée).
    """
    ordered = module_dates_sorted(module)
    chosen = picked_dates(module, raw_ids)
    if chosen:
        return chosen
    latest = next((gd for gd in module_dates_sorted(module, recent_first=True)
                   if gd.date), None)
    if latest is None and ordered:
        latest = ordered[-1]
    return [latest] if latest else []


def synthesis_counts(module, grade_dates):
    """Effectifs par élément de liste, colonne par colonne.

    La présence est comptée par étudiant : les étudiants actifs inscrits en
    mode individuel, les membres actifs des groupes en mode groupe. Les
    étoiles sont comptées sur l'unité notée du module (étudiants ou groupes).
    Une cellule d'étoiles jamais saisie vaut « 0 », comme dans la grille ; une
    cellule de présence vide est « Non renseigné ».

    Retourne {"students": n, "units": n, "unit_label": str, "dates": [
      {"date": GradeDate,
       "presence": [(colonne, {statut: n})], "stars": [(colonne, {jeton: n})]}]}.
    """
    if module.is_group_mode:
        student_ids = {m["id"] for rows in module_members(module).values()
                       for m in rows if m["active"]}
        unit_ids = {s["id"] for s in module_subjects(module)}
        unit_label = "groupes"
    else:
        student_ids = {s["id"] for s in module_subjects(module) if s["active"]}
        unit_ids = student_ids
        unit_label = "étudiants"
    stype = _subject_type(module)

    presence_cols = [c for gd in grade_dates for c in gd.presence_columns]
    star_cols = [c for gd in grade_dates for c in gd.star_columns]

    presence_vals = {}
    if presence_cols:
        for pv in PresenceValue.query.filter(
                PresenceValue.subject_type == SUBJECT_STUDENT,
                PresenceValue.presence_column_id.in_([c.id for c in presence_cols])):
            if pv.subject_id in student_ids:
                presence_vals[(pv.presence_column_id, pv.subject_id)] = pv.status
    star_vals = {}
    if star_cols:
        for st in Star.query.filter(
                Star.subject_type == stype,
                Star.star_column_id.in_([c.id for c in star_cols])):
            if st.subject_id in unit_ids:
                star_vals[(st.star_column_id, st.subject_id)] = st.value

    dates = []
    for gd in grade_dates:
        presence = []
        for col in gd.presence_columns:
            counts = dict.fromkeys(list(grading.PRESENCE_STATUSES) + [PRESENCE_UNSET], 0)
            for sid in student_ids:
                status = presence_vals.get((col.id, sid))
                counts[status if status in counts else PRESENCE_UNSET] += 1
            presence.append((col, counts))
        stars = []
        for col in gd.star_columns:
            counts = dict.fromkeys(grading.ALL_TOKENS, 0)
            for sid in unit_ids:
                value = str(star_vals.get((col.id, sid), "0")).strip()
                if value not in grading.SPECIAL_STATUSES:
                    value = str(grading.token_points(value))
                counts[value] = counts.get(value, 0) + 1
            stars.append((col, counts))
        dates.append({"date": gd, "presence": presence, "stars": stars})
    return {"students": len(student_ids), "units": len(unit_ids),
            "unit_label": unit_label, "dates": dates}


@modules_bp.route("/modules/<int:module_id>/synthesis.xlsx")
@login_required
def export_synthesis(module_id):
    """Synthèse Excel d'une ou plusieurs séances (la plus récente par défaut) :
    pour chaque colonne « Présence » et « Étoiles », le nombre d'étudiants
    (ou de groupes) concernés par chaque élément de la liste."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    module = get_module_or_403(module_id)
    grade_dates = synthesis_dates(module, request.args.getlist("dates"))
    if not grade_dates:
        flash("Aucune séance à synthétiser : ajoutez d'abord une date.", "error")
        return _module_redirect(module)
    data = synthesis_counts(module, grade_dates)

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"

    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="F1F5F9")
    fills = {
        "red": PatternFill("solid", fgColor="FEE2E2"),
        "orange": PatternFill("solid", fgColor="FFEDD5"),
        "grey": PatternFill("solid", fgColor="F1F5F9"),
    }
    center = Alignment(horizontal="center")

    ws["A1"] = f"Synthèse — {module.name}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"{module.klass.name} · {module.klass.school.name} · {module.klass.academic_year.label}"
    effectif = f"Effectif : {data['students']} étudiant(s)"
    if module.is_group_mode:
        effectif += f", {data['units']} groupe(s)"
    ws["A3"] = effectif
    row = 5

    def table(title, columns, labels, colors):
        """Un tableau : éléments de la liste en lignes, colonnes en colonnes."""
        nonlocal row
        ws.cell(row=row, column=1, value=title).font = bold
        ws.cell(row=row, column=1).fill = head_fill
        for j, (col, _) in enumerate(columns, start=2):
            c = ws.cell(row=row, column=j, value=col.title)
            c.font, c.fill, c.alignment = bold, head_fill, center
        row += 1
        for key, label in labels:
            first = ws.cell(row=row, column=1, value=label)
            fill = fills.get(colors.get(key))
            if fill:
                first.fill = fill
            for j, (_, counts) in enumerate(columns, start=2):
                ws.cell(row=row, column=j, value=counts.get(key, 0)).alignment = center
            row += 1
        row += 1

    for block in data["dates"]:
        gd = block["date"]
        title = ("Séance du " + gd.date.strftime("%d/%m/%Y")) if gd.date else "Séance sans date"
        if gd.label:
            title += f" · {gd.label}"
        ws.cell(row=row, column=1, value=title).font = Font(bold=True, size=12)
        row += 1
        if block["presence"]:
            table("Présence (nombre d'étudiants)", block["presence"],
                  [(k, k) for k in list(grading.PRESENCE_STATUSES) + [PRESENCE_UNSET]],
                  grading.PRESENCE_STATUSES)
        if block["stars"]:
            # Les statuts retirés de la liste (ABS…) n'apparaissent que s'ils
            # figurent encore dans une cellule saisie auparavant.
            legacy = [k for k in grading.SPECIAL_STATUSES
                      if k not in grading.ALL_TOKENS
                      and any(counts.get(k) for _, counts in block["stars"])]
            table(f"Étoiles (nombre d'{data['unit_label']})", block["stars"],
                  [(k, grading.star_label(k)) for k in grading.ALL_TOKENS + legacy],
                  grading.SPECIAL_STATUSES)
        if not block["presence"] and not block["stars"]:
            ws.cell(row=row, column=1,
                    value="Aucune colonne « Présence » ni « Étoiles » pour cette séance.")
            row += 2

    ws.column_dimensions["A"].width = 34
    max_cols = max((len(b["presence"]) for b in data["dates"]), default=0)
    max_cols = max(max_cols, max((len(b["stars"]) for b in data["dates"]), default=0))
    for j in range(2, 2 + max_cols):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 16

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = re.sub(r"[^\w\-]+", "_", module.name).strip("_") or "module"
    last = grade_dates[-1]
    if len(grade_dates) == 1 and last.date:
        filename += "_" + last.date.strftime("%Y-%m-%d")
    return send_file(
        bio, as_attachment=True, download_name=f"synthese_{filename}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --------------------------------------------------------------------------- #
# Export Excel de la grille telle qu'elle est affichée
# --------------------------------------------------------------------------- #
def _date_title(gd):
    """Intitulé d'une séance, comme dans l'en-tête de la grille."""
    title = gd.date.strftime("%d/%m/%Y") if gd.date else "Sans date"
    return title + (f" · {gd.label}" if gd.label else "")


def _file_slug(text, default):
    return re.sub(r"[^\w\-]+", "_", text or "").strip("_") or default


def grid_export_filename(module, grade_dates):
    """« <date de la séance>_<école>_<module>.xlsx ».

    Plusieurs séances : la première et la dernière date, « 2025-09-30_au_
    2025-10-14 ». Aucune séance datée : pas de date du tout plutôt qu'une date
    inventée.
    """
    days = sorted({gd.date for gd in grade_dates if gd.date})
    parts = []
    if days:
        stamp = days[0].strftime("%Y-%m-%d")
        if len(days) > 1:
            stamp += "_au_" + days[-1].strftime("%Y-%m-%d")
        parts.append(stamp)
    parts.append(_file_slug(module.klass.school.name, "ecole"))
    parts.append(_file_slug(module.name, "module"))
    return "_".join(parts) + ".xlsx"


@modules_bp.route("/modules/<int:module_id>/grid.xlsx")
@login_required
def export_grid(module_id):
    """Exporte en .xlsx la zone de notation telle qu'elle est à l'écran.

    `dates` porte les séances sélectionnées dans le bandeau ; sans sélection,
    toutes les séances sont exportées. Les groupes sont toujours exportés
    dépliés, quel que soit leur état à l'écran : colonne A le groupe, colonne B
    l'étudiant (la ligne du groupe lui-même laisse B vide). Un module
    individuel n'a que la colonne « Étudiant ». Chaque séance coiffe ses
    colonnes d'une cellule fusionnée, comme l'en-tête de la grille.

    Comme à l'écran, les étudiants neutralisés n'y figurent pas, et le total
    d'étoiles et la note /20 portent sur **tout** le module, même quand seules
    quelques séances sont exportées.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    module = get_module_or_403(module_id)
    klass = module.klass
    grade_dates = (picked_dates(module, request.args.getlist("dates"))
                   or module_dates_sorted(module))

    # Lignes : chaque unité notée, suivie de ses membres actifs.
    rows = _export_rows(module)
    subject_ids = [r["id"] for r in rows if not r["is_member"]]
    grades = grading.compute_module_grades(module, subject_ids, set(subject_ids))
    member_totals = grading.compute_member_totals(
        module, [r["id"] for r in rows if r["is_member"]])
    group_names = {g.id: g.name for g in module.groups}

    # Colonnes de chaque séance, dans l'ordre de la grille.
    kinds = (("presence", "presence_columns", PresenceValue,
              PresenceValue.presence_column_id, "status"),
             ("star", "star_columns", Star, Star.star_column_id, "value"),
             ("url", "url_columns", UrlValue, UrlValue.url_column_id, "url"),
             ("text", "text_columns", TextValue, TextValue.text_column_id, "content"))
    values = {}
    for kind, rel, model, fk, attr in kinds:
        col_ids = [c.id for gd in grade_dates for c in getattr(gd, rel)]
        if col_ids:
            for v in model.query.filter(fk.in_(col_ids)).all():
                values[(kind, v.subject_type, v.subject_id,
                        getattr(v, fk.key))] = getattr(v, attr)
    note_cols = module.note_columns
    if note_cols:
        for n in NoteValue.query.filter(
                NoteValue.note_column_id.in_([c.id for c in note_cols])).all():
            values[("note", n.subject_type, n.subject_id, n.note_column_id)] = n.score
    color_map = {
        (c.subject_type, c.subject_id): c.color
        for c in SubjectColor.query.filter_by(module_id=module.id).all()
    }

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_title(module.name)

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wrap = Alignment(vertical="top", wrap_text=True)
    head_fill = PatternFill("solid", fgColor="F1F5F9")
    date_fill = PatternFill("solid", fgColor="E0E7FF")
    yellow = PatternFill("solid", fgColor="FEF9C3")
    status_fills = {
        "red": PatternFill("solid", fgColor="FEE2E2"),
        "orange": PatternFill("solid", fgColor="FFEDD5"),
        "grey": PatternFill("solid", fgColor="F1F5F9"),
    }
    subject_fills = {
        "green": PatternFill("solid", fgColor="DCFCE7"),
        "yellow": PatternFill("solid", fgColor="FEF9C3"),
        "red": PatternFill("solid", fgColor="FEE2E2"),
        "grey": PatternFill("solid", fgColor="E2E8F0"),
    }

    ws["A1"] = (f"{module.name} — {klass.name} · {klass.school.name} · "
                f"{klass.academic_year.label}")
    ws["A1"].font = Font(bold=True, size=13)
    TOP, SUB, FIRST = 2, 3, 4   # séances, intitulés de colonnes, 1re ligne

    def head(row, col, title, fill=head_fill, tall=False):
        """En-tête ; `tall` l'étend sur les deux lignes (colonne hors séance)."""
        cell = ws.cell(row=row, column=col, value=title)
        cell.font, cell.fill, cell.alignment = bold, fill, center
        if tall:
            ws.cell(row=SUB, column=col).fill = fill
            ws.merge_cells(start_row=TOP, start_column=col, end_row=SUB, end_column=col)

    label_heads = ["Groupe", "Étudiant"] if module.is_group_mode else ["Étudiant"]
    for j, title in enumerate(label_heads, start=1):
        head(TOP, j, title, tall=True)
        ws.column_dimensions[get_column_letter(j)].width = 26

    # Colonnes de séance : (colonne Excel, nature, colonne de la grille).
    grid_cols = []
    col = len(label_heads) + 1
    for gd in grade_dates:
        start = col
        for kind, rel, *_ in kinds:
            for c in getattr(gd, rel):
                head(SUB, col, c.title)
                ws.column_dimensions[get_column_letter(col)].width = (
                    36 if kind in ("url", "text") else 14)
                grid_cols.append((col, kind, c))
                col += 1
        if col == start:   # séance sans colonne : une colonne vide, comme à l'écran
            head(SUB, col, "—")
            col += 1
        title = _date_title(gd)
        if gd.duration_hours:
            hours = f"{gd.duration_hours:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            title += f" · {hours} h"
        head(TOP, start, title, fill=date_fill)
        for j in range(start + 1, col):
            ws.cell(row=TOP, column=j).fill = date_fill
        if col - start > 1:
            ws.merge_cells(start_row=TOP, start_column=start,
                           end_row=TOP, end_column=col - 1)

    total_col, note20_col = col, col + 1
    head(TOP, total_col, "Total ★", tall=True)
    head(TOP, note20_col, "Note /20", tall=True)
    first_note = note20_col + 1
    for j, nc in enumerate(note_cols, start=first_note):
        head(TOP, j, nc.title, fill=yellow, tall=True)
        ws.column_dimensions[get_column_letter(j)].width = 14
    comment_col = first_note + len(note_cols)
    head(TOP, comment_col, "Commentaire", tall=True)
    ws.column_dimensions[get_column_letter(comment_col)].width = 44

    for r, row in enumerate(rows, start=FIRST):
        stype, sid = row["type"], row["id"]
        if module.is_group_mode:
            group_id = row["group_id"] if row["is_member"] else sid
            labels = [group_names.get(group_id, ""),
                      row["label"] if row["is_member"] else None]
        else:
            labels = [row["label"]]
        fill = subject_fills.get(color_map.get((stype, sid)))
        for j, label in enumerate(labels, start=1):
            cell = ws.cell(row=r, column=j, value=label)
            if not row["is_member"]:
                cell.font = bold
            if fill:
                cell.fill = fill

        for j, kind, c in grid_cols:
            value = values.get((kind, stype, sid, c.id))
            cell = ws.cell(row=r, column=j)
            status_fill = None
            if kind == "star":
                # Comme à l'écran : une cellule jamais saisie vaut 0 étoile.
                value = "0" if value is None else str(value).strip()
                cell.value = grading.display_token(value) or "—"
                cell.alignment = center
                status_fill = status_fills.get(grading.status_color(value))
            elif kind == "presence":
                # La présence est celle d'un étudiant : vide sur un groupe.
                cell.value = value if stype == SUBJECT_STUDENT else None
                cell.alignment = center
                status_fill = status_fills.get(grading.PRESENCE_STATUSES.get(value))
            else:
                cell.value = value
                cell.alignment = wrap
            if status_fill:
                cell.fill = status_fill

        if row["is_member"]:
            total, note = member_totals.get(sid, 0), "—"
        else:
            g = grades.get(sid, {"total": 0, "note": None})
            total, note = g["total"], ("N/A" if g["note"] is None else g["note"])
        ws.cell(row=r, column=total_col, value=total).alignment = center
        ws.cell(row=r, column=note20_col, value=note).alignment = center
        for j, nc in enumerate(note_cols, start=first_note):
            cell = ws.cell(row=r, column=j, value=values.get(("note", stype, sid, nc.id)))
            cell.fill, cell.alignment = yellow, center
        ws.cell(row=r, column=comment_col, value=row.get("comment")).alignment = wrap

    ws.freeze_panes = ws.cell(row=FIRST, column=len(label_heads) + 1)

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio, as_attachment=True,
        download_name=grid_export_filename(module, grade_dates),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --------------------------------------------------------------------------- #
# Dates & colonnes
# --------------------------------------------------------------------------- #
@modules_bp.route("/modules/<int:module_id>/dates", methods=["POST"])
@login_required
def add_date(module_id):
    module = get_module_or_403(module_id)
    from datetime import datetime
    raw_date = request.form.get("date", "").strip()
    parsed = None
    if raw_date:
        try:
            parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            parsed = None
    # Une durée illisible ne fait pas échouer la création : la séance compte
    # plus que son nombre d'heures, qui reste corrigeable depuis le panneau de
    # gestion. On le dit, sinon l'enseignant croirait l'avoir enregistrée.
    try:
        duration = parse_duration(request.form.get("duration_hours"))
        duration_error = False
    except ValueError:
        duration, duration_error = None, True

    gd = GradeDate(
        module_id=module.id,
        label=request.form.get("label", "").strip() or None,
        date=parsed,
        duration_hours=duration,
        position=_next_position(module.grade_dates),
    )
    db.session.add(gd)
    db.session.commit()
    flash("Date/séance ajoutée.", "success")
    if duration_error:
        flash(f"Durée non enregistrée : indiquez un nombre d'heures entre 0 et "
              f"{MAX_DURATION_HOURS} (ex. 1, 2 ou 2,5).", "error")
    return _module_redirect(module, f"date-{gd.id}")


@modules_bp.route("/dates/<int:date_id>/delete", methods=["POST"])
@login_required
def delete_date(date_id):
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    db.session.delete(gd)
    db.session.commit()
    flash("Date supprimée.", "success")
    return _module_redirect(module)


@modules_bp.route("/dates/<int:date_id>/star-columns", methods=["POST"])
@login_required
def add_star_column(date_id):
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    col = StarColumn(
        grade_date_id=gd.id,
        title=request.form.get("title", "").strip() or "Exercice",
        position=_next_position(gd.star_columns),
    )
    db.session.add(col)
    db.session.commit()
    flash("Colonne d'étoiles ajoutée.", "success")
    return _module_redirect(module, f"col-star-{col.id}")


@modules_bp.route("/dates/<int:date_id>/url-columns", methods=["POST"])
@login_required
def add_url_column(date_id):
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    col = UrlColumn(
        grade_date_id=gd.id,
        title=request.form.get("title", "").strip() or "Lien",
        position=_next_position(gd.url_columns),
    )
    db.session.add(col)
    db.session.commit()
    flash("Colonne URL ajoutée.", "success")
    return _module_redirect(module, f"col-url-{col.id}")


@modules_bp.route("/dates/<int:date_id>/text-columns", methods=["POST"])
@login_required
def add_text_column(date_id):
    """Colonne de texte libre rattachée à une séance.

    Sert à consigner une remarque propre à *cette* séance, là où le
    « Commentaire » de fin de ligne vaut pour tout le module.
    """
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    col = TextColumn(
        grade_date_id=gd.id,
        title=request.form.get("title", "").strip() or "Remarque",
        position=_next_position(gd.text_columns),
    )
    db.session.add(col)
    db.session.commit()
    flash("Colonne de commentaire ajoutée.", "success")
    return _module_redirect(module, f"col-text-{col.id}")


@modules_bp.route("/dates/<int:date_id>/presence-columns", methods=["POST"])
@login_required
def add_presence_column(date_id):
    """Colonne « Présence » (Présent / Absent / Retard / Pas de PC).

    Sans incidence sur les étoiles ni sur la note /20 : elle sert au suivi de
    l'assiduité et alimente la synthèse de séance.
    """
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    col = PresenceColumn(
        grade_date_id=gd.id,
        title=request.form.get("title", "").strip() or "Présence",
        position=_next_position(gd.presence_columns),
    )
    db.session.add(col)
    db.session.commit()
    flash("Colonne de présence ajoutée.", "success")
    return _module_redirect(module, f"col-presence-{col.id}")


@modules_bp.route("/star-columns/<int:col_id>/delete", methods=["POST"])
@login_required
def delete_star_column(col_id):
    col = db.session.get(StarColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    db.session.delete(col)
    db.session.commit()
    flash("Colonne supprimée.", "success")
    return _module_redirect(module)


@modules_bp.route("/url-columns/<int:col_id>/delete", methods=["POST"])
@login_required
def delete_url_column(col_id):
    col = db.session.get(UrlColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    db.session.delete(col)
    db.session.commit()
    flash("Colonne supprimée.", "success")
    return _module_redirect(module)


@modules_bp.route("/text-columns/<int:col_id>/delete", methods=["POST"])
@login_required
def delete_text_column(col_id):
    col = db.session.get(TextColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    db.session.delete(col)   # cascade : les TextValue de la colonne partent avec
    db.session.commit()
    flash("Colonne supprimée.", "success")
    return _module_redirect(module)


@modules_bp.route("/presence-columns/<int:col_id>/delete", methods=["POST"])
@login_required
def delete_presence_column(col_id):
    col = db.session.get(PresenceColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    db.session.delete(col)   # cascade : les PresenceValue de la colonne partent avec
    db.session.commit()
    flash("Colonne supprimée.", "success")
    return _module_redirect(module)


@modules_bp.route("/modules/<int:module_id>/note-columns", methods=["POST"])
@login_required
def add_note_column(module_id):
    module = get_module_or_403(module_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("L'intitulé de la colonne de note est requis.", "error")
        return _module_redirect(module)
    col = NoteColumn(
        module_id=module.id, title=title,
        position=_next_position(module.note_columns),
    )
    db.session.add(col)
    db.session.commit()
    flash("Colonne de note ajoutée.", "success")
    return _module_redirect(module, f"col-note-{col.id}")


@modules_bp.route("/note-columns/<int:col_id>/delete", methods=["POST"])
@login_required
def delete_note_column(col_id):
    col = db.session.get(NoteColumn, col_id) or abort(404)
    module = get_module_or_403(col.module_id)
    db.session.delete(col)
    db.session.commit()
    flash("Colonne de note supprimée.", "success")
    return _module_redirect(module)


# --------------------------------------------------------------------------- #
# Renommage, réorganisation et édition (dates & colonnes) — fiche §5.3
# --------------------------------------------------------------------------- #
def _reorder(item, siblings, direction):
    """Normalise les positions puis échange `item` avec son voisin (up/down)."""
    ordered = sorted(siblings, key=lambda x: (x.position or 0, x.id))
    for i, s in enumerate(ordered):
        s.position = i
    idx = ordered.index(item)
    j = idx + (-1 if direction == "up" else 1)
    if 0 <= j < len(ordered):
        ordered[idx].position, ordered[j].position = (
            ordered[j].position, ordered[idx].position,
        )


@modules_bp.route("/star-columns/<int:col_id>/rename", methods=["POST"])
@login_required
def rename_star_column(col_id):
    col = db.session.get(StarColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    title = request.form.get("title", "").strip()
    if title:
        col.title = title
        db.session.commit()
        flash("Colonne renommée.", "success")
    return _module_redirect(module, f"col-star-{col.id}")


@modules_bp.route("/star-columns/<int:col_id>/move", methods=["POST"])
@login_required
def move_star_column(col_id):
    col = db.session.get(StarColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    _reorder(col, col.grade_date.star_columns, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"col-star-{col.id}")


@modules_bp.route("/url-columns/<int:col_id>/rename", methods=["POST"])
@login_required
def rename_url_column(col_id):
    col = db.session.get(UrlColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    title = request.form.get("title", "").strip()
    if title:
        col.title = title
        db.session.commit()
        flash("Colonne renommée.", "success")
    return _module_redirect(module, f"col-url-{col.id}")


@modules_bp.route("/url-columns/<int:col_id>/move", methods=["POST"])
@login_required
def move_url_column(col_id):
    col = db.session.get(UrlColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    _reorder(col, col.grade_date.url_columns, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"col-url-{col.id}")


@modules_bp.route("/text-columns/<int:col_id>/rename", methods=["POST"])
@login_required
def rename_text_column(col_id):
    col = db.session.get(TextColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    title = request.form.get("title", "").strip()
    if title:
        col.title = title
        db.session.commit()
        flash("Colonne renommée.", "success")
    return _module_redirect(module, f"col-text-{col.id}")


@modules_bp.route("/text-columns/<int:col_id>/move", methods=["POST"])
@login_required
def move_text_column(col_id):
    col = db.session.get(TextColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    _reorder(col, col.grade_date.text_columns, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"col-text-{col.id}")


@modules_bp.route("/presence-columns/<int:col_id>/rename", methods=["POST"])
@login_required
def rename_presence_column(col_id):
    col = db.session.get(PresenceColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    title = request.form.get("title", "").strip()
    if title:
        col.title = title
        db.session.commit()
        flash("Colonne renommée.", "success")
    return _module_redirect(module, f"col-presence-{col.id}")


@modules_bp.route("/presence-columns/<int:col_id>/move", methods=["POST"])
@login_required
def move_presence_column(col_id):
    col = db.session.get(PresenceColumn, col_id) or abort(404)
    module = get_module_or_403(col.grade_date.module_id)
    _reorder(col, col.grade_date.presence_columns, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"col-presence-{col.id}")


@modules_bp.route("/note-columns/<int:col_id>/rename", methods=["POST"])
@login_required
def rename_note_column(col_id):
    col = db.session.get(NoteColumn, col_id) or abort(404)
    module = get_module_or_403(col.module_id)
    title = request.form.get("title", "").strip()
    if title:
        col.title = title
        db.session.commit()
        flash("Colonne renommée.", "success")
    return _module_redirect(module, f"col-note-{col.id}")


@modules_bp.route("/note-columns/<int:col_id>/move", methods=["POST"])
@login_required
def move_note_column(col_id):
    col = db.session.get(NoteColumn, col_id) or abort(404)
    module = get_module_or_403(col.module_id)
    _reorder(col, module.note_columns, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"col-note-{col.id}")


@modules_bp.route("/dates/<int:date_id>/edit", methods=["POST"])
@login_required
def edit_date(date_id):
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    from datetime import datetime
    raw = request.form.get("date", "").strip()
    if raw:
        try:
            gd.date = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    gd.label = request.form.get("label", "").strip() or None
    # Champ présent mais vide = durée effacée ; champ absent du formulaire =
    # durée inchangée (un futur formulaire partiel ne l'écrasera pas).
    error = None
    if "duration_hours" in request.form:
        try:
            gd.duration_hours = parse_duration(request.form["duration_hours"])
        except ValueError:
            error = (f"Durée invalide : indiquez un nombre d'heures entre 0 et "
                     f"{MAX_DURATION_HOURS} (ex. 1, 2 ou 2,5). Elle est restée "
                     f"inchangée.")
    db.session.commit()
    flash("Date mise à jour.", "success")
    if error:
        flash(error, "error")
    return _module_redirect(module, f"date-{gd.id}")


@modules_bp.route("/dates/<int:date_id>/move", methods=["POST"])
@login_required
def move_date(date_id):
    gd = db.session.get(GradeDate, date_id) or abort(404)
    module = get_module_or_403(gd.module_id)
    # Les séances s'affichent par date : seul l'ordre entre séances du même
    # jour (ou sans date) reste à la main de l'enseignant.
    same_day = [g for g in module.grade_dates if g.date == gd.date]
    _reorder(gd, same_day, request.form.get("dir", "up"))
    db.session.commit()
    return _module_redirect(module, f"date-{gd.id}")


# --------------------------------------------------------------------------- #
# Groupes (mode groupe)
# --------------------------------------------------------------------------- #
@modules_bp.route("/modules/<int:module_id>/groups", methods=["POST"])
@login_required
def add_group(module_id):
    module = get_module_or_403(module_id)
    if not module.is_group_mode:
        abort(400)
    name = request.form.get("name", "").strip()
    if name:
        group = Group(module_id=module.id, name=name)
        db.session.add(group)
        db.session.commit()
        flash("Groupe créé.", "success")
        return _module_redirect(module, f"subject-group-{group.id}")
    return _module_redirect(module)


@modules_bp.route("/groups/<int:group_id>/members", methods=["POST"])
@login_required
def add_group_member(group_id):
    group = db.session.get(Group, group_id) or abort(404)
    module = get_module_or_403(group.module_id)
    student_id = request.form.get("student_id", type=int)
    if student_id:
        # Un étudiant ne peut appartenir qu'à un seul groupe du module.
        existing_ids = {
            m.student_id for g in module.groups for m in g.members
        }
        if student_id not in existing_ids:
            db.session.add(GroupMember(group_id=group.id, student_id=student_id))
            db.session.commit()
            flash("Étudiant affecté au groupe.", "success")
        else:
            flash("Cet étudiant est déjà dans un groupe.", "error")
    return _module_redirect(module, f"subject-group-{group.id}")


@modules_bp.route("/group-members/<int:member_id>/delete", methods=["POST"])
@login_required
def remove_group_member(member_id):
    member = db.session.get(GroupMember, member_id) or abort(404)
    group = member.group
    module = get_module_or_403(group.module_id)
    db.session.delete(member)
    db.session.commit()
    flash("Étudiant retiré du groupe.", "success")
    return redirect(url_for("modules.view_module", module_id=module.id))


@modules_bp.route("/groups/<int:group_id>/delete", methods=["POST"])
@login_required
def delete_group(group_id):
    group = db.session.get(Group, group_id) or abort(404)
    module = get_module_or_403(group.module_id)
    # Purge les étoiles/notes/liens/couleurs du groupe (référencés par subject_id).
    purge_subject_data(SUBJECT_GROUP, group.id)
    db.session.delete(group)
    db.session.commit()
    flash("Groupe supprimé.", "success")
    return redirect(url_for("modules.view_module", module_id=module.id))


# --------------------------------------------------------------------------- #
# Saisie AJAX (étoiles, notes, URL, commentaires) + recalcul
# --------------------------------------------------------------------------- #
def _subject_type(module):
    return SUBJECT_GROUP if module.is_group_mode else SUBJECT_STUDENT


def _payload_subject(module, data):
    """Sujet visé par une saisie : ((type, id), None) ou (None, réponse d'erreur).

    Le type accompagne désormais l'identifiant : dans un module en groupe, la
    grille porte des lignes de groupe **et** des lignes de membre, et
    `subject_id` seul serait ambigu (le groupe 3 et l'étudiant 3). En son
    absence on retombe sur le type du module.

    Le sujet doit être une ligne notable **de ce module** — sans ce contrôle, un
    identifiant quelconque crée des lignes orphelines, invisibles dans la grille
    mais comptées ailleurs — et un étudiant neutralisé n'accepte plus de saisie.
    """
    stype = str(data.get("subject_type") or _subject_type(module))
    try:
        sid = int(data.get("subject_id"))
    except (TypeError, ValueError):
        sid = None

    if (stype, sid) not in valid_subjects(module):
        return None, (jsonify(error="Sujet invalide"), 400)
    if stype == SUBJECT_STUDENT:
        student = db.session.get(Student, sid)
        if not (student and student.active):
            return None, (jsonify(error="Étudiant neutralisé : saisie impossible"), 403)
    return (stype, sid), None


def _grade_payload(module):
    """Totaux + notes /20 recalculés pour tout le module, indexés « type:id ».

    Les lignes de membre d'un module en groupe apparaissent avec leur total
    d'étoiles et un tiret en guise de note : la seule note /20 d'un module en
    groupe est celle du groupe.
    """
    subjects = module_subjects(module)
    subject_ids = [s["id"] for s in subjects]
    active_ids = {s["id"] for s in subjects if s.get("active", True)}
    grades = grading.compute_module_grades(module, subject_ids, active_ids)
    stype = _subject_type(module)

    payload = {
        f"{stype}:{sid}": {
            "total": g["total"],
            # "—" pour un sujet neutralisé, "N/A" si personne n'a d'étoile.
            "note": ("—" if not g["active"] else
                     ("N/A" if g["note"] is None else g["note"])),
            "is_reference": g["is_reference"],
        }
        for sid, g in grades.items()
    }

    member_ids = [m["id"] for rows in module_members(module).values() for m in rows]
    for sid, total in grading.compute_member_totals(module, member_ids).items():
        payload[f"{SUBJECT_STUDENT}:{sid}"] = {
            "total": total, "note": "—", "is_reference": False,
        }
    return payload


@modules_bp.route("/modules/<int:module_id>/save-star", methods=["POST"])
@login_required
def save_star(module_id):
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    column_id = data.get("column_id")
    value = str(data.get("value", "0")).strip()

    if value not in grading.ALL_TOKENS:
        return jsonify(error="Valeur invalide"), 400
    col = db.session.get(StarColumn, column_id)
    if not col or col.grade_date.module_id != module.id:
        return jsonify(error="Colonne invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject
    star = Star.query.filter_by(
        subject_type=stype, subject_id=subject_id, star_column_id=column_id,
    ).first()
    if star:
        star.value = value
    else:
        db.session.add(Star(
            subject_type=stype, subject_id=subject_id,
            star_column_id=column_id, value=value,
        ))
    db.session.commit()

    return jsonify(
        ok=True,
        display=grading.display_token(value),
        color=grading.status_color(value),
        grades=_grade_payload(module),
    )


@modules_bp.route("/modules/<int:module_id>/save-note", methods=["POST"])
@login_required
def save_note(module_id):
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    column_id = data.get("column_id")
    raw = str(data.get("value", "")).strip().replace(",", ".")

    col = db.session.get(NoteColumn, column_id)
    if not col or col.module_id != module.id:
        return jsonify(error="Colonne invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject

    score = None
    if raw != "":
        try:
            score = float(raw)
        except ValueError:
            return jsonify(error="Note invalide"), 400
        if not (0 <= score <= 20):
            return jsonify(error="La note doit être entre 0 et 20"), 400

    nv = NoteValue.query.filter_by(
        subject_type=stype, subject_id=subject_id, note_column_id=column_id,
    ).first()
    if nv:
        nv.score = score
    else:
        db.session.add(NoteValue(
            subject_type=stype, subject_id=subject_id,
            note_column_id=column_id, score=score,
        ))
    db.session.commit()
    return jsonify(ok=True, value=("" if score is None else score))


@modules_bp.route("/modules/<int:module_id>/save-url", methods=["POST"])
@login_required
def save_url(module_id):
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    column_id = data.get("column_id")
    try:
        url = clean_url(str(data.get("value") or ""))
    except ValueError:
        return jsonify(error=URL_ERROR), 400

    col = db.session.get(UrlColumn, column_id)
    if not col or col.grade_date.module_id != module.id:
        return jsonify(error="Colonne invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject

    uv = UrlValue.query.filter_by(
        subject_type=stype, subject_id=subject_id, url_column_id=column_id,
    ).first()
    if uv:
        uv.url = url
    else:
        db.session.add(UrlValue(
            subject_type=stype, subject_id=subject_id,
            url_column_id=column_id, url=url,
        ))
    db.session.commit()
    return jsonify(ok=True, value=url or "")


@modules_bp.route("/modules/<int:module_id>/save-text", methods=["POST"])
@login_required
def save_text(module_id):
    """Texte libre d'une cellule de colonne « commentaire de séance ».

    Une valeur vide supprime la ligne plutôt que de stocker une chaîne nulle :
    seules les remarques réellement saisies restent en base.
    """
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    column_id = data.get("column_id")
    content = str(data.get("value", "")).strip() or None

    col = db.session.get(TextColumn, column_id)
    if not col or col.grade_date.module_id != module.id:
        return jsonify(error="Colonne invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject

    tv = TextValue.query.filter_by(
        subject_type=stype, subject_id=subject_id, text_column_id=column_id,
    ).first()
    if content is None:
        if tv:
            db.session.delete(tv)
    elif tv:
        tv.content = content
    else:
        db.session.add(TextValue(
            subject_type=stype, subject_id=subject_id,
            text_column_id=column_id, content=content,
        ))
    db.session.commit()
    return jsonify(ok=True, value=content or "")


@modules_bp.route("/modules/<int:module_id>/save-presence", methods=["POST"])
@login_required
def save_presence(module_id):
    """Statut d'une cellule de colonne « Présence ».

    La présence est celle d'un étudiant : une ligne de groupe n'en porte pas.
    Une valeur vide supprime la ligne (cellule « non renseignée »).
    """
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    column_id = data.get("column_id")
    status = str(data.get("value", "")).strip()

    if status and status not in grading.PRESENCE_STATUSES:
        return jsonify(error="Valeur invalide"), 400
    col = db.session.get(PresenceColumn, column_id)
    if not col or col.grade_date.module_id != module.id:
        return jsonify(error="Colonne invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject
    if stype != SUBJECT_STUDENT:
        return jsonify(error="La présence se saisit par étudiant"), 400

    pv = PresenceValue.query.filter_by(
        subject_type=stype, subject_id=subject_id, presence_column_id=column_id,
    ).first()
    if not status:
        if pv:
            db.session.delete(pv)
    elif pv:
        pv.status = status
    else:
        db.session.add(PresenceValue(
            subject_type=stype, subject_id=subject_id,
            presence_column_id=column_id, status=status,
        ))
    db.session.commit()
    return jsonify(ok=True, value=status,
                   color=grading.PRESENCE_STATUSES.get(status))


@modules_bp.route("/modules/<int:module_id>/save-comment", methods=["POST"])
@login_required
def save_comment(module_id):
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    comment = str(data.get("value", "")).strip() or None

    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject

    # Un membre déplié commente comme un étudiant, même en module groupe.
    if stype == SUBJECT_GROUP:
        db.session.get(Group, subject_id).comment = comment
    else:
        enr = Enrollment.query.filter_by(
            student_id=subject_id, class_id=module.class_id,
        ).first()
        if not enr:
            return jsonify(error="Inscription introuvable"), 400
        enr.general_comment = comment
    db.session.commit()
    return jsonify(ok=True)


@modules_bp.route("/modules/<int:module_id>/save-color", methods=["POST"])
@login_required
def save_color(module_id):
    """Pose (ou retire) la couleur de fond de la cellule d'un sujet.

    Valeur vide = aucune couleur : la ligne est alors supprimée plutôt que
    stockée, pour ne garder en base que les couleurs réellement posées.
    """
    module = get_module_or_403(module_id)
    data = request.get_json(silent=True) or {}
    color = str(data.get("value", "")).strip()

    if color and color not in SUBJECT_COLORS:
        return jsonify(error="Couleur invalide"), 400
    subject, err = _payload_subject(module, data)
    if err:
        return err
    stype, subject_id = subject

    existing = SubjectColor.query.filter_by(
        module_id=module.id, subject_type=stype, subject_id=subject_id,
    ).first()
    if not color:
        if existing:
            db.session.delete(existing)
    elif existing:
        existing.color = color
    else:
        db.session.add(SubjectColor(
            module_id=module.id, subject_type=stype,
            subject_id=subject_id, color=color,
        ))
    db.session.commit()
    return jsonify(ok=True, value=color)


# --------------------------------------------------------------------------- #
# Export / import Excel des notes manuelles (colonnes jaunes) + commentaire
# --------------------------------------------------------------------------- #
def _safe_sheet_title(name):
    """Titre d'onglet valide pour Excel (max 31 car., pas de []:*?/\\)."""
    title = re.sub(r"[\[\]:\*\?/\\]", " ", name or "Notes").strip()
    return (title or "Notes")[:31]


def _export_rows(module):
    """Lignes du classeur : chaque unité notée, suivie de ses membres.

    En mode groupe, un groupe est suivi de ses membres actifs, qui portent
    leurs propres notes manuelles et leur propre commentaire.
    """
    members = module_members(module)
    rows = []
    for subject in module_subjects(module):
        if not subject.get("active", True):
            continue
        rows.append({**subject, "is_member": False})
        rows += [{**m, "is_member": True}
                 for m in members.get(subject["id"], []) if m["active"]]
    return rows


def _row_token(module, row):
    """Valeur de la colonne « ID » masquée d'une ligne du classeur.

    En mode groupe la feuille mêle groupes et membres : l'identifiant seul
    serait ambigu, on le préfixe donc de G (groupe) ou E (étudiant). En mode
    individuel l'identifiant nu est conservé, pour que les fichiers déjà
    exportés restent réimportables.
    """
    if not module.is_group_mode:
        return row["id"]
    return f"{'E' if row['type'] == SUBJECT_STUDENT else 'G'}{row['id']}"


def _parse_token(module, raw):
    """(subject_type, id) d'une cellule « ID », ou None si illisible.

    Accepte les jetons préfixés et l'identifiant nu des fichiers antérieurs,
    rattaché au type par défaut du module.
    """
    text = str(raw).strip()
    if len(text) > 1 and text[0].upper() in ("G", "E") and text[1:].isdigit():
        stype = SUBJECT_GROUP if text[0].upper() == "G" else SUBJECT_STUDENT
        return stype, int(text[1:])
    try:
        return _subject_type(module), int(float(text))
    except ValueError:
        return None


def _set_comment(module, stype, subject_id, comment):
    if stype == SUBJECT_GROUP:
        group = db.session.get(Group, subject_id)
        if group and group.module_id == module.id:
            group.comment = comment
    else:
        enr = Enrollment.query.filter_by(
            student_id=subject_id, class_id=module.class_id,
        ).first()
        if enr:
            enr.general_comment = comment


@modules_bp.route("/modules/<int:module_id>/export.xlsx")
@login_required
def export_module(module_id):
    """Exporte un module en .xlsx : nom du module, nom de l'étudiant/groupe,
    ses notes manuelles (colonnes jaunes) et son commentaire."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    module = get_module_or_403(module_id)
    rows_data = _export_rows(module)
    note_cols = module.note_columns

    note_map = {}
    if note_cols:
        for n in NoteValue.query.filter(
                NoteValue.note_column_id.in_([c.id for c in note_cols])).all():
            note_map[(n.subject_type, n.subject_id, n.note_column_id)] = n.score

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_title(module.name)

    yellow = PatternFill("solid", fgColor="FEF9C3")
    grey = PatternFill("solid", fgColor="F1F5F9")
    bold = Font(bold=True)

    # Ligne 1 : nom du module.
    ws["B1"] = f"Module : {module.name}"
    ws["B1"].font = Font(bold=True, size=13)

    # Ligne 2 : en-têtes.
    label_head = "Groupe / Étudiant" if module.is_group_mode else "Étudiant"
    headers = ["ID", label_head] + [c.title for c in note_cols] + ["Commentaire"]
    for col_idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col_idx, value=title)
        cell.font = bold
        if 3 <= col_idx <= 2 + len(note_cols):   # colonnes de note = jaune
            cell.fill = yellow
        elif col_idx <= 2:
            cell.fill = grey

    # Données : les membres sont indentés sous leur groupe et en maigre, pour
    # qu'un coup d'œil suffise à distinguer les deux niveaux.
    for r, row in enumerate(rows_data, start=3):
        ws.cell(row=r, column=1, value=_row_token(module, row))
        label = ws.cell(row=r, column=2, value=row["label"])
        if row["is_member"]:
            label.alignment = Alignment(indent=2)
        else:
            label.font = bold
        for j, nc in enumerate(note_cols, start=3):
            c = ws.cell(row=r, column=j,
                        value=note_map.get((row["type"], row["id"], nc.id)))
            c.fill = yellow
        ws.cell(row=r, column=3 + len(note_cols), value=row.get("comment"))

    # Mise en forme : colonne ID masquée (ne pas éditer), largeurs, gel.
    ws.column_dimensions["A"].hidden = True
    ws.column_dimensions["B"].width = 26
    for j in range(3, 3 + len(note_cols)):
        ws.column_dimensions[ws.cell(row=2, column=j).column_letter].width = 14
    ws.column_dimensions[ws.cell(row=2, column=3 + len(note_cols)).column_letter].width = 40
    ws.freeze_panes = "C3"

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = re.sub(r"[^\w\-]+", "_", module.name).strip("_") or "module"
    return send_file(
        bio, as_attachment=True, download_name=f"notes_{filename}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@modules_bp.route("/modules/<int:module_id>/import", methods=["POST"])
@login_required
def import_module(module_id):
    """Réimporte un fichier .xlsx exporté : met à jour les notes manuelles et
    les commentaires. Le matching se fait par la colonne ID ; les colonnes de
    note sont reconnues par leur intitulé."""
    from openpyxl import load_workbook

    module = get_module_or_403(module_id)
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".xlsx"):
        flash("Veuillez fournir un fichier .xlsx (exporté depuis ce module).", "error")
        return redirect(url_for("modules.view_module", module_id=module.id))

    try:
        wb = load_workbook(file, data_only=True)
    except Exception:
        flash("Fichier Excel illisible.", "error")
        return redirect(url_for("modules.view_module", module_id=module.id))
    ws = wb.active

    rows = list(ws.iter_rows())
    # Repère la ligne d'en-tête (celle contenant "ID").
    header_row_idx = None
    for i, row in enumerate(rows):
        values = [(c.value if c.value is not None else "") for c in row]
        if any(str(v).strip().lower() == "id" for v in values):
            header_row_idx = i
            headers = [str(v).strip() for v in values]
            break
    if header_row_idx is None:
        flash("En-tête introuvable : utilisez un fichier exporté depuis ce module.", "error")
        return redirect(url_for("modules.view_module", module_id=module.id))

    # Index des colonnes.
    id_col = next(i for i, h in enumerate(headers) if h.lower() == "id")
    comment_col = next((i for i, h in enumerate(headers) if h.lower() == "commentaire"), None)
    note_by_title = {c.title: c for c in module.note_columns}
    note_cols_pos = {i: note_by_title[h] for i, h in enumerate(headers) if h in note_by_title}

    valid_rows = {(r["type"], r["id"]) for r in _export_rows(module)}
    existing = {
        (nv.subject_type, nv.subject_id, nv.note_column_id): nv
        for nv in NoteValue.query.filter(
            NoteValue.note_column_id.in_(
                [c.id for c in module.note_columns] or [0])).all()
    }

    n_notes, n_comments, errors = 0, 0, []
    for row in rows[header_row_idx + 1:]:
        cells = list(row)
        raw_id = cells[id_col].value if id_col < len(cells) else None
        if raw_id in (None, ""):
            continue
        subject = _parse_token(module, raw_id)
        if subject is None or subject not in valid_rows:
            continue
        stype, sid = subject

        # Notes manuelles.
        for pos, nc in note_cols_pos.items():
            if pos >= len(cells):
                continue
            val = cells[pos].value
            score = None
            if val not in (None, ""):
                try:
                    score = float(str(val).replace(",", "."))
                except ValueError:
                    errors.append(f"« {nc.title} » ligne ID {sid} : valeur non numérique")
                    continue
                if not (0 <= score <= 20):
                    errors.append(f"« {nc.title} » ligne ID {sid} : hors 0–20")
                    continue
            nv = existing.get((stype, sid, nc.id))
            if nv:
                nv.score = score
            else:
                db.session.add(NoteValue(
                    subject_type=stype, subject_id=sid,
                    note_column_id=nc.id, score=score,
                ))
            n_notes += 1

        # Commentaire.
        if comment_col is not None and comment_col < len(cells):
            cval = cells[comment_col].value
            _set_comment(module, stype, sid,
                         str(cval).strip() if cval not in (None, "") else None)
            n_comments += 1

    db.session.commit()
    msg = f"Import terminé : {n_notes} note(s) et {n_comments} commentaire(s) mis à jour."
    if errors:
        msg += " Ignoré(s) : " + " ; ".join(errors[:5])
        if len(errors) > 5:
            msg += f" … (+{len(errors) - 5})"
        flash(msg, "error")
    else:
        flash(msg, "success")
    return redirect(url_for("modules.view_module", module_id=module.id))
