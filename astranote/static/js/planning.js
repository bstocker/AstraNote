// Planning : réservation des demi-journées et copie du lien de partage.
// Chaque case cochée est enregistrée immédiatement (AJAX) — un planning d'année
// se remplit par dizaines de cases, un bouton « Enregistrer » ferait perdre la
// saisie au moindre oubli.
(function () {
  const table = document.getElementById("planning");
  if (!table) return;

  const url = table.dataset.saveSlot;
  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  const total = document.getElementById("reservedTotal");

  // Compteurs recalculés depuis le DOM : la source de vérité visible est la
  // grille elle-même, et le serveur n'a pas à renvoyer des totaux que le
  // navigateur sait déduire.
  function refreshCounts(row) {
    if (row) {
      const cell = row.querySelector("td.count");
      if (cell) cell.textContent = row.querySelectorAll("td.slot.busy").length;
    }
    if (total) total.textContent = table.querySelectorAll("td.slot.busy").length;
  }

  table.querySelectorAll("input.slot-box").forEach((box) => {
    box.addEventListener("change", async () => {
      const cell = box.closest("td.slot");
      const busy = box.checked;
      cell.classList.toggle("busy", busy);
      refreshCounts(cell.closest("tr"));
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
          body: JSON.stringify({
            date: cell.dataset.date,
            half: cell.dataset.half,
            busy: busy,
          }),
        });
        if (!res.ok) {
          let msg = "Erreur d'enregistrement";
          try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
          throw new Error(msg);
        }
        // L'infobulle porte l'état : elle doit suivre la case.
        cell.title = cell.title.replace(
          busy ? "Disponible" : "Non disponible",
          busy ? "Non disponible" : "Disponible");
      } catch (e) {
        // Échec : on remet la case et les compteurs dans leur état d'avant,
        // sinon l'écran affirmerait une réservation qui n'existe pas en base.
        box.checked = !busy;
        cell.classList.toggle("busy", !busy);
        refreshCounts(cell.closest("tr"));
        alert(e.message);
      }
    });
  });
})();

// Copie du lien de partage dans le presse-papier.
(function () {
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const field = document.querySelector(btn.dataset.copy);
      if (!field) return;
      field.select();
      try {
        // `navigator.clipboard` n'existe qu'en HTTPS (ou sur localhost) :
        // ailleurs, le texte reste sélectionné, prêt pour un Ctrl+C manuel.
        await navigator.clipboard.writeText(field.value);
        const label = btn.textContent;
        btn.textContent = "Copié ✓";
        setTimeout(() => { btn.textContent = label; }, 1500);
      } catch (e) { /* sélection laissée à l'utilisateur */ }
    });
  });
})();
