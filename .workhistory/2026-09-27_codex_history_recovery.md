# RunPod Codex history recovery — 2026-09-27

Current process used /root/.codex (one current conversation); persistent /workspace/.codex contained 19 historical threads: 3 CLI conversations and 16 guardian review threads. The main working conversation is 01a0349b-b2b5-7c11-9265-4f98135f1324, updated 2026-09-26.

Backups: /workspace/.codex/recovery-backups/20260927T142253Z. SQLite online backups preserve state/history and related databases; current session rollout copied as a point-in-time snapshot. Existing authentication and security settings were not changed.

Changes: added CODEX_HOME=/workspace/.codex to /root/.bashrc and /root/.profile; created executable /workspace/codex-resume.sh; repaired the stale rollout_path for 01a03476-5a74-7973-be41-7dc6372d7ad1 from /root to its existing /workspace file. No conversation was deleted or merged.

Validation: Codex doctor through persistent launcher reports 20 OK, 1 idle, 0 warnings/failures; database health and rollout inventory match; provider HTTP/WebSocket connectivity works. Authentication is configured; no model inference was requested. Interactive resume picker verified through a PTY: all three user conversations displayed. No conversation was submitted for execution. The default daemon failed because the persistent-volume socket parent permissions did not satisfy its ownership/security checks. The launcher therefore uses the supported --no-daemon mode, which successfully displayed the picker.

Resume list: /workspace/codex-resume.sh
Resume main work: /workspace/codex-resume.sh resume 01a0349b-b2b5-7c11-9265-4f98135f1324

The current already-running app server retains /root/.codex. New shell configuration does not retroactively change it; use the explicit launcher in a separate terminal. Root shell changes and installed /root binary are container-local and may require recreation/reinstallation after another pod replacement. Persistent launcher and historical data live on /workspace.

Outstanding environment issue: sandbox exec fails with bwrap namespace permissions. Approved outside-sandbox commands were used; no blanket bypass or host kernel/security change was made. Doctor's policy check does not test actual namespace execution.
