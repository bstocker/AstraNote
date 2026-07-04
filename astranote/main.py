"""Structure (écoles, années, classes), étudiants, recherche, tableau de bord.

Cloisonnement des droits (fiche §4) : un enseignant ne voit que *ses* classes ;
l'administrateur voit toute la base.
"""
import unicodedata

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, abort,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from .models import (
    db, School, AcademicYear, Class, Module, Student, Enrollment, Teacher,
    Star, UrlValue, NoteValue, SUBJECT_STUDENT, SUBJECT_GROUP,
)

main_bp = Blueprint("main", __name__)


# --------------------------------------------------------------------------- #
# Nettoyage des données orphelines
# --------------------------------------------------------------------------- #
def purge_subject_data(subject_type, subject_id,
                       star_col_ids=None, url_col_ids=None, note_col_ids=None):
    """Supprime les étoiles / notes / liens d'un sujet (étudiant ou groupe).

    Ces tables référencent `subject_id` sans clé étrangère : sans ce nettoyage,
    supprimer un étudiant/groupe laisserait des lignes orphelines. Si une liste
    de colonnes est fournie, on se limite à celles-ci ; sinon on purge tout.
    """
    def _delete(model, col_attr, col_ids):
        q = model.query.filter_by(subject_type=subject_type, subject_id=subject_id)
        if col_ids is not None:
            q = q.filter(col_attr.in_(col_ids or [0]))
        q.delete(synchronize_session=False)

    _delete(Star, Star.star_column_id, star_col_ids)
    _delete(UrlValue, UrlValue.url_column_id, url_col_ids)
    _delete(NoteValue, NoteValue.note_column_id, note_col_ids)


def _class_column_ids(klass):
    """Colonnes (étoiles, URL, notes) de tous les modules d'une classe."""
    star_ids, url_ids, note_ids = [], [], []
    for m in klass.modules:
        note_ids += [nc.id for nc in m.note_columns]
        for gd in m.grade_dates:
            star_ids += [sc.id for sc in gd.star_columns]
            url_ids += [uc.id for uc in gd.url_columns]
    return star_ids, url_ids, note_ids


# --------------------------------------------------------------------------- #
# Helpers de périmètre / droits
# --------------------------------------------------------------------------- #
def visible_classes_query():
    """Classes visibles par l'utilisateur courant (toutes si admin)."""
    q = Class.query
    if not current_user.is_admin:
        q = q.filter(Class.teacher_id == current_user.id)
    return q


def get_class_or_403(class_id):
    klass = db.session.get(Class, class_id) or abort(404)
    if not current_user.is_admin and klass.teacher_id != current_user.id:
        abort(403)
    return klass


def visible_schools_query():
    """Écoles visibles : les siennes + les communes (admin) ; tout si admin."""
    q = School.query
    if not current_user.is_admin:
        q = q.filter(or_(School.teacher_id == current_user.id,
                         School.teacher_id.is_(None)))
    return q.order_by(School.name)


def visible_years_query():
    q = AcademicYear.query
    if not current_user.is_admin:
        q = q.filter(or_(AcademicYear.teacher_id == current_user.id,
                         AcademicYear.teacher_id.is_(None)))
    return q.order_by(AcademicYear.label.desc())


def can_manage_owned(obj):
    """Vrai si l'utilisateur peut modifier/supprimer une école/année.

    L'admin gère tout ; un enseignant uniquement ce qu'il possède (pas les
    entités communes, teacher_id NULL).
    """
    return current_user.is_admin or obj.teacher_id == current_user.id


def strip_accents(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# --------------------------------------------------------------------------- #
# Tableau de bord
# --------------------------------------------------------------------------- #
@main_bp.route("/")
@login_required
def dashboard():
    years = visible_years_query().all()

    # Année sélectionnée : celle de l'URL si valide, sinon la plus récente.
    selected_year_id = request.args.get("year", type=int)
    valid_year_ids = {y.id for y in years}
    if selected_year_id not in valid_year_ids:
        selected_year_id = years[0].id if years else None

    # Classes visibles de l'année choisie, regroupées par école.
    groups = []
    if selected_year_id:
        classes = (
            visible_classes_query()
            .filter(Class.academic_year_id == selected_year_id)
            .all()
        )
        by_school = {}
        for c in classes:
            by_school.setdefault(c.school, []).append(c)
        groups = [
            (school, sorted(cls, key=lambda c: c.name.lower()))
            for school, cls in sorted(by_school.items(), key=lambda kv: kv[0].name.lower())
        ]

    stats = {c.id: class_saisie_progress(c)
             for _, cls in groups for c in cls}

    return render_template(
        "dashboard.html", years=years, groups=groups,
        selected_year_id=selected_year_id, stats=stats,
    )


def class_saisie_progress(klass):
    """Avancement de saisie d'une classe : % de cellules d'étoiles remplies.

    Une cellule = un sujet (étudiant actif ou groupe) × une colonne d'étoiles.
    Retourne None si aucune cellule possible (aucune colonne / aucun sujet).
    """
    total, filled = 0, 0
    for module in klass.modules:
        star_col_ids = [sc.id for gd in module.grade_dates for sc in gd.star_columns]
        if module.is_group_mode:
            subj_count = len(module.groups)
            stype = SUBJECT_GROUP
        else:
            subj_count = sum(1 for e in klass.enrollments if e.student.active)
            stype = SUBJECT_STUDENT
        total += subj_count * len(star_col_ids)
        if star_col_ids and subj_count:
            filled += Star.query.filter(
                Star.subject_type == stype,
                Star.star_column_id.in_(star_col_ids)).count()
    if total == 0:
        return None
    return round(100 * min(filled, total) / total)


# --------------------------------------------------------------------------- #
# Écoles & années
# Chaque enseignant gère les siennes ; l'admin gère tout. Les entités créées
# par l'admin (teacher_id NULL) sont communes et visibles par tous (fiche §4).
# --------------------------------------------------------------------------- #
def _owner_id_for_new():
    """Propriétaire d'une entité nouvellement créée : l'enseignant, ou NULL
    (commune) si c'est l'admin."""
    return None if current_user.is_admin else current_user.id


@main_bp.route("/schools", methods=["GET", "POST"])
@login_required
def schools():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            db.session.add(School(name=name, teacher_id=_owner_id_for_new()))
            db.session.commit()
            flash("École ajoutée.", "success")
        return redirect(url_for("main.schools"))

    schools = visible_schools_query().all()
    years = visible_years_query().all()
    return render_template("structure/schools.html", schools=schools, years=years)


@main_bp.route("/schools/<int:school_id>/delete", methods=["POST"])
@login_required
def delete_school(school_id):
    school = db.session.get(School, school_id) or abort(404)
    if not can_manage_owned(school):
        abort(403)
    db.session.delete(school)
    db.session.commit()
    flash("École supprimée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/schools/<int:school_id>/rename", methods=["POST"])
@login_required
def rename_school(school_id):
    school = db.session.get(School, school_id) or abort(404)
    if not can_manage_owned(school):
        abort(403)
    name = request.form.get("name", "").strip()
    if name:
        school.name = name
        db.session.commit()
        flash("École renommée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/schools/<int:school_id>/details", methods=["POST"])
@login_required
def update_school_details(school_id):
    """Contacts de facturation (emails) et observation libre d'une école."""
    school = db.session.get(School, school_id) or abort(404)
    if not can_manage_owned(school):
        abort(403)
    school.billing_emails = request.form.get("billing_emails", "").strip() or None
    school.observation = request.form.get("observation", "").strip() or None
    db.session.commit()
    flash("Informations de facturation de l'école enregistrées.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/years", methods=["POST"])
@login_required
def create_year():
    label = request.form.get("label", "").strip()
    if label:
        db.session.add(AcademicYear(label=label, teacher_id=_owner_id_for_new()))
        db.session.commit()
        flash("Année académique ajoutée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/years/<int:year_id>/rename", methods=["POST"])
@login_required
def rename_year(year_id):
    year = db.session.get(AcademicYear, year_id) or abort(404)
    if not can_manage_owned(year):
        abort(403)
    label = request.form.get("label", "").strip()
    if label:
        year.label = label
        db.session.commit()
        flash("Année renommée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/years/<int:year_id>/delete", methods=["POST"])
@login_required
def delete_year(year_id):
    year = db.session.get(AcademicYear, year_id) or abort(404)
    if not can_manage_owned(year):
        abort(403)
    db.session.delete(year)
    db.session.commit()
    flash("Année supprimée.", "success")
    return redirect(url_for("main.schools"))


# --------------------------------------------------------------------------- #
# Classes
# --------------------------------------------------------------------------- #
@main_bp.route("/classes/new", methods=["GET", "POST"])
@login_required
def create_class():
    schools = visible_schools_query().all()
    years = visible_years_query().all()
    teachers = Teacher.query.order_by(Teacher.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        school_id = request.form.get("school_id", type=int)
        year_id = request.form.get("academic_year_id", type=int)
        # Un enseignant crée pour lui-même ; l'admin peut choisir.
        teacher_id = (
            request.form.get("teacher_id", type=int)
            if current_user.is_admin else current_user.id
        )
        # L'école / l'année choisies doivent être dans le périmètre visible
        # (empêche de rattacher une classe à une entité d'un autre enseignant).
        visible_school_ids = {s.id for s in schools}
        visible_year_ids = {y.id for y in years}
        if school_id not in visible_school_ids or year_id not in visible_year_ids:
            flash("École ou année invalide.", "error")
        elif not (name and school_id and year_id and teacher_id):
            flash("Tous les champs sont requis.", "error")
        else:
            klass = Class(
                name=name, school_id=school_id,
                academic_year_id=year_id, teacher_id=teacher_id,
            )
            db.session.add(klass)
            db.session.commit()
            flash("Classe créée.", "success")
            return redirect(url_for("main.view_class", class_id=klass.id))

    if not schools or not years:
        flash("Créez d'abord au moins une école et une année académique.", "error")

    return render_template(
        "structure/class_form.html", schools=schools, years=years, teachers=teachers,
    )


@main_bp.route("/classes/<int:class_id>")
@login_required
def view_class(class_id):
    klass = get_class_or_403(class_id)
    return render_template("structure/class_detail.html", klass=klass)


@main_bp.route("/classes/<int:class_id>/billing", methods=["POST"])
@login_required
def update_class_billing(class_id):
    """Taux horaire €/h de la classe (pour la facturation)."""
    klass = get_class_or_403(class_id)
    raw = request.form.get("hourly_rate", "").strip().replace(",", ".")
    if raw == "":
        klass.hourly_rate = None
    else:
        try:
            rate = float(raw)
            if rate < 0:
                raise ValueError
        except ValueError:
            flash("Taux horaire invalide.", "error")
            return redirect(url_for("main.view_class", class_id=class_id))
        klass.hourly_rate = rate
    db.session.commit()
    flash("Taux horaire enregistré.", "success")
    return redirect(url_for("main.view_class", class_id=class_id))


@main_bp.route("/classes/<int:class_id>/delete", methods=["POST"])
@login_required
def delete_class(class_id):
    klass = get_class_or_403(class_id)
    db.session.delete(klass)
    db.session.commit()
    flash("Classe supprimée.", "success")
    return redirect(url_for("main.dashboard"))


# --------------------------------------------------------------------------- #
# Étudiants (inscription dans une classe)
# --------------------------------------------------------------------------- #
@main_bp.route("/classes/<int:class_id>/students", methods=["POST"])
@login_required
def add_student(class_id):
    klass = get_class_or_403(class_id)
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Le nom de l'étudiant est requis.", "error")
        return redirect(url_for("main.view_class", class_id=class_id))

    email = request.form.get("email", "").strip()
    discord = request.form.get("discord_alias", "").strip()
    github = request.form.get("github_url", "").strip()

    student = Student(
        full_name=full_name, email=email or None,
        discord_alias=discord or None, github_url=github or None,
    )
    db.session.add(student)
    db.session.flush()
    db.session.add(Enrollment(student_id=student.id, class_id=klass.id))
    db.session.commit()
    flash("Étudiant ajouté.", "success")
    return redirect(url_for("main.view_class", class_id=class_id))


@main_bp.route("/enrollments/<int:enrollment_id>/student", methods=["POST"])
@login_required
def edit_student(enrollment_id):
    """Modifie les caractéristiques de l'étudiant (nom, email, Discord, GitHub).

    Ces champs sont propres à l'étudiant : la modification vaut pour toutes ses
    classes. L'accès est contrôlé via l'inscription (donc via la classe).
    """
    enr = db.session.get(Enrollment, enrollment_id) or abort(404)
    get_class_or_403(enr.class_id)
    student = enr.student

    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Le nom de l'étudiant est requis.", "error")
        return redirect(url_for("main.view_class", class_id=enr.class_id))

    student.full_name = full_name
    student.email = request.form.get("email", "").strip() or None
    student.discord_alias = request.form.get("discord_alias", "").strip() or None
    student.github_url = request.form.get("github_url", "").strip() or None
    db.session.commit()
    flash("Étudiant mis à jour.", "success")
    return redirect(url_for("main.view_class", class_id=enr.class_id))


@main_bp.route("/enrollments/<int:enrollment_id>/toggle-active", methods=["POST"])
@login_required
def toggle_student_active(enrollment_id):
    """Neutralise / réactive un étudiant (a quitté l'école).

    Neutralisé : grisé dans les modules et exclu du calcul du prorata. Ses
    étoiles sont conservées ; l'opération est réversible.
    """
    enr = db.session.get(Enrollment, enrollment_id) or abort(404)
    get_class_or_403(enr.class_id)
    student = enr.student
    student.active = not student.active
    db.session.commit()
    flash(
        "Étudiant neutralisé." if not student.active else "Étudiant réactivé.",
        "success",
    )
    return redirect(url_for("main.view_class", class_id=enr.class_id))


@main_bp.route("/enrollments/<int:enrollment_id>/comment", methods=["POST"])
@login_required
def update_comment(enrollment_id):
    enr = db.session.get(Enrollment, enrollment_id) or abort(404)
    get_class_or_403(enr.class_id)
    enr.general_comment = request.form.get("general_comment", "").strip() or None
    db.session.commit()
    flash("Commentaire enregistré.", "success")
    return redirect(request.referrer or url_for("main.view_class", class_id=enr.class_id))


@main_bp.route("/enrollments/<int:enrollment_id>/delete", methods=["POST"])
@login_required
def remove_student(enrollment_id):
    enr = db.session.get(Enrollment, enrollment_id) or abort(404)
    klass = get_class_or_403(enr.class_id)
    student = enr.student

    # Purge les étoiles/notes/liens de l'étudiant dans les modules de cette classe.
    star_ids, url_ids, note_ids = _class_column_ids(klass)
    purge_subject_data(SUBJECT_STUDENT, student.id, star_ids, url_ids, note_ids)

    if len(student.enrollments) <= 1:
        # Dernier rattachement : purge résiduelle puis suppression de l'étudiant
        # (la suppression de l'étudiant supprime l'inscription en cascade).
        purge_subject_data(SUBJECT_STUDENT, student.id)
        db.session.delete(student)
    else:
        db.session.delete(enr)
    db.session.commit()
    flash("Étudiant retiré de la classe.", "success")
    return redirect(url_for("main.view_class", class_id=klass.id))


# --------------------------------------------------------------------------- #
# Recherche globale d'étudiant (fiche §5.10)
# --------------------------------------------------------------------------- #
@main_bp.route("/search")
@login_required
def search():
    raw = request.args.get("q", "").strip()
    results = []
    if raw:
        needle = strip_accents(raw)
        # Pré-filtre SQL large (insensible à la casse), puis filtre accents en Python.
        like = f"%{raw}%"
        candidates = (
            Student.query
            .join(Enrollment, Enrollment.student_id == Student.id)
            .join(Class, Class.id == Enrollment.class_id)
        )
        if not current_user.is_admin:
            candidates = candidates.filter(Class.teacher_id == current_user.id)
        candidates = candidates.filter(
            or_(Student.full_name.ilike(like), Student.email.ilike(like),
                Student.discord_alias.ilike(like))
        ).distinct().all()

        for student in candidates:
            if needle not in strip_accents(student.full_name):
                # Vérifie aussi email / discord sans accents.
                blob = strip_accents(
                    f"{student.email or ''} {student.discord_alias or ''}"
                )
                if needle not in blob:
                    continue
            # Rattachements visibles seulement.
            rows = []
            for enr in student.enrollments:
                klass = enr.klass
                if not current_user.is_admin and klass.teacher_id != current_user.id:
                    continue
                rows.append({
                    "class": klass,
                    "school": klass.school,
                    "year": klass.academic_year,
                    "modules": klass.modules,
                })
            if rows:
                results.append({"student": student, "rows": rows})

    return render_template("search.html", query=raw, results=results)
