"""AstraNote — application factory.

Suivi et notation des étudiants par étoiles, avec calcul de la note /20 au
prorata (cf. fiche fonctionnelle). Flask + SQLAlchemy + Flask-Login.
"""
import os
import secrets

from flask import Flask, flash, redirect, request, url_for
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash

from config import Config, INSTANCE_DIR
from .models import db, Teacher

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Teacher, int(user_id))


# Ancienne valeur par défaut, publique dans l'historique du dépôt : traitée
# comme une clé absente, où qu'elle ait été recopiée.
LEGACY_SECRET_KEY = "dev-secret-change-me"


def _persistent_secret_key(instance_dir):
    """Clé de session propre à cette installation, générée au premier besoin.

    Sert quand ASTRANOTE_SECRET_KEY n'est pas définie. La clé est tirée au
    hasard puis conservée dans `instance/secret_key` — dossier jamais versionné
    ni écrasé par le déploiement — pour que les sessions survivent aux
    redémarrages. Création exclusive : si deux processus démarrent ensemble,
    le second relit la clé du premier au lieu d'en écrire une autre.
    """
    path = os.path.join(instance_dir, "secret_key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, encoding="ascii") as f:
            key = f.read().strip()
        if key:
            return key
        # Fichier vide (écriture interrompue) : on le remplit.
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key)
    return key


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    if app.config.get("SECRET_KEY") in (None, "", LEGACY_SECRET_KEY):
        app.config["SECRET_KEY"] = _persistent_secret_key(INSTANCE_DIR)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import auth_bp
    from .main import main_bp
    from .modules import modules_bp
    from .planning import planning_bp
    from .billing import billing_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(413)
    def too_large(_err):
        """Fichier trop gros (cf. MAX_CONTENT_LENGTH) : message lisible plutôt
        que la page d'erreur brute de Werkzeug."""
        flash("Fichier trop volumineux : 8 Mo maximum.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    from . import grading

    @app.template_filter("stars_display")
    def stars_display(value):
        return grading.display_token(value)

    @app.template_filter("safe_url")
    def safe_url(value):
        """Lien affichable dans un `href`, ou chaîne vide s'il est douteux.

        Les liens sont contrôlés à la saisie ; ce filtre couvre ceux qui ont
        été enregistrés avant ce contrôle.
        """
        from .main import clean_url
        try:
            return clean_url(value) or ""
        except ValueError:
            return ""

    @app.template_filter("hours")
    def hours(value):
        """Durée en heures telle qu'on l'écrit : « 2 », « 2,5 ».

        Un Float SQLite s'affiche « 2.0 » et « 2.5 » : ni l'un ni l'autre ne
        correspond à ce qu'un enseignant francophone lit sur un emploi du temps.
        """
        if value is None:
            return ""
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")

    with app.app_context():
        db.create_all()
        _run_migrations(app)
        _ensure_admin(app)

    return app


def _run_migrations(app):
    """Migrations légères et idempotentes pour les bases SQLite existantes.

    `db.create_all()` crée les tables manquantes mais n'altère jamais une table
    existante. On ajoute donc à la main les colonnes introduites après coup.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    def add_column_if_missing(table, column, ddl_type):
        if table not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            db.session.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl_type}')
            )
            db.session.commit()
            app.logger.warning("Migration : colonne %s.%s ajoutée.", table, column)

    # Évolution : écoles / années rattachables à un enseignant propriétaire.
    add_column_if_missing("school", "teacher_id", "INTEGER")
    add_column_if_missing("academic_year", "teacher_id", "INTEGER")
    # Évolution : neutralisation d'un étudiant (actif par défaut).
    add_column_if_missing("student", "active", "BOOLEAN NOT NULL DEFAULT 1")
    # Évolution : lien Discord cliquable sur un module.
    add_column_if_missing("module", "discord_url", "VARCHAR(500)")
    # Évolution : second lien Discord (salon de référence).
    add_column_if_missing("module", "discord_ref_url", "VARCHAR(500)")
    # Évolution : suivi de l'envoi des notes à l'établissement.
    add_column_if_missing("module", "notes_sent", "BOOLEAN NOT NULL DEFAULT 0")
    add_column_if_missing("module", "notes_sent_date", "DATE")
    add_column_if_missing("module", "notes_sent_method", "VARCHAR(20)")
    add_column_if_missing("module", "notes_sent_detail", "VARCHAR(200)")
    # Évolution : facturation (école : contacts + observation ; classe : taux horaire).
    add_column_if_missing("school", "billing_emails", "VARCHAR(500)")
    add_column_if_missing("school", "observation", "TEXT")
    add_column_if_missing("class", "hourly_rate", "FLOAT")
    # Évolution : contacts en copie et numéro de contrat de l'école.
    add_column_if_missing("school", "billing_cc_emails", "VARCHAR(500)")
    add_column_if_missing("school", "contract_number", "VARCHAR(100)")
    # Évolution : durée d'une séance en heures.
    add_column_if_missing("grade_date", "duration_hours", "FLOAT")
    # Évolution : facturation des séances et niveau des classes (bilan NDA).
    add_column_if_missing("grade_date", "billing_ref", "VARCHAR(120)")
    add_column_if_missing("class", "level", "VARCHAR(60)")
    # Évolution : demandes de réservation déposées depuis un lien de partage.
    add_column_if_missing("planning_slot", "link_id", "INTEGER")
    add_column_if_missing("planning_slot", "pending", "BOOLEAN NOT NULL DEFAULT 0")

    # Évolution : plusieurs liens nommés par année. L'ancienne table portait
    # une contrainte « un lien par enseignant et par année » que SQLite ne sait
    # pas retirer : ses liens sont repris dans la nouvelle, jeton inchangé pour
    # que les adresses déjà diffusées continuent de fonctionner.
    if "planning_share" in inspector.get_table_names():
        moved = db.session.execute(text(
            "INSERT INTO planning_link"
            " (teacher_id, academic_year_id, token, name, color, created_at)"
            " SELECT teacher_id, academic_year_id, token, 'Lien de partage',"
            " '#fde68a', created_at FROM planning_share"
            " WHERE token NOT IN (SELECT token FROM planning_link)"
        )).rowcount
        db.session.execute(text("DROP TABLE planning_share"))
        db.session.commit()
        app.logger.warning(
            "Migration : %s lien(s) de partage repris dans planning_link.", moved)

    # Réparation : étudiants sans aucune inscription. Avant
    # `purge_orphan_students`, supprimer une classe laissait leurs fiches en
    # base. Placée avant la réparation suivante, qui balaie leurs affectations.
    if "student" in inspector.get_table_names():
        from .main import purge_orphan_students
        removed = purge_orphan_students()
        db.session.commit()
        if removed:
            app.logger.warning(
                "Migration : %s étudiant(s) sans inscription supprimé(s).", removed)

    # Réparation : affectations de groupe pointant vers un étudiant supprimé.
    # Avant la cascade `Student.group_memberships`, retirer un étudiant de sa
    # dernière classe laissait ces lignes derrière lui, et la grille du module
    # en groupe répondait alors 500.
    if "group_member" in inspector.get_table_names():
        removed = db.session.execute(text(
            "DELETE FROM group_member WHERE student_id NOT IN"
            " (SELECT id FROM student)"
        )).rowcount
        db.session.commit()
        if removed:
            app.logger.warning(
                "Migration : %s affectation(s) de groupe orpheline(s) supprimée(s).",
                removed,
            )


def _ensure_admin(app):
    """Crée le compte administrateur au premier démarrage s'il n'existe pas."""
    email = app.config["ADMIN_EMAIL"]
    if Teacher.query.filter_by(email=email).first():
        return

    password = app.config.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    admin = Teacher(
        name="Administrateur",
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
    )
    db.session.add(admin)
    db.session.commit()

    banner = (
        "\n" + "=" * 62 + "\n"
        "  AstraNote — compte administrateur créé\n"
        f"  Email    : {email}\n"
        f"  Password : {password}\n"
        "  (Modifiable via la variable ASTRANOTE_ADMIN_PASSWORD)\n"
        + "=" * 62 + "\n"
    )
    app.logger.warning(banner)
    print(banner)
