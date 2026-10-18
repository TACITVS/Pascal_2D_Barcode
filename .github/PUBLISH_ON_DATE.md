# Publish this repository on a date

`.github/workflows/publish-on-date.yml` runs once a day. When the date in
`.github/publish-on` has arrived (UTC), it changes this repository from
private to public. Nothing happens before that date.

* **Postpone**: change the date in `.github/publish-on`.
* **Cancel**: delete `.github/publish-on` (or disable the workflow under
  Actions → publish-on-date → ⋯ → Disable workflow).
* **Test**: Actions → publish-on-date → Run workflow (leave "dry run" ticked).
  It checks the date and the token and changes nothing.

## One-time setup: the token

The workflow's built-in `GITHUB_TOKEN` cannot change repository visibility, so
it needs a personal access token stored as a repository secret.

1. GitHub → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token.
   * Repository access: Only select repositories → this repository (add more
     later for other repositories using the same switch).
   * Permissions → Repository permissions → **Administration: Read and
     write** (Metadata: Read-only is added automatically).
   * Expiration: a date **after** the publication date. If the token expires
     first, the run fails and GitHub emails you; generate a new token and
     update the secret.
2. This repository → Settings → Secrets and variables → Actions → New
   repository secret: name `PUBLISH_TOKEN`, value the token.
3. Run the workflow once by hand with "dry run" ticked. The log should end
   with "Dry run: the token works; nothing changed."

## Before the date

Going public exposes the whole git history, issues, pull requests and the
Actions logs. Check that no commit contains secrets or private data, and add a
`LICENSE` file if you want others to be allowed to use the code (without one,
public code is visible but not licensed for reuse).

## Reusing it in another repository

Copy `.github/workflows/publish-on-date.yml` and `.github/publish-on` (with the
new date) into that repository, add it to the token's repository list, and add
the `PUBLISH_TOKEN` secret there.

Scheduled workflows in private repositories keep running indefinitely; GitHub
only pauses them after 60 days of inactivity in *public* repositories, which
no longer matters once the switch has done its job. Each daily run uses a few
seconds of Actions minutes.
