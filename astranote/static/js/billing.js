// Page de facturation : coche des séances, total du lot en direct, et saisie
// immédiate (AJAX) de la durée et de la référence de chaque séance.
(function () {
  const form = document.getElementById("billingForm");
  if (!form) return;

  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  const rows = Array.from(document.querySelectorAll(".billing-row"));
  const totalEl = document.getElementById("billingTotal");
  const exportBtn = document.getElementById("exportBtn");
  // Enregistrements en cours : l'extraction les attend, sinon une référence
  // tapée juste avant le clic manquerait dans le fichier.
  const pending = new Set();

  function hoursOf(row) {
    const v = parseFloat(row.querySelector(".billing-hours").value.replace(",", "."));
    return isNaN(v) ? 0 : v;
  }

  function fmt(h) {
    return (Math.round(h * 100) / 100).toString().replace(".", ",");
  }

  function refresh() {
    const checked = rows.filter((r) => r.querySelector(".billing-check").checked);
    const total = checked.reduce((sum, r) => sum + hoursOf(r), 0);
    totalEl.textContent = `Sélection : ${checked.length} séance${checked.length > 1 ? "s" : ""} · ${fmt(total)} h`;
    exportBtn.disabled = checked.length === 0;
    rows.forEach((r) => r.classList.toggle("checked", r.querySelector(".billing-check").checked));
  }

  function flash(el, ok) {
    el.style.transition = "background-color .1s";
    el.style.backgroundColor = ok ? "#dcfce7" : "#fee2e2";
    setTimeout(() => { el.style.backgroundColor = ""; }, 350);
  }

  async function save(row, payload, input, keepalive = false) {
    input.dataset.saved = input.value;
    const url = form.dataset.saveUrl.replace("/seances/0", "/seances/" + row.dataset.session);
    const job = fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify(payload),
      keepalive: keepalive,
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Erreur d'enregistrement");
      row.classList.toggle("billed", !!data.billed);
      flash(input, true);
    }).catch((e) => { flash(input, false); alert(e.message); });
    pending.add(job);
    job.finally(() => pending.delete(job));
    return job;
  }

  rows.forEach((row) => {
    row.querySelectorAll(".billing-hours, .billing-ref").forEach((i) => { i.dataset.saved = i.value; });
    row.querySelector(".billing-check").addEventListener("change", refresh);
    const hours = row.querySelector(".billing-hours");
    hours.addEventListener("input", refresh);
    hours.addEventListener("change", () => save(row, { duration_hours: hours.value }, hours));
    const ref = row.querySelector(".billing-ref");
    // Grisé dès la frappe ; la coche reste en l'état pour le lot en cours.
    ref.addEventListener("input", () => row.classList.toggle("billed", ref.value.trim() !== ""));
    ref.addEventListener("change", () => save(row, { billing_ref: ref.value }, ref));
  });

  // Rafraîchissement ou départ de la page, curseur encore dans un champ : le
  // « change » n'a pas eu lieu, on envoie quand même la saisie.
  window.addEventListener("pagehide", () => {
    rows.forEach((row) => {
      const hours = row.querySelector(".billing-hours");
      const ref = row.querySelector(".billing-ref");
      if (hours.value !== hours.dataset.saved) save(row, { duration_hours: hours.value }, hours, true);
      if (ref.value !== ref.dataset.saved) save(row, { billing_ref: ref.value }, ref, true);
    });
  });

  // « Tout cocher » ne coche que ce qui reste à facturer : les séances
  // grisées fausseraient le total. Elles restent cochables une par une.
  document.getElementById("checkAll").addEventListener("click", () => {
    rows.forEach((r) => {
      if (!r.classList.contains("billed")) r.querySelector(".billing-check").checked = true;
    });
    refresh();
  });
  document.getElementById("uncheckAll").addEventListener("click", () => {
    rows.forEach((r) => { r.querySelector(".billing-check").checked = false; });
    refresh();
  });

  form.addEventListener("submit", async (ev) => {
    if (!pending.size) return;
    ev.preventDefault();
    // Un champ encore en cours d'édition n'a pas émis « change » : on le force.
    if (document.activeElement) document.activeElement.blur();
    await Promise.allSettled(Array.from(pending));
    form.submit();
  });

  // Le navigateur peut restaurer des cases cochées au retour arrière : on
  // repart d'un lot vide, comme promis.
  rows.forEach((r) => { r.querySelector(".billing-check").checked = false; });
  refresh();
})();
