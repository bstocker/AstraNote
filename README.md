# AstraNote

**Suivi et notation des étudiants** — application web Flask qui remplace les
fichiers Excel de notation par étoiles. Voir la
[fiche fonctionnelle](AstraNote_Fiche_Fonctionnelle.md) pour le détail métier.

Chaque séance, l'enseignant attribue des **étoiles** (0 à 4) par exercice.
L'application calcule automatiquement une **note /20 au prorata** (le meilleur
total = 20/20, les autres proportionnellement, arrondi au 0,5). Les notes
finales restent saisies à la main par l'enseignant.

## Fonctionnalités

### Comptes et périmètre

- Authentification enseignants (Flask-Login, hash Werkzeug) ; comptes créés par l'admin.
- Page **Mon compte** : changement de mot de passe en autonomie.
- Structure **École › Année académique › Classe › Module**. Chaque enseignant gère
  ses propres écoles/années (visibles de lui seul) ; celles créées par l'admin sont
  communes (visibles par tous).
- Cloisonnement : un enseignant ne voit que **ses** classes, l'administrateur voit tout.

### Grille de notation

- Modules **individuels** ou **en groupe**.
- **Dates/séances**, **colonnes d'étoiles** (ajoutables à tout moment), **colonnes
  URL**, **colonnes de note manuelles** (« Note CC », « Note Examen »…) ; toutes
  renommables et réordonnables.
- Saisie immédiate (AJAX) avec **recalcul du prorata en direct** et raccourcis
  clavier (0–4 pour la valeur, Entrée pour descendre d'une ligne).
- Statuts spéciaux (ABS, Retard, Pas de PC…) affichés en couleur, valant 0 étoile.
- Calcul automatique de la **note /20 au prorata** (règles R1–R12).
- **Couleur de fond** libre sur la cellule d'un étudiant ou d'un groupe, propre à
  chaque module.
- Commentaire général par étudiant / par groupe.
- **Modules en groupe** : chaque groupe se **déplie** pour noter ses membres
  individuellement sur les mêmes colonnes. Le membre obtient un **total d'étoiles**
  propre, qui mesure sa contribution ; la seule note /20 reste celle du groupe.
- Deux liens Discord par module (salon du module, salon de référence) et pseudo
  Discord affiché sous le nom de l'étudiant.

### Étudiants

- Ajout et **édition des caractéristiques** (nom, email, pseudo Discord, GitHub).
- **Neutralisation** réversible d'un étudiant ayant quitté l'école : grisé, saisie
  verrouillée, exclu du calcul du prorata, ses étoiles conservées.
- **Export et import Excel** de la liste administrative d'une classe.
- **Recherche globale** d'étudiant, insensible à la casse et aux accents, respectant
  les droits.

### Suivi et pilotage

- **Tableau de bord** : sélecteur d'année, classes regroupées par école, avancement
  de saisie de chaque classe.
- **Dashboard de classement** par module : podium général et podium par séance.
- **Suivi de la transmission des notes** à l'établissement (envoyé ou non, date,
  moyen, précision libre), remonté sur le tableau de bord.
- **Facturation** : taux horaire par classe, contacts et observation par école.
- **Export / import Excel** des notes manuelles d'un module (les membres d'un
  groupe y figurent avec leurs propres notes).
- **Administration** : compteurs de la base et téléchargement de la sauvegarde en
  un clic.

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
| `ASTRANOTE_COOKIE_SECURE` | Cookie de session `Secure` (exige HTTPS) ; `0` pour désactiver en local | `1` |
| `ASTRANOTE_DB_FILE` | Force le fichier sauvegardé par `scripts/backup_db.py` | déduit de `ASTRANOTE_DATABASE_URI` |
| `ASTRANOTE_BACKUP_DIR` | Dossier des sauvegardes de `scripts/backup_db.py` | `~/astranote-backups` |

`run.py` force `ASTRANOTE_COOKIE_SECURE=0` : en local l'application est servie en
HTTP, où un cookie `Secure` ne serait pas transmis et la connexion échouerait.

## Structure du projet

```
config.py              Configuration (env vars)
run.py                 Point d'entrée local
wsgi.py                Point d'entrée WSGI (PythonAnywhere)
astranote/
  __init__.py          App factory + migrations légères + création admin
  models.py            Modèle de données (17 tables SQLite)
  grading.py           Calcul du prorata /20 et classement (règles R1–R12)
  auth.py              Login / logout / mon compte / comptes enseignants
  main.py              Structure, étudiants, recherche, dashboard, administration
  modules.py           Grille, dates, colonnes, groupes, saisie AJAX, Excel
  templates/           Jinja2
  static/              CSS + JS de la grille
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

La suite couvre l'authentification/CSRF et l'open redirect, le prorata et son
arrondi (R1–R12), la neutralisation, le périmètre écoles/années, le nettoyage des
orphelins, le renommage/réordonnancement des colonnes, l'édition de module et le
suivi d'envoi des notes, la facturation, le classement, la progression du tableau
de bord, les couleurs de cellule, la notation individuelle des membres d'un
groupe, et les aller-retours Excel (notes d'un module, liste des étudiants).

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

Deux moyens :

- **Depuis l'application** (le plus simple) : menu **Administration → Télécharger
  la sauvegarde (.db)** (réservé à l'admin). Produit une copie cohérente à
  télécharger en un clic.
- **Tâche planifiée** : `scripts/backup_db.py` crée une copie horodatée de la base
  SQLite (via l'API `backup`, cohérente même en écriture) et conserve les 14
  dernières dans `~/astranote-backups/`. À planifier en tâche quotidienne sur
  PythonAnywhere :

  ```bash
  python3 /home/astranote/mysite/scripts/backup_db.py
  ```

  Le script sauvegarde la base **que l'application utilise réellement** : il lit
  le même `config.py`, et suit donc `ASTRANOTE_DATABASE_URI` sans réglage
  supplémentaire. En cas de problème (base introuvable, copie impossible) il
  écrit sur la sortie d'erreur et **sort en code non nul**, pour que la tâche
  planifiée apparaisse en échec au lieu de ne rien sauvegarder en silence.

## Reste à faire (cf. fiche §8)

- Duplication d'une classe d'une année sur l'autre.

Les autres points de la version 2 sont livrés : export Excel (notes d'un module et
liste des étudiants), tableau de bord et statistiques (avancement de saisie,
classement par module).
