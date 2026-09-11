# Bulk Candidate Import Design Notes

**Date:** 2026-09-11
**Status:** Approved product direction; implementation deferred until Jobs modularization is merged

## Scope decisions

The future bulk candidate importer will:
- accept multiple PDF/DOCX files and ZIP archives;
- associate imported candidates to a selected job;
- detect duplicates using candidate data and document identity;
- support asynchronous ingestion, evaluation, and ranking workflows;
- expose real processing states and progress;
- include animated asynchronous UI states such as progress transitions, skeletons, processing indicators, and completion/error transitions;
- respect `prefers-reduced-motion` and accessibility requirements;
- avoid fake progress percentages when the backend cannot provide measurable progress.

The importer will **not**:
- store or display a CV/source-origin field such as Computrabajo, LinkedIn, referral, or manual;
- integrate Browser Use;
- depend on Computrabajo automation or scraping.

## UX direction

Async states should map to actual backend lifecycle states, for example:

`queued -> parsing -> ingesting -> evaluating -> ranking -> completed | failed`

Animations are a presentation of those real states, not a substitute for backend state. The UI should remain usable when motion is disabled.

## Delivery order

Implement this feature in a separate branch/PR after the Jobs application-boundary refactor is merged and verified. Do not mix importer product work into architecture-only PRs.
