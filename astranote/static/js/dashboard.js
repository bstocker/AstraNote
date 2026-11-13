// Tableau de bord : mémorise l'état replié/déplié de chaque école et gère
// « Tout replier / Tout déplier ».
// L'état vit dans le navigateur (localStorage) et non en base : c'est une
// préférence d'affichage, propre à chaque poste, qui ne mérite pas de
// requête serveur. Sans localStorage (navigation privée…), tout reste
// déplié, comme avant.
(function () {
  const panels = Array.from(document.querySelectorAll(".school-panel"));
  if (!panels.length) return;

  const KEY = "astranote.dashboard.closedSchools";

  function load() {
    try {
      return new Set(JSON.parse(localStorage.getItem(KEY)) || []);
    } catch (e) {
      return new Set();
    }
  }

  function save(closed) {
    try {
      localStorage.setItem(KEY, JSON.stringify(Array.from(closed)));
    } catch (e) {
      /* stockage indisponible : l'état ne sera simplement pas retenu */
    }
  }

  // On retient les écoles repliées plutôt que les dépliées : une école
  // nouvellement créée apparaît ainsi dépliée.
  const closed = load();
  panels.forEach((p) => {
    if (closed.has(p.dataset.schoolId)) p.open = false;
  });

  function record() {
    panels.forEach((p) => {
      if (p.open) closed.delete(p.dataset.schoolId);
      else closed.add(p.dataset.schoolId);
    });
    save(closed);
  }

  // « toggle » ne remonte pas (pas de bubbling) : un écouteur par panneau.
  panels.forEach((p) => p.addEventListener("toggle", record));

  document.querySelectorAll("[data-toggle-all]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const open = btn.dataset.toggleAll === "open";
      panels.forEach((p) => { p.open = open; });
      record();
    });
  });
})();
