"""Planning : demi-journées réservées de l'enseignant et liens de réservation.

Vue de synthèse d'une année académique entière, une ligne par semaine et deux
cellules par jour (matin / après-midi). Cocher une demi-journée la réserve pour
les cours : elle devient « Non disponible ». Des liens publics, un par client,
permettent à l'extérieur de consulter ces disponibilités sans compte et de
demander les demi-journées libres ; l'enseignant valide ou refuse ces demandes.
"""
import re
import secrets
from datetime import date as date_type, datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from .models import (
    db, AcademicYear, PlanningSlot, PlanningLink, LINK_COLORS,
    HALF_AM, HALF_PM, HALF_DAYS,
)
from .main import visible_years_query, selected_year_id

planning_bp = Blueprint("planning", __name__)

# Jours ouvrés affichés : le planning ne couvre pas le week-end.
WEEK_DAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")
HALVES = (HALF_AM, HALF_PM)

# Libellés français en dur : le serveur d'hébergement n'a aucune locale fr
# garantie, et `strftime('%B')` y renverrait des mois en anglais.
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre")
MONTHS_SHORT = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
                "août", "sept.", "oct.", "nov.", "déc.")


@planning_bp.app_context_processor
def _inject_planning_labels():
    """Libellés du tableau, pour que les deux gabarits (privé / public) n'aient
    pas à les redéclarer chacun de leur côté."""
    return {
        "week_days": WEEK_DAYS, "halves": HALVES, "half_labels": HALF_DAYS,
        # Libellés posés par le script dès la coche, avant la réponse serveur.
        "slot_texts": {"free": TEXT_FREE, "edit": TEXT_BUSY, "book": TEXT_REQUESTED},
    }


def has_current_week(months):
    """Vrai si l'année affichée contient aujourd'hui (cible du saut de semaine)."""
    return any(w["is_current"] for m in months for w in m["weeks"])


# --------------------------------------------------------------------------- #
# Bornes d'une année académique
# --------------------------------------------------------------------------- #
def year_bounds(label, today=None):
    """Premier et dernier jour couverts par une année académique.

    Les bornes sont **déduites du libellé** (« 2025-2026 » -> 1er septembre
    2025 au 31 août 2026) : l'année académique n'a pas de dates en base, et en
    inventer deux colonnes obligerait à les ressaisir sur toutes les années
    existantes. Un libellé ne portant qu'un millésime (« 2026 ») est lu comme
    le début de l'année scolaire ; un libellé sans millésime lisible retombe
    sur l'année scolaire en cours, pour afficher malgré tout un planning utile.
    """
    today = today or date_type.today()
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", label or "")]
    if years:
        start_year = years[0]
        end_year = years[1] if len(years) > 1 else start_year + 1
        if end_year <= start_year:
            end_year = start_year + 1
    else:
        # Avant septembre, l'année scolaire en cours a commencé l'an dernier.
        start_year = today.year if today.month >= 9 else today.year - 1
        end_year = start_year + 1
    return date_type(start_year, 9, 1), date_type(end_year, 8, 31)


def _week_label(monday, friday):
    """« 15 → 19 sept. », ou « 29 sept. → 3 oct. » à cheval sur deux mois."""
    end = f"{friday.day} {MONTHS_SHORT[friday.month - 1]}"
    if monday.month == friday.month:
        return f"{monday.day} → {end}"
    return f"{monday.day} {MONTHS_SHORT[monday.month - 1]} → {end}"


# États d'une demi-journée à l'écran. « request » est une demande en attente
# (affichée dans la couleur du lien), « granted » une demande validée vue par
# le client qui l'a déposée.
FREE, BUSY, REQUEST, GRANTED = "free", "busy", "request", "granted"
TEXT_FREE, TEXT_BUSY = "Disponible", "Non disponible"
TEXT_REQUESTED = "Votre demande, en attente de validation"
FREE_CELL = {"state": FREE, "color": None, "text": TEXT_FREE}


def planning_months(start, end, busy=(), today=None, cells=None, counted=(BUSY,)):
    """Structure d'affichage : mois -> semaines -> 5 jours × 2 demi-journées.

    `cells` associe à chaque couple (date, demi-journée) non libre son état
    d'affichage (cf. `cell_states`) ; `busy`, simple ensemble de couples, en
    est le raccourci quand tout ce qui est pris est « Non disponible ».
    `counted` désigne les états comptés dans le total de la semaine. Les
    semaines de bord débordent des bornes de l'année : les jours concernés sont
    marqués `in_year=False` et affichés inertes, ce qui garde un tableau
    rectangulaire plutôt qu'une première ligne tronquée.
    """
    today = today or date_type.today()
    if cells is None:
        cells = {key: {"state": BUSY, "color": None, "text": TEXT_BUSY}
                 for key in busy}
    monday = start - timedelta(days=start.weekday())
    last_monday = end - timedelta(days=end.weekday())

    months = []
    while monday <= last_monday:
        days = [monday + timedelta(days=i) for i in range(5)]
        # Mois d'accueil d'une semaine à cheval : celui de son jour médian, donc
        # celui où tombe la majorité de ses jours. La médiane est prise parmi les
        # jours situés DANS l'année, sinon la dernière semaine — un seul jour
        # utile, le reste en débord — ouvrirait un mois de plus en fin de tableau.
        in_year_days = [d for d in days if start <= d <= end] or days
        pivot = in_year_days[len(in_year_days) // 2]
        if not months or months[-1]["key"] != (pivot.year, pivot.month):
            months.append({
                "key": (pivot.year, pivot.month),
                "label": f"{MONTHS[pivot.month - 1].capitalize()} {pivot.year}",
                "weeks": [],
            })

        rows = []
        for day in days:
            in_year = start <= day <= end
            day_cells = {
                h: (cells.get((day, h)) if in_year else None) or FREE_CELL
                for h in HALVES
            }
            rows.append({
                "date": day,
                "in_year": in_year,
                "label": day_label(day),
                "is_today": day == today,
                "is_past": day < today,
                "cells": day_cells,
                HALF_AM: day_cells[HALF_AM]["state"] == BUSY,
                HALF_PM: day_cells[HALF_PM]["state"] == BUSY,
            })
        months[-1]["weeks"].append({
            "iso": monday.isocalendar()[1],
            "label": _week_label(monday, days[4]),
            "days": rows,
            "count": sum(1 for d in rows for h in HALVES
                         if d["cells"][h]["state"] in counted),
            "is_current": days[0] <= today <= days[4],
        })
        monday += timedelta(days=7)
    return months


def day_label(day):
    """« lundi 15 septembre »."""
    return f"{WEEK_DAYS[day.weekday()].lower()} {day.day} {MONTHS[day.month - 1]}"


def _slots(teacher_id, start, end):
    return PlanningSlot.query.filter(
        PlanningSlot.teacher_id == teacher_id,
        PlanningSlot.date >= start,
        PlanningSlot.date <= end,
    ).order_by(PlanningSlot.date, PlanningSlot.half).all()


def cell_state(slot, viewer=None):
    """État d'affichage d'une demi-journée prise.

    Sans `viewer`, c'est l'enseignant qui regarde : une demande en attente
    porte la couleur et le nom de son lien. Avec `viewer` (le lien du client
    qui consulte), seules ses propres demandes se distinguent — celles des
    autres clients sont de simples « Non disponible », sans nom ni couleur :
    un client n'a pas à savoir qui d'autre réserve.
    """
    link = slot.link
    if viewer is None:
        if slot.pending and link is not None:
            return {"state": REQUEST, "color": link.color,
                    "text": f"Demande de « {link.name} » — cochez pour valider"}
        text = TEXT_BUSY + (f" · {link.name}" if link is not None else "")
        return {"state": BUSY, "color": None, "text": text}
    if slot.link_id == viewer.id:
        if slot.pending:
            return {"state": REQUEST, "color": viewer.color,
                    "text": TEXT_REQUESTED}
        return {"state": GRANTED, "color": viewer.color,
                "text": "Réservation confirmée"}
    return {"state": BUSY, "color": None, "text": TEXT_BUSY}


def cell_states(slots, viewer=None):
    return {(s.date, s.half): cell_state(s, viewer) for s in slots}


def _count(cells, *states):
    return sum(1 for c in cells.values() if c["state"] in states)


def _state_json(cells):
    """États des demi-journées prises, pour le rafraîchissement en direct."""
    res = jsonify(slots={f"{d.isoformat()}|{h}": c for (d, h), c in cells.items()})
    res.headers["Cache-Control"] = "no-store"
    return res


def _parse_slot(data):
    """(date, demi-journée) d'une requête d'écriture, ou (None, message)."""
    try:
        day = datetime.strptime(str(data.get("date") or ""), "%Y-%m-%d").date()
    except ValueError:
        return None, "Date invalide."
    half = str(data.get("half") or "")
    if half not in HALF_DAYS:
        return None, "Demi-journée inconnue."
    if day.weekday() >= 5:
        return None, "Le planning ne couvre que le lundi au vendredi."
    return (day, half), None


def _visible_year_or_404(year_id):
    return visible_years_query().filter(AcademicYear.id == year_id).first() or abort(404)


# --------------------------------------------------------------------------- #
# Planning de l'enseignant connecté
# --------------------------------------------------------------------------- #
@planning_bp.route("/planning")
@login_required
def view_planning():
    """Synthèse de l'année : coche des demi-journées réservées pour les cours."""
    years = visible_years_query().all()
    year_id = selected_year_id(years)
    year = db.session.get(AcademicYear, year_id) if year_id else None

    months, start, end, cells, links = [], None, None, {}, []
    if year:
        start, end = year_bounds(year.label)
        slots = _slots(current_user.id, start, end)
        cells = cell_states(slots)
        months = planning_months(start, end, cells=cells)
        for link in PlanningLink.query.filter_by(
                teacher_id=current_user.id, academic_year_id=year.id,
        ).order_by(PlanningLink.created_at, PlanningLink.id).all():
            mine = [s for s in slots if s.link_id == link.id]
            links.append({
                "link": link,
                "requests": [s for s in mine if s.pending],
                "granted": sum(1 for s in mine if not s.pending),
            })

    return render_template(
        "planning/planning.html",
        years=years, year=year, selected_year_id=year_id,
        months=months, start=start, end=end,
        reserved=_count(cells, BUSY), pending=_count(cells, REQUEST),
        has_current=has_current_week(months), links=links,
        next_color=LINK_COLORS[len(links) % len(LINK_COLORS)],
        day_label=day_label,
    )


@planning_bp.route("/planning/state")
@login_required
def planning_state():
    """État courant du planning : les demandes des clients arrivent sans que
    l'enseignant ait à recharger la page."""
    year = _visible_year_or_404(request.args.get("year", type=int))
    start, end = year_bounds(year.label)
    return _state_json(cell_states(_slots(current_user.id, start, end)))


@planning_bp.route("/planning/slot", methods=["POST"])
@login_required
def save_slot():
    """Réserve (ou libère) une demi-journée de l'enseignant connecté.

    Une demi-journée réservée existe en base, une demi-journée libre n'existe
    pas : décocher supprime la ligne. L'appel est idempotent, ce qui évite un
    doublon si deux onglets cochent la même case.

    Cocher une demande en attente la **valide** ; la décocher la refuse. La
    validation exige `confirm` : si un client a déposé sa demande pendant que
    l'enseignant regardait une case encore blanche, la cocher ne doit pas
    l'accepter à son insu.
    """
    data = request.get_json(silent=True) or {}
    key, error = _parse_slot(data)
    if error:
        return jsonify(error=error), 400
    day, half = key

    busy = bool(data.get("busy"))
    slot = PlanningSlot.query.filter_by(
        teacher_id=current_user.id, date=day, half=half).first()
    if busy and slot is None:
        db.session.add(PlanningSlot(teacher_id=current_user.id, date=day, half=half))
    elif busy and slot.pending:
        if not data.get("confirm"):
            return jsonify(error=f"« {slot.link.name} » vient de demander cette "
                                 "demi-journée : elle apparaît maintenant sur "
                                 "votre planning."), 409
        slot.pending = False
    elif not busy and slot is not None:
        db.session.delete(slot)
    try:
        db.session.commit()
    except IntegrityError:
        # Un client a pris la demi-journée entre la lecture et l'écriture.
        db.session.rollback()
        return jsonify(error="Un client vient de demander cette demi-journée."), 409
    return jsonify(ok=True, busy=busy)


# --------------------------------------------------------------------------- #
# Liens de réservation (un par client)
# --------------------------------------------------------------------------- #
def _own_link_or_404(link_id):
    return PlanningLink.query.filter_by(
        id=link_id, teacher_id=current_user.id).first() or abort(404)


def _back_to_links(year_id):
    return redirect(url_for("planning.view_planning", year=year_id,
                            _anchor="tools-share"))


@planning_bp.route("/planning/share", methods=["POST"])
@login_required
def share_link():
    """Crée un lien de réservation nommé, dans la couleur choisie."""
    year = _visible_year_or_404(request.form.get("year", type=int))
    name = (request.form.get("name") or "").strip()[:80]
    if not name:
        flash("Donnez un nom au lien (ex. « Formation STEAME »).", "error")
        return _back_to_links(year.id)

    color = (request.form.get("color") or "").strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        count = PlanningLink.query.filter_by(
            teacher_id=current_user.id, academic_year_id=year.id).count()
        color = LINK_COLORS[count % len(LINK_COLORS)]

    db.session.add(PlanningLink(
        teacher_id=current_user.id, academic_year_id=year.id,
        token=secrets.token_urlsafe(32), name=name, color=color,
    ))
    db.session.commit()
    flash(f"Lien « {name} » créé.", "success")
    return _back_to_links(year.id)


@planning_bp.route("/planning/share/<int:link_id>/delete", methods=["POST"])
@login_required
def revoke_link(link_id):
    """Supprime un lien : son adresse cesse de fonctionner, ses demandes en
    attente sont libérées, les demi-journées déjà validées restent réservées."""
    link = _own_link_or_404(link_id)
    year_id, name = link.academic_year_id, link.name
    db.session.delete(link)
    db.session.commit()
    flash(f"Lien « {name} » supprimé.", "success")
    return _back_to_links(year_id)


@planning_bp.route("/planning/share/<int:link_id>/requests", methods=["POST"])
@login_required
def answer_requests(link_id):
    """Valide ou refuse les demandes d'un lien : une seule (date + demi-journée
    fournies) ou toutes celles en attente."""
    link = _own_link_or_404(link_id)
    accept = request.form.get("action") == "accept"
    query = PlanningSlot.query.filter_by(link_id=link.id, pending=True)
    if request.form.get("date"):
        key, error = _parse_slot(request.form)
        if error:
            abort(400)
        query = query.filter_by(date=key[0], half=key[1])

    slots = query.all()
    for slot in slots:
        if accept:
            slot.pending = False
        else:
            db.session.delete(slot)
    db.session.commit()
    if slots:
        flash(f"{len(slots)} demande(s) de « {link.name} » "
              f"{'validée(s)' if accept else 'refusée(s)'}.", "success")
    return _back_to_links(link.academic_year_id)


# --------------------------------------------------------------------------- #
# Page publique d'un lien
# --------------------------------------------------------------------------- #
def _link_or_404(token):
    return PlanningLink.query.filter_by(token=token).first() or abort(404)


def _public_cells(link):
    start, end = year_bounds(link.academic_year.label)
    return start, end, cell_states(_slots(link.teacher_id, start, end), viewer=link)


@planning_bp.route("/planning/partage/<token>")
def public_planning(token):
    """Disponibilités et demandes de réservation, sans compte, via le jeton.

    Volontairement hors `login_required` : c'est la page qu'on communique à
    l'extérieur. Elle n'expose que le nom de l'enseignant, l'année, les
    demi-journées occupées et les demandes du client lui-même — aucune classe,
    aucun étudiant, aucune note, ni le nom des autres clients. Le jeton fait
    office de secret : pas de lien, pas d'accès.
    """
    link = _link_or_404(token)
    start, end, cells = _public_cells(link)
    months = planning_months(start, end, cells=cells, counted=(REQUEST, GRANTED))
    return render_template(
        "planning/public.html",
        link=link, teacher=link.teacher, year=link.academic_year, months=months,
        start=start, end=end, reserved=_count(cells, REQUEST, GRANTED),
        has_current=has_current_week(months),
    )


@planning_bp.route("/planning/partage/<token>/etat")
def public_state(token):
    """État courant, interrogé régulièrement par la page publique : une
    demi-journée prise par un autre client s'y ferme sans rechargement."""
    return _state_json(_public_cells(_link_or_404(token))[2])


@planning_bp.route("/planning/partage/<token>/slot", methods=["POST"])
def public_slot(token):
    """Dépose (ou retire) une demande de réservation depuis un lien.

    Le client ne touche qu'aux demi-journées libres et à ses propres demandes
    en attente. Deux clients qui visent la même demi-journée au même instant
    sont départagés par la contrainte d'unicité : le second reçoit un 409.
    """
    link = _link_or_404(token)
    key, error = _parse_slot(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400
    day, half = key
    start, end = year_bounds(link.academic_year.label)
    if not start <= day <= end:
        return jsonify(error="Date hors de l'année partagée."), 400

    taken = "Cette demi-journée n'est plus disponible."
    busy = bool((request.get_json(silent=True) or {}).get("busy"))
    slot = PlanningSlot.query.filter_by(
        teacher_id=link.teacher_id, date=day, half=half).first()
    if slot is not None and slot.link_id != link.id:
        return jsonify(error=taken), 409
    if busy and slot is None:
        if day < date_type.today():
            return jsonify(error="Cette date est passée."), 400
        db.session.add(PlanningSlot(teacher_id=link.teacher_id, date=day,
                                    half=half, link_id=link.id, pending=True))
    elif not busy and slot is not None:
        if not slot.pending:
            return jsonify(error="Cette réservation est déjà confirmée : "
                                 f"contactez {link.teacher.name} pour "
                                 "l'annuler."), 409
        db.session.delete(slot)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error=taken), 409
    return jsonify(ok=True, busy=busy)
