# AstraNote — Fiche fonctionnelle

**Suivi et notation des étudiants**

Version : 2.1 · Date : 4 juillet 2026 · Auteur : Boris Stocker

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

**R10 — Étudiant neutralisé.** Un étudiant neutralisé (ayant quitté l'école) est **exclu du calcul du prorata** : il n'entre pas dans le total maximum de référence (R3) et n'obtient pas de note d'étoiles (affichée « — »). Les autres étudiants sont notés au prorata du meilleur total **parmi les étudiants actifs**. Ses étoiles restent conservées ; la neutralisation est réversible.

---

## 4. Rôles et droits

| Rôle | Droits |
|---|---|
| **Administrateur** | Gère les comptes enseignants et l'ensemble des écoles/années (dont les **écoles/années communes**) ; accès global à toutes les données. |
| **Enseignant** | Crée/gère **ses propres écoles et années académiques**, ses classes, modules, dates, colonnes ; saisit étoiles et notes ; consulte la note d'étoiles calculée. Ne voit que **ses** écoles, années et classes, **plus les écoles/années communes**. |

**Écoles / années propres vs communes.** Une école ou une année créée par un enseignant lui **appartient** : elle n'est visible et modifiable que par lui (et par l'administrateur). Une école ou une année créée par l'**administrateur** est **commune** : visible par tous les enseignants (qui peuvent la réutiliser pour leurs classes) mais modifiable/supprimable uniquement par l'administrateur. Cela évite qu'un même établissement soit ressaisi par chaque enseignant tout en garantissant que chacun gère son propre périmètre.

**Pas d'accès étudiant.** L'application est un outil interne aux enseignants.

---

## 5. Fonctionnalités

### 5.1 Authentification et comptes
- Connexion par email / mot de passe (hash sécurisé via Werkzeug).
- Gestion de session (Flask-Login), déconnexion.
- Création des comptes enseignants par l'administrateur.

### 5.2 Structure : écoles, années, classes
- CRUD **écoles**, **années académiques**, **classes**.
- **Chaque enseignant peut créer ses propres écoles et années** ; il ne voit que les siennes plus les **écoles/années communes** créées par l'administrateur.
- Association d'une classe à une école + une année (choisies parmi celles visibles par l'enseignant).
- Duplication d'une classe d'une année sur l'autre (report de la structure sans les étoiles).

### 5.3 Modules, dates et colonnes
- CRUD **modules** au sein d'une classe.
- À la création d'un module, choix du **mode de travail** : **individuel** ou **en groupe**.
- **Édition d'un module** : nom et **lien Discord** (URL cliquable). Le mode de travail n'est **pas** modifiable après création (il conditionne groupes et notes déjà saisis).
- Ajout de **dates** (séances) dans un module.
- **Plusieurs colonnes d'étoiles par date** : une date peut porter autant d'exercices (colonnes) que nécessaire.
- **Ajout d'une colonne d'étoiles à tout moment**, y compris sur une date **existante**, avec un intitulé (ex. « CMAKE », « Projet »).
- **Ajout de colonnes URL** rattachées à une date, contenant un lien par étudiant/groupe (dépôt GitHub, rapport, lab…), cliquable.
- Ajout de **colonnes de note manuelles** (« Note CC », « Note Examen »… — autant que nécessaire), affichées **fond jaune et police en gras**.
- Réorganisation / renommage / suppression des colonnes.

### 5.4 Étudiants
- Ajout d'étudiants (nom, email `@ecoles-epsi.net`, pseudo Discord).
- **Modification des caractéristiques** d'un étudiant à tout moment (nom, email, pseudo Discord, lien GitHub). La modification vaut pour toutes ses classes.
- **Neutralisation** d'un étudiant ayant quitté l'école : il est **grisé** dans les modules et **exclu du calcul du prorata** (il n'est plus la référence 20/20 et ne pénalise plus les autres). Ses étoiles sont **conservées** et l'opération est **réversible** (réactivation).
- Rattachement à une classe.
- **Commentaire général** libre par étudiant : appréciation globale saisie par l'enseignant, éditable à tout moment.
- Champs annexes optionnels : lien GitHub, lien rapport (board.net), URL lab.

### 5.4bis Groupes (modules en mode groupe)
- Pour un module en mode groupe, **création des groupes** et affectation des étudiants de la classe à un groupe.
- Un groupe porte un nom (ex. « Groupe 1 »).
- **Étudiants sans groupe** : un encart met en évidence les étudiants **actifs** de la classe **non encore affectés** à un groupe (avec leur nombre), et permet de les affecter directement. Les étudiants **neutralisés** (ayant quitté l'école) n'ont pas besoin de groupe et **n'y figurent pas**. Un message confirme lorsque tous les étudiants actifs sont affectés.
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
- Les **étudiants neutralisés** sont regroupés **en bas** du tableau, grisés, et leurs cellules sont **en lecture seule** (aucune saisie possible).

### 5.6 Calcul et affichage de la note d'étoiles
- Calcul automatique de la **note /20 au prorata**, arrondie au 0,5 (règles R1–R9).
- Mise en évidence de l'étudiant de référence (20/20).
- Recalcul instantané à chaque modification.

### 5.7 Saisie des notes finales
- Saisie manuelle des notes dans les colonnes « Note CC », « Note Examen », etc.
- Plusieurs colonnes de note par module/classe.
- Ces notes sont indépendantes du calcul d'étoiles (aucune pondération automatique).
- **Suivi de la transmission des notes** : pour chaque module, l'enseignant précise si les notes ont été **envoyées à l'établissement**, à quelle **date** et par quel **moyen** (mail, outil institutionnel de l'école, autre), avec une précision libre optionnelle. Le statut est affiché sur la page du module et sur la carte du module dans la classe.

### 5.8 Export / import Excel des notes
- **Export** d'un module en `.xlsx` contenant le **nom du module**, le **nom de l'étudiant** (ou du groupe), ses **notes manuelles** (colonnes jaunes) et son **commentaire**.
- **Import** du même fichier après édition dans Excel : les notes manuelles et commentaires sont **mis à jour**. Le rapprochement se fait sur une colonne `ID` masquée ; les colonnes de note sont reconnues par leur intitulé.
- Contrôles à l'import : notes bornées à 0–20 (valeurs invalides signalées et ignorées), étudiants neutralisés exclus, fichier non conforme rejeté.
- Les étoiles ne sont pas concernées par cet import (elles se saisissent dans la grille).

### 5.9 Tableau de bord
- **Sélecteur d'année académique** en tête : l'enseignant choisit l'année, et le tableau de bord affiche alors les **écoles**, et **sous chaque école ses classes** de l'année sélectionnée.
- Par défaut, l'année la plus récente est présélectionnée.
- Chaque classe est cliquable et donne accès à ses modules.
- **Avancement de la saisie** : chaque classe affiche une barre indiquant le pourcentage de cellules d'étoiles remplies (sur l'ensemble de ses modules).
- **Envoi des notes** : sous chaque classe, la liste de ses modules affiche une **coche verte ✔** pour ceux dont les notes ont été envoyées à l'établissement (○ sinon), avec la date/le moyen en infobulle. Chaque module est cliquable.
- Périmètre respectant les droits (l'enseignant ne voit que ses classes et ses écoles/années plus les communes).

### 5.10 Recherche d'étudiant
- **Recherche globale par nom** dans toute la base, depuis n'importe quelle page.
- Recherche partielle et insensible à la casse/aux accents.
- Résultats listant, pour chaque étudiant trouvé, ses **écoles, années, classes et modules** de rattachement, avec accès direct.
- Périmètre respectant les droits : l'enseignant cherche dans **ses** classes, l'administrateur dans toute la base.

---

## 6. Modèle de données (SQLite)

```
School(id, name, teacher_id)                  # teacher_id = propriétaire ; NULL = école commune (admin)
AcademicYear(id, label, teacher_id)           # ex. "2025-2026" ; NULL = année commune (admin)
Teacher(id, name, email, password_hash, role) # role = admin | teacher
Class(id, name, school_id, academic_year_id, teacher_id)
Module(id, name, discord_url, class_id, work_mode,          # work_mode = individual | group
       notes_sent, notes_sent_date, notes_sent_method, notes_sent_detail)  # transmission des notes à l'établissement
GradeDate(id, module_id, label, date, position)      # une date/séance
StarColumn(id, grade_date_id, title, position)        # colonne d'étoiles ; title = titre de l'exercice
UrlColumn(id, grade_date_id, title, position)         # colonne de liens rattachée à une date
NoteColumn(id, module_id, title, position)            # "Note CC", "Note Examen"... (affichage fond jaune, gras)
Student(id, full_name, email, discord_alias, github_url, active)  # active=False => neutralisé (grisé, hors calcul)
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
- **Auth & sécurité** : Flask-Login + Werkzeug (hash de mots de passe) ; **Flask-WTF** (protection CSRF de tous les formulaires et des appels AJAX).
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
- **Écoles / années par enseignant** *(v2.1)* : chaque enseignant crée et gère ses propres écoles et années (il ne voit que les siennes). Les écoles/années créées par l'administrateur sont **communes** (visibles par tous, modifiables par l'admin seul).
- **Colonnes d'étoiles** : ajoutables à tout moment ; structure date → colonnes.
- **Plusieurs dates** par module/classe.
- **Note finale manuelle** via colonnes Note CC / Note Examen (pondération faite par l'enseignant) ; plusieurs notes possibles par classe.
- **Démarrage à neuf** (pas d'import Excel).
- **Pas d'accès étudiant**.
- **Arrondi au 0,5**.
