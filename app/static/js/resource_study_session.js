function formatDuration(totalSeconds) {
  const seconds = Math.max(Number.parseInt(totalSeconds, 10) || 0, 0);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`;
  }
  return `${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`;
}

function resolvePomodoroState(elapsedSeconds, workSeconds, breakSeconds, targetCycles) {
  if (!workSeconds || workSeconds <= 0) {
    return null;
  }

  const safeBreakSeconds = Math.max(breakSeconds || 0, 0);
  const safeElapsedSeconds = Math.max(elapsedSeconds, 0);

  if (Number.isFinite(targetCycles) && targetCycles > 0) {
    const totalPlannedSeconds = (targetCycles * workSeconds) + (Math.max(targetCycles - 1, 0) * safeBreakSeconds);
    let remainingElapsedSeconds = Math.min(safeElapsedSeconds, totalPlannedSeconds);

    for (let cycleIndex = 1; cycleIndex <= targetCycles; cycleIndex += 1) {
      if (remainingElapsedSeconds < workSeconds) {
        return {
          phaseLabel: "Work",
          phaseRemainingSeconds: workSeconds - remainingElapsedSeconds,
          cycleLabel: `Cycle ${cycleIndex}`,
          completedCycles: cycleIndex - 1,
          isComplete: false,
        };
      }

      remainingElapsedSeconds -= workSeconds;
      const completedCycles = cycleIndex;

      if (cycleIndex === targetCycles) {
        return {
          phaseLabel: "Complete",
          phaseRemainingSeconds: 0,
          cycleLabel: `Cycle ${cycleIndex}`,
          completedCycles,
          isComplete: true,
        };
      }

      if (safeBreakSeconds > 0) {
        if (remainingElapsedSeconds < safeBreakSeconds) {
          const nextCycle = cycleIndex + 1;
          return {
            phaseLabel: "Break",
            phaseRemainingSeconds: safeBreakSeconds - remainingElapsedSeconds,
            cycleLabel: `Cycle ${nextCycle}`,
            completedCycles,
            isComplete: false,
          };
        }
        remainingElapsedSeconds -= safeBreakSeconds;
      }
    }
  }

  const cycleLength = Math.max(workSeconds + safeBreakSeconds, workSeconds);
  const cycleIndex = Math.floor(safeElapsedSeconds / cycleLength) + 1;
  const cycleOffset = safeElapsedSeconds % cycleLength;
  const inBreak = safeBreakSeconds > 0 && cycleOffset >= workSeconds;

  let completedCycles = 0;
  if (safeElapsedSeconds >= workSeconds) {
    completedCycles = 1 + Math.floor(Math.max(safeElapsedSeconds - workSeconds, 0) / cycleLength);
  }

  return {
    phaseLabel: inBreak ? "Break" : "Work",
    phaseRemainingSeconds: inBreak ? Math.max(safeBreakSeconds - (cycleOffset - workSeconds), 0) : Math.max(workSeconds - cycleOffset, 0),
    cycleLabel: `Cycle ${cycleIndex}`,
    completedCycles,
    isComplete: false,
  };
}

function initResourceSessionWidget() {
  const widget = document.querySelector("[data-resource-session-widget]");
  if (!(widget instanceof HTMLElement)) {
    return;
  }

  const dialog = widget.querySelector("[data-session-feedback-dialog]");
  const openDialogButton = widget.querySelector("[data-open-session-feedback]");
  const closeDialogButton = widget.querySelector("[data-close-session-feedback]");
  const pageInput = document.querySelector("[data-page-input]");
  const formFields = Array.from(widget.querySelectorAll("[data-session-current-page]"));
  const returnFields = Array.from(widget.querySelectorAll("[data-session-return-to]"));
  const forms = Array.from(widget.querySelectorAll("[data-session-return-form]")).filter(
    (element) => element instanceof HTMLFormElement,
  );

  let completionDialogShown = false;

  const syncPageContext = () => {
    const currentPage = pageInput instanceof HTMLInputElement ? pageInput.value || "1" : "1";
    formFields.forEach((field) => {
      if (field instanceof HTMLInputElement) {
        field.value = currentPage;
      }
    });
    returnFields.forEach((field) => {
      if (field instanceof HTMLInputElement) {
        field.value = `${window.location.pathname}${window.location.search}#study-session-widget`;
      }
    });
  };

  const updateWidget = () => {
    const status = widget.dataset.sessionStatus;
    const baseElapsedSeconds = Number.parseInt(widget.dataset.sessionElapsedSeconds || "0", 10) || 0;
    const activeStartedAt = widget.dataset.sessionActiveStartedAt;
    let elapsedSeconds = baseElapsedSeconds;

    if (status === "running" && activeStartedAt) {
      const activeStartedAtMs = Date.parse(activeStartedAt);
      if (!Number.isNaN(activeStartedAtMs)) {
        elapsedSeconds += Math.max(Math.floor((Date.now() - activeStartedAtMs) / 1000), 0);
      }
    }

    const elapsedTarget = widget.querySelector("[data-session-elapsed]");
    if (elapsedTarget instanceof HTMLElement) {
      elapsedTarget.textContent = formatDuration(elapsedSeconds);
    }

    if (widget.dataset.timerMode !== "pomodoro") {
      return;
    }

    const workSeconds = Number.parseInt(widget.dataset.pomodoroWorkSeconds || "0", 10) || 0;
    const breakSeconds = Number.parseInt(widget.dataset.pomodoroBreakSeconds || "0", 10) || 0;
    const targetCycles = Number.parseInt(widget.dataset.targetCycles || "", 10);
    const pomodoroState = resolvePomodoroState(
      elapsedSeconds,
      workSeconds,
      breakSeconds,
      Number.isNaN(targetCycles) ? null : targetCycles,
    );
    if (!pomodoroState) {
      return;
    }

    const phaseTarget = widget.querySelector("[data-session-phase]");
    if (phaseTarget instanceof HTMLElement) {
      phaseTarget.textContent = pomodoroState.phaseLabel;
    }

    const remainingTarget = widget.querySelector("[data-session-phase-remaining]");
    if (remainingTarget instanceof HTMLElement) {
      remainingTarget.textContent = formatDuration(pomodoroState.phaseRemainingSeconds);
    }

    const cycleTarget = widget.querySelector("[data-session-cycle]");
    if (cycleTarget instanceof HTMLElement) {
      cycleTarget.textContent = pomodoroState.cycleLabel;
    }

    const targetProgressTarget = widget.querySelector("[data-session-target-progress]");
    if (targetProgressTarget instanceof HTMLElement && !Number.isNaN(targetCycles)) {
      targetProgressTarget.textContent = `${pomodoroState.completedCycles} / ${targetCycles}`;
    }

    const needsFeedback = widget.dataset.sessionNeedsFeedback === "true" || pomodoroState.isComplete;
    if (needsFeedback && dialog instanceof HTMLDialogElement && !completionDialogShown) {
      completionDialogShown = true;
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "open");
      }
    }
  };

  syncPageContext();
  updateWidget();
  window.setInterval(updateWidget, 1000);
  window.addEventListener("popstate", syncPageContext);

  if (pageInput instanceof HTMLInputElement) {
    pageInput.addEventListener("change", syncPageContext);
    pageInput.addEventListener("input", syncPageContext);
  }

  forms.forEach((form) => {
    form.addEventListener("submit", syncPageContext);
  });

  if (openDialogButton instanceof HTMLButtonElement && dialog instanceof HTMLDialogElement) {
    openDialogButton.addEventListener("click", () => {
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "open");
      }
    });
  }

  if (closeDialogButton instanceof HTMLButtonElement && dialog instanceof HTMLDialogElement) {
    closeDialogButton.addEventListener("click", () => {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    });
  }
}

initResourceSessionWidget();
