"""Modèle de données AstraNote (SQLite) — cf. fiche fonctionnelle §6.

Hiérarchie : School > AcademicYear > Class > Module > GradeDate > StarColumn.
L'unité notée (`subject`) est l'étudiant (mode individuel) ou le groupe
(mode groupe) : Star / UrlValue / NoteValue référencent l'un ou l'autre via
(subject_type, subject_id).
"""
from datetime import date as date_type

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

SUBJECT_STUDENT = "student"
SUBJECT_GROUP = "group"

WORK_MODE_INDIVIDUAL = "individual"
WORK_MODE_GROUP = "group"


class School(db.Model):
    __tablename__ = "school"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    # Propriétaire : l'enseignant qui l'a créée. NULL = école commune (admin),
    # visible par tous les enseignants.
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=True)

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

    modules = db.relationship("Module", backref="klass", cascade="all, delete-orphan")
    enrollments = db.relationship("Enrollment", backref="klass", cascade="all, delete-orphan")


class Module(db.Model):
    __tablename__ = "module"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    discord_channel = db.Column(db.String(120))
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    work_mode = db.Column(db.String(20), nullable=False, default=WORK_MODE_INDIVIDUAL)

    grade_dates = db.relationship(
        "GradeDate", backref="module", cascade="all, delete-orphan",
        order_by="GradeDate.position",
    )
    note_columns = db.relationship(
        "NoteColumn", backref="module", cascade="all, delete-orphan",
        order_by="NoteColumn.position",
    )
    groups = db.relationship("Group", backref="module", cascade="all, delete-orphan")

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

    star_columns = db.relationship(
        "StarColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="StarColumn.position",
    )
    url_columns = db.relationship(
        "UrlColumn", backref="grade_date", cascade="all, delete-orphan",
        order_by="UrlColumn.position",
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

    student = db.relationship("Student")


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
