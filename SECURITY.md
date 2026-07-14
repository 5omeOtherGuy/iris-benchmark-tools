# Security policy

## Report a vulnerability

Use the repository's private GitHub security-advisory form. Do not put credentials, private benchmark logs, or exploit details in a public issue.

Include the affected revision, impact, reproduction steps, and the smallest safe example. Maintainers will acknowledge the report and coordinate a fix and disclosure.

## Credential exposure

If a token or credential file reaches a commit, revoke or rotate it immediately. Removing a file in a later commit does not remove it from Git history. Notify the maintainer before rewriting or republishing affected history.

## Sensitive benchmark data

Trial logs and transcripts can contain model prompts, tool arguments, command output, task assets, and credentials exposed by the environment. Keep all real `jobs/` directories and derived unsanitized reports private. This repository accepts synthetic fixtures only.

## Supported versions

Security fixes target the current default branch. Older revisions are not maintained separately.
