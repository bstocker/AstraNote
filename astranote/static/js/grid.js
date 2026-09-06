// Saisie inline de la grille de module : étoiles, notes, URL, commentaires.
// Chaque modification est enregistrée immédiatement (AJAX) ; la note /20 au
// prorata est recalculée côté serveur puis réappliquée à toutes les lignes.
(function () {
  const grid = document.getElementById("grid");
  if (!grid) return;

  const urls = {
    star: grid.dataset.saveStar,
    note: grid.dataset.saveNote,
    url: grid.dataset.saveUrl,
    comment: grid.dataset.saveComment,
    color: grid.dataset.saveColor,
  };

  const CELL_COLORS = ["green", "yellow", "red", "grey"];

  const SPECIAL_COLORS = {
    "ABS": "red", "Pas de PC": "red",
    "Retard": "orange", "Non réalisé": "orange",
    "-": "grey", "?": "grey",
  };

  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // Sujet visé par une cellule : le type accompagne l'identifiant.
  function subjectOf(cell) {
    return {
      subject_id: Number(cell.dataset.subject),
      subject_type: cell.dataset.subjectType,
    };
  }

  async function postJSON(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let msg = "Erreur d'enregistrement";
      try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
      throw new Error(msg);
    }
    return res.json();
  }

  function flash(el, ok) {
    el.style.transition = "background-color .1s";
    const prev = el.style.backgroundColor;
    el.style.backgroundColor = ok ? "#dcfce7" : "#fee2e2";
    setTimeout(() => { el.style.backgroundColor = prev; }, 350);
  }

  // Les clés sont « type:id » (« group:3 », « student:12 ») : une grille de
  // module en groupe porte les lignes du groupe et celles de ses membres, et
  // l'identifiant seul y serait ambigu.
  function refreshGrades(grades) {
    if (!grades) return;
    Object.keys(grades).forEach((key) => {
      const g = grades[key];
      const totalCell = grid.querySelector(`[data-total-key="${key}"]`);
      const noteCell = grid.querySelector(`[data-note20-key="${key}"]`);
      if (totalCell) totalCell.textContent = g.total;
      if (noteCell) {
        noteCell.textContent = g.note;
        noteCell.classList.toggle("ref", !!g.is_reference);
        const row = noteCell.closest("tr");
        if (row) row.classList.toggle("reference", !!g.is_reference);
      }
    });
  }

  // --- Étoiles (select) ---
  grid.querySelectorAll(".star-select").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const cell = sel.closest(".star-cell");
      const value = sel.value;
      // Couleur de statut immédiate.
      cell.classList.remove("st-red", "st-orange", "st-grey");
      if (SPECIAL_COLORS[value]) cell.classList.add("st-" + SPECIAL_COLORS[value]);
      try {
        const data = await postJSON(urls.star, {
          ...subjectOf(cell),
          column_id: Number(cell.dataset.column),
          value: value,
        });
        refreshGrades(data.grades);
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
    });

    // Saisie clavier rapide : taper 0–4 fixe la valeur ; Entrée descend d'une ligne.
    const cell = sel.closest(".star-cell");
    sel.addEventListener("focus", () => cell.classList.add("kb-focus"));
    sel.addEventListener("blur", () => cell.classList.remove("kb-focus"));
    sel.addEventListener("keydown", (e) => {
      if (/^[0-4]$/.test(e.key)) {
        e.preventDefault();
        if (sel.value !== e.key) {
          sel.value = e.key;
          sel.dispatchEvent(new Event("change"));
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        const col = cell.dataset.column;
        // offsetParent null = ligne masquée : on saute les membres repliés.
        const all = Array.from(grid.querySelectorAll(
          `.star-cell[data-column="${col}"] .star-select`))
          .filter((s) => s.offsetParent !== null);
        const next = all[all.indexOf(sel) + 1];
        if (next) next.focus();
      }
    });
  });

  // --- Notes manuelles ---
  grid.querySelectorAll(".note-input").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const cell = inp.closest(".note-cell");
      try {
        await postJSON(urls.note, {
          ...subjectOf(cell),
          column_id: Number(cell.dataset.column),
          value: inp.value,
        });
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
    });
  });

  // --- Liens (URL) ---
  grid.querySelectorAll(".url-input").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const cell = inp.closest(".url-cell");
      try {
        await postJSON(urls.url, {
          ...subjectOf(cell),
          column_id: Number(cell.dataset.column),
          value: inp.value,
        });
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
    });
  });

  // --- Commentaires ---
  grid.querySelectorAll(".comment-input").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const cell = inp.closest(".comment-cell");
      try {
        await postJSON(urls.comment, {
          ...subjectOf(cell),
          value: inp.value,
        });
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
    });
  });

  // --- Couleur de fond de la cellule sujet ---
  grid.querySelectorAll(".color-picker").forEach((picker) => {
    const cell = picker.closest("td.subject");
    picker.querySelectorAll(".swatch").forEach((sw) => {
      sw.addEventListener("click", async () => {
        const color = sw.dataset.color;
        try {
          await postJSON(urls.color, {
            ...subjectOf(cell),
            value: color,
          });
          CELL_COLORS.forEach((c) => cell.classList.remove("col-" + c));
          if (color) cell.classList.add("col-" + color);
          picker.querySelectorAll(".swatch").forEach((o) => o.classList.remove("on"));
          sw.classList.add("on");
        } catch (e) { alert(e.message); }
      });
    });
  });

  // --- Dépliage d'un groupe : afficher / masquer ses membres ---
  grid.querySelectorAll(".fold-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!open));
      btn.textContent = open ? "▸" : "▾";
      grid.querySelectorAll(`tr.member-row[data-group="${btn.dataset.group}"]`)
        .forEach((tr) => { tr.hidden = open; });
    });
  });

  // --- Ajout de colonne (route dépendant de la date + type) ---
  const addColForm = document.getElementById("addColForm");
  if (addColForm) {
    addColForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const dateId = document.getElementById("colDate").value;
      const type = document.getElementById("colType").value;
      const title = document.getElementById("colTitle").value;
      const base = type === "url"
        ? addColForm.dataset.urlAction
        : addColForm.dataset.starAction;
      // Les routes sont générées avec date_id=0 ; on remplace /dates/0/ par la vraie date.
      const action = base.replace("/dates/0/", "/dates/" + dateId + "/");
      // Construit dynamiquement le POST.
      const f = document.createElement("form");
      f.method = "post";
      f.action = action;
      const inp = document.createElement("input");
      inp.name = "title"; inp.value = title;
      f.appendChild(inp);
      const csrf = document.createElement("input");
      csrf.name = "csrf_token"; csrf.value = CSRF;
      f.appendChild(csrf);
      document.body.appendChild(f);
      f.submit();
    });
  }
})();

// Envoi des notes : pré-remplit la date du jour quand on coche « envoyées ».
(function () {
  const chk = document.querySelector('input[name="notes_sent"]');
  const date = document.querySelector('input[name="notes_sent_date"]');
  if (!chk || !date) return;
  chk.addEventListener("change", () => {
    if (chk.checked && !date.value) {
      date.value = new Date().toISOString().slice(0, 10);
    }
  });
})();
