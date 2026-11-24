# Phase 10 acceptance fixes

Scope: repair the two failures observed against `3d88709`, preserving existing
data, pending acceptance documents and native privilege boundaries.

- [x] Trace native picker callback, receiver and IPC completion using fixed
  temporary debug milestones; reproduce Cancel before selecting a fix.
- [x] Preserve cancellation as a non-writing result and verify repeat selection
  recovers. Add regression coverage for the proven fault where practical.
- [x] Restore minimized windows before focus for existing gateway/bootstrap;
  reproduce the minimized second-launch case, then verify the same live window
  is restored without another core.
- [x] Run Node/native checks and build; repeat real picker Cancel and second
  launch. Record acceptance honestly and remove temporary instrumentation.
