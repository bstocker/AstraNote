"""Point d'entrée WSGI pour PythonAnywhere.

Dans l'onglet "Web" de PythonAnywhere, pointez le fichier WSGI vers ce module
et exposez la variable `application`. Les variables d'environnement
ASTRANOTE_SECRET_KEY et ASTRANOTE_ADMIN_* sont facultatives (cf. README).
"""
import os
import sys

# Ajoute le dossier du projet au chemin d'import (adapter si besoin sur PA).
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from astranote import create_app  # noqa: E402

application = create_app()
