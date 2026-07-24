# Category Unit Mode Help Text Implementation Plan

> **For the implementation agent:** Follow this plan task-by-task and keep the behavior scoped to the two category unit controls.

**Goal:** Show a detailed explanation for the currently selected mode beneath each artillery and war-machine rule control, with both groups updating independently.

**Architecture:** Keep the existing data-driven `CATEGORY_UNIT_CONTROLS` loop. Map the selected normalized mode to one shared localization key and render that localized description under each group. The selected mode remains local to the existing draft setting, so changing one group cannot affect the other.

**Testing:** Extend the component test to verify the default full-mode explanation, immediate explanation changes after clicking health/half/full, and independent explanations for artillery and war machines. Run the focused test first to capture the failing state, then the full frontend test suite and production build.

## Task 1: Add failing interaction coverage

- Update `frontend/src/components/__tests__/GameDataModificationModal.test.js` with assertions for the per-group help elements and their mode-specific text.
- Verify a click changes only the clicked group’s help text and that the other group keeps its selected-mode explanation.
- Run the focused test and confirm it fails because the new help elements/text do not exist yet.

## Task 2: Implement selected-mode explanations

- Add a small helper in `GameDataModificationModal.vue` that normalizes the selected value and returns the mode-help localization key.
- Render the selected mode explanation below each category control, with a stable test id.
- Add localized health, half-scale, and full-scale descriptions to every supported language catalog.

## Task 3: Verify and deliver

- Run the full frontend test suite and Vite production build with the bundled Node/pnpm runtime.
- Run `git diff --check` and inspect the final diff.
- Commit the implementation and tests with a focused message.
