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
| **Module** | Unité d'enseignement (matière) au sein d'une classe (ex. Cryptographie, Hacking). Correspond à un onglet Excel. Contient la grille de notation. Chaque module est **individuel** ou **en groupe**. |
| **Mode de travail** | Propriété du module fixée à sa création : **individuel** (notation par étudiant) ou **groupe** (notation par groupe). |
| **Groupe** | Ensemble d'étudiants d'un module en mode groupe. Les étoiles, notes et commentaire portent sur le **groupe entier**. |
| **Date / Séance** | Repère temporel dans un module (ex. 2025-09-30). Un module comporte **plusieurs dates**. |
| **Colonne d'étoiles** | Colonne d'exercice rattachée à une date, où l'on saisit les étoiles. On peut **en ajouter à tout moment**. |
| **Étoile** | Unité de points de suivi continu (`*` = 1 point). Une cellule vaut de 0 à 4 étoiles. |
| **Statut spécial** | Marqueur non-noté valant **0 étoile** : `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé`. |
| **Note d'étoiles** | Note /20 calculée automatiquement au prorata du meilleur total d'étoiles du module. |
| **Colonne de note** | Note chiffrée /20 **saisie manuellement** par l'enseignant (ex. « Note CC », « Note Examen »). Une classe/un module peut en avoir **plusieurs**. Affichée **fond jaune, police en gras**. |
| **Colonne URL** | Colonne rattachée à une date contenant un **lien** par étudiant/groupe (ex. dépôt GitHub, rapport board.net, URL lab). Cliquable, non notée. |

### Hiérarchie et structure de la grille

```
École
 └── Année académique
      └── Classe / Promotion
           ├── Étudiants (nom, email, pseudo Discord)
           └── Modules (plusieurs par classe — un onglet chacun)
                └── Module (ex. Cryptographie)
                     ├── Date 1 ── Colonne étoiles A ── Colonne étoiles B ...
                     ├── Date 2 ── Colonne étoiles C ...
                     ├── ...  (autant de dates que nécessaire)
                     └── Colonnes de note manuelles : Note CC, Note Examen, ... (X possibles)
```

Une **classe peut contenir plusieurs modules** (ex. B3 ASRBD → Hacking + Sécurisation). Chaque module a sa propre grille (dates, colonnes d'étoiles, colonnes de notes) et son propre calcul au prorata.

Structure d'une grille de module : **une date, puis une ou plusieurs colonnes d'étoiles**, répété pour chaque date. À droite, les **colonnes de notes** saisies à la main.

---

## 3. Règles de gestion (notation)

**R1 — Comptage des étoiles.** Pour un module, le total d'un étudiant = somme des étoiles de **toutes ses colonnes d'étoiles** (`*`=1, `**`=2, `***`=3, `****`=4), toutes dates confondues.

**R2 — Statuts spéciaux.** `Retard`, `ABS`, `-`, `?`, `Pas de PC`, `Non réalisé` comptent pour **0 étoile**. Ils sont **affichés en couleur** pour repérage visuel :

| Statut | Couleur |
|---|---|
| `ABS` | **Rouge** |
| `Pas de PC` | **Rouge** |
| `Retard` | **Orange** |
| `Non réalisé` | **Orange** |
| Autres (`-`, `?`) | Gris/neutre |

Le contenu d'une cellule (étoiles ↔ statut) est **modifiable à tout moment** : l'enseignant peut changer le statut d'une cellule quand il le souhaite, avec recalcul automatique.

**R3 — Référence.** L'étudiant avec le **total d'étoiles le plus élevé** du module obtient **20/20**.

**R4 — Prorata.** Pour tout autre étudiant :

> **note_étoiles = (total_étoiles_étudiant ÷ total_étoiles_max) × 20**

**R5 — Arrondi.** La note d'étoiles est arrondie **au 0,5** le plus proche.

**R6 — Recalcul automatique.** La note d'étoiles se recalcule automatiquement à chaque ajout/modification d'étoile ou de colonne. L'ajout d'une nouvelle colonne d'étoiles est possible **à tout moment** et met à jour les totaux.

**R7 — Calcul par module.** Le calcul du prorata se fait **par module** séparément. Aucune agrégation automatique entre modules.

**R7bis — Modules en groupe.** Si le module est en mode **groupe**, l'unité notée est le **groupe** : étoiles, note d'étoiles, notes manuelles et commentaire portent sur le groupe entier. Le prorata s'applique alors entre **groupes** (le groupe au plus grand total d'étoiles = 20/20). Chaque étudiant hérite de la note et du commentaire de son groupe.

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
- À la création d'un module, choix du **mode de travail** : **individuel** ou **en groupe**.
- Ajout de **dates** (séances) dans un module.
- **Plusieurs colonnes d'étoiles par date** : une date peut porter autant d'exercices (colonnes) que nécessaire.
- **Ajout d'une colonne d'étoiles à tout moment**, y compris sur une date **existante**, avec un intitulé (ex. « CMAKE », « Projet »).
- **Ajout de colonnes URL** rattachées à une date, contenant un lien par étudiant/groupe (dépôt GitHub, rapport, lab…), cliquable.
- Ajout de **colonnes de note manuelles** (« Note CC », « Note Examen »… — autant que nécessaire), affichées **fond jaune et police en gras**.
- Réorganisation / renommage / suppression des colonnes.

### 5.4 Étudiants
- Ajout d'étudiants (nom, email `@ecoles-epsi.net`, pseudo Discord).
- Rattachement à une classe.
- **Commentaire général** libre par étudiant : appréciation globale saisie par l'enseignant, éditable à tout moment.
- Champs annexes optionnels : lien GitHub, lien rapport (board.net), URL lab.

### 5.4bis Groupes (modules en mode groupe)
- Pour un module en mode groupe, **création des groupes** et affectation des étudiants de la classe à un groupe.
- Un groupe porte un nom (ex. « Groupe 1 »).
- La suite du processus est **identique** au mode individuel — étoiles, notes, commentaire — mais s'applique au **groupe entier** (une ligne par groupe au lieu d'une ligne par étudiant).

### 5.5 Vue module et saisie des étoiles
- L'ouverture d'un module affiche un **tableau** unique servant à la fois à **consulter** et à **saisir les étoiles**.
- Disposition du tableau :
  - **Lignes** = étudiants (ou **groupes** en mode groupe) ;
  - **Colonnes** = colonnes d'étoiles (exercices) **regroupées par date** (en-tête à deux niveaux : date, puis titre d'exercice) ;
  - **Colonnes URL** possibles sous une date (liens cliquables) ;
  - **Colonnes de fin** : total d'étoiles, **note d'étoiles /20** (auto), colonnes de notes manuelles (Note CC, Note Examen… — **fond jaune, gras**), et commentaire général.
- Saisie rapide des étoiles (0 à 4) au clic/clavier directement dans la cellule.
- Sélection des statuts spéciaux (`ABS`, `Retard`, etc.), affichés en couleur.
- Enregistrement immédiat ; totaux et note d'étoiles **mis à jour en direct**.

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

### 5.10 Recherche d'étudiant
- **Recherche globale par nom** dans toute la base, depuis n'importe quelle page.
- Recherche partielle et insensible à la casse/aux accents.
- Résultats listant, pour chaque étudiant trouvé, ses **écoles, années, classes et modules** de rattachement, avec accès direct.
- Périmètre respectant les droits : l'enseignant cherche dans **ses** classes, l'administrateur dans toute la base.

---

## 6. Modèle de données (SQLite)

```
School(id, name)
AcademicYear(id, label)                       # ex. "2025-2026"
Teacher(id, name, email, password_hash, role) # role = admin | teacher
Class(id, name, school_id, academic_year_id, teacher_id)
Module(id, name, discord_channel, class_id, work_mode)  # work_mode = individual | group
GradeDate(id, module_id, label, date, position)      # une date/séance
StarColumn(id, grade_date_id, title, position)        # colonne d'étoiles ; title = titre de l'exercice
UrlColumn(id, grade_date_id, title, position)         # colonne de liens rattachée à une date
NoteColumn(id, module_id, title, position)            # "Note CC", "Note Examen"... (affichage fond jaune, gras)
Student(id, full_name, email, discord_alias, github_url)
Enrollment(id, student_id, class_id, general_comment)  # commentaire général de l'enseignant
Group(id, module_id, name)                            # module en mode groupe
GroupMember(id, group_id, student_id)
Star(id, subject_type, subject_id, star_column_id, value)     # subject = student | group
UrlValue(id, subject_type, subject_id, url_column_id, url)     # lien par étudiant/groupe
NoteValue(id, subject_type, subject_id, note_column_id, score) # note manuelle /20
GroupComment(id, group_id, comment)                  # commentaire général du groupe
```

L'**unité notée** (`subject`) est l'étudiant en mode individuel, le groupe en mode groupe : `Star` et `NoteValue` référencent l'un ou l'autre selon le `work_mode` du module. La note d'étoiles est **dérivée** (calculée à la volée) et non stockée en dur ; les notes manuelles sont stockées telles quelles.

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
