# AstraNote

**Suivi et notation des étudiants** — application web Flask qui remplace les
fichiers Excel de notation par étoiles. Voir la
[fiche fonctionnelle](AstraNote_Fiche_Fonctionnelle.md) pour le détail métier.

Chaque séance, l'enseignant attribue des **étoiles** (0 à 4) par exercice.
L'application calcule automatiquement une **note /20 au prorata** (le meilleur
total = 20/20, les autres proportionnellement, arrondi au 0,5). Les notes
finales restent saisies à la main par l'enseignant.

## Fonctionnalités (MVP v1)

- Authentification enseignants (Flask-Login, hash Werkzeug) ; comptes créés par l'admin.
- Structure **École › Année académique › Classe › Module**. Chaque enseignant gère
  ses propres écoles/années (visibles de lui seul) ; celles créées par l'admin sont
  communes (visibles par tous).
- Modules **individuels** ou **en groupe**.
- Grille de saisie : **dates**, **colonnes d'étoiles** (ajoutables à tout moment),
  **colonnes URL**, **colonnes de note manuelles** (« Note CC », « Note Examen »…).
- Statuts spéciaux (ABS, Retard, Pas de PC…) affichés en couleur, valant 0 étoile.
- Calcul automatique de la **note /20 au prorata** (règles R1–R9), recalcul en direct.
- Commentaire général par étudiant / par groupe.
- **Recherche globale** d'étudiant (insensible casse/accents), respectant les droits.

## Démarrage local

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

L'application démarre sur http://127.0.0.1:5000. Au **premier lancement**, un
compte administrateur est créé et ses identifiants sont **affichés dans la
console** (email `admin@astranote.local`, mot de passe généré).

### Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `ASTRANOTE_SECRET_KEY` | Clé de session Flask (à définir en prod) | `dev-secret-change-me` |
| `ASTRANOTE_DATABASE_URI` | URI SQLAlchemy | `sqlite:///instance/astranote.db` |
| `ASTRANOTE_ADMIN_EMAIL` | Email de l'admin initial | `admin@astranote.local` |
| `ASTRANOTE_ADMIN_PASSWORD` | Mot de passe admin initial | généré aléatoirement |

## Structure du projet

```
config.py              Configuration (env vars)
run.py                 Point d'entrée local
wsgi.py                Point d'entrée WSGI (PythonAnywhere)
astranote/
  __init__.py          App factory + création admin
  models.py            Modèle de données (14 tables SQLite)
  grading.py           Calcul du prorata /20 (règles R1–R9)
  auth.py              Login / logout / comptes enseignants
  main.py              Structure, étudiants, recherche, dashboard
  modules.py           Grille, dates, colonnes, groupes, saisie AJAX
  templates/           Jinja2
  static/              CSS + JS de la grille
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

La suite couvre l'authentification/CSRF, le prorata (R1–R10), la neutralisation,
le périmètre écoles/années, le nettoyage des orphelins, le renommage/réordonnancement
des colonnes, l'édition de module et l'export/import Excel.

## Déploiement (PythonAnywhere)

Le workflow `.github/workflows/CICD.yml` lance d'abord les **tests** (job `test`)
puis, seulement s'ils passent, uploade le code sur PythonAnywhere et recharge la
webapp. Il **exclut** la base SQLite et le dossier `instance/` pour ne pas
écraser les données de production.

Secrets GitHub requis : `PA_USERNAME`, `PA_TOKEN`, `PA_TARGET_DIR`,
`PA_WEBAPP_DOMAIN` (et `PA_HOST` si compte EU). Sur PythonAnywhere, pointez le
fichier WSGI vers `wsgi.py` (variable `application`) et définissez
`ASTRANOTE_SECRET_KEY`.

> ⚠️ Le déploiement copie les fichiers mais **n'installe pas** les dépendances.
> Après un changement de `requirements.txt` (ex. ajout de Flask-WTF), lancez une
> fois dans une console PythonAnywhere : `pip install --user -r <TARGET_DIR>/requirements.txt`,
> puis **Reload**. Vous pouvez aussi en faire une tâche planifiée (onglet *Tasks*).

## Sauvegarde de la base

`scripts/backup_db.py` crée une copie horodatée de la base SQLite (via l'API
`backup` de SQLite, cohérente même en écriture) et conserve les 14 dernières.
À planifier en tâche quotidienne sur PythonAnywhere :

```bash
python3 /home/astranote/mysite/scripts/backup_db.py
```

## Roadmap (v2, cf. fiche §8)

- Export Excel / CSV (openpyxl est déjà dans les dépendances).
- Duplication d'une classe d'une année sur l'autre.
- Statistiques du tableau de bord.
