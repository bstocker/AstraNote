# AstraNote — contexte pour Claude Code

Application Flask de suivi et de notation d'étudiants par étoiles (0–4), note
/20 au prorata. Un seul développeur (Boris Stocker), échanges en **français**.
Détail métier : `AstraNote_Fiche_Fonctionnelle.md` ; vue d'ensemble : `README.md`.

## Commandes

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # ~50 s, doit rester entièrement vert
python run.py                # serveur local http://127.0.0.1:5000
```

## Façon de travailler

- Commits **directement sur `main`**, en français, au format
  « Sujet : description » (voir `git log`).
- **Un push sur `main` déploie en production** (PythonAnywhere, workflow
  `.github/workflows/CICD.yml`, tests puis upload). Ne pousser que sur demande
  explicite ; `[skip ci]` dans le message évite un déploiement inutile.
- Chaque évolution arrive avec ses tests (`tests/test_app.py`,
  `test_planning.py`, `test_billing.py`) et une mise à jour du README.
- Les commentaires du code expliquent le *pourquoi* des choix : garder ce style.

## Repères dans le code

- `astranote/__init__.py` : factory, migrations légères (`_run_migrations`,
  ajout de colonnes et réparations idempotentes au démarrage), clé de session.
- `astranote/main.py` : structure, étudiants, recherche, admin ; helpers de
  droits (`get_class_or_403`, `visible_*_query`), `clean_url`,
  `purge_subject_data`, `purge_orphan_students`.
- `astranote/modules.py` : la grille (cœur de l'appli), saisie AJAX, exports
  Excel (`export_module`, `export_synthesis`, `export_grid`).
- `astranote/planning.py`, `astranote/billing.py` : planning partagé, facturation.
- Étoiles, notes, URL, présences référencent leur sujet par
  `(subject_type, subject_id)` **sans clé étrangère** : toute suppression
  d'étudiant ou de groupe doit passer par les fonctions de purge.
- Toute URL saisie par l'utilisateur passe par `clean_url` (http/https
  uniquement) et s'affiche via le filtre Jinja `safe_url`.

## État au 8 octobre 2026 (commit `1fc90a4`, déployé)

Livré lors de la dernière session :

- Export Excel de la grille affichée (`/modules/<id>/grid.xlsx`, bouton dans
  le bandeau des séances) : séances sélectionnées ou toutes, colonne A groupe,
  colonne B étudiant, groupes toujours dépliés.
- Liens limités à http(s) ; clé de session générée dans `instance/secret_key`
  à défaut de `ASTRANOTE_SECRET_KEY` ; suppression des étudiants sans
  inscription (à la suppression d'une classe/école/année, et au démarrage).

Questions laissées ouvertes à Boris :

- Le bouton d'export n'a pas été essayé dans un navigateur (route et syntaxe
  JS vérifiées seulement).
- L'export suit les séances **sélectionnées** (en surbrillance), même sans
  « Afficher la sélection » : à confirmer, ou à restreindre à l'affichage.

Pistes proposées, non commencées, par ordre d'utilité :

1. Limiter les tentatives de connexion ; 8 caractères minimum pour les mots de
   passe créés par l'admin (`auth.create_teacher`).
2. Duplication d'une classe d'une année sur l'autre (« Reste à faire » du README).
3. Le déploiement ne supprime jamais du serveur un fichier retiré du dépôt.

Dette connue, non urgente : `modules.py` (~1 900 lignes) et
`module_detail.html` très denses, routes ajouter/renommer/déplacer/supprimer
dupliquées pour les cinq types de colonne ; migrations maison limitées à
l'ajout de colonnes (Alembic au premier renommage) ; requêtes par classe sur
le tableau de bord.
