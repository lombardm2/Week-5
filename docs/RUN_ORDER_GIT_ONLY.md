# Run order: git only (no `gh`, no Homebrew)

Everything below is plain `git` in Terminal, plus three one-click steps on github.com that
git cannot do: create the empty repo, click "Create pull request", and set branch protection.

Total time: about 45 minutes, most of it waiting for CI.

---

## 1. Unzip and check git (off camera)

```bash
cd ~/Downloads
unzip lumen-deposits-controls.zip
cd lumen-deposits-controls
git --version              # if macOS offers to install developer tools, click Install, then re-run
ls -a                      # you must see a .git folder
git branch                 # you must see github-demo-start
```

Optional local check (needs Python 3.11+; skip it if Python isn't available, since CI runs the same steps):
```bash
python3 -m pip install -r requirements.txt && bash scripts/run_gate_local.sh ""
```

## 2. Create the empty repo (github.com, off camera)

1. Go to **github.com/new**.
2. Name it `lumen-deposits-controls` and select **Public**. Branch protection is free on public
   repos; the data is synthetic.
3. Leave **README, .gitignore and license unticked**. The repo must be empty.
4. Click **Create repository** and note your username, shown in the page URL.

## 3. Get a push token (github.com, off camera)

GitHub doesn't accept your account password for `git push`.

1. Go to GitHub → profile picture → **Settings** → **Developer settings** →
   **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Name it `lumen-demo`, set expiry to 7 days, and tick **repo** and **workflow**.
   The **workflow** box is required, or GitHub refuses to accept the `.github/workflows` files.
3. Copy the token. You won't see it again.

## 4. Push the starting state (Terminal, off camera)

Replace `YOUR-USERNAME` with your username, not your email:

```bash
git config user.name  "Your Name"
git config user.email "lombardm2@csp.edu"

git remote remove origin 2>/dev/null
git remote add origin https://github.com/YOUR-USERNAME/lumen-deposits-controls.git
git push origin github-demo-start:main
```
When prompted: **Username** = your GitHub username, **Password** = paste the token.
macOS Keychain remembers it after that.

Then point your local `main` at what GitHub now has:
```bash
git checkout github-demo-start
git branch -f main github-demo-start
git checkout main
git fetch origin
git branch --set-upstream-to=origin/main main
```

On github.com, open the repo's **Actions** tab. A **promote-to-staging** run starts from this push.
Wait for it to go green (~5 min). It creates your first `staging-…` release tag, which is the
rollback target later.

If its "Tag release" step fails with a permissions error, go to **Settings → Actions → General →
Workflow permissions**, select **Read and write**, save, and click **Re-run jobs**.

## 5. Recording: Scenes 1–2 (repo tour)

Start recording. Walk through the README control matrix, then `data/raw/_manifest.json`
(or `generator/generate_core_banking.py`), then `contracts/accounts.yml`, using
`docs/RECORDING_SCRIPT.md`.

## 6. Recording: run the demo script (Scenes 3–7)

```bash
bash scripts/demo_git_only.sh
```

It pauses at every step. Here's what you do at each pause:

| Script step | What you do in the browser | Scene |
|---|---|---|
| 1. Pushes the breaking branch, prints a link | Open the link → **Create pull request**. Show the diff. Wait for checks to go **red** (~4 min) | 4 |
| *(first run only)* | **Set branch protection now** (see the settings below). The check names only appear after they've run once, which is why this comes after the PR | 3 |
| 2. `git push` to main → **rejected (GH006)** | Nothing. The terminal *is* the proof. Then open each failing check and narrate | 4–5 |
| 3. Pushes the fix | Wait for checks to go **green** | 6 |
| 3b. `git push` to main → **accepted** | Show the PR page: it now says **Merged** | 6 |
| 4. Promotion | Actions → **promote-to-staging** → show the summary and the new tag | 6 |
| 5. Pushes `rollback/<previous tag>` | Actions → **rollback-staging** → show the run summary | 7 |

**Branch protection settings** (Settings → Branches → **Add classic branch protection rule**):

- **Branch name pattern:** `main`
- ☑ **Require status checks to pass before merging**
  - ☑ Require branches to be up to date before merging
  - Search for and add: `gate`, `layered-tests`, `contract-validation`
- ☑ **Do not allow bypassing the above settings** (otherwise you, as owner, could skip the gate)
- ☐ **Leave "Require a pull request before merging" UNticked.** That way the merge can be done by
  `git push`, and the required checks are still enforced on that push. If it's ticked, the push
  is refused for a different reason ("must be made through a pull request"), which muddies the
  demo.
- Click **Create**.

## 7. Recording: close (Scene 8)

Return to the README control matrix.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| `Authentication failed` on push | Use the token as the password, not your account password. Check it has **repo** and **workflow** ticked |
| `refusing to allow a Personal Access Token to create or update workflow` | Token is missing the **workflow** scope. Make a new one |
| Step 2 push was **accepted** instead of rejected | Branch protection isn't active, or the checks weren't added to it. Fix the rule, then `git push --force origin github-demo-start:main` and re-run the script |
| Step 3b push rejected although checks are green | "Require a pull request" is ticked. Untick it, or click **Merge pull request** on the PR page; the script waits |
| `main already contains the fix` | `git push --force origin github-demo-start:main`, then `git checkout main && git reset --hard origin/main` |
| `Local main can't fast-forward` | `git checkout main && git reset --hard origin/main` |
| Only one `staging-` tag at step 5 | The promotion from step 4 of this guide didn't finish. Check Actions, re-run it, then push the rollback tag by hand: `git tag -a rollback/<tag> origin/main -m "INC-0042 rollback drill" && git push origin rollback/<tag>` |

Command output from each step is saved in `docs/evidence/github/`.
