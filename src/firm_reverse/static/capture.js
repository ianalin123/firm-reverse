(function () {
  const fr = window.firmReverse;
  const slot = document.getElementById("captureSlot");
  if (!fr || !slot) return;
  const { el } = fr;

  const style = document.createElement("style");
  style.textContent = `
    .capture-fits { color: #1d6b3d; font-weight: 700; }
    .capture-mismatch { color: var(--fault, #c23b22); font-weight: 700; }
    .capture-card h2 { font-size: 16px; margin: 0 0 4px; }
    .capture-card .hint { font-size: 13.5px; color: var(--muted); margin: 0 0 10px; }
    .capture-card form { display: flex; flex-wrap: wrap; gap: 8px; align-items: stretch; }
    .capture-card input[type=file] { font: 13px var(--mono); flex: 1 1 220px; min-width: 0; align-self: center; }
    .capture-card input[type=text] { flex: 1 1 200px; min-height: 46px; }
    .capture-card button { min-height: 46px; }
    .capture-card pre { font: 12.5px/1.45 var(--mono); background: var(--paper); border: 1px solid var(--rule); border-radius: 6px; padding: 8px 10px; margin: 10px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 320px; overflow: auto; }
    .capture-card pre:empty { display: none; }
    .capture-card .capture-head { font: 600 12px var(--mono); color: var(--trace); margin-top: 10px; }
    .capture-card.probe-now { border: 2px solid var(--trace); box-shadow: 0 0 0 4px color-mix(in srgb, var(--trace) 15%, transparent); }
    .capture-card.probe-now h2::after { content: "  now"; font: 600 12px var(--mono); color: var(--trace); }
  `;
  document.head.append(style);

  const file = el("input", { type: "file", accept: ".csv,.vcd,.sr" });
  file.setAttribute("aria-label", "Saleae capture file");
  const note = el("input", { type: "text", placeholder: "Optional note, e.g. CH0 on SCL, CH1 on SDA, pressed power" });
  const button = el("button", { type: "submit", textContent: "Add capture", disabled: true });
  const head = el("div", { className: "capture-head" });
  const output = el("pre");
  const form = el("form", {}, file, note, button);
  const card = el("section", { className: "card capture-card" },
    el("h2", { textContent: "Probe with the Saleae" }),
    el("p", { className: "hint", textContent: "Clip where the guide says, capture in Logic 2, then File, Export Data, CSV." }),
    form, head, output);
  slot.replaceChildren(card);

  file.addEventListener("change", () => { button.disabled = !file.files.length; });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const chosen = file.files[0];
    if (!chosen) return;
    button.disabled = true;
    fr.setBusy(true, "Decoding the capture and asking the guide...");
    try {
      await fr.ensureSession();
      const body = new FormData();
      body.append("capture", chosen);
      body.append("note", note.value.trim());
      const res = await fr.api(`/api/guide/${fr.session()}/capture`, { method: "POST", body });
      const result = await res.json();
      head.textContent = `Capture ${result.capture}, decoded`;
      output.textContent = result.summary;
      fr.render(result.turn);
      const check = (result.turn.capture_check || []).find((c) => Number(c.capture) === Number(result.capture));
      if (check) {
        const fits = check.verdict === "fits";
        head.textContent = `Capture ${result.capture}, decoded. ${fits ? "Fits this device." : check.verdict === "mismatch" ? "Does not fit this device, not used as evidence." : "Unclear fit."}`;
        head.className = fits ? "capture-fits" : "capture-mismatch";
        output.textContent = `${result.summary}\n\nCheck: ${check.reason || ""}`;
      }
      file.value = "";
      note.value = "";
      fr.setBusy(false, `Capture ${result.capture} added.`);
    } catch (error) {
      fr.setBusy(false, `Capture failed: ${error.message}`, true);
    } finally {
      button.disabled = !file.files.length;
    }
  });

  const kind = document.getElementById("kind");
  if (kind) {
    const sync = () => card.classList.toggle("probe-now", kind.textContent.includes("probe"));
    new MutationObserver(sync).observe(kind, { childList: true, characterData: true, subtree: true });
    sync();
  }
})();
