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
  };

  const SPECIAL_COLORS = {
    "ABS": "red", "Pas de PC": "red",
    "Retard": "orange", "Non réalisé": "orange",
    "-": "grey", "?": "grey",
  };

  async function postJSON(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

  function refreshGrades(grades) {
    if (!grades) return;
    Object.keys(grades).forEach((sid) => {
      const g = grades[sid];
      const totalCell = grid.querySelector(`[data-total="${sid}"]`);
      const noteCell = grid.querySelector(`[data-note20="${sid}"]`);
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
          subject_id: Number(cell.dataset.subject),
          column_id: Number(cell.dataset.column),
          value: value,
        });
        refreshGrades(data.grades);
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
    });
  });

  // --- Notes manuelles ---
  grid.querySelectorAll(".note-input").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const cell = inp.closest(".note-cell");
      try {
        await postJSON(urls.note, {
          subject_id: Number(cell.dataset.subject),
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
          subject_id: Number(cell.dataset.subject),
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
          subject_id: Number(cell.dataset.subject),
          value: inp.value,
        });
        flash(cell, true);
      } catch (e) { flash(cell, false); alert(e.message); }
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
      document.body.appendChild(f);
      f.submit();
    });
  }
})();
