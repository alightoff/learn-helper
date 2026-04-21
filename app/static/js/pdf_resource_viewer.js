import * as pdfjsLib from "../vendor/pdfjs/legacy/build/pdf.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "../vendor/pdfjs/legacy/build/pdf.worker.mjs",
  import.meta.url,
).toString();

const viewerRoot = document.querySelector("[data-pdf-resource-viewer]");

if (viewerRoot instanceof HTMLElement) {
  void initPdfResourceViewer(viewerRoot);
}

async function initPdfResourceViewer(root) {
  const canvas = root.querySelector("[data-pdf-canvas]");
  const pageInput = root.querySelector("[data-page-input]");
  const pageLabel = root.querySelector("[data-page-label]");
  const prevButton = root.querySelector("[data-action='prev-page']");
  const nextButton = root.querySelector("[data-action='next-page']");
  const scaleSelect = root.querySelector("[data-scale-select]");
  const loadingMessage = root.querySelector("[data-pdf-loading]");
  const errorMessage = root.querySelector("[data-pdf-error]");
  const outlineButtons = Array.from(root.querySelectorAll("[data-outline-page]")).filter(
    (element) => element instanceof HTMLButtonElement,
  );

  if (!(canvas instanceof HTMLCanvasElement)) {
    return;
  }

  const context = canvas.getContext("2d", { alpha: false });
  if (!context) {
    showError(errorMessage, "The browser could not initialize the PDF canvas.");
    return;
  }

  let pdfDocument = null;
  let currentPage = clampPositiveNumber(root.dataset.initialPage, 1);
  let scale = clampScale(scaleSelect instanceof HTMLSelectElement ? scaleSelect.value : "1.25");
  let activeOutlineButton = null;
  let activeRenderTask = null;
  let renderVersion = 0;

  bindEvents();

  try {
    setLoading(loadingMessage, true);
    pdfDocument = await loadDocument(root.dataset.fileUrl);
    currentPage = clampPage(currentPage, pdfDocument.numPages);
    await renderCurrentPage();
  } catch (error) {
    showError(
      errorMessage,
      error instanceof Error ? error.message : "The PDF could not be loaded.",
    );
  } finally {
    setLoading(loadingMessage, false);
  }

  function bindEvents() {
    if (prevButton instanceof HTMLButtonElement) {
      prevButton.addEventListener("click", () => {
        setCurrentPage(currentPage - 1);
      });
    }

    if (nextButton instanceof HTMLButtonElement) {
      nextButton.addEventListener("click", () => {
        setCurrentPage(currentPage + 1);
      });
    }

    if (pageInput instanceof HTMLInputElement) {
      pageInput.addEventListener("change", () => {
        setCurrentPage(clampPositiveNumber(pageInput.value, currentPage));
      });
    }

    if (scaleSelect instanceof HTMLSelectElement) {
      scaleSelect.addEventListener("change", () => {
        scale = clampScale(scaleSelect.value);
        void renderCurrentPage();
      });
    }

    outlineButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const outlinePage = clampPositiveNumber(button.dataset.outlinePage, currentPage);
        setCurrentPage(outlinePage);
      });
    });

    window.addEventListener("popstate", () => {
      setCurrentPage(getPageFromUrl(), { updateHistory: false });
    });
  }

  async function renderCurrentPage({ updateHistory = true } = {}) {
    if (!pdfDocument) {
      return;
    }

    const version = ++renderVersion;
    await cancelActiveRenderTask();
    const page = await pdfDocument.getPage(currentPage);
    const viewport = page.getViewport({ scale });
    const outputScale = window.devicePixelRatio || 1;

    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;

    activeRenderTask = page.render({
      canvasContext: context,
      viewport,
      transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
      background: "#ffffff",
    });

    try {
      await activeRenderTask.promise;
    } catch (error) {
      if (isCancelledRender(error)) {
        return;
      }
      throw error;
    } finally {
      activeRenderTask = null;
    }

    if (version !== renderVersion) {
      return;
    }

    updateControls();
    highlightActiveOutline();
    if (updateHistory) {
      syncUrl();
    }
  }

  function setCurrentPage(nextPage, { updateHistory = true } = {}) {
    const boundedPage = clampPage(nextPage, pdfDocument?.numPages ?? null);
    if (boundedPage === currentPage && updateHistory) {
      highlightActiveOutline();
      syncUrl();
      updateControls();
      return;
    }

    currentPage = boundedPage;
    updateControls();
    void renderCurrentPage({ updateHistory });
  }

  function updateControls() {
    const totalPages = pdfDocument?.numPages ?? clampPositiveNumber(root.dataset.pageCount, 1);

    if (pageInput instanceof HTMLInputElement) {
      pageInput.value = String(currentPage);
      pageInput.max = String(totalPages);
    }

    if (pageLabel instanceof HTMLElement) {
      pageLabel.textContent = `of ${totalPages}`;
    }

    if (prevButton instanceof HTMLButtonElement) {
      prevButton.disabled = currentPage <= 1;
    }

    if (nextButton instanceof HTMLButtonElement) {
      nextButton.disabled = currentPage >= totalPages;
    }
  }

  function highlightActiveOutline() {
    const nextActiveButton = findActiveOutlineButton(outlineButtons, currentPage);
    if (activeOutlineButton === nextActiveButton) {
      return;
    }

    if (activeOutlineButton instanceof HTMLButtonElement) {
      activeOutlineButton.classList.remove("is-active");
    }

    activeOutlineButton = nextActiveButton;

    if (activeOutlineButton instanceof HTMLButtonElement) {
      activeOutlineButton.classList.add("is-active");
      activeOutlineButton.scrollIntoView({ block: "nearest" });
    }
  }

  function syncUrl() {
    const url = new URL(window.location.href);
    if (currentPage <= 1) {
      url.searchParams.delete("page");
    } else {
      url.searchParams.set("page", String(currentPage));
    }
    window.history.replaceState({ page: currentPage }, "", url);
  }

  async function cancelActiveRenderTask() {
    if (!activeRenderTask) {
      return;
    }

    activeRenderTask.cancel();
    try {
      await activeRenderTask.promise;
    } catch (error) {
      if (!isCancelledRender(error)) {
        throw error;
      }
    } finally {
      activeRenderTask = null;
    }
  }
}

async function loadDocument(fileUrl) {
  if (!fileUrl) {
    throw new Error("The PDF file URL is missing.");
  }

  const loadingTask = pdfjsLib.getDocument({
    url: fileUrl,
    cMapUrl: new URL("../vendor/pdfjs/cmaps/", import.meta.url).toString(),
    cMapPacked: true,
    standardFontDataUrl: new URL("../vendor/pdfjs/standard_fonts/", import.meta.url).toString(),
  });

  return loadingTask.promise;
}

function findActiveOutlineButton(buttons, currentPage) {
  let bestMatch = null;
  let bestPage = 0;

  buttons.forEach((button) => {
    const page = clampPositiveNumber(button.dataset.outlinePage, 0);
    if (page <= currentPage && page >= bestPage) {
      bestMatch = button;
      bestPage = page;
    }
  });

  return bestMatch;
}

function getPageFromUrl() {
  const url = new URL(window.location.href);
  const page = url.searchParams.get("page");
  if (!page) {
    return 1;
  }
  return clampPositiveNumber(page, 1);
}

function clampPositiveNumber(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return parsed;
}

function clampPage(value, totalPages) {
  if (!Number.isFinite(totalPages) || totalPages === null || totalPages < 1) {
    return Math.max(value, 1);
  }
  return Math.max(1, Math.min(value, totalPages));
}

function clampScale(value) {
  const parsed = Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(parsed) || parsed < 0.5) {
    return 1.25;
  }
  return parsed;
}

function setLoading(element, isLoading) {
  if (element instanceof HTMLElement) {
    element.hidden = !isLoading;
  }
}

function showError(element, message) {
  if (!(element instanceof HTMLElement)) {
    return;
  }

  element.textContent = message;
  element.hidden = false;
}

function isCancelledRender(error) {
  return error instanceof Error && error.name === "RenderingCancelledException";
}
