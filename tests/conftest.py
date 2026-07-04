"""Fixtures pytest pour AstraNote : app de test (SQLite en mémoire, CSRF off)."""
import os

import pytest

# Doit être défini avant l'import de l'app (utilisé au démarrage).
os.environ.setdefault("ASTRANOTE_ADMIN_PASSWORD", "test-admin-pw")

from config import Config  # noqa: E402
from astranote import create_app  # noqa: E402
from astranote.models import (  # noqa: E402,F401
    db, School, AcademicYear, Class, Module, Student, Enrollment,
    GradeDate, StarColumn, NoteColumn, Group, Star, NoteValue, Teacher,
)

ADMIN_PW = "test-admin-pw"


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    ADMIN_PASSWORD = ADMIN_PW


@pytest.fixture
def app():
    return create_app(TestConfig)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    """Client connecté en administrateur."""
    client.post("/login", data={"email": "admin@astranote.local", "password": ADMIN_PW})
    return client


def make_teacher(app, name, email, pw="pw123456", role="teacher"):
    from werkzeug.security import generate_password_hash
    with app.app_context():
        t = Teacher(name=name, email=email, role=role,
                    password_hash=generate_password_hash(pw))
        db.session.add(t)
        db.session.commit()
        return t.id


def login(client, email, pw="pw123456"):
    return client.post("/login", data={"email": email, "password": pw})
