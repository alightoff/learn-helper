function syncThemeButton() {
  const theme = document.documentElement.dataset.theme || "light";
  const label = document.querySelector("[data-theme-label]");
  if (label) {
    label.textContent = theme === "dark" ? "Light theme" : "Dark theme";
  }
}

function initThemeToggle() {
  const toggle = document.querySelector("[data-theme-toggle]");
  syncThemeButton();
  if (!toggle) {
    return;
  }

  toggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.dataset.theme || "light";
    const nextTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    try {
      window.localStorage.setItem("learn-helper-theme", nextTheme);
    } catch (error) {
      // Theme persistence is optional.
    }
    syncThemeButton();
  });
}

function initSidebarToggle() {
  const shell = document.querySelector("[data-app-shell]");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  if (!shell || !toggle) {
    return;
  }

  try {
    if (window.localStorage.getItem("learn-helper-sidebar") === "collapsed") {
      shell.classList.add("is-sidebar-collapsed");
    }
  } catch (error) {
    // Sidebar persistence is optional.
  }

  toggle.addEventListener("click", () => {
    shell.classList.toggle("is-sidebar-collapsed");
    const nextState = shell.classList.contains("is-sidebar-collapsed") ? "collapsed" : "expanded";
    try {
      window.localStorage.setItem("learn-helper-sidebar", nextState);
    } catch (error) {
      // Sidebar persistence is optional.
    }
  });
}

function initLanguageToggle() {
  const toggle = document.querySelector("[data-lang-toggle]");
  if (!toggle) {
    return;
  }

  const translations = {
    en: {
      "nav-dashboard": "Dashboard",
      "nav-courses": "Courses",
      "nav-reader": "PDF Reader",
      "nav-review": "Review Queue",
      "nav-sessions": "Sessions",
      "search-placeholder": "Search resources...",
      "page-Dashboard": "Dashboard",
      "page-Courses": "Courses",
      "page-PDF Reader": "PDF Reader",
      "page-Review": "Review",
      "page-Sessions": "Sessions",
      "action-new-course": "New course",
      "action-create-course": "Create course",
      "action-cancel": "Cancel",
      "action-open-courses": "Open courses",
      "action-start-session": "Start session",
      "label-active-courses": "Active courses",
      "label-modules-done": "Modules done",
      "label-review-queue": "Review queue",
      "label-study-time": "Study time",
    },
    ru: {
      "nav-dashboard": "Дашборд",
      "nav-courses": "Курсы",
      "nav-reader": "PDF Ридер",
      "nav-review": "Повторение",
      "nav-sessions": "Сессии",
      "search-placeholder": "Поиск ресурсов...",
      "page-Dashboard": "Дашборд",
      "page-Courses": "Курсы",
      "page-PDF Reader": "PDF Ридер",
      "page-Review": "Повторение",
      "page-Sessions": "Сессии",
      "action-new-course": "Новый курс",
      "action-create-course": "Создать курс",
      "action-cancel": "Отмена",
      "action-open-courses": "Открыть курсы",
      "action-start-session": "Начать сессию",
      "label-active-courses": "Активные курсы",
      "label-modules-done": "Модули пройдены",
      "label-review-queue": "Очередь повторения",
      "label-study-time": "Время учебы",
    },
  };

  const applyLanguage = (language) => {
    document.documentElement.lang = language;
    toggle.textContent = language.toUpperCase();
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.dataset.i18n;
      if (key && translations[language][key]) {
        element.textContent = translations[language][key];
      }
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      const key = element.dataset.i18nPlaceholder;
      if (key && translations[language][key]) {
        element.setAttribute("placeholder", translations[language][key]);
      }
    });
    document.querySelectorAll("[data-page-title]").forEach((element) => {
      const key = `page-${element.dataset.pageTitle}`;
      if (translations[language][key]) {
        element.textContent = translations[language][key];
      }
    });
  };

  let currentLanguage = "en";
  try {
    currentLanguage = window.localStorage.getItem("learn-helper-lang") || "en";
  } catch (error) {
    currentLanguage = "en";
  }
  applyLanguage(currentLanguage);

  toggle.addEventListener("click", () => {
    const nextLanguage = document.documentElement.lang === "ru" ? "en" : "ru";
    try {
      window.localStorage.setItem("learn-helper-lang", nextLanguage);
    } catch (error) {
      // Language persistence is optional.
    }
    applyLanguage(nextLanguage);
  });
}

function initGlobalSearch() {
  const input = document.querySelector("[data-global-search]");
  if (!(input instanceof HTMLInputElement)) {
    return;
  }

  const emptyNotice = document.createElement("div");
  emptyNotice.className = "empty-state global-search-empty";
  emptyNotice.textContent = "No visible items match this search.";
  emptyNotice.hidden = true;
  const content = document.querySelector(".app-main__inner");
  if (content) {
    content.appendChild(emptyNotice);
  }

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    const items = Array.from(document.querySelectorAll("[data-search-item]"));
    let visibleCount = 0;

    items.forEach((item) => {
      const text = item.getAttribute("data-search-item") || item.textContent || "";
      const matches = !query || text.toLowerCase().includes(query);
      item.hidden = !matches;
      if (matches) {
        visibleCount += 1;
      }
    });

    emptyNotice.hidden = !query || items.length === 0 || visibleCount > 0;
  });
}

function initDialogs() {
  document.querySelectorAll("[data-dialog-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const dialogId = trigger.getAttribute("data-dialog-open");
      const dialog = dialogId ? document.getElementById(dialogId) : null;
      if (dialog instanceof HTMLDialogElement) {
        dialog.showModal();
      }
    });
  });

  document.querySelectorAll("[data-dialog]").forEach((dialog) => {
    if (!(dialog instanceof HTMLDialogElement)) {
      return;
    }

    dialog.querySelectorAll("[data-dialog-close]").forEach((trigger) => {
      trigger.addEventListener("click", () => dialog.close());
    });

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  });
}

function initReaderResizer() {
  const layout = document.querySelector("[data-resizable-viewer]");
  const resizer = document.querySelector("[data-reader-resizer]");
  if (!(layout instanceof HTMLElement) || !(resizer instanceof HTMLElement)) {
    return;
  }

  try {
    const storedWidth = window.localStorage.getItem("learn-helper-reader-sidebar-width");
    if (storedWidth) {
      layout.style.setProperty("--reader-sidebar-width", storedWidth);
    }
  } catch (error) {
    // Reader pane persistence is optional.
  }

  let isDragging = false;

  const applyWidth = (clientX) => {
    const bounds = layout.getBoundingClientRect();
    const width = Math.min(Math.max(clientX - bounds.left, 240), Math.min(560, bounds.width * 0.55));
    const value = `${Math.round(width)}px`;
    layout.style.setProperty("--reader-sidebar-width", value);
    try {
      window.localStorage.setItem("learn-helper-reader-sidebar-width", value);
    } catch (error) {
      // Reader pane persistence is optional.
    }
  };

  resizer.addEventListener("pointerdown", (event) => {
    isDragging = true;
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-reader");
  });

  resizer.addEventListener("pointermove", (event) => {
    if (isDragging) {
      applyWidth(event.clientX);
    }
  });

  const stopDragging = () => {
    isDragging = false;
    document.body.classList.remove("is-resizing-reader");
  };

  resizer.addEventListener("pointerup", stopDragging);
  resizer.addEventListener("pointercancel", stopDragging);
}

initThemeToggle();
initSidebarToggle();
initLanguageToggle();
initGlobalSearch();
initDialogs();
initReaderResizer();

document.documentElement.dataset.appReady = "true";
