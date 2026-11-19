(function () {
  "use strict";

  const viewer = document.querySelector("#viewer");
  const previousButton = document.querySelector("#previous");
  const nextButton = document.querySelector("#next");
  const stepLabel = document.querySelector("#step-label");
  const progressBar = document.querySelector("#progress-bar");
  const fileInput = document.querySelector("#rlo-file");
  const brand = document.querySelector(".brand");

  let rlo = normalizeRlo(window.SAMPLE_RLO);
  let screens = buildScreens(rlo);
  let currentIndex = 0;

  function normalizeRlo(input) {
    const value = input?.draft || input?.rlo || input;
    if (!value || !Array.isArray(value.components)) {
      throw new Error("This file does not contain an RLO with a components array.");
    }
    return {
      ...value,
      displayTitle: value.displayTitle || sentenceCase(value.title || value.topic || "Reusable Learning Object"),
      duration: value.duration || value.estimated_duration_minutes,
      bloom_level: value.enabling_objective?.bloom_level || value.bloom_level || value.performance_level
    };
  }

  function buildScreens(value) {
    return [{ kind: "intro", rlo: value }].concat(
      value.components.map((component, index) => ({
        kind: isQuestion(component) ? "question" : "content",
        component,
        index
      }))
    );
  }

  function isQuestion(component) {
    const content = component.content?.content || component.content || component.canonical_content;
    return Boolean(content && Array.isArray(content.options));
  }

  function render() {
    const screen = screens[currentIndex];
    viewer.innerHTML = "";
    viewer.append(screen.kind === "intro" ? renderIntro(screen.rlo) : renderComponent(screen.component, screen.kind));

    previousButton.disabled = currentIndex === 0;
    nextButton.textContent = currentIndex === screens.length - 1 ? "Start over" : "Next";
    stepLabel.textContent = `${currentIndex + 1} of ${screens.length}`;
    progressBar.style.width = `${((currentIndex + 1) / screens.length) * 100}%`;
    document.title = `${rlo.displayTitle} · RLO Showcase`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderIntro(value) {
    const section = element("article", "screen");
    const eyebrow = element("div", "eyebrow-row");
    eyebrow.append(
      textElement("span", "eyebrow", "Reusable Learning Object"),
      textElement("span", "pill", `${sentenceCase(value.content_type || "learning")} × ${sentenceCase(value.bloom_level || "apply")}`)
    );

    const title = textElement("h1", "hero-title", value.displayTitle);
    const objective = textElement(
      "p",
      "hero-objective",
      value.enabling_objective?.statement || value.terminal_objective || value.topic || value.title
    );
    const meta = element("div", "meta-row");
    if (value.duration) meta.append(textElement("span", "pill", `${value.duration} minutes`));
    if (value.audience?.length) meta.append(textElement("span", "pill", value.audience.join(", ")));
    meta.append(textElement("span", "pill", `${value.components.length} learning elements`));

    section.append(eyebrow, title, objective, meta);
    return section;
  }

  function renderComponent(component, kind) {
    const section = element("article", "screen");
    const layout = element("div", "content-layout");
    const main = element("div", "content-main");
    const origin = component.content?.origin || component.canonical_content?.origin;

    const eyebrow = element("div", "eyebrow-row");
    eyebrow.append(textElement("span", "eyebrow", labelFor(component)));
    if (origin) eyebrow.append(textElement("span", `pill pill-${origin}`, origin === "mixed" ? "Source + AI" : "Source grounded"));

    main.append(eyebrow, textElement("h1", "content-title", component.title || labelFor(component)));
    main.append(kind === "question" ? renderQuestion(component) : renderRichText(contentText(component)));

    layout.append(main);
    section.append(layout);
    return section;
  }

  function renderQuestion(component) {
    const content = component.content?.content || component.content || component.canonical_content;
    const wrapper = element("div", "question");
    const stem = element("div", "content-body question-stem");
    stem.innerHTML = markdown(content.stem || "Choose the best response.");
    const options = element("div", "options");
    const feedback = element("div", "feedback");
    feedback.hidden = true;

    content.options.forEach((option) => {
      const button = textElement("button", "option", option.text);
      button.type = "button";
      button.addEventListener("click", () => {
        options.querySelectorAll(".option").forEach((item) => item.classList.remove("correct", "incorrect"));
        button.classList.add(option.correct ? "correct" : "incorrect");
        feedback.innerHTML = `<strong>${option.correct ? "Correct" : "Not quite"}</strong><br>${escapeHtml(option.feedback || "Try another response.")}`;
        feedback.hidden = false;
      });
      options.append(button);
    });

    wrapper.append(stem, options, feedback);
    return wrapper;
  }

  function renderRichText(text) {
    const body = element("div", "content-body");
    body.innerHTML = markdown(text);
    return body;
  }

  function contentText(component) {
    const content = component.content?.content ?? component.content ?? component.canonical_content?.content ?? component.canonical_content;
    return typeof content === "string" ? content : JSON.stringify(content, null, 2);
  }

  function labelFor(component) {
    const labels = {
      hook: "Context",
      rule: "Learn",
      recall_prompt: "Prepare",
      example: "Worked example",
      multiple_choice_single: "Practice",
      transfer: "Apply"
    };
    return labels[component.type || component.cdt_type] || "Learning element";
  }

  function markdown(source) {
    const lines = String(source || "").replace(/\r/g, "").split("\n");
    let html = "";
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      if (line.startsWith("|")) {
        const tableLines = [];
        while (index < lines.length && lines[index].startsWith("|")) tableLines.push(lines[index++]);
        html += renderTable(tableLines);
        continue;
      }

      const heading = line.match(/^(#{2,3})\s+(.+)$/);
      if (heading) {
        const level = heading[1].length;
        html += `<h${level}>${inline(heading[2])}</h${level}>`;
        index += 1;
        continue;
      }

      if (/^[-*]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^[-*]\s+/.test(lines[index])) items.push(lines[index++].replace(/^[-*]\s+/, ""));
        html += `<ul>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`;
        continue;
      }

      if (/^\d+\.\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\d+\.\s+/.test(lines[index])) items.push(lines[index++].replace(/^\d+\.\s+/, ""));
        html += `<ol>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ol>`;
        continue;
      }

      const paragraph = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !/^(#{2,3})\s+|^[-*]\s+|^\d+\.\s+|^\|/.test(lines[index])) {
        paragraph.push(lines[index++]);
      }
      html += `<p>${inline(paragraph.join(" "))}</p>`;
    }
    return html;
  }

  function renderTable(lines) {
    if (lines.length < 2) return `<p>${inline(lines.join(" "))}</p>`;
    const rows = lines.map((line) => line.slice(1, -1).split("|").map((cell) => cell.trim()));
    const bodyRows = /^:?-+/.test(rows[1][0]) ? rows.slice(2) : rows.slice(1);
    return `<table><thead><tr>${rows[0].map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${bodyRows
      .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
      .join("")}</tbody></table>`;
  }

  function inline(value) {
    return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function sentenceCase(value) {
    const text = String(value || "").replace(/[_-]+/g, " ");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function element(tag, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  function textElement(tag, className, text) {
    const node = element(tag, className);
    node.textContent = text;
    return node;
  }

  function move(delta) {
    if (currentIndex === screens.length - 1 && delta > 0) currentIndex = 0;
    else currentIndex = Math.max(0, Math.min(screens.length - 1, currentIndex + delta));
    render();
  }

  previousButton.addEventListener("click", () => move(-1));
  nextButton.addEventListener("click", () => move(1));
  brand.addEventListener("click", (event) => {
    event.preventDefault();
    currentIndex = 0;
    render();
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.closest("button, input, label")) return;
    if (event.key === "ArrowRight") move(1);
    if (event.key === "ArrowLeft") move(-1);
  });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      rlo = normalizeRlo(JSON.parse(await file.text()));
      screens = buildScreens(rlo);
      currentIndex = 0;
      render();
    } catch (error) {
      viewer.innerHTML = `<div class="error-message"><strong>Could not open this RLO.</strong><br>${escapeHtml(error.message)}</div>`;
    } finally {
      fileInput.value = "";
    }
  });

  render();
})();
