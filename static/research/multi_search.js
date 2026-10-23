(() => {
  const selection = document.querySelector("[data-selection]");
  if (selection) {
    const selected = new Map();
    const key = selection.dataset.storageKey;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || "[]");
      if (Array.isArray(saved)) {
        for (const item of saved.slice(0, 5)) {
          if (Array.isArray(item) && /^\d+$/.test(item[0]) && typeof item[1] === "string") {
            selected.set(String(item[0]), item[1]);
          }
        }
      }
    } catch { /* Storage can be disabled; selection still works in this tab. */ }
    const list = document.getElementById("multi-companies");
    const notice = document.getElementById("selection-notice");
    const form = document.getElementById("batch-create");
    const launch = document.getElementById("launch-batch");
    const update = () => {
      document.getElementById("selection-count").textContent = selected.size + " / 5";
      document.getElementById("selection-empty").hidden = selected.size > 0;
      launch.disabled = selected.size === 0;
      launch.textContent = selected.size ? "Lancer " + selected.size + " recherche" + (selected.size > 1 ? "s" : "") : "Lancer les recherches";
      const basket = document.getElementById("selected-companies");
      const inputs = document.getElementById("selection-inputs");
      basket.replaceChildren();
      inputs.replaceChildren();
      for (const [id, name] of selected) {
        const row = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", "Retirer " + name);
        remove.addEventListener("click", () => {
          selected.delete(id);
          update();
          notice.textContent = name + " retirée de la sélection.";
          document.getElementById("multi-query").focus();
        });
        row.append(label, remove);
        basket.append(row);
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "record_ids";
        input.value = id;
        inputs.append(input);
      }
      for (const input of list.querySelectorAll("input[type=checkbox]")) {
        input.removeAttribute("name"); // Hidden inputs include selections from other pages.
        input.checked = selected.has(input.value);
        input.disabled = selected.size === 5 && !input.checked;
      }
      try { sessionStorage.setItem(key, JSON.stringify([...selected])); } catch {}
    };
    list.addEventListener("change", (event) => {
      const input = event.target;
      if (!input.matches("input[type=checkbox]")) return;
      if (input.checked && selected.size < 5) selected.set(input.value, input.dataset.companyName);
      else selected.delete(input.value);
      update();
      notice.textContent = selected.size === 5 ? "Les 5 entreprises sont sélectionnées. Tu peux lancer le lot." : selected.size + " entreprise(s) sélectionnée(s).";
    });
    const randomButton = document.getElementById("random-selection");
    randomButton.disabled = false;
    randomButton.addEventListener("click", async () => {
      randomButton.disabled = true;
      randomButton.textContent = "Tirage en cours…";
      notice.textContent = "Sélection aléatoire en cours…";
      const url = new URL(location.href);
      url.search = "";
      url.searchParams.set("q", document.getElementById("multi-query").value);
      url.searchParams.set("random", "1");
      try {
        const response = await fetch(url, {headers: {"Accept": "application/json"}});
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error();
        const data = await response.json();
        if (!data.companies.length) {
          notice.textContent = "Aucune entreprise trouvée pour ce tirage. Ta sélection est conservée.";
          return;
        }
        selected.clear();
        for (const company of data.companies) selected.set(company.id, company.name);
        update();
        notice.textContent = selected.size + " entreprise(s) sélectionnée(s) au hasard. Tu peux modifier la sélection ou lancer les recherches.";
      } catch {
        notice.textContent = "Impossible de tirer les entreprises au hasard. Réessaie. Ta sélection est conservée.";
      } finally {
        randomButton.disabled = false;
        randomButton.textContent = "Sélectionner 5 au hasard";
      }
    });
    let filterRequest;
    const load = async (url) => {
      filterRequest?.abort();
      filterRequest = new AbortController();
      const controller = filterRequest;
      url.searchParams.set("fragment", "1");
      list.setAttribute("aria-busy", "true");
      try {
        const response = await fetch(url, {signal: controller.signal, headers: {"Accept": "application/json"}});
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error();
        const data = await response.json();
        list.innerHTML = data.html;
        update();
        url.searchParams.delete("fragment");
        history.replaceState(null, "", url);
        notice.textContent = "Liste actualisée. Ta sélection est conservée.";
      } catch (error) {
        if (error.name !== "AbortError") notice.textContent = "Impossible d’actualiser la liste. Réessaie la recherche.";
      } finally {
        if (filterRequest === controller) list.removeAttribute("aria-busy");
      }
    };
    document.getElementById("multi-filter").addEventListener("submit", (event) => {
      event.preventDefault();
      const url = new URL(location.href);
      url.search = "";
      url.searchParams.set("q", document.getElementById("multi-query").value);
      load(url);
    });
    list.addEventListener("click", (event) => {
      const link = event.target.closest(".pagination-link");
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
      event.preventDefault();
      load(new URL(link.href));
    });
    form.addEventListener("submit", (event) => {
      if (!selected.size) { event.preventDefault(); return; }
      launch.disabled = true;
      launch.textContent = "Lancement…";
    });
    update();
  }

  const results = document.querySelector("[data-results]");
  if (results) {
    const notice = document.getElementById("report-notice");
    const active = () => results.querySelector("[data-active]")?.dataset.active === "true";
    let failures = 0;
    const poll = async () => {
      if (!active()) return;
      try {
        const response = await fetch(results.dataset.pollUrl, {headers: {"Accept": "application/json"}});
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error();
        const data = await response.json();
        if (results.innerHTML.trim() !== data.html.trim()) results.innerHTML = data.html;
        if (failures) notice.textContent = "Connexion rétablie. Les résultats sont à jour.";
        failures = 0;
        if (data.active) setTimeout(poll, 3000);
      } catch {
        failures += 1;
        notice.textContent = "La mise à jour est interrompue. Nouvelle tentative automatique…";
        setTimeout(poll, Math.min(3000 * failures, 15000));
      }
    };
    if (active()) setTimeout(poll, 2000);
    document.getElementById("copy-report").addEventListener("click", async () => {
      const text = document.getElementById("batch-report-text");
      try {
        await navigator.clipboard.writeText(text.value);
        notice.textContent = active() ? "Les résultats disponibles ont été copiés avec leurs liens." : "Les résumés et leurs liens ont été copiés.";
      } catch {
        text.hidden = false;
        text.focus();
        text.select();
        notice.textContent = "Le texte est sélectionné. Utilise Ctrl+C pour le copier.";
      }
    });
  }
})();
