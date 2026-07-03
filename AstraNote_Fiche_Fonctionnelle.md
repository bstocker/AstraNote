# AstraNote — Fiche fonctionnelle

**Suivi et notation des étudiants**

Version : 2.0 · Date : 3 juillet 2026 · Auteur : Boris Stocker

---

## 1. Contexte et objectif

Le suivi des étudiants repose aujourd'hui sur des fichiers Excel (un fichier par classe, un onglet par module). À chaque séance, l'enseignant attribue des **étoiles** (`*` à `****`) selon la qualité du travail rendu. En fin de module, l'étudiant ayant le plus d'étoiles sert de référence (20/20) et les autres sont notés **au prorata**. La **note finale** reste décidée par l'enseignant, qui la pondère lui-même.

**AstraNote** remplace ces fichiers Excel par une application web **Flask** simple, hébergée sur **PythonAnywhere** avec une base **SQLite**. Elle permet de :

- structurer les données sur plusieurs **écoles** et plusieurs **années académiques** ;
- saisir les **étoiles** dans une grille par dates et colonnes, **extensible à tout moment** ;
- **calculer automatiquement** la note d'étoiles /20 au prorata ;
- laisser l'enseignant **saisir manuellement** ses notes finales (Note CC, Note Examen…) ;
- fonctionner en **multi-enseignants**, chacun gérant ses classes.

Démarrage **à neuf** : pas de reprise des fichiers Excel existants.

---

## 2. Concepts et vocabulaire

| Terme | Définition |
|---|---|
| **École** | Établissement géré (ex. EPSI). Un enseignant peut intervenir dans plusieurs écoles. |
| **Année académique** | Cycle annuel (ex. 2025-2026). Chaque classe appartient à une année. |
| **Classe / Promotion** | Groupe d'étudiants (ex. B3 IA, M1 Cyber, B3 ASRBD). |
| **Module** | Unité d'enseignement au sein d'une classe (ex. Cryptographie, Hacking). Correspond à un onglet Excel. Contient la grille de notation. |
| **Date / Séance** | Repère temporel dans un module (ex. 2025-09-30). Un module comporte **plusieurs dates**. |
| **Colonne d'étoiles** | Colonne d'exercice rattachée à une date, où l'on saisit les étoiles. On peut **en ajouter à tout moment**. |
| **Étoile** | Unité de points de suivi continu (`*` = 1 point). Une cellule vaut de 0 à 4 étoiles. |
| **Statut spécial** | Marqueur non-noté valant **0 étoile** : `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé`. |
| **Note d'étoiles** | Note /20 calculée automatiquement au prorata du meilleur total d'étoiles du module. |
| **Colonne de note** | Note chiffrée /20 **saisie manuellement** par l'enseignant (ex. « Note CC », « Note Examen »). Une classe/un module peut en avoir **plusieurs**. |

### Hiérarchie et structure de la grille

```
École
 └── Année académique
      └── Classe / Promotion
           ├── Étudiants (nom, email, pseudo Discord)
           └── Module (onglet)
                ├── Date 1 ── Colonne étoiles A ── Colonne étoiles B ...
                ├── Date 2 ── Colonne étoiles C ...
                ├── ...  (autant de dates que nécessaire)
                └── Colonnes de note manuelles : Note CC, Note Examen, ... (X possibles)
```

Structure d'une grille de module : **une date, puis une ou plusieurs colonnes d'étoiles**, répété pour chaque date. À droite, les **colonnes de notes** saisies à la main.

---

## 3. Règles de gestion (notation)

**R1 — Comptage des étoiles.** Pour un module, le total d'un étudiant = somme des étoiles de **toutes ses colonnes d'étoiles** (`*`=1, `**`=2, `***`=3, `****`=4), toutes dates confondues.

**R2 — Statuts spéciaux.** `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé` comptent pour **0 étoile**.

**R3 — Référence.** L'étudiant avec le **total d'étoiles le plus élevé** du module obtient **20/20**.

**R4 — Prorata.** Pour tout autre étudiant :

> **note_étoiles = (total_étoiles_étudiant ÷ total_étoiles_max) × 20**

**R5 — Arrondi.** La note d'étoiles est arrondie **au 0,5** le plus proche.

**R6 — Recalcul automatique.** La note d'étoiles se recalcule automatiquement à chaque ajout/modification d'étoile ou de colonne. L'ajout d'une nouvelle colonne d'étoiles est possible **à tout moment** et met à jour les totaux.

**R7 — Calcul par module.** Le calcul du prorata se fait **par module** séparément. Aucune agrégation automatique entre modules.

**R8 — Note finale manuelle.** La **note finale n'est pas calculée** par l'application. L'enseignant la saisit lui-même dans une **colonne de note** (« Note CC », « Note Examen »…), car il applique sa propre pondération (note d'étoiles, partiels, appréciation). Plusieurs colonnes de note sont possibles.

**R9 — Cas limite.** Si aucun étudiant n'a d'étoile (max = 0), la note d'étoiles s'affiche « N/A » (pas de division par zéro).

---

## 4. Rôles et droits

| Rôle | Droits |
|---|---|
| **Administrateur** | Gère les écoles, années et comptes enseignants ; accès global. |
| **Enseignant** | Crée/gère ses classes, modules, dates, colonnes ; saisit étoiles et notes ; consulte la note d'étoiles calculée. Ne voit que **ses** classes. |

**Pas d'accès étudiant.** L'application est un outil interne aux enseignants.

---

## 5. Fonctionnalités

### 5.1 Authentification et comptes
- Connexion par email / mot de passe (hash sécurisé via Werkzeug).
- Gestion de session (Flask-Login), déconnexion.
- Création des comptes enseignants par l'administrateur.

### 5.2 Structure : écoles, années, classes
- CRUD **écoles**, **années académiques**, **classes**.
- Association d'une classe à une école + une année.
- Duplication d'une classe d'une année sur l'autre (report de la structure sans les étoiles).

### 5.3 Modules, dates et colonnes
- CRUD **modules** au sein d'une classe.
- Ajout de **dates** (séances) dans un module.
- **Ajout d'une colonne d'étoiles à tout moment**, rattachée à une date, avec un intitulé (ex. « CMAKE », « Projet »).
- Ajout de **colonnes de note manuelles** (« Note CC », « Note Examen »… — autant que nécessaire).
- Réorganisation / renommage / suppression des colonnes.

### 5.4 Étudiants
- Ajout d'étudiants (nom, email `@ecoles-epsi.net`, pseudo Discord).
- Rattachement à une classe.
- Champs annexes optionnels : lien GitHub, lien rapport (board.net), URL lab.

### 5.5 Saisie des étoiles
- **Grille tableur** : lignes = étudiants, colonnes = colonnes d'étoiles regroupées par date.
- Saisie rapide (0 à 4 étoiles) au clic/clavier.
- Sélection des statuts spéciaux (`Retard`, `ABS`, etc.).
- Enregistrement immédiat ; total d'étoiles par étudiant affiché en direct.

### 5.6 Calcul et affichage de la note d'étoiles
- Calcul automatique de la **note /20 au prorata**, arrondie au 0,5 (règles R1–R9).
- Mise en évidence de l'étudiant de référence (20/20).
- Recalcul instantané à chaque modification.

### 5.7 Saisie des notes finales
- Saisie manuelle des notes dans les colonnes « Note CC », « Note Examen », etc.
- Plusieurs colonnes de note par module/classe.
- Ces notes sont indépendantes du calcul d'étoiles (aucune pondération automatique).

### 5.8 Export *(optionnel, v2)*
- Export d'un module en `.xlsx` / `.csv` (étoiles, note d'étoiles, notes manuelles).

### 5.9 Tableau de bord
- Vue par enseignant : classes, modules, avancement de la saisie.

---

## 6. Modèle de données (SQLite)

```
School(id, name)
AcademicYear(id, label)                       # ex. "2025-2026"
Teacher(id, name, email, password_hash, role) # role = admin | teacher
Class(id, name, school_id, academic_year_id, teacher_id)
Module(id, name, discord_channel, class_id)
GradeDate(id, module_id, label, date, position)      # une date/séance
StarColumn(id, grade_date_id, title, position)        # colonne d'étoiles
NoteColumn(id, module_id, title, position)            # "Note CC", "Note Examen"...
Student(id, full_name, email, discord_alias, github_url)
Enrollment(id, student_id, class_id)
Star(id, student_id, star_column_id, value)           # 0..4 OU statut spécial
NoteValue(id, student_id, note_column_id, score)      # note manuelle /20
```

La note d'étoiles est **dérivée** (calculée à la volée à partir des étoiles) et non stockée en dur ; les notes manuelles sont stockées telles quelles.

---

## 7. Pile technique et hébergement

- **Hébergement** : **PythonAnywhere** (application web WSGI).
- **Backend** : Python 3 + **Flask**, SQLAlchemy (ORM).
- **Base de données** : **SQLite** (fichier unique, simple à sauvegarder).
- **Frontend** : templates Jinja2 + JavaScript léger (ou HTMX) pour la grille de saisie.
- **Auth** : Flask-Login + Werkzeug (hash de mots de passe).
- **Export** : openpyxl (Excel/CSV).

Contraintes PythonAnywhere prises en compte : une seule base SQLite, pas de service de fond permanent requis, dépendances minimales.

---

## 8. Périmètre et priorisation

### MVP (v1)
- Comptes enseignants + structure École / Année / Classe / Module.
- Gestion des dates et **ajout de colonnes d'étoiles à tout moment**.
- Gestion des étudiants.
- Saisie des étoiles + statuts spéciaux.
- Calcul automatique de la note d'étoiles /20 (arrondi 0,5).
- Colonnes de notes manuelles (Note CC, Note Examen…).

### Version 2
- Export Excel / CSV.
- Tableau de bord et statistiques.
- Duplication de classe d'une année sur l'autre.

---

## 9. Décisions arrêtées

- **Hébergement** : PythonAnywhere, Flask + SQLite (solution simple).
- **Colonnes d'étoiles** : ajoutables à tout moment ; structure date → colonnes.
- **Plusieurs dates** par module/classe.
- **Note finale manuelle** via colonnes Note CC / Note Examen (pondération faite par l'enseignant) ; plusieurs notes possibles par classe.
- **Démarrage à neuf** (pas d'import Excel).
- **Pas d'accès étudiant**.
- **Arrondi au 0,5**.
