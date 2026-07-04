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
)
from .auth import admin_required

main_bp = Blueprint("main", __name__)


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


def strip_accents(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# --------------------------------------------------------------------------- #
# Tableau de bord
# --------------------------------------------------------------------------- #
@main_bp.route("/")
@login_required
def dashboard():
    classes = visible_classes_query().all()
    schools = School.query.order_by(School.name).all()
    years = AcademicYear.query.order_by(AcademicYear.label.desc()).all()
    return render_template(
        "dashboard.html", classes=classes, schools=schools, years=years,
    )


# --------------------------------------------------------------------------- #
# Écoles & années (gérées par l'administrateur — fiche §4)
# --------------------------------------------------------------------------- #
@main_bp.route("/schools", methods=["GET", "POST"])
@admin_required
def schools():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            db.session.add(School(name=name))
            db.session.commit()
            flash("École ajoutée.", "success")
        return redirect(url_for("main.schools"))

    schools = School.query.order_by(School.name).all()
    years = AcademicYear.query.order_by(AcademicYear.label.desc()).all()
    return render_template("structure/schools.html", schools=schools, years=years)


@main_bp.route("/schools/<int:school_id>/delete", methods=["POST"])
@admin_required
def delete_school(school_id):
    school = db.session.get(School, school_id) or abort(404)
    db.session.delete(school)
    db.session.commit()
    flash("École supprimée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/years", methods=["POST"])
@admin_required
def create_year():
    label = request.form.get("label", "").strip()
    if label:
        db.session.add(AcademicYear(label=label))
        db.session.commit()
        flash("Année académique ajoutée.", "success")
    return redirect(url_for("main.schools"))


@main_bp.route("/years/<int:year_id>/delete", methods=["POST"])
@admin_required
def delete_year(year_id):
    year = db.session.get(AcademicYear, year_id) or abort(404)
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
    schools = School.query.order_by(School.name).all()
    years = AcademicYear.query.order_by(AcademicYear.label.desc()).all()
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
        if not (name and school_id and year_id and teacher_id):
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
    db.session.delete(enr)
    # Supprime l'étudiant s'il n'est plus inscrit nulle part.
    if student and len(student.enrollments) <= 1:
        db.session.delete(student)
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
