"""Tests du planning : demi-journées réservées et liens de réservation."""
from datetime import date

from astranote import planning
from astranote.models import db, AcademicYear, PlanningLink, PlanningSlot
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
# Liens de réservation
# --------------------------------------------------------------------------- #
# Année loin dans le futur : un client ne réserve pas une date passée, et les
# tests ne doivent pas se mettre à échouer le jour où 2025-2026 sera écoulée.
FUTURE = "2098-2099"
DAY = "2098-09-15"           # un lundi


def make_link(app, client, year_id, name="Formation STEAME", color="#bbf7d0"):
    client.post("/planning/share",
                data={"year": year_id, "name": name, "color": color})
    with app.app_context():
        link = PlanningLink.query.filter_by(name=name).order_by(
            PlanningLink.id.desc()).first()
        return link.id, link.token


def book(guest, token, day=DAY, half="am", busy=True):
    return guest.post(f"/planning/partage/{token}/slot",
                      json={"date": day, "half": half, "busy": busy})


def state(client, url):
    return client.get(url).get_json()["slots"]


def test_link_is_created_with_its_name_and_colour(app, admin):
    year_id = make_year(app, admin, FUTURE)
    make_link(app, admin, year_id, "Formation STEAME", "#BBF7D0")
    make_link(app, admin, year_id, "Client B", "pas-une-couleur")

    with app.app_context():
        first, second = PlanningLink.query.order_by(PlanningLink.id).all()
        assert (first.name, first.color) == ("Formation STEAME", "#bbf7d0")
        # Couleur illisible : repli sur la palette, jamais de CSS arbitraire.
        assert second.color.startswith("#") and len(second.color) == 7
        assert first.token != second.token
    html = admin.get(f"/planning?year={year_id}").get_data(as_text=True)
    assert "Formation STEAME" in html and "Client B" in html

    # Un lien sans nom n'est pas créé.
    admin.post("/planning/share", data={"year": year_id, "name": "  "})
    with app.app_context():
        assert PlanningLink.query.count() == 2


def test_public_link_is_readable_without_login(app, admin):
    year_id = make_year(app, admin, FUTURE)
    toggle(admin, DAY)
    _, token = make_link(app, admin, year_id)

    res = visitor(app).get(f"/planning/partage/{token}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Administrateur" in html and FUTURE in html and "Formation STEAME" in html
    assert f'class="slot busy" data-date="{DAY}" data-half="am"' in html
    # Un lien diffusé par message n'a rien à faire dans un moteur de recherche.
    assert "noindex" in html


def test_public_link_exposes_nothing_but_availability(app, admin):
    """La page publique ne laisse filtrer ni classe, ni étudiant, ni email,
    ni le nom des autres clients."""
    year_id = make_year(app, admin, FUTURE)
    from test_app import bootstrap_class
    bootstrap_class(app, admin)  # crée école, classe, étudiants, module
    _, token = make_link(app, admin, year_id)
    _, other = make_link(app, admin, year_id, "Client Secret", "#bfdbfe")
    book(visitor(app), other)

    guest = visitor(app)
    html = guest.get(f"/planning/partage/{token}").get_data(as_text=True)
    raw = guest.get(f"/planning/partage/{token}/etat").get_data(as_text=True)
    for leak in ("Alice", "Bob", "Chloe", "B3", "Crypto", "EPSI", "Client Secret",
                 "#bfdbfe", "admin@astranote.local", "Tableau de bord"):
        assert leak not in html, leak
        assert leak not in raw, leak


def test_client_requests_a_free_half_day(app, admin):
    year_id = make_year(app, admin, FUTURE)
    link_id, token = make_link(app, admin, year_id)
    guest = visitor(app)

    assert book(guest, token).status_code == 200
    with app.app_context():
        slot = PlanningSlot.query.one()
        assert slot.pending and slot.link_id == link_id

    # Le client retrouve sa demande, dans la couleur de son lien.
    mine = state(guest, f"/planning/partage/{token}/etat")[f"{DAY}|am"]
    assert mine["state"] == "request" and mine["color"] == "#bbf7d0"
    # L'enseignant la voit dans cette couleur, avec le nom du lien — et elle
    # ne compte pas encore parmi ses demi-journées réservées.
    seen = state(admin, f"/planning/state?year={year_id}")[f"{DAY}|am"]
    assert seen["state"] == "request" and seen["color"] == "#bbf7d0"
    assert "Formation STEAME" in seen["text"]
    html = admin.get(f"/planning?year={year_id}").get_data(as_text=True)
    assert 'id="reservedTotal">0</strong>' in html
    assert 'id="pendingTotal">1</strong>' in html
    assert "lundi 15 septembre 2098" in html

    # Tant qu'elle n'est pas validée, le client peut la retirer.
    assert book(guest, token, busy=False).status_code == 200
    with app.app_context():
        assert PlanningSlot.query.count() == 0


def test_client_cannot_take_a_busy_half_day(app, admin):
    year_id = make_year(app, admin, FUTURE)
    toggle(admin, DAY)
    _, token = make_link(app, admin, year_id)
    guest = visitor(app)

    assert book(guest, token).status_code == 409
    # … ni libérer une demi-journée de l'enseignant.
    assert book(guest, token, busy=False).status_code == 409
    with app.app_context():
        slot = PlanningSlot.query.one()
        assert not slot.pending and slot.link_id is None


def test_requested_half_day_is_closed_to_other_clients(app, admin):
    """Disponibilités en temps réel : le premier qui demande l'emporte."""
    year_id = make_year(app, admin, FUTURE)
    first_id, first = make_link(app, admin, year_id, "Client 1", "#bbf7d0")
    _, second = make_link(app, admin, year_id, "Client 2", "#bfdbfe")
    one, two = visitor(app), visitor(app)

    assert book(one, first).status_code == 200
    assert book(two, second).status_code == 409
    # Le client 2 ne peut pas non plus retirer la demande du client 1.
    assert book(two, second, busy=False).status_code == 409
    # Chez lui, la demi-journée est simplement « Non disponible ».
    other = state(two, f"/planning/partage/{second}/etat")[f"{DAY}|am"]
    assert other == {"state": "busy", "color": None, "text": "Non disponible"}
    html = two.get(f"/planning/partage/{second}").get_data(as_text=True)
    assert f'class="slot busy" data-date="{DAY}" data-half="am"' in html
    with app.app_context():
        assert PlanningSlot.query.one().link_id == first_id

    # Demande retirée : la demi-journée redevient disponible pour le client 2.
    book(one, first, busy=False)
    assert book(two, second).status_code == 200


def test_client_request_rejects_invalid_input(app, admin):
    year_id = make_year(app, admin, FUTURE)
    _, token = make_link(app, admin, year_id)
    guest = visitor(app)

    assert book(guest, token, day="2098-09-20").status_code == 400   # samedi
    assert book(guest, token, half="soir").status_code == 400
    assert book(guest, token, day="2097-09-16").status_code == 400   # hors année
    assert book(guest, "jeton-inconnu").status_code == 404
    with app.app_context():
        assert PlanningSlot.query.count() == 0


def test_client_cannot_request_a_past_date(app, admin):
    year_id = make_year(app, admin, "2020-2021")
    _, token = make_link(app, admin, year_id)
    guest = visitor(app)

    assert book(guest, token, day="2020-09-14").status_code == 400
    html = guest.get(f"/planning/partage/{token}").get_data(as_text=True)
    assert "slot-box" not in html and "Date passée" in html


def test_teacher_validates_a_request_from_the_grid(app, admin):
    year_id = make_year(app, admin, FUTURE)
    link_id, token = make_link(app, admin, year_id)
    guest = visitor(app)
    book(guest, token)

    # Sans `confirm` (case vue blanche, demande arrivée entre-temps) : refus.
    assert toggle(admin, DAY).status_code == 409
    with app.app_context():
        assert PlanningSlot.query.one().pending

    res = admin.post("/planning/slot",
                     json={"date": DAY, "half": "am", "busy": True, "confirm": True})
    assert res.status_code == 200
    with app.app_context():
        slot = PlanningSlot.query.one()
        assert not slot.pending and slot.link_id == link_id
    # Couleur habituelle du planning côté enseignant, confirmation côté client.
    html = admin.get(f"/planning?year={year_id}").get_data(as_text=True)
    assert f'class="slot busy" data-date="{DAY}" data-half="am"' in html
    mine = state(guest, f"/planning/partage/{token}/etat")[f"{DAY}|am"]
    assert mine["state"] == "granted"
    # Une réservation confirmée ne se retire plus depuis le lien.
    assert book(guest, token, busy=False).status_code == 409


def test_teacher_answers_requests_from_the_list(app, admin):
    year_id = make_year(app, admin, FUTURE)
    link_id, token = make_link(app, admin, year_id)
    guest = visitor(app)
    for half in ("am", "pm"):
        book(guest, token, half=half)
    book(guest, token, day="2098-09-16")

    # Une seule demande refusée : la demi-journée est libérée.
    admin.post(f"/planning/share/{link_id}/requests",
               data={"action": "refuse", "date": DAY, "half": "pm"})
    with app.app_context():
        assert PlanningSlot.query.count() == 2
    # « Tout valider » traite ce qui reste.
    admin.post(f"/planning/share/{link_id}/requests", data={"action": "accept"})
    with app.app_context():
        assert [s.pending for s in PlanningSlot.query.all()] == [False, False]


def test_deleted_link_returns_404_and_frees_its_requests(app, admin):
    year_id = make_year(app, admin, FUTURE)
    link_id, token = make_link(app, admin, year_id)
    guest = visitor(app)
    book(guest, token, half="am")
    book(guest, token, half="pm")
    admin.post(f"/planning/share/{link_id}/requests",
               data={"action": "accept", "date": DAY, "half": "am"})

    admin.post(f"/planning/share/{link_id}/delete")
    assert guest.get(f"/planning/partage/{token}").status_code == 404
    assert book(guest, token, day="2098-09-17").status_code == 404
    assert guest.get("/planning/partage/inconnu").status_code == 404
    with app.app_context():
        assert PlanningLink.query.count() == 0
        # La demande en attente part avec le lien, la demi-journée validée reste.
        slot = PlanningSlot.query.one()
        assert (slot.half, slot.pending, slot.link_id) == ("am", False, None)


def test_links_are_per_teacher(app, admin):
    """Un enseignant ne gère que ses propres liens et leurs demandes."""
    year_id = make_year(app, admin, FUTURE)
    link_id, token = make_link(app, admin, year_id)
    book(visitor(app), token)

    make_teacher(app, "Bob", "bob@ex.fr")
    other = app.test_client()
    login(other, "bob@ex.fr")
    assert other.post(f"/planning/share/{link_id}/delete").status_code == 404
    assert other.post(f"/planning/share/{link_id}/requests",
                      data={"action": "accept"}).status_code == 404
    # La demande déposée chez l'administrateur n'apparaît pas chez Bob.
    assert state(other, f"/planning/state?year={year_id}") == {}
    with app.app_context():
        assert PlanningLink.query.count() == 1
        assert PlanningSlot.query.one().pending


def test_share_rejects_year_out_of_reach(app, admin):
    """Une année appartenant à un autre enseignant n'est pas partageable."""
    other_id = make_teacher(app, "Bob", "bob@ex.fr")
    with app.app_context():
        private = AcademicYear(label="2030-2031", teacher_id=other_id)
        db.session.add(private)
        db.session.commit()
        private_id = private.id

    make_teacher(app, "Carole", "carole@ex.fr")
    carole = app.test_client()
    login(carole, "carole@ex.fr")
    assert carole.post("/planning/share",
                       data={"year": private_id, "name": "X"}).status_code == 404
    assert carole.get(f"/planning/state?year={private_id}").status_code == 404


def test_old_share_links_are_migrated(app):
    """Les liens de l'ancienne table sont repris, jeton inchangé."""
    from sqlalchemy import text
    from astranote import _run_migrations
    with app.app_context():
        year = AcademicYear(label=FUTURE)
        db.session.add(year)
        db.session.commit()
        db.session.execute(text(
            "CREATE TABLE planning_share (id INTEGER PRIMARY KEY, teacher_id INTEGER,"
            " academic_year_id INTEGER, token VARCHAR(64), created_at DATETIME)"))
        db.session.execute(text(
            "INSERT INTO planning_share VALUES (1, 1, :y, 'ancien-jeton',"
            " '2025-09-01 00:00:00')"), {"y": year.id})
        db.session.commit()
        _run_migrations(app)
        assert PlanningLink.query.one().token == "ancien-jeton"
    assert visitor(app).get("/planning/partage/ancien-jeton").status_code == 200


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


def test_deleting_the_year_removes_its_share_links(app, admin):
    """Le lien ne doit pas survivre à son année : il pointerait dans le vide."""
    year_id = make_year(app, admin, FUTURE)
    _, token = make_link(app, admin, year_id)
    book(visitor(app), token)
    assert admin.post(f"/years/{year_id}/delete").status_code == 302

    with app.app_context():
        assert PlanningLink.query.count() == 0
        assert PlanningSlot.query.count() == 0   # demande en attente libérée
    assert visitor(app).get(f"/planning/partage/{token}").status_code == 404
