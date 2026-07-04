"""Authentification (Flask-Login) et création de comptes enseignants.

Connexion email / mot de passe (hash Werkzeug). Les comptes enseignants sont
créés par l'administrateur (fiche §4, §5.1).
"""
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, abort,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from .models import db, Teacher

auth_bp = Blueprint("auth", __name__)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        teacher = Teacher.query.filter_by(email=email).first()
        if teacher and check_password_hash(teacher.password_hash, password):
            login_user(teacher)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.dashboard"))
        flash("Email ou mot de passe incorrect.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    """Page « Mon compte » : changement de mot de passe self-service."""
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(current_user.password_hash, current):
            flash("Mot de passe actuel incorrect.", "error")
        elif len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "error")
        elif new != confirm:
            flash("La confirmation ne correspond pas au nouveau mot de passe.", "error")
        else:
            current_user.password_hash = generate_password_hash(new)
            db.session.commit()
            flash("Mot de passe mis à jour.", "success")
            return redirect(url_for("auth.account"))
    return render_template("auth/account.html")


@auth_bp.route("/teachers")
@admin_required
def teachers():
    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template("auth/teachers.html", teachers=teachers)


@auth_bp.route("/teachers/new", methods=["POST"])
@admin_required
def create_teacher():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "teacher")

    if not (name and email and password):
        flash("Nom, email et mot de passe sont requis.", "error")
        return redirect(url_for("auth.teachers"))
    if Teacher.query.filter_by(email=email).first():
        flash("Un compte existe déjà avec cet email.", "error")
        return redirect(url_for("auth.teachers"))

    db.session.add(Teacher(
        name=name, email=email, role=role,
        password_hash=generate_password_hash(password),
    ))
    db.session.commit()
    flash(f"Compte enseignant créé : {email}", "success")
    return redirect(url_for("auth.teachers"))


@auth_bp.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@admin_required
def delete_teacher(teacher_id):
    teacher = db.session.get(Teacher, teacher_id) or abort(404)
    if teacher.id == current_user.id:
        flash("Vous ne pouvez pas supprimer votre propre compte.", "error")
        return redirect(url_for("auth.teachers"))
    if teacher.classes:
        flash("Impossible : cet enseignant a encore des classes rattachées.", "error")
        return redirect(url_for("auth.teachers"))
    db.session.delete(teacher)
    db.session.commit()
    flash("Compte supprimé.", "success")
    return redirect(url_for("auth.teachers"))
