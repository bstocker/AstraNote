"""Configuration de l'application AstraNote.

Les valeurs sensibles (SECRET_KEY) sont lues depuis l'environnement pour ne
jamais figer de secret dans le dépôt. En local, des valeurs par défaut sûres
sont fournies pour un démarrage immédiat.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("ASTRANOTE_SECRET_KEY", "dev-secret-change-me")

    # Base SQLite (fichier unique, simple à sauvegarder — cf. fiche §7).
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "ASTRANOTE_DATABASE_URI",
        "sqlite:///" + os.path.join(INSTANCE_DIR, "astranote.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Identifiants du compte administrateur créé au premier démarrage.
    ADMIN_EMAIL = os.environ.get("ASTRANOTE_ADMIN_EMAIL", "admin@astranote.local")
    ADMIN_PASSWORD = os.environ.get("ASTRANOTE_ADMIN_PASSWORD")  # None => généré
