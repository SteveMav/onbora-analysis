(() => {
  const form = document.getElementById("serp-search-form");
  if (!form) return;
  const scenario = document.getElementById("id_scenario");
  const engine = document.getElementById("id_engine");
  const query = document.getElementById("id_query");
  const helper = document.getElementById("serp-query-helper");
  const hint = document.getElementById("serp-scenario-hint");
  const subject = document.getElementById("serp-subject");
  const city = document.getElementById("serp-city");
  const companySources = document.querySelectorAll('input[name="company_source"]');
  const arspPicker = document.getElementById("serp-arsp-picker");
  function updateCompanySource() {
    const selected = document.querySelector('input[name="company_source"]:checked');
    arspPicker.hidden = selected?.value !== "arsp";
  }
  companySources.forEach((radio) => radio.addEventListener("change", updateCompanySource));
  updateCompanySource();
  const scenarios = {
    complete: { engine: "all", hint: "Chercher la même entreprise sur Google Web, Maps et News : 3 appels, jusqu’à 3 crédits hors cache.", suffix: "" },
    discovery: { engine: "google_maps", hint: "Trouver des établissements et leurs coordonnées publiques.", suffix: "" },
    profile: { engine: "google", hint: "Retrouver le site, les activités et les implantations d’une entreprise.", suffix: "activité services site officiel" },
    news: { engine: "google_news", hint: "Chercher des projets, partenariats et ouvertures. Ajoute when:1y pour cibler la dernière année.", suffix: "projet partenariat ouverture" },
    technology: { engine: "google", hint: "Chercher des indices publics. Ils ne prouvent pas une intention d’achat.", suffix: "technologie réseau fournisseur transformation numérique" },
  };
  helper.hidden = false;
  function updateHint() { hint.textContent = scenarios[scenario.value].hint; }
  updateHint();
  scenario.addEventListener("change", () => {
    engine.value = scenarios[scenario.value].engine;
    updateHint();
  });
  document.getElementById("serp-build-query").addEventListener("click", () => {
    if (!subject.value.trim()) { subject.focus(); return; }
    const selected = scenarios[scenario.value];
    query.value = [subject.value.trim(), city.value.trim(), "RDC", selected.suffix].filter(Boolean).join(" ");
    engine.value = selected.engine;
    query.focus();
  });
  const countries = document.getElementById("id_country");
  const coordinates = document.getElementById("id_coordinates");
  function updateEngine() {
    countries.disabled = engine.value === "google_maps";
    coordinates.disabled = !["google_maps", "all"].includes(engine.value);
    const combined = engine.value === "all";
    form.querySelector('[type="submit"]').textContent = combined ? "Lancer Web + Maps + News" : "Lancer la recherche SerpApi";
    document.getElementById("serp-progress").textContent = combined
      ? "3 appels en parallèle, jusqu’à 3 crédits hors cache. Aucun appel IA."
      : "1 appel, jusqu’à 1 crédit hors cache. Aucun appel IA.";
  }
  // Re-enable these controls before submit so Django receives all form fields.
  engine.addEventListener("change", updateEngine);
  scenario.addEventListener("change", updateEngine);
  document.getElementById("serp-build-query").addEventListener("click", updateEngine);
  updateEngine();
  form.addEventListener("submit", (event) => {
    if (form.dataset.submitting) { event.preventDefault(); return; }
    form.dataset.submitting = "true";
    // Keep all validated form fields in the submitted payload.
    countries.disabled = false;
    coordinates.disabled = false;
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = "Recherche en cours…";
    form.setAttribute("aria-busy", "true");
    document.getElementById("serp-progress").textContent = engine.value === "all"
      ? "Google Web, Maps et News recherchent en parallèle. 3 appels, sans relance automatique."
      : "SerpApi recherche les résultats. Un seul appel est envoyé, sans relance automatique.";
  });
  window.addEventListener("pageshow", () => {
    if (form.dataset.submitting) window.location.reload();
  });
})();
