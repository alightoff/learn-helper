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

  let phaseLabel = "Work";
  let phaseElapsed = cycleOffset;
  let phaseDuration = workSeconds;

  if (safeBreakSeconds > 0 && cycleOffset >= workSeconds) {
    phaseLabel = "Break";
    phaseElapsed = cycleOffset - workSeconds;
    phaseDuration = safeBreakSeconds;
  }

  let completedCycles = 0;
  if (safeElapsedSeconds >= workSeconds) {
    completedCycles = 1 + Math.floor(Math.max(safeElapsedSeconds - workSeconds, 0) / cycleLength);
  }

  return {
    phaseLabel,
    phaseRemainingSeconds: Math.max(phaseDuration - phaseElapsed, 0),
    cycleLabel: `Cycle ${cycleIndex}`,
    completedCycles,
    isComplete: false,
  };
}

function playCompletionSound() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    return;
  }

  const audioContext = new AudioContextClass();
  const gain = audioContext.createGain();
  gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.18, audioContext.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.9);
  gain.connect(audioContext.destination);

  [660, 880, 990].forEach((frequency, index) => {
    const oscillator = audioContext.createOscillator();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    oscillator.connect(gain);
    oscillator.start(audioContext.currentTime + (index * 0.16));
    oscillator.stop(audioContext.currentTime + 0.14 + (index * 0.16));
  });
}

function updateTimerCard(timerCard) {
  const status = timerCard.dataset.sessionStatus;
  const baseElapsedSeconds = Number.parseInt(timerCard.dataset.sessionElapsedSeconds || "0", 10) || 0;
  const activeStartedAt = timerCard.dataset.sessionActiveStartedAt;

  let elapsedSeconds = baseElapsedSeconds;
  if (status === "running" && activeStartedAt) {
    const activeStartedAtMs = Date.parse(activeStartedAt);
    if (!Number.isNaN(activeStartedAtMs)) {
      elapsedSeconds += Math.max(Math.floor((Date.now() - activeStartedAtMs) / 1000), 0);
    }
  }

  const elapsedTarget = timerCard.querySelector("[data-session-elapsed]");
  if (elapsedTarget) {
    elapsedTarget.textContent = formatDuration(elapsedSeconds);
  }

  if (timerCard.dataset.timerMode !== "pomodoro") {
    return;
  }

  const workSeconds = Number.parseInt(timerCard.dataset.pomodoroWorkSeconds || "0", 10) || 0;
  const breakSeconds = Number.parseInt(timerCard.dataset.pomodoroBreakSeconds || "0", 10) || 0;
  const targetCycles = Number.parseInt(timerCard.dataset.targetCycles || "", 10);
  const pomodoroState = resolvePomodoroState(
    elapsedSeconds,
    workSeconds,
    breakSeconds,
    Number.isNaN(targetCycles) ? null : targetCycles,
  );
  if (!pomodoroState) {
    return;
  }

  if (pomodoroState.isComplete && timerCard.dataset.completionSoundPlayed !== "true") {
    timerCard.dataset.completionSoundPlayed = "true";
    playCompletionSound();
  }

  const phaseTarget = timerCard.querySelector("[data-session-phase]");
  if (phaseTarget) {
    phaseTarget.textContent = pomodoroState.phaseLabel;
  }

  const remainingTarget = timerCard.querySelector("[data-session-phase-remaining]");
  if (remainingTarget) {
    remainingTarget.textContent = formatDuration(pomodoroState.phaseRemainingSeconds);
  }

  const cycleTarget = timerCard.querySelector("[data-session-cycle]");
  if (cycleTarget) {
    cycleTarget.textContent = pomodoroState.cycleLabel;
  }

  const completedCyclesTarget = timerCard.querySelector("[data-session-completed-cycles]");
  if (completedCyclesTarget) {
    completedCyclesTarget.textContent = String(pomodoroState.completedCycles);
  }

  const targetProgressTarget = timerCard.querySelector("[data-session-target-progress]");
  if (targetProgressTarget && !Number.isNaN(targetCycles)) {
    targetProgressTarget.textContent = `${pomodoroState.completedCycles} / ${targetCycles}`;
  }
}

function initActiveSessionTimer() {
  const timerCard = document.querySelector("[data-session-timer]");
  if (!timerCard) {
    return;
  }

  updateTimerCard(timerCard);
  window.setInterval(() => {
    updateTimerCard(timerCard);
  }, 1000);
}

function initStartSessionForm() {
  const form = document.querySelector("[data-session-start-form]");
  if (!form) {
    return;
  }

  const timerModeSelect = form.querySelector("[data-timer-mode-select]");
  const pomodoroFields = form.querySelectorAll("[data-pomodoro-field]");
  const targetCyclesInput = form.querySelector("[data-target-cycles-input]");
  const resourceSelect = form.querySelector("[data-session-resource-select]");
  const outlineSelect = form.querySelector("[data-session-outline-select]");
  const modeButtons = form.closest(".session-setup")?.querySelectorAll("[data-session-mode-option]") || [];

  const syncPomodoroFields = () => {
    const showPomodoroFields = timerModeSelect && timerModeSelect.value === "pomodoro";
    pomodoroFields.forEach((field) => {
      field.hidden = !showPomodoroFields;
    });
    if (targetCyclesInput instanceof HTMLInputElement) {
      targetCyclesInput.required = showPomodoroFields;
    }
    modeButtons.forEach((button) => {
      button.classList.toggle("session-mode-card--active", button.dataset.sessionModeOption === timerModeSelect.value);
    });
  };

  const syncOutlineOptions = () => {
    if (!(resourceSelect instanceof HTMLSelectElement) || !(outlineSelect instanceof HTMLSelectElement)) {
      return;
    }

    const selectedResourceId = resourceSelect.value;
    const options = Array.from(outlineSelect.options);
    options.forEach((option, index) => {
      if (index === 0) {
        option.hidden = false;
        option.disabled = false;
        return;
      }

      const optionResourceId = option.dataset.resourceId || "";
      const matches = !selectedResourceId || optionResourceId === selectedResourceId;
      option.hidden = !matches;
      option.disabled = !matches;
    });

    const selectedOption = outlineSelect.selectedOptions[0];
    if (selectedOption && selectedOption.disabled) {
      outlineSelect.value = "";
    }
  };

  syncPomodoroFields();
  syncOutlineOptions();

  if (timerModeSelect) {
    timerModeSelect.addEventListener("change", syncPomodoroFields);
  }
  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (timerModeSelect instanceof HTMLSelectElement) {
        timerModeSelect.value = button.dataset.sessionModeOption || timerModeSelect.value;
        timerModeSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });
  if (resourceSelect) {
    resourceSelect.addEventListener("change", syncOutlineOptions);
  }
}

initActiveSessionTimer();
initStartSessionForm();
