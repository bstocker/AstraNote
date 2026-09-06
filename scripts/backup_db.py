#!/usr/bin/env python3
"""Sauvegarde horodatée de la base SQLite d'AstraNote.

À planifier comme tâche quotidienne sur PythonAnywhere (onglet « Tasks ») :

    python3 /home/astranote/mysite/scripts/backup_db.py

Utilise l'API `backup` de SQLite (copie cohérente même si l'application écrit)
et conserve les 14 dernières sauvegardes dans ~/astranote-backups/.

Le chemin de la base est **déduit de la configuration de l'application**, et
peut être forcé via ASTRANOTE_DB_FILE. En cas d'échec, le script sort en code
non nul : une tâche planifiée qui ne sauvegarde rien doit se voir.
"""
import glob
import os
import sqlite3
import sys
from datetime import datetime

# Le script vit dans scripts/ : il faut le dossier du projet dans le chemin
# d'import pour lire config.py, seule source de vérité du chemin de la base.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from config import Config  # noqa: E402

# Destination surchargeable : permet de viser un autre disque, et rend le
# script testable sans écrire dans le dossier personnel.
DEST = os.path.expanduser(
    os.environ.get("ASTRANOTE_BACKUP_DIR", "~/astranote-backups")
)
KEEP = 14


def database_path():
    """Fichier SQLite à sauvegarder, ou None s'il n'y en a pas.

    Dérivé de `Config` plutôt que codé en dur : la sauvegarde suit ainsi
    automatiquement ASTRANOTE_DATABASE_URI et ne peut plus viser un fichier que
    l'application n'utilise pas — c'était le cas du chemin fixe précédent, qui
    faisait échouer la tâche planifiée en silence.
    """
    forced = os.environ.get("ASTRANOTE_DB_FILE")
    if forced:
        return os.path.abspath(os.path.expanduser(forced))

    from sqlalchemy.engine import make_url

    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if url.get_backend_name() != "sqlite":
        return None
    if not url.database or url.database == ":memory:":
        return None
    return os.path.abspath(url.database)


def backup(db_path, out):
    """Copie cohérente de `db_path` vers `out` (API backup de SQLite).

    En cas d'échec, le fichier partiel est retiré : laissé en place, il
    passerait pour une sauvegarde valide et la rotation finirait par lui faire
    évincer une bonne sauvegarde.
    """
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(out)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    except BaseException:
        if os.path.exists(out):
            os.remove(out)
        raise
    finally:
        src.close()


def main():
    db_path = database_path()
    if not db_path:
        print("Aucune base SQLite à sauvegarder "
              f"(ASTRANOTE_DATABASE_URI = {Config.SQLALCHEMY_DATABASE_URI}).",
              file=sys.stderr)
        return 1
    if not os.path.exists(db_path):
        print(f"Base introuvable : {db_path}\n"
              "Vérifiez ASTRANOTE_DATABASE_URI, ou forcez le chemin avec "
              "ASTRANOTE_DB_FILE.", file=sys.stderr)
        return 1

    os.makedirs(DEST, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(DEST, f"astranote-{stamp}.db")

    try:
        backup(db_path, out)
    except (sqlite3.Error, OSError) as err:
        print(f"Échec de la sauvegarde de {db_path} : {err}", file=sys.stderr)
        return 1
    print("Sauvegarde créée :", out)

    # Rotation : ne garder que les KEEP plus récentes. N'est atteinte qu'après
    # une sauvegarde réussie, pour ne jamais purger sur un échec.
    for old in sorted(glob.glob(os.path.join(DEST, "astranote-*.db")))[:-KEEP]:
        os.remove(old)
        print("Ancienne sauvegarde supprimée :", old)
    return 0


if __name__ == "__main__":
    sys.exit(main())
