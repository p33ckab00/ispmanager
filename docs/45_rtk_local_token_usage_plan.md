# RTK Local Token Usage Plan

This document records the RTK setup for this repository.

Status: installed project-locally on April 30, 2026 after explicit approval.

## Goal

Use RTK as a local developer-assistant helper for `/opt/ispmanager` so verbose command output consumes fewer LLM tokens during coding sessions.

RTK should be used for noisy inspection and verification commands, especially:

- `git status`
- `git diff`
- `pytest`
- `ruff check`
- long logs or diagnostic output

RTK should not become part of the Django app, deployment scripts, production services, system PATH, or global shell behavior.

## Scope Decision

The approved direction is project-local only:

- Install under `/opt/ispmanager`.
- Use a dedicated local folder.
- Do not use `rtk init -g`.
- Do not install global hooks.
- Do not modify shell startup files.
- Do not require RTK for the app to run.
- Keep RTK artifacts out of Git commits unless explicitly approved later.

Recommended local layout:

```text
/opt/ispmanager/
  .tools/
    rtk/
      rtk
      checksums.txt
      rtk-local
  .rtk/
    config/
    data/
    cache/
  AGENTS.md
  RTK.md
```

`rtk-local` is a tiny wrapper that sets `RTK_TELEMETRY_DISABLED=1` before running the binary. It also points `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_CACHE_HOME` into `/opt/ispmanager/.rtk/`, keeping RTK config, tracking data, and cache local to this project instead of the user home directory.

## Install Method

Installed method:

1. Created `/opt/ispmanager/.tools/rtk/`.
2. Downloaded pinned RTK release `v0.38.0` for the current platform.
3. Downloaded the release checksum file.
4. Verified the archive with `sha256sum`.
5. Extracted only the RTK binary into `.tools/rtk/`.
6. Verified with:

   ```bash
   ./.tools/rtk/rtk --version
   ./.tools/rtk/rtk gain
   ```

7. Added local exclude rules to `.git/info/exclude`:

   ```gitignore
   .tools/
   AGENTS.md
   RTK.md
   .rtk/
   ```

8. Added local Codex guidance in `AGENTS.md` and `RTK.md` so Codex uses RTK only inside this project.

Avoid `curl | sh` for this repository. Prefer pinned release download plus checksum verification.

## Operating Rules

Use RTK when output is expected to be large or repetitive:

```bash
./.tools/rtk/rtk-local git status
./.tools/rtk/rtk-local git diff
./.tools/rtk/rtk-local pytest
./.tools/rtk/rtk-local ruff check .
```

Use raw commands when exact output matters:

- security review
- release and deploy checks
- migrations
- exact stack traces
- exact logs for incident review
- any command where filtered output looks suspicious or incomplete

If RTK output is unclear, rerun the raw command.

RTK may occasionally print a warning that no global hook is installed and suggest `rtk init -g`. That warning is expected here. The project-local setup intentionally avoids global hooks.

## Telemetry Policy

Set `RTK_TELEMETRY_DISABLED=1` for project-local RTK usage.

Reason:

- RTK documentation says telemetry is opt-in and disabled by default.
- The environment variable is still useful as a hard safety switch.
- It prevents telemetry from sending even if a future local config accidentally enables it.
- Telemetry is not needed for the token-saving goal.
- Disabling telemetry does not affect command filtering or token reduction.

Preferred wrapper behavior:

```bash
#!/usr/bin/env bash
export RTK_TELEMETRY_DISABLED=1
exec "$(dirname "$0")/rtk" "$@"
```

## Uninstall

Because this setup is project-local, uninstall is just local cleanup:

```bash
rm -rf /opt/ispmanager/.tools/rtk
rm -f /opt/ispmanager/AGENTS.md /opt/ispmanager/RTK.md
rm -rf /opt/ispmanager/.rtk
```

Then remove the RTK-related lines from:

```bash
/opt/ispmanager/.git/info/exclude
```

No global hooks or system packages should need removal if the local-scope plan is followed.

## Go Signal

RTK was installed after the user explicitly approved installation. Future upgrades should use the same local-only pattern: pinned release, checksum verification, local wrapper, no global hooks.
