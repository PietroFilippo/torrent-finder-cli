# Stable credentials and deferred Windows package updates

Status: Accepted

## Context

A Windows laptop appeared to lose all credentials, and Madokami searches returned
empty results without a login warning. The previous credential store used
LOCALAPPDATA, which can vary between Store Python installations. Saving after a
read or JSON error silently replaced the entire store with the edited fields.
These are plausible causes; the laptop's original files were not inspected.

In-app pipx upgrades also attempted to replace the currently running Windows
launcher. The resulting WinError 32 was treated as success if package metadata
had changed, even though pipx had exited with an error.

## Decision

Use the existing machine-stable user directory for credentials. When the target
does not exist, read legacy locations and merge by integration, keeping each
username/password pair from one source. The newest source containing fields for
that integration wins. Keep originals and honor existing stable files, even
empty ones. Abort migration/save on unreadable data, retry failed reads, and
replace files atomically. Do not print secret values in diagnostics.

Surface missing/rejected logins as actionable SearchError messages. Refresh
cached sessions after credential changes.

Queue Windows pip/pipx upgrades in a hidden helper that waits for the app process
to exit. Preserve output in update.log and record the actual exit code in a
status file consumed on next launch. Expired pending jobs report incomplete;
nonzero exits never become success because package metadata advanced.

Show progress in a separate read-only console viewer on Windows. The hidden
worker remains independent so closing the viewer cannot interrupt installation.
Identify status records by job ID, preserve phase and version metadata, and allow
the viewer to read a completion report already archived by startup. Use an
indeterminate activity bar because the installer has no reliable overall percent.
The terminal preview and exported visual replay share the production renderer
and never invoke an installer.

After a successful interactive Windows update, the worker waits three seconds
and reopens the package with a fresh interpreter in a new console. The viewer
only observes that countdown and closes when the worker reports launch; closing
it early cannot cancel reopening. Installation failure never starts the app.
If launch fails, preserve the successful installation status and offer manual
reopening. Previews simulate this countdown without launching the application.

## Consequences

Python installation changes no longer change the credential location. Existing
legacy credentials can be recovered without destroying evidence. Truly deleted
files or missing environment variables cannot be recovered by this migration.
The store remains plaintext; environment overrides retain precedence.

Windows users must close other app instances and wait before reopening during
an update. The helper avoids the active launcher's file lock but still reports
network, permission, or locks held by other processes as failures. Updating an
old version for the first time may require running pipx manually after closing
the app.
