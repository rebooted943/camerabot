# GitHub Pages — setup & troubleshooting

> For the **read-only** online viewer. For the fully interactive online
> dashboard, see [`DEPLOY.md`](DEPLOY.md).

## First-time setup

1. **Merge** the dashboard changes so `pages.yml` is on `main`.
2. Repo → **Settings → Pages → Build and deployment** → **Source: GitHub Actions**.
3. Wait for (or manually run) workflow **Publish dashboard (Pages)** under **Actions**.

Your site URL will be:

`https://<user>.github.io/<repo>/`

(Public repos get Pages for free.)

---

## Error: `Branch "main" is not allowed to deploy to github-pages`

The **github-pages environment** only allows deployments from specific branches,
and `main` is not in the list (often left pointing at an old feature branch after
the first Pages enable).

### Fix

1. Repo → **Settings** → **Environments** → click **github-pages**.
2. Under **Deployment branches**: choose **All branches**, or **Selected
   branches** → add **`main`** (and remove obsolete `cursor/...` branches).
3. If **Required reviewers** is enabled, approve the pending deployment under
   **Actions** (yellow “Review deployments”) or disable reviewers for solo use.
4. **Actions** → **Publish dashboard (Pages)** → **Re-run all jobs**.

---

## Verify it is up

| Check | Where |
| ----- | ----- |
| Workflow succeeded | Actions → “Publish dashboard (Pages)” → green |
| Site URL | Settings → Pages → “Your site is live at …” |
| Page loads | Open the URL; yellow banner: “Read-only online view” |
| Data present | Items/targets visible (needs a scan with `seen_ads.db` committed) |

---

## Pages vs the hosted dashboard

| Feature | Pages (online) | Hosted app ([DEPLOY.md](DEPLOY.md)) | Local |
| ------- | -------------- | ----------------------------------- | ----- |
| View items + filters | Yes | Yes | Yes |
| Add/remove targets | No | Yes | Yes |
| Scan now / filters | No | Yes | Yes |
| Change sources | No | Yes | Yes |

Pages is a free read-only viewer; deploy the hosted app for full online control.
