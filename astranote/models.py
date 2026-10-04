"""Modèle de données AstraNote (SQLite) — cf. fiche fonctionnelle §6.

Hiérarchie : School > AcademicYear > Class > Module > GradeDate > StarColumn.
L'unité notée (`subject`) est l'étudiant (mode individuel) ou le groupe
(mode groupe) : Star / UrlValue / TextValue / NoteValue référencent l'un ou
l'autre via
(subject_type, subject_id).
"""
from datetime import date as date_type, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.orm import Session

db = SQLAlchemy()

SUBJECT_STUDENT = "student"
SUBJECT_GROUP = "group"

WORK_MODE_INDIVIDUAL = "individual"
WORK_MODE_GROUP = "group"

# Couleurs de fond posables sur la cellule « Étudiant » / « Groupe » d'une
# grille de module. La signification est laissée à l'enseignant.
SUBJECT_COLORS = ("green", "yellow", "red", "grey")


class School(db.Model):
    __tablename__ = "school"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    # Propriétaire : l'enseignant qui l'a créée. NULL = école commune (admin),
    # visible par tous les enseignants.
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=True)
    # Facturation : destinataires des factures (emails), contacts en copie,
    # numéro de contrat et observation libre.
    billing_emails = db.Column(db.String(500))
    billing_cc_emails = db.Column(db.String(500))
    contract_number = db.Column(db.String(100))
    observation = db.Column(db.Text)

    classes = db.relationship("Class", backref="school", cascade="all, delete-orphan")
    owner = db.relationship("Teacher", backref="owned_schools")


class AcademicYear(db.Model):
    __tablename__ = "academic_year"
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(20), nullable=False)  # ex. "2025-2026"
    # Propriétaire : cf. School.teacher_id. NULL = année commune (admin).
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=True)

    classes = db.relationship("Class", backref="academic_year", cascade="all, delete-orphan")
    owner = db.relationship("Teacher", backref="owned_years")


class Teacher(UserMixin, db.Model):
    __tablename__ = "teacher"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="teacher")  # admin | teacher

    classes = db.relationship("Class", backref="teacher")

    @property
    def is_admin(self):
        return self.role == "admin"


class Class(db.Model):
    __tablename__ = "class"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey("school.id"), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_year.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    hourly_rate = db.Column(db.Float)  # taux horaire €/h pour la facturation
    # Niveau (Bachelor, Mastère, L3…) : regroupe les classes d'une école dans
    # le bilan NDA (cadre G, heures-stagiaires par école et par niveau).
    level = db.Column(db.String(60))

    modules = db.relationship("Module", backref="klass", cascade="all, delete-orphan")
    enrollments = db.relationship("Enrollment", backref="klass", cascade="all, delete-orphan")


class Module(db.Model):
    __tablename__ = "module"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    discord_url = db.Column(db.String(500))  # lien vers le salon Discord (cliquable)
    # Second lien Discord : le salon « de référence » (ressources, consignes…).
    discord_ref_url = db.Column(db.String(500))
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    work_mode = db.Column(db.String(20), nullable=False, default=WORK_MODE_INDIVIDUAL)
    # Suivi de la transmission des notes à l'établissement.
    notes_sent = db.Column(db.Boolean, nullable=False, default=False)
    notes_sent_date = db.Column(db.Date)
    notes_sent_method = db.Column(db.String(20))   # mail | institutional | other
    notes_sent_detail = db.Column(db.String(200))  # précision libre (outil, remarque)

    grade_dates = db.relationship(
        "GradeDate", backref="module", cascade="all, delete-orphan",
        order_by="GradeDate.position",
    )
    note_columns = db.relationship(
        "NoteColumn", backref="module", cascade="all, delete-orphan",
        order_by="NoteColumn.position",
    )
    groups = db.relationship("Group", backref="module", cascade="all, delete-orphan")
    subject_colors = db.relationship(
        "SubjectColor", backref="module", cascade="all, delete-orphan",
    )

    @property
    def is_group_mode(self):
        return self.work_mode == WORK_MODE_GROUP


class GradeDate(db.Model):
    __tablename__ = "grade_date"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False)
    label = db.Column(db.String(120))
    date = db.Column(db.Date, default=date_type.today)
    position = db.Column(db.Integer, default=0)
    # Durée de la séance en heures (1, 2, 2.5...). Facultative : les séances
    # créées avant cette colonne n'en ont pas, et une séance peut rester sans
    # durée connue. Sert au cumul d'heures du module (cf. taux horaire de la
    # classe), jamais au calcul des notes.
    duration_hours = db.Column(db.Float)
    # Référence de facturation libre (n° de facture, de lot…). Une séance qui
    # en porte une est considérée comme facturée : grisée sur la page de
    # facturation et exclue du « tout cocher ».
    billing_ref = db.Column(db.String(120))

    star_columns = db.relationship(
        "StarColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="StarColumn.position",
    )
    url_columns = db.relationship(
        "UrlColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="UrlColumn.position",
    )
    text_columns = db.relationship(
        "TextColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="TextColumn.position",
    )
    presence_columns = db.relationship(
        "PresenceColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="PresenceColumn.position",
    )


class StarColumn(db.Model):
    __tablename__ = "star_column"
    id = db.Column(db.Integer, primary_key=True)
    grade_date_id = db.Column(db.Integer, db.ForeignKey("grade_date.id"), nullable=False)
    title = db.Column(db.String(120))
    position = db.Column(db.Integer, default=0)

    stars = db.relationship("Star", backref="star_column", cascade="all, delete-orphan")


class UrlColumn(db.Model):
    __tablename__ = "url_column"
    id = db.Column(db.Integer, primary_key=True)
    grade_date_id = db.Column(db.Integer, db.ForeignKey("grade_date.id"), nullable=False)
    title = db.Column(db.String(120))
    position = db.Column(db.Integer, default=0)

    values = db.relationship("UrlValue", backref="url_column", cascade="all, delete-orphan")


class TextColumn(db.Model):
    """Colonne de texte libre rattachée à une séance.

    Permet de consigner une remarque propre à cette séance (« a présenté seul »,
    « rendu hors délai »…), sans incidence sur les étoiles ni sur la note /20.
    Distincte du commentaire général, qui vaut pour tout le module.
    """
    __tablename__ = "text_column"
    id = db.Column(db.Integer, primary_key=True)
    grade_date_id = db.Column(db.Integer, db.ForeignKey("grade_date.id"), nullable=False)
    title = db.Column(db.String(120))
    position = db.Column(db.Integer, default=0)

    values = db.relationship("TextValue", backref="text_column", cascade="all, delete-orphan")


class PresenceColumn(db.Model):
    """Colonne « Présence » rattachée à une séance.

    Chaque cellule prend une valeur de `grading.PRESENCE_STATUSES` (Présent,
    Absent, Retard, Pas de PC). Sans incidence sur les étoiles ni sur la note
    /20 ; alimente la synthèse de séance.
    """
    __tablename__ = "presence_column"
    id = db.Column(db.Integer, primary_key=True)
    grade_date_id = db.Column(db.Integer, db.ForeignKey("grade_date.id"), nullable=False)
    title = db.Column(db.String(120))
    position = db.Column(db.Integer, default=0)

    values = db.relationship("PresenceValue", backref="presence_column",
                             cascade="all, delete-orphan")


class NoteColumn(db.Model):
    __tablename__ = "note_column"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)  # "Note CC", "Note Examen"...
    position = db.Column(db.Integer, default=0)

    values = db.relationship("NoteValue", backref="note_column", cascade="all, delete-orphan")


class Student(db.Model):
    __tablename__ = "student"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160))
    discord_alias = db.Column(db.String(120))
    github_url = db.Column(db.String(300))
    # Étudiant actif ; False = "neutralisé" (a quitté l'école) : grisé dans les
    # modules et exclu du calcul du prorata. Ses étoiles restent conservées.
    active = db.Column(db.Boolean, nullable=False, default=True)

    enrollments = db.relationship("Enrollment", backref="student", cascade="all, delete-orphan")


class Enrollment(db.Model):
    __tablename__ = "enrollment"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    general_comment = db.Column(db.Text)  # commentaire général de l'enseignant


class Group(db.Model):
    __tablename__ = "group"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    comment = db.Column(db.Text)  # commentaire général du groupe (GroupComment fusionné)

    members = db.relationship("GroupMember", backref="group", cascade="all, delete-orphan")


class GroupMember(db.Model):
    __tablename__ = "group_member"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)

    # Cascade déclarée côté étudiant : supprimer un étudiant (retrait de sa
    # dernière classe) doit emporter ses affectations de groupe. Sans elle, la
    # ligne restait avec un `student_id` pointant dans le vide et la grille du
    # module en groupe plantait en lisant `member.student.active`.
    student = db.relationship(
        "Student",
        backref=db.backref("group_memberships", cascade="all, delete-orphan"),
    )


class Star(db.Model):
    __tablename__ = "star"
    id = db.Column(db.Integer, primary_key=True)
    subject_type = db.Column(db.String(10), nullable=False)  # student | group
    subject_id = db.Column(db.Integer, nullable=False)
    star_column_id = db.Column(db.Integer, db.ForeignKey("star_column.id"), nullable=False)
    value = db.Column(db.String(20), nullable=False, default="0")  # "0".."4" ou statut

    __table_args__ = (
        db.UniqueConstraint("subject_type", "subject_id", "star_column_id",
                            name="uq_star_subject_col"),
    )


class UrlValue(db.Model):
    __tablename__ = "url_value"
    id = db.Column(db.Integer, primary_key=True)
    subject_type = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    url_column_id = db.Column(db.Integer, db.ForeignKey("url_column.id"), nullable=False)
    url = db.Column(db.String(500))

    __table_args__ = (
        db.UniqueConstraint("subject_type", "subject_id", "url_column_id",
                            name="uq_url_subject_col"),
    )


class TextValue(db.Model):
    __tablename__ = "text_value"
    id = db.Column(db.Integer, primary_key=True)
    subject_type = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    text_column_id = db.Column(db.Integer, db.ForeignKey("text_column.id"), nullable=False)
    content = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("subject_type", "subject_id", "text_column_id",
                            name="uq_text_subject_col"),
    )


class PresenceValue(db.Model):
    __tablename__ = "presence_value"
    id = db.Column(db.Integer, primary_key=True)
    subject_type = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    presence_column_id = db.Column(db.Integer, db.ForeignKey("presence_column.id"),
                                   nullable=False)
    status = db.Column(db.String(20), nullable=False)  # cf. PRESENCE_STATUSES

    __table_args__ = (
        db.UniqueConstraint("subject_type", "subject_id", "presence_column_id",
                            name="uq_presence_subject_col"),
    )


class NoteValue(db.Model):
    __tablename__ = "note_value"
    id = db.Column(db.Integer, primary_key=True)
    subject_type = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    note_column_id = db.Column(db.Integer, db.ForeignKey("note_column.id"), nullable=False)
    score = db.Column(db.Float)  # note manuelle /20

    __table_args__ = (
        db.UniqueConstraint("subject_type", "subject_id", "note_column_id",
                            name="uq_note_subject_col"),
    )


# Demi-journées d'une journée de planning (valeur -> libellé).
HALF_AM, HALF_PM = "am", "pm"
HALF_DAYS = {HALF_AM: "Matin", HALF_PM: "Après-midi"}


class PlanningSlot(db.Model):
    """Demi-journée réservée par un enseignant : il n'y est pas disponible.

    Une ligne = une demi-journée réservée. L'absence de ligne signifie
    « disponible » : le planning d'une année vierge ne coûte donc rien en base,
    et décocher une case supprime simplement la ligne.

    Une **demande de réservation** déposée par un client depuis un lien de
    partage est la même ligne, marquée `pending` et rattachée à son lien : la
    contrainte d'unicité fait alors tout le travail d'exclusivité — tant que la
    demande existe, ni l'enseignant ni un autre client ne peut prendre la
    demi-journée. La valider revient à lever `pending` ; le lien reste attaché
    pour savoir à quel client la demi-journée a été accordée.

    L'année académique n'est pas stockée : elle se déduit de la date (cf.
    `planning.year_bounds`). Une seule vérité, et redéfinir les bornes d'une
    année ne laisse pas de réservations orphelines derrière elle.
    """
    __tablename__ = "planning_slot"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    half = db.Column(db.String(2), nullable=False)  # am | pm
    link_id = db.Column(db.Integer, db.ForeignKey("planning_link.id"))
    pending = db.Column(db.Boolean, nullable=False, default=False)

    teacher = db.relationship(
        "Teacher",
        backref=db.backref("planning_slots", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint("teacher_id", "date", "half",
                            name="uq_planning_teacher_date_half"),
    )


# Couleurs proposées tour à tour à la création d'un lien. Aucune n'est proche
# du rouge des demi-journées « Non disponible » : une demande doit se
# distinguer d'un cours au premier regard.
LINK_COLORS = ("#fde68a", "#bbf7d0", "#bfdbfe", "#ddd6fe", "#fed7aa", "#a5f3fc")


class PlanningLink(db.Model):
    """Lien de réservation du planning d'un enseignant, remis à un client.

    Le jeton vaut mot de passe : sans compte, il permet de consulter les
    disponibilités de l'année et de **demander** des demi-journées libres.
    Chaque client reçoit son propre lien, nommé et coloré : les demandes
    apparaissent dans cette couleur sur le planning de l'enseignant, qui les
    valide ou les refuse. Supprimer le lien coupe l'accès de ce client seul.
    """
    __tablename__ = "planning_link"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_year.id"),
                                 nullable=False)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(7), nullable=False, default=LINK_COLORS[0])  # #rrggbb
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    teacher = db.relationship(
        "Teacher",
        backref=db.backref("planning_links", cascade="all, delete-orphan"),
    )
    academic_year = db.relationship(
        "AcademicYear",
        backref=db.backref("planning_links", cascade="all, delete-orphan"),
    )
    # Pas de cascade : les demi-journées validées survivent à leur lien (elles
    # sont devenues des réservations de l'enseignant). Seules les demandes en
    # attente partent avec lui, cf. `_drop_pending_requests`.
    slots = db.relationship("PlanningSlot", backref="link")


@event.listens_for(Session, "before_flush")
def _drop_pending_requests(session, _context, _instances):
    """Un lien supprimé emporte ses demandes en attente.

    Fait ici plutôt que dans la route de suppression : un lien disparaît aussi
    par cascade (année ou enseignant supprimé), et une demande orpheline
    bloquerait la demi-journée sans que personne puisse plus la valider.
    """
    for obj in list(session.deleted):
        if isinstance(obj, PlanningLink):
            for slot in list(obj.slots):
                if slot.pending:
                    session.delete(slot)


class SubjectColor(db.Model):
    """Couleur de fond de la cellule d'un sujet, propre à un module.

    Un même étudiant peut donc être vert dans un module et rouge dans un
    autre. L'absence de ligne = aucune couleur.
    """
    __tablename__ = "subject_color"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False)
    subject_type = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(10), nullable=False)  # cf. SUBJECT_COLORS

    __table_args__ = (
        db.UniqueConstraint("module_id", "subject_type", "subject_id",
                            name="uq_color_module_subject"),
    )
