// Planning : réservation des demi-journées, demandes des clients et copie des
// liens de partage. Le même script sert la vue de l'enseignant (mode « edit »)
// et la page d'un lien (mode « book »).
// Chaque case cochée est enregistrée immédiatement (AJAX) — un planning d'année
// se remplit par dizaines de cases, un bouton « Enregistrer » ferait perdre la
// saisie au moindre oubli.
(function () {
  const table = document.getElementById("planning");
  if (!table) return;

  const booking = table.dataset.mode === "book";
  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  const total = document.getElementById("reservedTotal");
  const pendingTotal = document.getElementById("pendingTotal");
  const stale = document.getElementById("requestsStale");
  const cells = Array.from(table.querySelectorAll("td.slot[data-date]"));

  // Ce que compte la colonne de droite : les réservations pour l'enseignant,
  // ses propres demandes pour un client.
  const COUNTED = booking ? "td.slot.request, td.slot.granted" : "td.slot.busy";
  const STATES = ["busy", "request", "granted"];
  const FREE = { state: "free", color: null, text: table.dataset.freeText };
  // État posé dès la coche, sans attendre le serveur.
  const CHECKED = booking
    ? { state: "request", color: table.dataset.color, text: table.dataset.onText }
    : { state: "busy", color: null, text: table.dataset.onText };

  const key = (cell) => cell.dataset.date + "|" + cell.dataset.half;
  const requestKeys = () =>
    cells.filter((c) => c.classList.contains("request")).map(key).join(",");

  function render(cell, st) {
    cell._st = st;
    STATES.forEach((s) => cell.classList.toggle(s, s === st.state));
    if (st.color) cell.style.setProperty("--req", st.color);
    else cell.style.removeProperty("--req");
    // L'infobulle porte l'état : elle doit suivre la case.
    cell.title = cell.dataset.label + " — " + st.text;
    const sr = cell.querySelector(".sr-only");
    if (sr) sr.textContent = st.text;
    const box = cell.querySelector("input.slot-box");
    if (box) {
      box.checked = st.state === CHECKED.state;
      box.disabled = booking && (st.state === "busy" || st.state === "granted");
    }
  }

  // Compteurs recalculés depuis le DOM : la source de vérité visible est la
  // grille elle-même, et le serveur n'a pas à renvoyer des totaux que le
  // navigateur sait déduire.
  function refreshCounts() {
    table.querySelectorAll("tbody tr").forEach((row) => {
      const cell = row.querySelector("td.count");
      if (cell) cell.textContent = row.querySelectorAll(COUNTED).length;
    });
    if (total) total.textContent = table.querySelectorAll(COUNTED).length;
    if (pendingTotal) {
      pendingTotal.textContent = table.querySelectorAll("td.slot.request").length;
    }
    // La liste des demandes sous la grille date du chargement de la page.
    if (stale) stale.hidden = requestKeys() === listedRequests;
  }

  cells.forEach((cell) => {
    cell._st = {
      state: cell.dataset.state,
      color: cell.style.getPropertyValue("--req").trim() || null,
      text: cell.title.slice(cell.dataset.label.length + 3),
    };
  });
  const listedRequests = requestKeys();

  // ---- Rafraîchissement en direct ------------------------------------- //
  // Les disponibilités bougent sans nous : un client dépose une demande,
  // l'enseignant en valide une. Les cases dont l'enregistrement est en cours
  // sont laissées de côté, et une réponse partie avant une écriture locale est
  // jetée (`writes`) : elle décrirait un état déjà dépassé.
  const saving = new Set();
  let writes = 0;

  async function refresh() {
    const seen = writes;
    let slots;
    try {
      const res = await fetch(table.dataset.state, { cache: "no-store" });
      if (!res.ok) return;
      slots = (await res.json()).slots || {};
    } catch (e) { return; }  // hors ligne : on réessaiera au prochain tour
    if (seen !== writes) return refresh();
    cells.forEach((cell) => {
      if (saving.has(cell)) return;
      const st = slots[key(cell)] || FREE;
      const cur = cell._st;
      // Une case libre d'un jour passé garde son libellé « Date passée ».
      if (st.state === "free" && cur.state === "free") return;
      if (st.state !== cur.state || st.color !== cur.color || st.text !== cur.text) {
        render(cell, st);
      }
    });
    refreshCounts();
  }

  setInterval(() => { if (!document.hidden) refresh(); }, 10000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });

  // ---- Coche d'une demi-journée ---------------------------------------- //
  table.querySelectorAll("input.slot-box").forEach((box) => {
    box.addEventListener("change", async () => {
      const cell = box.closest("td.slot");
      const before = cell._st;
      const busy = box.checked;
      saving.add(cell);
      render(cell, busy ? CHECKED : FREE);
      refreshCounts();
      let conflict = false;
      try {
        const res = await fetch(table.dataset.saveSlot, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
          body: JSON.stringify({
            date: cell.dataset.date,
            half: cell.dataset.half,
            busy: busy,
            // Cocher une demande affichée, c'est la valider en connaissance
            // de cause ; cocher une case blanche ne valide jamais rien.
            confirm: before.state === "request",
          }),
        });
        if (!res.ok) {
          conflict = res.status === 409;
          let msg = "Enregistrement impossible : rechargez la page et réessayez.";
          try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
          throw new Error(msg);
        }
      } catch (e) {
        // Échec : on remet la case et les compteurs dans leur état d'avant,
        // sinon l'écran affirmerait une réservation qui n'existe pas en base.
        render(cell, before);
        refreshCounts();
        alert(e.message);
      }
      saving.delete(cell);
      writes += 1;
      // Après un conflit, l'état réel vient du serveur (case prise entre-temps) ;
      // après un succès, il apporte le libellé exact de l'infobulle.
      if (conflict || cell._st !== before) refresh();
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
