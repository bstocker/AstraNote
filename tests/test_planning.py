"""Tests du planning : réservation des demi-journées et partage en lecture."""
from datetime import date

from astranote import planning
from astranote.models import db, AcademicYear, PlanningShare, PlanningSlot
from conftest import make_teacher, login


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_year(app, admin, label="2025-2026"):
    admin.post("/years", data={"label": label})
    with app.app_context():
        return AcademicYear.query.filter_by(label=label).first().id


def visitor(app):
    """Navigateur sans session : celui d'une personne extérieure."""
    return app.test_client()


def toggle(client, day, half="am", busy=True):
    return client.post("/planning/slot",
                       json={"date": day, "half": half, "busy": busy})


# --------------------------------------------------------------------------- #
# Bornes de l'année académique (déduites du libellé)
# --------------------------------------------------------------------------- #
def test_year_bounds_from_label():
    assert planning.year_bounds("2025-2026") == (date(2025, 9, 1), date(2026, 8, 31))
    # Libellé enrichi : les millésimes restent lisibles.
    assert planning.year_bounds("BTS 2025/2026") == (date(2025, 9, 1), date(2026, 8, 31))
    # Un seul millésime = début d'année scolaire.
    assert planning.year_bounds("2026") == (date(2026, 9, 1), date(2027, 8, 31))
    # Millésimes inversés : la fin ne peut pas précéder le début.
    assert planning.year_bounds("2026-2025") == (date(2026, 9, 1), date(2027, 8, 31))


def test_year_bounds_without_label_falls_back_on_current_school_year():
    # En juin, l'année scolaire en cours a commencé en septembre précédent.
    assert planning.year_bounds("Promo A", today=date(2026, 6, 15)) == (
        date(2025, 9, 1), date(2026, 8, 31))
    assert planning.year_bounds("", today=date(2026, 10, 1)) == (
        date(2026, 9, 1), date(2027, 8, 31))


def test_planning_months_shape():
    """Semaines du lundi au vendredi, mois groupés, débords marqués."""
    start, end = planning.year_bounds("2025-2026")
    months = planning.planning_months(start, end, busy=set(), today=date(2025, 9, 15))
    weeks = [w for m in months for w in m["weeks"]]

    assert months[0]["label"] == "Septembre 2025"
    assert months[-1]["label"] == "Août 2026"
    for week in weeks:
        assert [d["date"].weekday() for d in week["days"]] == [0, 1, 2, 3, 4]
    # 1er septembre 2025 = un lundi : la première semaine commence pile dessus.
    assert weeks[0]["days"][0]["date"] == date(2025, 9, 1)
    # Débord de fin : le 31 août 2026 est un lundi, la semaine sort de l'année.
    assert weeks[-1]["days"][0]["in_year"] is True
    assert weeks[-1]["days"][4]["in_year"] is False
    # Une seule semaine porte le repère « en cours ».
    assert sum(1 for w in weeks if w["is_current"]) == 1


def test_planning_months_counts_busy_halves():
    start, end = planning.year_bounds("2025-2026")
    busy = {(date(2025, 9, 1), "am"), (date(2025, 9, 1), "pm"),
            (date(2025, 9, 3), "am")}
    months = planning.planning_months(start, end, busy, today=date(2025, 9, 1))
    first = months[0]["weeks"][0]
    assert first["count"] == 3
    assert first["days"][0]["am"] and first["days"][0]["pm"]
    assert first["days"][2]["am"] and not first["days"][2]["pm"]


# --------------------------------------------------------------------------- #
# Vue enseignant
# --------------------------------------------------------------------------- #
def test_planning_requires_login(client):
    assert client.get("/planning").status_code == 302
    assert client.post("/planning/slot", json={}).status_code == 302


def test_planning_button_next_to_the_year_selector(app, admin):
    """Le point d'entrée est le tableau de bord, sur l'année sélectionnée."""
    year_id = make_year(app, admin)
    html = admin.get("/").get_data(as_text=True)

    assert f'href="/planning?year={year_id}"' in html
    assert "📅 Planning" in html
    # Le bouton est dans le formulaire du sélecteur d'année, pas dans le menu.
    start = html.index("Année académique")   # le menu porte déjà un <form> avant
    selector = html[start:html.index("</form>", start)]
    assert "/planning" in selector
    assert "/planning" not in html[:html.index("<main")]


def test_planning_grid_rendered_for_selected_year(app, admin):
    year_id = make_year(app, admin)
    html = admin.get(f"/planning?year={year_id}").get_data(as_text=True)

    assert "Septembre 2025" in html and "Août 2026" in html
    assert "Lundi" in html and "Vendredi" in html
    assert "Samedi" not in html and "Dimanche" not in html
    assert 'data-date="2025-09-01" data-half="am"' in html
    assert "slot-box" in html                      # cases cochables


def test_toggle_slot_creates_then_removes(app, admin):
    make_year(app, admin)
    assert toggle(admin, "2025-09-15").get_json()["busy"] is True
    with app.app_context():
        assert PlanningSlot.query.count() == 1

    # Idempotent : recocher la même demi-journée ne crée pas de doublon.
    toggle(admin, "2025-09-15")
    with app.app_context():
        assert PlanningSlot.query.count() == 1

    assert toggle(admin, "2025-09-15", busy=False).get_json()["busy"] is False
    with app.app_context():
        assert PlanningSlot.query.count() == 0


def test_toggle_slot_rejects_invalid_input(app, admin):
    make_year(app, admin)
    assert toggle(admin, "2025-09-15", half="soir").status_code == 400
    assert toggle(admin, "pas-une-date").status_code == 400
    # 2025-09-20 est un samedi : le planning ne couvre pas le week-end.
    assert toggle(admin, "2025-09-20").status_code == 400
    with app.app_context():
        assert PlanningSlot.query.count() == 0


def test_reserved_slot_shown_as_busy(app, admin):
    year_id = make_year(app, admin)
    toggle(admin, "2025-09-15", half="pm")
    html = admin.get(f"/planning?year={year_id}").get_data(as_text=True)
    assert 'class="slot busy" data-date="2025-09-15" data-half="pm"' in html
    assert 'id="reservedTotal">1</strong>' in html


def test_planning_is_private_to_each_teacher(app, admin):
    """Le planning d'un enseignant n'apparaît jamais dans celui d'un autre."""
    year_id = make_year(app, admin)
    toggle(admin, "2025-09-15")

    make_teacher(app, "Bob", "bob@ex.fr")
    other = app.test_client()
    login(other, "bob@ex.fr")
    html = other.get(f"/planning?year={year_id}").get_data(as_text=True)
    assert 'class="slot busy" data-date="2025-09-15"' not in html
    with app.app_context():
        assert PlanningSlot.query.count() == 1


# --------------------------------------------------------------------------- #
# Partage en lecture seule
# --------------------------------------------------------------------------- #
def share_token(app, client, year_id):
    client.post("/planning/share", data={"year": year_id})
    with app.app_context():
        return PlanningShare.query.filter_by(academic_year_id=year_id).first().token


def test_public_link_is_readable_without_login(app, admin):
    year_id = make_year(app, admin)
    toggle(admin, "2025-09-15")
    token = share_token(app, admin, year_id)

    res = visitor(app).get(f"/planning/partage/{token}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Administrateur" in html and "2025-2026" in html
    assert 'class="slot busy" data-date="2025-09-15"' in html
    # Lecture seule : aucune case à cocher, aucune cible d'enregistrement.
    assert "slot-box" not in html and "data-save-slot" not in html
    # Un lien diffusé par message n'a rien à faire dans un moteur de recherche.
    assert "noindex" in html


def test_public_link_exposes_nothing_but_availability(app, admin):
    """La page publique ne laisse filtrer ni classe, ni étudiant, ni email."""
    year_id = make_year(app, admin)
    from test_app import bootstrap_class
    bootstrap_class(app, admin)  # crée école, classe, étudiants, module
    token = share_token(app, admin, year_id)

    html = visitor(app).get(f"/planning/partage/{token}").get_data(as_text=True)
    for leak in ("Alice", "Bob", "Chloe", "B3", "Crypto", "EPSI",
                 "admin@astranote.local", "Tableau de bord"):
        assert leak not in html, leak


def test_public_link_cannot_write(app, admin):
    year_id = make_year(app, admin)
    share_token(app, admin, year_id)
    # Le visiteur n'a pas de session : l'endpoint d'écriture le renvoie au login.
    assert visitor(app).post("/planning/slot",
                       json={"date": "2025-09-15", "half": "am", "busy": True}
                       ).status_code == 302
    with app.app_context():
        assert PlanningSlot.query.count() == 0


def test_regenerating_link_invalidates_the_previous_one(app, admin):
    year_id = make_year(app, admin)
    first = share_token(app, admin, year_id)
    second = share_token(app, admin, year_id)
    guest = visitor(app)

    assert first != second
    assert guest.get(f"/planning/partage/{first}").status_code == 404
    assert guest.get(f"/planning/partage/{second}").status_code == 200
    with app.app_context():
        assert PlanningShare.query.count() == 1  # un seul lien par année


def test_revoked_link_returns_404(app, admin):
    year_id = make_year(app, admin)
    token = share_token(app, admin, year_id)
    admin.post("/planning/share/delete", data={"year": year_id})
    guest = visitor(app)

    assert guest.get(f"/planning/partage/{token}").status_code == 404
    assert guest.get("/planning/partage/inconnu").status_code == 404


def test_share_links_are_per_teacher(app, admin):
    """Un enseignant ne partage que son propre planning, jamais celui d'un autre."""
    year_id = make_year(app, admin)
    admin_token = share_token(app, admin, year_id)

    make_teacher(app, "Bob", "bob@ex.fr")
    other = app.test_client()
    login(other, "bob@ex.fr")
    bob_token = share_token_for(app, other, year_id, "Bob")

    assert bob_token != admin_token
    # Supprimer son lien laisse celui de l'autre intact.
    other.post("/planning/share/delete", data={"year": year_id})
    with app.app_context():
        remaining = PlanningShare.query.all()
        assert [s.token for s in remaining] == [admin_token]


def share_token_for(app, client, year_id, teacher_name):
    client.post("/planning/share", data={"year": year_id})
    with app.app_context():
        from astranote.models import Teacher
        tid = Teacher.query.filter_by(name=teacher_name).first().id
        return PlanningShare.query.filter_by(
            academic_year_id=year_id, teacher_id=tid).first().token


def test_share_rejects_year_out_of_reach(app, admin):
    """Une année appartenant à un autre enseignant n'est pas partageable."""
    other_id = make_teacher(app, "Bob", "bob@ex.fr")
    with app.app_context():
        private = AcademicYear(label="2030-2031", teacher_id=other_id)
        db.session.add(private)
        db.session.commit()
        private_id = private.id

    teacher_id = make_teacher(app, "Carole", "carole@ex.fr")
    assert teacher_id
    carole = app.test_client()
    login(carole, "carole@ex.fr")
    assert carole.post("/planning/share", data={"year": private_id}).status_code == 404
    assert carole.post("/planning/share/delete",
                       data={"year": private_id}).status_code == 404


# --------------------------------------------------------------------------- #
# Géométrie du tableau (l'alignement des colonnes se voit, mais se teste mal
# à l'œil sur une année entière : 5 jours × 2 demi-journées + semaine + total)
# --------------------------------------------------------------------------- #
def table_rows(html):
    """Lignes du tableau de planning : [(balise, [(cellule, colspan), …]), …]."""
    from html.parser import HTMLParser

    class Rows(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_table = False
            self.rows = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "table" and "planning" in (attrs.get("class") or ""):
                self.in_table = True
            elif not self.in_table:
                return
            elif tag == "tr":
                self.rows.append([])
            elif tag in ("th", "td") and self.rows:
                self.rows[-1].append((tag, int(attrs.get("colspan", 1))))

        def handle_endtag(self, tag):
            if tag == "table":
                self.in_table = False

    parser = Rows()
    parser.feed(html)
    return parser.rows


def test_every_row_spans_twelve_columns(app, admin):
    year_id = make_year(app, admin)
    toggle(admin, "2025-09-15")
    rows = table_rows(admin.get(f"/planning?year={year_id}").get_data(as_text=True))

    assert len(rows) > 50  # une année ≈ 52 semaines + les intitulés de mois
    for cells in rows:
        width = sum(span for _, span in cells)
        # La seconde rangée d'en-tête passe sous les cellules à rowspan=2
        # (« Semaine » et « Rés. »), d'où ses 10 colonnes.
        assert width in (10, 12), cells


def test_deleting_the_year_removes_its_share_link(app, admin):
    """Le lien ne doit pas survivre à son année : il pointerait dans le vide."""
    year_id = make_year(app, admin)
    token = share_token(app, admin, year_id)
    assert admin.post(f"/years/{year_id}/delete").status_code == 302

    with app.app_context():
        assert PlanningShare.query.count() == 0
    assert visitor(app).get(f"/planning/partage/{token}").status_code == 404
