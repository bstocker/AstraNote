"""AstraNote — application factory.

Suivi et notation des étudiants par étoiles, avec calcul de la note /20 au
prorata (cf. fiche fonctionnelle). Flask + SQLAlchemy + Flask-Login.
"""
import os
import secrets

from flask import Flask
from flask_login import LoginManager
from werkzeug.security import generate_password_hash

from config import Config, INSTANCE_DIR
from .models import db, Teacher

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Teacher, int(user_id))


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    os.makedirs(INSTANCE_DIR, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .auth import auth_bp
    from .main import main_bp
    from .modules import modules_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(modules_bp)

    from . import grading

    @app.template_filter("stars_display")
    def stars_display(value):
        return grading.display_token(value)

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
