"""Tests de bout en bout des flux clés d'AstraNote."""
from io import BytesIO

from openpyxl import load_workbook

from astranote import create_app, grading
from astranote.models import (
    db, School, AcademicYear, Class, Module, Student, Enrollment,
    GradeDate, StarColumn, UrlColumn, NoteColumn, Group, Star, UrlValue,
    NoteValue, SubjectColor, Teacher,
)
from conftest import make_teacher, login, ADMIN_PW, TestConfig


# --------------------------------------------------------------------------- #
# Helpers de construction
# --------------------------------------------------------------------------- #
def bootstrap_class(app, admin, students=("Alice", "Bob", "Chloe"), work_mode="individual"):
    admin.post("/schools", data={"name": "EPSI"})
    admin.post("/years", data={"label": "2025-2026"})
    with app.app_context():
        sid = School.query.first().id
        yid = AcademicYear.query.first().id
    admin.post("/classes/new", data={"name": "B3", "school_id": sid,
                                     "academic_year_id": yid, "teacher_id": 1})
    with app.app_context():
        cid = Class.query.first().id
    for n in students:
        admin.post(f"/classes/{cid}/students", data={"full_name": n})
    admin.post(f"/classes/{cid}/modules/new", data={"name": "Crypto", "work_mode": work_mode})
    with app.app_context():
        mid = Module.query.first().id
        ids = {s.full_name: s.id for s in Student.query.all()}
        enr = {e.student.full_name: e.id for e in Class.query.get(cid).enrollments}
    return cid, mid, ids, enr


def add_star_column(app, admin, mid):
    admin.post(f"/modules/{mid}/dates", data={"date": "2025-09-30"})
    with app.app_context():
        did = GradeDate.query.first().id
    admin.post(f"/dates/{did}/star-columns", data={"title": "A"})
    with app.app_context():
        return did, StarColumn.query.order_by(StarColumn.id.desc()).first().id


# --------------------------------------------------------------------------- #
# Auth & CSRF
# --------------------------------------------------------------------------- #
def test_login_required(client):
    assert client.get("/", follow_redirects=False).status_code == 302


def test_csrf_field_rendered(client):
    assert b"csrf_token" in client.get("/login").data


# --------------------------------------------------------------------------- #
# Notation : prorata R1–R10
# --------------------------------------------------------------------------- #
def test_prorata_and_rounding(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    _, scid = add_star_column(app, admin, mid)
    admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Alice"], "column_id": scid, "value": "4"})
    admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Bob"], "column_id": scid, "value": "2"})
    r = admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Chloe"], "column_id": scid, "value": "3"})
    g = r.get_json()["grades"]
    assert g[str(ids["Alice"])]["note"] == 20.0 and g[str(ids["Alice"])]["is_reference"]
    assert g[str(ids["Bob"])]["note"] == 10.0
    assert g[str(ids["Chloe"])]["note"] == 15.0


def test_round_half():
    assert grading.round_half(3 / 7 * 20) == 8.5
    assert grading.round_half(2 / 3 * 20) == 13.5


def test_na_when_no_stars(app, admin):
    _, mid, _, _ = bootstrap_class(app, admin)
    add_star_column(app, admin, mid)
    assert b"N/A" in admin.get(f"/modules/{mid}").data


# --------------------------------------------------------------------------- #
# Neutralisation
# --------------------------------------------------------------------------- #
def test_neutralized_excluded_and_locked(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    _, scid = add_star_column(app, admin, mid)
    for n, v in [("Alice", "4"), ("Bob", "2"), ("Chloe", "3")]:
        admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids[n], "column_id": scid, "value": v})
    admin.post(f"/enrollments/{enr['Alice']}/toggle-active")
    # Saisie bloquée pour Alice (neutralisée)
    r = admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Alice"], "column_id": scid, "value": "1"})
    assert r.status_code == 403
    # Recalcul : Chloe devient référence, Bob 2/3*20 = 13.5
    r = admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Bob"], "column_id": scid, "value": "2"})
    g = r.get_json()["grades"]
    assert g[str(ids["Alice"])]["note"] == "—"
    assert g[str(ids["Chloe"])]["note"] == 20.0
    assert g[str(ids["Bob"])]["note"] == 13.5


# --------------------------------------------------------------------------- #
# Périmètre écoles/années
# --------------------------------------------------------------------------- #
def test_school_scoping(app, admin):
    make_teacher(app, "Prof A", "a@x.fr")
    admin.post("/schools", data={"name": "Commune"})  # admin => commune (NULL)
    ca = app.test_client()
    login(ca, "a@x.fr")
    ca.post("/schools", data={"name": "EcoleA"})
    html = ca.get("/schools").get_data(as_text=True)
    assert "EcoleA" in html and "Commune" in html
    # Un 2e prof ne voit pas EcoleA
    make_teacher(app, "Prof B", "b@x.fr")
    cb = app.test_client()
    login(cb, "b@x.fr")
    assert "EcoleA" not in cb.get("/schools").get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Nettoyage des orphelins
# --------------------------------------------------------------------------- #
def test_orphan_cleanup_on_student_delete(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    _, scid = add_star_column(app, admin, mid)
    admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Alice"], "column_id": scid, "value": "3"})
    with app.app_context():
        assert Star.query.filter_by(subject_type="student", subject_id=ids["Alice"]).count() == 1
    admin.post(f"/enrollments/{enr['Alice']}/delete")
    with app.app_context():
        assert Star.query.filter_by(subject_type="student", subject_id=ids["Alice"]).count() == 0
        assert db.session.get(Student, ids["Alice"]) is None


def test_orphan_cleanup_on_group_delete(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin, work_mode="group")
    admin.post(f"/modules/{mid}/groups", data={"name": "G1"})
    with app.app_context():
        gid = Group.query.first().id
    _, scid = add_star_column(app, admin, mid)
    admin.post(f"/modules/{mid}/save-star", json={"subject_id": gid, "column_id": scid, "value": "2"})
    with app.app_context():
        assert Star.query.filter_by(subject_type="group", subject_id=gid).count() == 1
    admin.post(f"/groups/{gid}/delete")
    with app.app_context():
        assert Star.query.filter_by(subject_type="group", subject_id=gid).count() == 0


# --------------------------------------------------------------------------- #
# Renommage / réorganisation
# --------------------------------------------------------------------------- #
def test_rename_and_reorder_columns(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/dates", data={"date": "2025-09-30"})
    with app.app_context():
        did = GradeDate.query.first().id
    admin.post(f"/dates/{did}/star-columns", data={"title": "A"})
    admin.post(f"/dates/{did}/star-columns", data={"title": "B"})
    with app.app_context():
        cols = StarColumn.query.order_by(StarColumn.position).all()
        a_id, b_id = cols[0].id, cols[1].id
    admin.post(f"/star-columns/{a_id}/rename", data={"title": "Alpha"})
    admin.post(f"/star-columns/{a_id}/move", data={"dir": "down"})
    with app.app_context():
        cols = StarColumn.query.order_by(StarColumn.position).all()
        assert cols[0].id == b_id and cols[1].id == a_id
        assert db.session.get(StarColumn, a_id).title == "Alpha"


# --------------------------------------------------------------------------- #
# Édition module
# --------------------------------------------------------------------------- #
def test_edit_module_discord(app, admin):
    _, mid, _, _ = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/edit", data={
        "name": "Crypto+", "discord_url": "https://discord.com/z",
        "discord_ref_url": "https://discord.com/ref",
    })
    with app.app_context():
        m = db.session.get(Module, mid)
        assert m.name == "Crypto+" and m.discord_url == "https://discord.com/z"
        assert m.discord_ref_url == "https://discord.com/ref"
    # Les deux liens sont indépendants : vider l'un conserve l'autre.
    admin.post(f"/modules/{mid}/edit", data={
        "name": "Crypto+", "discord_url": "", "discord_ref_url": "https://discord.com/ref",
    })
    html = admin.get(f"/modules/{mid}").get_data(as_text=True)
    with app.app_context():
        m = db.session.get(Module, mid)
        assert m.discord_url is None and m.discord_ref_url == "https://discord.com/ref"
    assert "Discord de référence" in html


def test_create_module_with_both_discord_links(app, admin):
    cid, _, _, _ = bootstrap_class(app, admin)
    admin.post(f"/classes/{cid}/modules/new", data={
        "name": "Réseau", "work_mode": "individual",
        "discord_url": "https://discord.com/a", "discord_ref_url": "https://discord.com/b",
    })
    with app.app_context():
        m = Module.query.filter_by(name="Réseau").first()
        assert m.discord_url == "https://discord.com/a"
        assert m.discord_ref_url == "https://discord.com/b"


# --------------------------------------------------------------------------- #
# Export / import Excel
# --------------------------------------------------------------------------- #
def test_excel_round_trip(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/note-columns", data={"title": "Note CC"})
    with app.app_context():
        ncid = NoteColumn.query.first().id
    r = admin.get(f"/modules/{mid}/export.xlsx")
    assert r.status_code == 200
    wb = load_workbook(BytesIO(r.data))
    ws = wb.active
    # trouve la ligne d'Alice et écrit sa note
    for row in range(3, 8):
        if ws.cell(row=row, column=1).value == ids["Alice"]:
            ws.cell(row=row, column=3).value = 14.5
            ws.cell(row=row, column=4).value = "Bien"
            break
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    admin.post(f"/modules/{mid}/import", data={"file": (out, "n.xlsx")},
               content_type="multipart/form-data")
    with app.app_context():
        nv = NoteValue.query.filter_by(subject_type="student", subject_id=ids["Alice"],
                                       note_column_id=ncid).first()
        assert nv.score == 14.5
        comment = Enrollment.query.filter_by(student_id=ids["Alice"], class_id=cid).first().general_comment
        assert comment == "Bien"


def test_import_rejects_out_of_range(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/note-columns", data={"title": "Note CC"})
    with app.app_context():
        ncid = NoteColumn.query.first().id
    r = admin.get(f"/modules/{mid}/export.xlsx")
    wb = load_workbook(BytesIO(r.data))
    ws = wb.active
    for row in range(3, 8):
        if ws.cell(row=row, column=1).value == ids["Bob"]:
            ws.cell(row=row, column=3).value = 25   # hors 0-20
            break
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    resp = admin.post(f"/modules/{mid}/import", data={"file": (out, "n.xlsx")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert "hors 0" in resp.get_data(as_text=True)
    with app.app_context():
        assert NoteValue.query.filter_by(subject_id=ids["Bob"], note_column_id=ncid).first() is None


# --------------------------------------------------------------------------- #
# Tableau de bord : avancement de saisie
# --------------------------------------------------------------------------- #
def test_notes_sent_tracking(app, admin):
    _, mid, _, _ = bootstrap_class(app, admin)
    # Marque comme envoyées par mail à une date donnée.
    admin.post(f"/modules/{mid}/notes-sent", data={
        "notes_sent": "on", "notes_sent_date": "2026-07-01",
        "notes_sent_method": "mail", "notes_sent_detail": "au secrétariat",
    })
    with app.app_context():
        m = db.session.get(Module, mid)
        assert m.notes_sent is True
        assert m.notes_sent_date.isoformat() == "2026-07-01"
        assert m.notes_sent_method == "mail"
        assert m.notes_sent_detail == "au secrétariat"
    assert "Notes envoyées" in admin.get(f"/modules/{mid}").get_data(as_text=True)
    # Décoche : tout est réinitialisé.
    admin.post(f"/modules/{mid}/notes-sent", data={})
    with app.app_context():
        m = db.session.get(Module, mid)
        assert m.notes_sent is False and m.notes_sent_date is None
        assert m.notes_sent_method is None
    # Moyen invalide ignoré.
    admin.post(f"/modules/{mid}/notes-sent", data={"notes_sent": "on", "notes_sent_method": "pigeon"})
    with app.app_context():
        assert db.session.get(Module, mid).notes_sent_method is None


def test_dashboard_shows_notes_sent(app, admin):
    _, mid, _, _ = bootstrap_class(app, admin)
    html = admin.get("/").get_data(as_text=True)
    assert "check-unsent" in html          # module listé, non envoyé
    admin.post(f"/modules/{mid}/notes-sent", data={"notes_sent": "on", "notes_sent_date": "2026-07-01"})
    html = admin.get("/").get_data(as_text=True)
    assert "check-sent" in html and "✔" in html


def test_notes_sent_defaults_to_today(app, admin):
    from datetime import date
    _, mid, _, _ = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/notes-sent", data={"notes_sent": "on"})  # sans date
    with app.app_context():
        assert db.session.get(Module, mid).notes_sent_date == date.today()


def test_change_password(app, admin):
    # Mauvais mot de passe actuel -> refusé
    r = admin.post("/account", data={"current_password": "wrong",
                                     "new_password": "newpass12", "confirm_password": "newpass12"},
                   follow_redirects=True)
    assert "incorrect" in r.get_data(as_text=True)
    # Trop court -> refusé
    r = admin.post("/account", data={"current_password": ADMIN_PW,
                                     "new_password": "court", "confirm_password": "court"},
                   follow_redirects=True)
    assert "8 caractères" in r.get_data(as_text=True)
    # Correct -> le nouveau mot de passe fonctionne
    admin.post("/account", data={"current_password": ADMIN_PW,
                                 "new_password": "newpass12", "confirm_password": "newpass12"})
    c2 = app.test_client()
    r = c2.post("/login", data={"email": "admin@astranote.local", "password": "newpass12"},
                follow_redirects=True)
    assert "Tableau de bord" in r.get_data(as_text=True)


def test_rename_school_and_year(app, admin):
    admin.post("/schools", data={"name": "EPSI"})
    admin.post("/years", data={"label": "2025-2026"})
    with app.app_context():
        sid = School.query.first().id
        yid = AcademicYear.query.first().id
    admin.post(f"/schools/{sid}/rename", data={"name": "EPSI Lille"})
    admin.post(f"/years/{yid}/rename", data={"label": "2026-2027"})
    with app.app_context():
        assert db.session.get(School, sid).name == "EPSI Lille"
        assert db.session.get(AcademicYear, yid).label == "2026-2027"


def test_teacher_cannot_rename_common_school(app, admin):
    admin.post("/schools", data={"name": "Commune"})  # admin => commune (NULL)
    with app.app_context():
        sid = School.query.first().id
    make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    assert c.post(f"/schools/{sid}/rename", data={"name": "Pirate"}).status_code == 403


def test_school_billing_and_class_rate(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    with app.app_context():
        sid = School.query.first().id
    # Infos de facturation de l'école
    admin.post(f"/schools/{sid}/details", data={
        "billing_emails": "compta@epsi.fr, direction@epsi.fr",
        "observation": "Payer sous 30 jours.",
    })
    # Taux horaire de la classe (virgule décimale acceptée)
    admin.post(f"/classes/{cid}/billing", data={"hourly_rate": "55,5"})
    with app.app_context():
        s = db.session.get(School, sid)
        assert s.billing_emails == "compta@epsi.fr, direction@epsi.fr"
        assert s.observation == "Payer sous 30 jours."
        assert db.session.get(Class, cid).hourly_rate == 55.5
    # Affichage sur la fiche de classe
    html = admin.get(f"/classes/{cid}").get_data(as_text=True)
    assert "compta@epsi.fr" in html and "55" in html


def test_invalid_hourly_rate_rejected(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/classes/{cid}/billing", data={"hourly_rate": "55"})
    r = admin.post(f"/classes/{cid}/billing", data={"hourly_rate": "abc"}, follow_redirects=True)
    assert "invalide" in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Class, cid).hourly_rate == 55  # inchangé


def test_teacher_cannot_edit_common_school_billing(app, admin):
    admin.post("/schools", data={"name": "Commune"})
    with app.app_context():
        sid = School.query.first().id
    make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    assert c.post(f"/schools/{sid}/details", data={"billing_emails": "x@x.fr"}).status_code == 403


def test_secure_cookie_flags(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


# --------------------------------------------------------------------------- #
# Administration : sauvegarde de la base
# --------------------------------------------------------------------------- #
def test_admin_page_access_control(app, admin):
    assert admin.get("/admin").status_code == 200
    make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    assert c.get("/admin").status_code == 403
    assert c.get("/admin/download-db").status_code == 403


def test_download_db_returns_sqlite_file(tmp_path):
    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'astranote.db'}"

    a = create_app(FileConfig)
    c = a.test_client()
    c.post("/login", data={"email": "admin@astranote.local", "password": ADMIN_PW})
    r = c.get("/admin/download-db")
    assert r.status_code == 200
    # Un fichier SQLite valide commence par cet en-tête.
    assert r.data[:16] == b"SQLite format 3\x00"
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_dashboard_progress(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    _, scid = add_star_column(app, admin, mid)
    # 1 colonne × 3 étudiants = 3 cellules ; on en remplit 1 => ~33%
    admin.post(f"/modules/{mid}/save-star", json={"subject_id": ids["Alice"], "column_id": scid, "value": "3"})
    with app.app_context():
        from astranote.main import class_saisie_progress
        klass = db.session.get(Class, cid)
        assert class_saisie_progress(klass) == 33


# --------------------------------------------------------------------------- #
# Couleur de fond de la cellule sujet (propre au module)
# --------------------------------------------------------------------------- #
def test_subject_color_is_per_module(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/classes/{cid}/modules/new", data={"name": "Réseau"})
    with app.app_context():
        other = Module.query.filter_by(name="Réseau").first().id

    assert admin.post(f"/modules/{mid}/save-color",
                      json={"subject_id": ids["Alice"], "value": "green"}).status_code == 200
    assert admin.post(f"/modules/{other}/save-color",
                      json={"subject_id": ids["Alice"], "value": "red"}).status_code == 200
    # La même étudiante est verte dans un module, rouge dans l'autre.
    assert "subject col-green" in admin.get(f"/modules/{mid}").get_data(as_text=True)
    assert "subject col-red" in admin.get(f"/modules/{other}").get_data(as_text=True)

    # Valeur vide = retrait : la ligne est supprimée, pas conservée.
    admin.post(f"/modules/{mid}/save-color", json={"subject_id": ids["Alice"], "value": ""})
    with app.app_context():
        assert SubjectColor.query.filter_by(module_id=mid).count() == 0
        assert SubjectColor.query.filter_by(module_id=other).count() == 1


def test_subject_color_rejects_invalid_input(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    # Couleur hors liste
    assert admin.post(f"/modules/{mid}/save-color",
                      json={"subject_id": ids["Alice"], "value": "fuchsia"}).status_code == 400
    # Sujet qui n'appartient pas au module
    assert admin.post(f"/modules/{mid}/save-color",
                      json={"subject_id": 99999, "value": "red"}).status_code == 400
    # Étudiant neutralisé : verrouillé comme le reste de la saisie
    admin.post(f"/enrollments/{enr['Bob']}/toggle-active")
    assert admin.post(f"/modules/{mid}/save-color",
                      json={"subject_id": ids["Bob"], "value": "red"}).status_code == 403
    with app.app_context():
        assert SubjectColor.query.count() == 0


def test_subject_color_purged_on_delete(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    admin.post(f"/modules/{mid}/save-color", json={"subject_id": ids["Alice"], "value": "grey"})
    admin.post(f"/enrollments/{enr['Alice']}/delete")
    with app.app_context():
        assert SubjectColor.query.count() == 0


def test_group_color_purged_on_group_delete(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin, work_mode="group")
    admin.post(f"/modules/{mid}/groups", data={"name": "G1"})
    with app.app_context():
        gid = Group.query.first().id
    assert admin.post(f"/modules/{mid}/save-color",
                      json={"subject_id": gid, "value": "yellow"}).status_code == 200
    assert "subject col-yellow" in admin.get(f"/modules/{mid}").get_data(as_text=True)
    admin.post(f"/groups/{gid}/delete")
    with app.app_context():
        assert SubjectColor.query.count() == 0


# --------------------------------------------------------------------------- #
# Export Excel de la fiche administrative des étudiants
# --------------------------------------------------------------------------- #
def test_export_students_xlsx(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin, students=("Zoe", "Alice"))
    admin.post(f"/enrollments/{enr['Zoe']}/student", data={
        "full_name": "Zoe", "email": "zoe@ecoles-epsi.net",
        "discord_alias": "zozo#1", "github_url": "https://github.com/zoe",
    })
    admin.post(f"/enrollments/{enr['Zoe']}/toggle-active")   # neutralisée

    r = admin.get(f"/classes/{cid}/students.xlsx")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    ws = load_workbook(BytesIO(r.data)).active

    assert ws.cell(row=2, column=1).value == "Nom complet"
    rows = {ws.cell(row=r_, column=1).value: [ws.cell(row=r_, column=c).value
                                              for c in range(1, 6)]
            for r_ in range(3, ws.max_row + 1)}
    assert rows["Zoe"] == ["Zoe", "zoe@ecoles-epsi.net", "zozo#1",
                           "https://github.com/zoe", "Neutralisé"]
    assert rows["Alice"][4] == "Actif"           # les neutralisés restent listés
    assert list(rows) == ["Alice", "Zoe"]        # tri alphabétique
    # Le bouton est proposé sur la fiche de classe.
    assert "students.xlsx" in admin.get(f"/classes/{cid}").get_data(as_text=True)


def test_export_students_respects_scope(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    assert c.get(f"/classes/{cid}/students.xlsx").status_code == 403


# --------------------------------------------------------------------------- #
# Dashboard de classement (podium général + par séance)
# --------------------------------------------------------------------------- #
def test_ranked_places_ties_and_cutoff():
    """Places consécutives, ex æquo groupés, zéros écartés, 5 places max."""
    totals = {"A": 10, "B": 10, "C": 8, "D": 7, "E": 7, "F": 5, "G": 4, "H": 3, "I": 0}
    places = grading.ranked_places(totals)
    assert [(p["place"], sorted(p["ids"]), p["total"]) for p in places] == [
        (1, ["A", "B"], 10),
        (2, ["C"], 8),
        (3, ["D", "E"], 7),
        (4, ["F"], 5),
        (5, ["G"], 4),
    ]
    assert grading.ranked_places({"A": 0, "B": 0}) == []


def test_module_ranking_general_and_per_session(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin, students=("Alice", "Bob", "Chloe"))
    # Deux séances, une colonne d'étoiles chacune.
    for d in ("2025-09-30", "2025-10-07"):
        admin.post(f"/modules/{mid}/dates", data={"date": d})
    with app.app_context():
        dids = [g.id for g in GradeDate.query.order_by(GradeDate.position).all()]
    for did in dids:
        admin.post(f"/dates/{did}/star-columns", data={"title": "Ex"})
    with app.app_context():
        cols = {sc.grade_date_id: sc.id for sc in StarColumn.query.all()}

    # Séance 1 / séance 2 => totaux généraux : Alice 8, Bob 8, Chloe 6.
    for name, (v1, v2) in {"Alice": (4, 4), "Bob": (4, 4), "Chloe": (4, 2)}.items():
        admin.post(f"/modules/{mid}/save-star",
                   json={"subject_id": ids[name], "column_id": cols[dids[0]], "value": str(v1)})
        admin.post(f"/modules/{mid}/save-star",
                   json={"subject_id": ids[name], "column_id": cols[dids[1]], "value": str(v2)})

    html = admin.get(f"/modules/{mid}/ranking").get_data(as_text=True)
    assert "Classement général" in html and "Par séance" in html
    assert "ex æquo" in html          # Alice et Bob à la 1re place
    assert "30/09/2025" in html and "07/10/2025" in html
    # Séance 1 : les trois sont ex æquo à 4★ ; en général Chloe est 2e.
    assert "6 ★" in html and "8 ★" in html


def test_module_ranking_excludes_neutralized(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    _, scid = add_star_column(app, admin, mid)
    admin.post(f"/modules/{mid}/save-star",
               json={"subject_id": ids["Alice"], "column_id": scid, "value": "4"})
    admin.post(f"/modules/{mid}/save-star",
               json={"subject_id": ids["Bob"], "column_id": scid, "value": "2"})
    admin.post(f"/enrollments/{enr['Alice']}/toggle-active")
    html = admin.get(f"/modules/{mid}/ranking").get_data(as_text=True)
    assert "Alice" not in html and "Bob" in html


def test_module_ranking_empty_state_and_scope(app, admin):
    cid, mid, ids, enr = bootstrap_class(app, admin)
    html = admin.get(f"/modules/{mid}/ranking").get_data(as_text=True)
    assert "Aucune étoile saisie" in html
    make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    assert c.get(f"/modules/{mid}/ranking").status_code == 403


# --------------------------------------------------------------------------- #
# Durcissement : redirection de connexion, sujets de saisie, progression
# --------------------------------------------------------------------------- #
def test_login_next_url_must_be_internal(app):
    """Le paramètre `next` ne doit jamais renvoyer vers un site tiers."""
    for hostile in ("https://evil.example.com/", "//evil.example.com/",
                    "/\\evil.example.com/", "http://evil.example.com"):
        c = app.test_client()
        r = c.post(f"/login?next={hostile}",
                   data={"email": "admin@astranote.local", "password": ADMIN_PW})
        assert r.status_code == 302
        assert r.headers["Location"] == "/", hostile

    # Une destination interne reste honorée.
    c = app.test_client()
    r = c.post("/login?next=/schools",
               data={"email": "admin@astranote.local", "password": ADMIN_PW})
    assert r.headers["Location"] == "/schools"


def test_saisie_rejects_subject_outside_module(app, admin):
    """Un sujet étranger au module ne doit créer aucune ligne orpheline."""
    cid, mid, ids, enr = bootstrap_class(app, admin)
    did, scid = add_star_column(app, admin, mid)
    admin.post(f"/dates/{did}/url-columns", data={"title": "Rendu"})
    admin.post(f"/modules/{mid}/note-columns", data={"title": "Note CC"})
    with app.app_context():
        ucid = UrlColumn.query.first().id
        ncid = NoteColumn.query.first().id
        # Étudiant réel, actif, mais inscrit dans aucune classe de ce module.
        outsider = Student(full_name="Étranger")
        db.session.add(outsider)
        db.session.commit()
        oid = outsider.id

    for path, payload in (
        ("save-star", {"column_id": scid, "value": "4"}),
        ("save-url", {"column_id": ucid, "value": "http://x.fr"}),
        ("save-note", {"column_id": ncid, "value": "12"}),
        ("save-color", {"value": "red"}),
        ("save-comment", {"value": "coucou"}),
    ):
        r = admin.post(f"/modules/{mid}/{path}", json={"subject_id": oid, **payload})
        assert r.status_code == 400, path
        assert r.get_json()["error"] == "Sujet invalide"

    with app.app_context():
        assert Star.query.filter_by(subject_id=oid).count() == 0
        assert UrlValue.query.filter_by(subject_id=oid).count() == 0
        assert NoteValue.query.filter_by(subject_id=oid).count() == 0
        assert SubjectColor.query.filter_by(subject_id=oid).count() == 0


def test_saisie_rejects_unknown_group(app, admin):
    """En mode groupe, `_subject_is_active` est toujours vrai : c'est
    l'appartenance au module qui doit filtrer."""
    cid, mid, ids, enr = bootstrap_class(app, admin, work_mode="group")
    _, scid = add_star_column(app, admin, mid)
    r = admin.post(f"/modules/{mid}/save-star",
                   json={"subject_id": 4242, "column_id": scid, "value": "4"})
    assert r.status_code == 400
    with app.app_context():
        assert Star.query.filter_by(subject_type="group", subject_id=4242).count() == 0


def test_dashboard_progress_ignores_neutralized(app, admin):
    """Les étoiles d'un neutralisé ne comptent pas : il est hors dénominateur."""
    cid, mid, ids, enr = bootstrap_class(app, admin, students=("Alice", "Bob"))
    _, scid = add_star_column(app, admin, mid)
    admin.post(f"/modules/{mid}/save-star",
               json={"subject_id": ids["Bob"], "column_id": scid, "value": "3"})
    admin.post(f"/enrollments/{enr['Bob']}/toggle-active")
    with app.app_context():
        from astranote.main import class_saisie_progress
        klass = db.session.get(Class, cid)
        # Reste Alice, active et non saisie : 0 % (et non 100 %).
        assert class_saisie_progress(klass) == 0


def test_delete_teacher_blocked_by_owned_structure(app, admin):
    """Supprimer un enseignant propriétaire d'une école laisserait un
    teacher_id orphelin — donc une école « commune » par accident."""
    tid = make_teacher(app, "Prof", "p@x.fr")
    c = app.test_client()
    login(c, "p@x.fr")
    c.post("/schools", data={"name": "École du prof"})

    admin.post(f"/teachers/{tid}/delete")
    with app.app_context():
        assert db.session.get(Teacher, tid) is not None
        assert School.query.filter_by(teacher_id=tid).count() == 1

    # Une fois l'école supprimée, la suppression passe.
    with app.app_context():
        db.session.delete(School.query.filter_by(teacher_id=tid).first())
        db.session.commit()
    admin.post(f"/teachers/{tid}/delete")
    with app.app_context():
        assert db.session.get(Teacher, tid) is None


def test_upload_size_is_capped(app, admin):
    """Un .xlsx géant est refusé avant d'être chargé en mémoire par openpyxl."""
    assert app.config["MAX_CONTENT_LENGTH"] == 8 * 1024 * 1024
    cid, mid, ids, enr = bootstrap_class(app, admin)
    huge = BytesIO(b"x" * (app.config["MAX_CONTENT_LENGTH"] + 1024))
    r = admin.post(f"/modules/{mid}/import",
                   data={"file": (huge, "notes.xlsx")},
                   content_type="multipart/form-data")
    assert r.status_code == 302
    assert "trop volumineux" in admin.get("/", follow_redirects=True).get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Recherche d'étudiant
# --------------------------------------------------------------------------- #
def test_search_ignores_case_and_accents(app, admin):
    """« Herve », « HERVÉ » ou « leger » doivent trouver « Hervé Léger ».

    Le LIKE de SQLite n'ignore pas les accents et ne replie la casse que pour
    l'ASCII : un pré-filtre SQL sur la chaîne brute écartait ces candidats
    avant même le filtre sans accents.
    """
    bootstrap_class(app, admin, students=("Hervé Léger",))
    for q in ("Hervé", "Herve", "herve", "HERVÉ", "leger", "LÉGER", "rve lé"):
        html = admin.get("/search", query_string={"q": q}).get_data(as_text=True)
        assert "Hervé Léger" in html, q


def test_search_matches_email_and_discord(app, admin):
    cid, _, _, _ = bootstrap_class(app, admin, students=())
    admin.post(f"/classes/{cid}/students",
               data={"full_name": "Zoé Martin", "email": "zoe@ecole.fr",
                     "discord_alias": "Zozo"})
    for q in ("zoe@ecole", "ZOZO"):
        html = admin.get("/search", query_string={"q": q}).get_data(as_text=True)
        assert "Zoé Martin" in html, q
    # Pas de faux positif : le nom d'un autre étudiant ne doit rien ramener.
    html = admin.get("/search", query_string={"q": "Alice"}).get_data(as_text=True)
    assert "Zoé Martin" not in html


def test_search_respects_scope(app, admin):
    """Le pré-filtre SQL supprimé, le cloisonnement repose entièrement sur le
    join Enrollment/Class : un autre enseignant ne doit toujours rien voir."""
    bootstrap_class(app, admin, students=("Hervé Léger",))
    make_teacher(app, "Prof B", "b@x.fr")
    other = app.test_client()
    login(other, "b@x.fr")
    html = other.get("/search", query_string={"q": "herve"}).get_data(as_text=True)
    assert "Hervé Léger" not in html
