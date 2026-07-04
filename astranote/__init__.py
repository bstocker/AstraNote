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
        _ensure_admin(app)

    return app


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
