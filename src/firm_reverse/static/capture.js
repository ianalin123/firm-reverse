(function () {
  const fr = window.firmReverse;
  const slot = document.getElementById("captureSlot");
  if (!fr || !slot) return;
  const { el } = fr;

  const style = document.createElement("style");
  style.textContent = `
    .capture-fits { color: #1d6b3d; font-weight: 700; }
    .capture-mismatch { color: #b3261e; font-weight: 700; }
    .capture-card { position: relative; padding-left: 26px; }
    .capture-card::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 10px; border-radius: 2px 0 0 2px;
      background: linear-gradient(#17201c 0 12.5%, #7a4a1e 12.5% 25%, #c62828 25% 37.5%, #e8780c 37.5% 50%, #e9c400 50% 62.5%, #2e9b4f 62.5% 75%, #1f63c9 75% 87.5%, #7b3fb8 87.5%); }
    .capture-card h2 { margin-left: -26px; padding-left: 26px; }
    .capture-card .hint { font-size: 15.5px; color: var(--muted); margin: 0 0 12px; max-width: 64ch; }
    .capture-card form { display: flex; flex-wrap: wrap; gap: 8px; align-items: stretch; }
    .capture-card input[type=file] { font: 500 15px var(--sans); flex: 1 1 220px; min-width: 0; align-self: center; }
    .capture-card input[type=file]::file-selector-button { font: 700 16px var(--cond); background: var(--panel); color: var(--ink); border: 2px solid var(--ink); border-radius: 4px; padding: 8px 14px; margin-right: 10px; cursor: pointer; }
    .capture-card input[type=file]:focus-visible { outline: 3px solid var(--trace); outline-offset: 3px; }
    .capture-card input[type=text] { flex: 1 1 200px; min-height: 50px; }
    .capture-card button { min-height: 50px; }
    .capture-card pre { font: 500 13px/1.5 var(--mono); background: #f2f5ef; color: var(--ink); border: 1px solid var(--rule); border-left: 4px solid var(--good); border-radius: 2px; padding: 10px 12px; margin: 10px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 320px; overflow: auto; }
    .capture-card pre:empty { display: none; }
    .capture-card .capture-head { font: 700 17px var(--cond); color: var(--good); margin-top: 12px; }
    .capture-card .capture-head:empty { display: none; }
    .capture-card.probe-now { border-color: var(--mask); outline: 4px solid var(--pad); outline-offset: 0; }
    .capture-card.probe-now h2 { background: var(--mask); color: var(--silk); }
    .capture-card.probe-now h2::after { content: "Do this now"; margin-left: 12px; font: 700 15px/1 var(--cond); color: var(--mask-deep); background: var(--pad); padding: 4px 8px 3px; border-radius: 2px; vertical-align: 3px; }
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
