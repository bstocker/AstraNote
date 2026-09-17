"""Planning : demi-journées réservées de l'enseignant et partage en lecture.

Vue de synthèse d'une année académique entière, une ligne par semaine et deux
cellules par jour (matin / après-midi). Cocher une demi-journée la réserve pour
les cours : elle devient « Non disponible ». Un lien public, en lecture seule,
permet de communiquer ces disponibilités à l'extérieur sans donner de compte.
"""
import re
import secrets
from datetime import date as date_type, datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify,
)
from flask_login import login_required, current_user

from .models import (
    db, AcademicYear, PlanningSlot, PlanningShare, HALF_AM, HALF_PM, HALF_DAYS,
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
    return {"week_days": WEEK_DAYS, "halves": HALVES, "half_labels": HALF_DAYS}


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


def planning_months(start, end, busy, today=None):
    """Structure d'affichage : mois -> semaines -> 5 jours × 2 demi-journées.

    `busy` est l'ensemble des couples (date, demi-journée) réservés. Les
    semaines de bord débordent des bornes de l'année : les jours concernés sont
    marqués `in_year=False` et affichés inertes, ce qui garde un tableau
    rectangulaire plutôt qu'une première ligne tronquée.
    """
    today = today or date_type.today()
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
            rows.append({
                "date": day,
                "in_year": in_year,
                "label": f"{WEEK_DAYS[day.weekday()].lower()} {day.day} "
                         f"{MONTHS[day.month - 1]}",
                "is_today": day == today,
                HALF_AM: in_year and (day, HALF_AM) in busy,
                HALF_PM: in_year and (day, HALF_PM) in busy,
            })
        months[-1]["weeks"].append({
            "iso": monday.isocalendar()[1],
            "label": _week_label(monday, days[4]),
            "days": rows,
            "count": sum(1 for d in rows for h in HALVES if d[h]),
            "is_current": days[0] <= today <= days[4],
        })
        monday += timedelta(days=7)
    return months


def _busy_slots(teacher_id, start, end):
    return {
        (s.date, s.half)
        for s in PlanningSlot.query.filter(
            PlanningSlot.teacher_id == teacher_id,
            PlanningSlot.date >= start,
            PlanningSlot.date <= end,
        ).all()
    }


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

    months, start, end, busy = [], None, None, set()
    if year:
        start, end = year_bounds(year.label)
        busy = _busy_slots(current_user.id, start, end)
        months = planning_months(start, end, busy)

    share = None
    if year:
        share = PlanningShare.query.filter_by(
            teacher_id=current_user.id, academic_year_id=year.id).first()

    return render_template(
        "planning/planning.html",
        years=years, year=year, selected_year_id=year_id,
        months=months, start=start, end=end, reserved=len(busy),
        has_current=has_current_week(months), share=share,
    )


@planning_bp.route("/planning/slot", methods=["POST"])
@login_required
def save_slot():
    """Réserve (ou libère) une demi-journée de l'enseignant connecté.

    Une demi-journée réservée existe en base, une demi-journée libre n'existe
    pas : décocher supprime la ligne. L'appel est idempotent, ce qui évite un
    doublon si deux onglets cochent la même case.
    """
    data = request.get_json(silent=True) or {}
    try:
        day = datetime.strptime(str(data.get("date") or ""), "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="Date invalide."), 400

    half = str(data.get("half") or "")
    if half not in HALF_DAYS:
        return jsonify(error="Demi-journée inconnue."), 400
    if day.weekday() >= 5:
        return jsonify(error="Le planning ne couvre que le lundi au vendredi."), 400

    busy = bool(data.get("busy"))
    slot = PlanningSlot.query.filter_by(
        teacher_id=current_user.id, date=day, half=half).first()
    if busy and slot is None:
        db.session.add(PlanningSlot(teacher_id=current_user.id, date=day, half=half))
    elif not busy and slot is not None:
        db.session.delete(slot)
    db.session.commit()
    return jsonify(ok=True, busy=busy)


# --------------------------------------------------------------------------- #
# Partage en lecture seule
# --------------------------------------------------------------------------- #
@planning_bp.route("/planning/share", methods=["POST"])
@login_required
def share_link():
    """Crée le lien public de l'année, ou en régénère le jeton.

    Régénérer invalide le lien déjà diffusé : c'est le seul moyen de couper
    l'accès à quelqu'un sans supprimer le partage pour tout le monde.
    """
    year = _visible_year_or_404(request.form.get("year", type=int))
    share = PlanningShare.query.filter_by(
        teacher_id=current_user.id, academic_year_id=year.id).first()
    if share:
        share.token = secrets.token_urlsafe(32)
        flash("Nouveau lien de partage : l'ancien ne fonctionne plus.", "success")
    else:
        db.session.add(PlanningShare(
            teacher_id=current_user.id, academic_year_id=year.id,
            token=secrets.token_urlsafe(32),
        ))
        flash("Lien de partage créé.", "success")
    db.session.commit()
    return redirect(url_for("planning.view_planning", year=year.id))


@planning_bp.route("/planning/share/delete", methods=["POST"])
@login_required
def revoke_link():
    year = _visible_year_or_404(request.form.get("year", type=int))
    share = PlanningShare.query.filter_by(
        teacher_id=current_user.id, academic_year_id=year.id).first()
    if share:
        db.session.delete(share)
        db.session.commit()
        flash("Lien de partage supprimé.", "success")
    return redirect(url_for("planning.view_planning", year=year.id))


@planning_bp.route("/planning/partage/<token>")
def public_planning(token):
    """Planning en lecture seule, accessible sans compte via le jeton.

    Volontairement hors `login_required` : c'est la page qu'on communique à
    l'extérieur. Elle n'expose que le nom de l'enseignant, l'année et les
    demi-journées occupées — aucune classe, aucun étudiant, aucune note. Le
    jeton fait office de secret : pas de lien, pas d'accès.
    """
    share = PlanningShare.query.filter_by(token=token).first() or abort(404)
    year = share.academic_year
    start, end = year_bounds(year.label)
    busy = _busy_slots(share.teacher_id, start, end)
    months = planning_months(start, end, busy)
    return render_template(
        "planning/public.html",
        teacher=share.teacher, year=year, months=months,
        start=start, end=end, reserved=len(busy),
        has_current=has_current_week(months),
    )
