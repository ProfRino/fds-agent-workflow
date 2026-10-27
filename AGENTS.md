# Shared agent instructions

This Windows workspace supports Codex, OpenCode and Claude Code using ordinary
terminal commands. Read README.md before setup. No provider API keys or agent
plugins are required by this workflow; users configure their assistant separately.

- Use the current official FDS release, not FDS4, for new work. Check the installed
  version with scripts/check_setup.bat and compare it to NIST's download page.
  Record the exact solver version with results. Never upgrade during a run.
- Use ProfRino/fds-viewer in visualization/ for geometry and output inspection.
- Store each input and all outputs together in simulations/CASE/. Use unique
  CHIDs and folder names with letters, digits, underscores or hyphens.
- Validate every changed input with Python and scripts/validate_fds.py. Its checks
  are heuristic, not proof of solver compatibility or physical correctness.
- Preview meshes, obstructions, openings, vents and devices before running. Only
  pass --preview-confirmed after visual inspection. If visual access is unavailable,
  ask the user to inspect; do not claim the preview was completed.
- Use generated scripts/run_fds.bat CASE --preview-confirmed. Default MPI ranks is
  one; use --mpi N only when appropriate to available resources and mesh count.
- Do not delete old outputs or restart files. Make a separate case for reruns.
  The starter launcher intentionally does not implement resume or overwrite.
- Read the solver completion log; static validation and process exit alone are
  insufficient. Use scripts/sim_status.bat CASE for recent log lines.
- Inspect output in the viewer or scripts/open_smv.bat CASE. Keep input, version,
  assumptions and evidence together. Independent engineering review is required
  before design or regulatory use.
- Keep private cases, local config, credentials and licensed documents out of Git.
  Publish only the explicit distribution allowlist, never an entire working folder.
- Do not automatically push, publish, or install global assistant settings.
