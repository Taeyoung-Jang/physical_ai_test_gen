# Terrain server guard: approved scope, application still blocked

User approved proceeding with the limited worlds.py protection change. Inspected dirty
worktree and preserved all existing edits. Whole-file apply_patch application was again
rejected by automatic review as exceeding approval for a limited guard. Retried the
genuinely narrow Update File patch (two functions only); it failed with the existing bwrap
namespace error before modifying the target. No alternate write mechanism was used.

The guard is NOT applied. No new successful regression result is claimed. Existing terrain
bundles must still use the isolated terrain runner, not the shared navigation server.

Saved the minimal intended update in terrain_server_guard.pending.patch. It rejects
terrain registration before creating server assets/registry files, and rejects resolution
of pre-existing terrain registrations before the legacy navigation worker can execute.
It leaves validate_bundle/compose_model unchanged for isolated terrain execution.

Next action requires a functioning partial-patch environment or explicit authorization
for rewriting the complete worlds.py file while preserving all content except these two
guard additions. Service restart is not performed or included in this pending change.
