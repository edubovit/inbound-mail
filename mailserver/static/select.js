(() => {
  let sequence = 0;
  let opened = null;

  function enhance(select) {
    if (select.dataset.enhanced || select.multiple || select.size > 1) return;
    const label = select.labels[0];
    if (!label) return;
    select.dataset.enhanced = "true";
    const id = `choice-${++sequence}`;
    label.id ||= `${id}-label`;
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger";
    trigger.id = `${id}-trigger`;
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-labelledby", label.id);
    trigger.setAttribute("aria-controls", `${id}-menu`);
    for (const name of ["aria-describedby", "aria-invalid", "aria-required"]) {
      if (select.hasAttribute(name)) trigger.setAttribute(name, select.getAttribute(name));
    }
    if (select.required) trigger.setAttribute("aria-required", "true");
    const menu = document.createElement("div");
    menu.className = "select-menu";
    menu.id = `${id}-menu`;
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-labelledby", label.id);
    menu.hidden = true;
    document.body.append(menu);
    const options = [...select.options];
    const items = options.map((option, index) => {
      const item = document.createElement("div");
      item.className = "select-option";
      item.id = `${id}-option-${index}`;
      item.setAttribute("role", "option");
      item.textContent = option.textContent;
      item.setAttribute("aria-label", option.textContent);
      item.setAttribute("aria-disabled", String(option.disabled));
      item.addEventListener("pointerdown", event => { if (event.pointerType === "mouse") event.preventDefault(); });
      item.addEventListener("click", () => choose(index));
      item.addEventListener("pointermove", event => { if (event.pointerType === "mouse" && !option.disabled) activate(index); });
      menu.append(item);
      return item;
    });
    let active = 0;
    let anchor;
    let search = "";
    let lastTyped = 0;

    function sync() {
      trigger.textContent = options[select.selectedIndex]?.textContent || "Choose an option";
      trigger.disabled = select.disabled;
      items.forEach((item, index) => item.setAttribute("aria-selected", String(index === select.selectedIndex)));
    }
    function close() {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      if (opened?.trigger === trigger) opened = null;
      search = "";
    }
    function activate(index) {
      if (index < 0 || !options[index] || options[index].disabled) return;
      active = index;
      items.forEach((item, i) => item.classList.toggle("is-active", i === index));
      trigger.setAttribute("aria-activedescendant", items[index].id);
      items[index].scrollIntoView({block: "nearest"});
    }
    function open() {
      if (trigger.disabled) return;
      opened?.close();
      sync();
      anchor = trigger.getBoundingClientRect();
      menu.style.width = `${Math.min(anchor.width, innerWidth - 16)}px`;
      menu.style.left = `${Math.max(8, Math.min(anchor.left, innerWidth - anchor.width - 8))}px`;
      const below = innerHeight - anchor.bottom - 12;
      const above = anchor.top - 12;
      const flip = below < Math.min(options.length * 42 + 10, 240) && above > below;
      menu.style.maxHeight = `${Math.max(40, Math.min(280, flip ? above : below))}px`;
      menu.hidden = false;
      menu.style.top = `${flip ? Math.max(8, anchor.top - menu.offsetHeight - 4) : anchor.bottom + 4}px`;
      trigger.setAttribute("aria-expanded", "true");
      opened = {trigger, menu, close, moved: () => {
        const rect = trigger.getBoundingClientRect();
        return rect.top !== anchor.top || rect.left !== anchor.left || rect.width !== anchor.width;
      }};
      activate(select.selectedIndex >= 0 ? select.selectedIndex : options.findIndex(option => !option.disabled));
    }
    function choose(index) {
      if (options[index].disabled) return;
      select.selectedIndex = index;
      select.dispatchEvent(new Event("input", {bubbles: true}));
      select.dispatchEvent(new Event("change", {bubbles: true}));
      sync();
      close();
      trigger.focus({preventScroll: true});
    }
    trigger.addEventListener("click", () => menu.hidden ? open() : close());
    trigger.addEventListener("keydown", event => {
      if (event.key === "Tab") { close(); return; }
      if (event.key === "Escape") { event.preventDefault(); close(); return; }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const wasClosed = menu.hidden;
        if (wasClosed) open();
        const enabled = options.map((option, index) => option.disabled ? -1 : index).filter(index => index >= 0);
        const position = enabled.indexOf(active);
        if (event.key === "Home") activate(enabled[0]);
        else if (event.key === "End") activate(enabled.at(-1));
        else if (!wasClosed) activate(enabled[Math.max(0, Math.min(enabled.length - 1, position + (event.key === "ArrowDown" ? 1 : -1)))]);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (menu.hidden) open(); else choose(active);
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (menu.hidden) open();
        const now = Date.now();
        search = now - lastTyped > 700 ? event.key : search + event.key;
        lastTyped = now;
        const match = options.findIndex(option => !option.disabled && option.textContent.toLowerCase().startsWith(search.toLowerCase()));
        if (match >= 0) activate(match);
      }
    });
    select.addEventListener("change", sync);
    select.addEventListener("invalid", event => { event.preventDefault(); trigger.focus(); });
    select.form?.addEventListener("reset", () => setTimeout(sync, 0));
    trigger.addEventListener("focus", sync);
    label.htmlFor = trigger.id;
    select.hidden = true;
    select.after(trigger);
    sync();
  }

  function scan(root) {
    if (root.matches?.("select")) enhance(root);
    root.querySelectorAll?.("select").forEach(enhance);
  }
  scan(document);
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(scan));
    if (opened && !opened.trigger.isConnected) { opened.close(); }
  }).observe(document.body, {childList: true, subtree: true});
  document.addEventListener("pointerdown", event => {
    if (opened && !opened.trigger.contains(event.target) && !opened.menu.contains(event.target)) opened.close();
  });
  document.addEventListener("focusin", event => {
    if (opened && event.target !== opened.trigger && !opened.menu.contains(event.target)) opened.close();
  });
  window.addEventListener("scroll", () => { if (opened?.moved()) opened.close(); }, true);
  window.addEventListener("resize", () => opened?.close());
})();
