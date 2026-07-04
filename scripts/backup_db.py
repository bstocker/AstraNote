#!/usr/bin/env python3
"""Sauvegarde horodatée de la base SQLite d'AstraNote.

À planifier comme tâche quotidienne sur PythonAnywhere (onglet « Tasks ») :

    python3 /home/astranote/mysite/scripts/backup_db.py

Utilise l'API `backup` de SQLite (copie cohérente même si l'application écrit)
et conserve les 14 dernières sauvegardes dans ~/astranote-backups/.
Le chemin de la base peut être fixé via la variable ASTRANOTE_DB_FILE.
"""
import glob
import os
import sqlite3
from datetime import datetime

DB = os.environ.get(
    "ASTRANOTE_DB_FILE", os.path.expanduser("~/astranote-data/astranote.db")
)
DEST = os.path.expanduser("~/astranote-backups")
KEEP = 14


def main():
    if not os.path.exists(DB):
        print("Base introuvable :", DB)
        return
    os.makedirs(DEST, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(DEST, f"astranote-{stamp}.db")

    src = sqlite3.connect(DB)
    dst = sqlite3.connect(out)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print("Sauvegarde créée :", out)

    # Rotation : ne garder que les KEEP plus récentes.
    backups = sorted(glob.glob(os.path.join(DEST, "astranote-*.db")))
    for old in backups[:-KEEP]:
        os.remove(old)
        print("Ancienne sauvegarde supprimée :", old)


if __name__ == "__main__":
    main()
