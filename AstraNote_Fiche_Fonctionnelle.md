# AstraNote — Fiche fonctionnelle

**Suivi et notation des étudiants**

Version : 1.0 (brouillon) · Date : 3 juillet 2026 · Auteur : Boris Stocker

---

## 1. Contexte et objectif

Aujourd'hui, le suivi des étudiants repose sur des fichiers Excel (un fichier par classe, un onglet par module). Chaque séance, l'enseignant attribue des **étoiles** (`*` à `****`) selon la qualité du travail rendu. En fin de module, l'étudiant ayant le plus d'étoiles sert de référence (20/20) et les autres sont notés **au prorata**. Des **notes de partiel** chiffrées sont gérées séparément.

**AstraNote** vise à remplacer ces fichiers Excel par une application web sous **Flask**, centralisée, qui :

- structure les données sur plusieurs **écoles** et plusieurs **années académiques** ;
- simplifie la **saisie des étoiles** par séance ;
- **calcule automatiquement** les notes /20 selon la règle du prorata ;
- gère les **notes de partiel** en parallèle ;
- permet à **plusieurs enseignants** de gérer leurs propres classes.

---

## 2. Concepts et vocabulaire

| Terme | Définition |
|---|---|
| **École** | Établissement géré (ex. EPSI). Un enseignant peut intervenir dans plusieurs écoles. |
| **Année académique** | Cycle annuel (ex. 2025-2026). Chaque classe appartient à une année. |
| **Classe / Promotion** | Groupe d'étudiants (ex. B3 IA, M1 Cyber, B3 ASRBD). Correspond aujourd'hui à un fichier Excel. |
| **Module** | Unité d'enseignement au sein d'une classe (ex. Cryptographie, Hacking, Sécurisation). Correspond à un onglet Excel. |
| **Séance / Exercice** | Colonne d'évaluation datée à l'intérieur d'un module. |
| **Étoile** | Unité de points de suivi continu (`*` = 1 point). Une cellule vaut de 0 à 4 étoiles. |
| **Statut spécial** | Marqueur non-noté valant **0 étoile** : `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé`. |
| **Note d'étoiles** | Note /20 calculée au prorata du meilleur total d'étoiles du module. |
| **Note de partiel** | Note chiffrée /20 saisie manuellement, gérée à part. |

### Hiérarchie des données

```
École
 └── Année académique
      └── Classe / Promotion
           └── Module (onglet)
                ├── Séances / Exercices (colonnes datées)
                └── Étudiants
                     └── Étoiles (par séance) + Notes de partiel
```

---

## 3. Règles de gestion (notation)

**R1 — Comptage des étoiles.** Pour un module, le total d'un étudiant = somme des étoiles de toutes ses séances (`*`=1, `**`=2, `***`=3, `****`=4).

**R2 — Statuts spéciaux.** `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé` comptent pour **0 étoile**.

**R3 — Référence.** L'étudiant avec le **total d'étoiles le plus élevé** du module obtient **20/20**.

**R4 — Prorata.** Pour tout autre étudiant :

> **note_étoiles = (total_étoiles_étudiant ÷ total_étoiles_max) × 20**

arrondie à 0,25 (paramétrable).

**R5 — Calcul par module.** Le calcul se fait **par module (onglet) séparément**. Aucune agrégation automatique entre modules par défaut.

**R6 — Partiels.** Les notes de partiel sont chiffrées et **gérées à part** ; elles n'entrent pas dans le calcul du prorata. Une éventuelle **note finale** (moyenne pondérée étoiles/partiel) reste optionnelle et configurable par module.

**R7 — Cas limite.** Si aucun étudiant n'a d'étoile dans le module (max = 0), les notes d'étoiles ne sont pas calculées (affichage « N/A ») pour éviter une division par zéro.

---

## 4. Rôles et droits

| Rôle | Droits |
|---|---|
| **Administrateur** | Gère les écoles, années, comptes enseignants ; accès global. |
| **Enseignant** | Crée/gère ses classes, modules, séances ; saisit étoiles et partiels ; consulte les notes calculées. Ne voit que **ses** classes. |
| **Étudiant** *(optionnel, phase 2)* | Consultation en **lecture seule** de ses propres étoiles et notes. |

Multi-profs : chaque enseignant est propriétaire de ses classes. Un partage de classe entre enseignants peut être ajouté ultérieurement.

---

## 5. Fonctionnalités

### 5.1 Authentification et comptes
- Connexion par email / mot de passe (hash sécurisé).
- Gestion de session, déconnexion, réinitialisation de mot de passe.
- Création de comptes enseignants par l'administrateur.

### 5.2 Gestion de la structure (écoles, années, classes)
- CRUD **écoles**, **années académiques**, **classes**.
- Association d'une classe à une école + une année.
- Duplication d'une classe d'une année sur l'autre (report de structure sans les étoiles).

### 5.3 Gestion des modules et séances
- CRUD **modules** au sein d'une classe (nom, canal Discord, description).
- CRUD **séances/exercices** (intitulé, date).
- Réorganisation de l'ordre des séances.

### 5.4 Gestion des étudiants
- Ajout/import d'étudiants (nom, email `@ecoles-epsi.net`, pseudo Discord).
- Rattachement d'un étudiant à une ou plusieurs classes.
- Champs annexes optionnels : lien GitHub, lien rapport (board.net), URL lab.

### 5.5 Saisie des étoiles
- **Grille de saisie** type tableur : lignes = étudiants, colonnes = séances.
- Saisie rapide des étoiles (0 à 4) au clic/clavier.
- Sélection des statuts spéciaux (`Retard`, `ABS`, etc.).
- Enregistrement automatique ; total d'étoiles par étudiant affiché en direct.

### 5.6 Calcul et affichage des notes
- Calcul automatique des **notes /20 au prorata** (règles R1–R7).
- Mise en évidence de l'étudiant de référence (20/20).
- Recalcul instantané à chaque modification d'étoile.
- Vue par module : total d'étoiles, note d'étoiles, note(s) de partiel, note finale optionnelle.

### 5.7 Gestion des partiels
- Ajout de **notes de partiel** chiffrées par étudiant et par module.
- Plusieurs partiels possibles par module.
- Configuration optionnelle d'une pondération étoiles/partiel pour une note finale.

### 5.8 Import / Export *(recommandé)*
- **Import** des fichiers `.xlsx` existants (une classe = un fichier, un module = un onglet) pour reprise de l'historique.
- **Export** des notes calculées en `.xlsx` / `.csv` / `.pdf` (bulletin par classe ou par étudiant).

### 5.9 Tableau de bord
- Vue synthétique par enseignant : classes, modules, avancement de la saisie.
- Statistiques par module : moyenne, médiane, distribution des notes.

---

## 6. Modèle de données (indicatif)

```
School(id, name)
AcademicYear(id, label)                      # ex. "2025-2026"
Teacher(id, name, email, password_hash, role)
Class(id, name, school_id, academic_year_id, teacher_id)
Module(id, name, discord_channel, class_id)
Session(id, label, date, module_id, position)  # séance/exercice
Student(id, full_name, email, discord_alias, github_url)
Enrollment(id, student_id, class_id)
Star(id, student_id, session_id, value)      # 0..4 ou statut spécial
SpecialStatus(id, star_id, type)             # Retard, ABS, ...
ExamGrade(id, student_id, module_id, label, score) # note de partiel
```

Le calcul des notes est **dérivé** (non stocké en dur) : recalculé à la volée à partir des étoiles, ou mis en cache et invalidé à chaque changement.

---

## 7. Pile technique proposée

- **Backend** : Python 3 + **Flask**, SQLAlchemy (ORM).
- **Base de données** : SQLite en développement, PostgreSQL en production.
- **Frontend** : templates Jinja2 + un peu de JavaScript (grille de saisie), ou HTMX pour l'interactivité sans lourd framework.
- **Auth** : Flask-Login + Werkzeug (hash de mots de passe).
- **Export** : openpyxl (Excel), WeasyPrint/ReportLab (PDF).
- **Déploiement** : Gunicorn + Nginx, ou conteneur Docker.

---

## 8. Périmètre et priorisation

### MVP (v1)
- Comptes enseignants + structure École/Année/Classe/Module/Séance.
- Gestion des étudiants.
- Saisie des étoiles + statuts spéciaux.
- Calcul automatique des notes /20 au prorata.
- Gestion des notes de partiel.

### Version 2
- Import/Export Excel & PDF.
- Tableau de bord et statistiques.
- Accès étudiant en lecture seule.
- Partage de classes entre enseignants.

---

## 9. Points à trancher

- Arrondi des notes : au 0,25, au 0,5, ou à l'entier ?
- Note finale par module : garde-t-on étoiles et partiels totalement séparés, ou propose-t-on une moyenne pondérée configurable ?
- Import Excel : reprise de tout l'historique existant, ou démarrage à neuf ?
- Accès étudiant : souhaité dès la v1 ou reporté ?
