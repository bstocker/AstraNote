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
    # Facturation : destinataires des factures (emails) et observation libre.
    billing_emails = db.Column(db.String(500))
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

    L'année académique n'est pas stockée : elle se déduit de la date (cf.
    `planning.year_bounds`). Une seule vérité, et redéfinir les bornes d'une
    année ne laisse pas de réservations orphelines derrière elle.
    """
    __tablename__ = "planning_slot"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    half = db.Column(db.String(2), nullable=False)  # am | pm

    teacher = db.relationship(
        "Teacher",
        backref=db.backref("planning_slots", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint("teacher_id", "date", "half",
                            name="uq_planning_teacher_date_half"),
    )


class PlanningShare(db.Model):
    """Lien public de consultation du planning d'un enseignant pour une année.

    Le jeton vaut mot de passe : il donne un accès en **lecture seule** sans
    authentification. Un lien par (enseignant, année), régénérable — régénérer
    remplace le jeton, ce qui invalide le lien précédemment diffusé.
    """
    __tablename__ = "planning_share"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_year.id"),
                                 nullable=False)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    teacher = db.relationship(
        "Teacher",
        backref=db.backref("planning_shares", cascade="all, delete-orphan"),
    )
    academic_year = db.relationship(
        "AcademicYear",
        backref=db.backref("planning_shares", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint("teacher_id", "academic_year_id",
                            name="uq_planning_share_teacher_year"),
    )


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
