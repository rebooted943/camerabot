# GitHub Pages — setup & troubleshooting

## First-time setup

1. **Merge** the dashboard PR so `pages.yml` is on `main`.
2. Repo → **Settings → Pages → Build and deployment** → **Source: GitHub Actions**.
3. Wait for (or manually run) workflow **Publish dashboard (Pages)** under **Actions**.

Your site URL will be:

`https://rebooted943.github.io/camerabot/`

(Public repos get Pages for free.)

---

## Error: `Branch "main" is not allowed to deploy to github-pages`

This means the **github-pages environment** only allows deployments from specific
branches, and `main` is not in the list (often left pointing at an old feature
branch after the first Pages enable).

### Fix (2 minutes)

1. Repo → **Settings** → **Environments** → click **github-pages**.
2. Under **Deployment branches**:
   - Either choose **All branches**, **or**
   - **Selected branches** → add **`main`** (and remove obsolete branches like
     `cursor/...` if they are listed).
3. If **Required reviewers** is enabled, either approve the pending deployment
   under **Actions** (yellow “Review deployments”) or turn reviewers off for
   solo use.
4. **Actions** → **Publish dashboard (Pages)** → **Re-run all jobs** (or **Run workflow**).

The next green run should show **Deploy to GitHub Pages** succeeded and Settings
→ Pages will display the live URL.

---

## How to verify it is up

| Check | Where |
| ----- | ----- |
| Workflow succeeded | Actions → “Publish dashboard (Pages)” → green |
| Site URL | Settings → Pages → “Your site is live at …” |
| Page loads | Open the URL; yellow banner: “Read-only online view” |
| Data present | Items/targets visible (needs at least one scan with `seen_ads.db` committed) |

If the UI loads but shows no items, trigger **ArbitrageSniper** once, wait for
the DB commit, then re-run **Publish dashboard (Pages)**.

---

## What Pages can and cannot do

| Feature | Pages (online) | Local dashboard |
| ------- | -------------- | ----------------- |
| View targets & scanned items | Yes | Yes |
| Filters / search | Yes | Yes |
| Add/remove targets | No (read-only) | Yes |
| Scan now | No | Yes (needs Playwright) |
| Change scraping sources | No | Yes |

To run a scan from GitHub: **Actions → ArbitrageSniper → Run workflow**
(optional `query` / `providers` inputs).
