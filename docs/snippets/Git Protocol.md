# Git Protocol

## Add / Commit / Tag / Push to Remote Repo

- git add -A
- git commit -m "checkpoint: new chat ses entity in db"
- git push vcdb_v2 main

## SSH setup:

SSH is a great fit for your “set it once per machine, then forget about it” workflow on Ubuntu/Lubuntu. Here’s the quick, copy/paste setup that you repeat on each Linux box.

## 1) Make an SSH key on this machine

```bash
ssh-keygen -t ed25519 -C "github-$(whoami)@$(hostname)"
```

* When it asks where to save, just press **Enter** (defaults to `~/.ssh/id_ed25519`).
* Passphrase: **optional**. For maximum simplicity, you *can* leave it blank (just press Enter twice). GitHub covers passphrases here. ([GitHub Docs][1])

## 2) Start the SSH agent and load your key

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

This is exactly the flow GitHub documents for Linux. ([GitHub Docs][1])

> On some lightweight setups (like Lubuntu), you may need to run `ssh-add ~/.ssh/id_ed25519` again after a reboot/login. If Git ever prompts again, that’s usually all it takes.

## 3) Add the public key to GitHub

Print the public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the entire single line that starts with `ssh-ed25519`.

Then in **GitHub** (web):

* Settings → **SSH and GPG keys** → **New SSH key** → paste it → Save ([GitHub Docs][2])
  Tip: name it something like `zbook-17 Ubuntu 24.04` so later you know which machine it is.

## 4) Test the SSH login

```bash
ssh -T git@github.com
```

First time, you may be asked to confirm the host fingerprint—type `yes`. If it works, you’ll get a success message (GitHub has no shell access, so that’s normal). ([GitHub Docs][3])

## 5) Switch your repo remote from HTTPS to SSH

In your repo:

```bash
git remote -v
git remote set-url vcdb_v2 git@github.com:KengineeredKhaos/vcdb_v2.git
git remote -v
```

Now pushes should **not** ask for a PAT:

```bash
git push vcdb_v2 main
```

---

# Keeping it simple long-term (maintenance)

### Add SSH on each machine once

Do the same steps on each machine. You’ll end up with multiple keys listed in GitHub settings—one per machine. That’s normal and clean. ([GitHub Docs][2])

### If a machine dies or gets wiped

Just delete that key from GitHub “SSH and GPG keys” and you’re done (other machines keep working).

### If you’re on a network that blocks SSH port 22

GitHub supports SSH over port **443** as a fallback: ([GitHub Docs][4])
Test it:

```bash
ssh -T -p 443 git@ssh.github.com
```

If that works but normal doesn’t, you can make it permanent by adding this to `~/.ssh/config`:

```bash
Host github.com
  Hostname ssh.github.com
  Port 443
  User git
```

(Then `git push` just works.)

---

If you run this and anything feels “off,” paste the output of:

```bash
ssh -T git@github.com
git remote -v
```

…and I’ll tell you exactly what to fix.

[1]: https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent?utm_source=chatgpt.com "Generating a new SSH key and adding it to the ssh-agent"
[2]: https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account?utm_source=chatgpt.com "Adding a new SSH key to your GitHub account"
[3]: https://docs.github.com/en/authentication/connecting-to-github-with-ssh?utm_source=chatgpt.com "Connecting to GitHub with SSH"
[4]: https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port?utm_source=chatgpt.com "Using SSH over the HTTPS port"

## Add / Commit / Tag

- git add -A
- git commit -m "checkpoint: new chat ses entity in db"
- git tag -a v2-freeze-new_ses-entity_in_db

## If you want to "pseudo-rebase" a branch to the new main

- git log   # make sure you're on the right branch and commit is current
- git branch -f main HEAD   # make your branch the new main HEAD
- git switch main       # switch to the main so you're working on main
- git status        # check to see where you are...

Here’s a tight, copy-pasteable cheatsheet you can drop into your notes.
it covers creating a safe branch for UI work, staging/committing,
merging back, and moving HEAD (including “new head” via tags or resets).

```bash
# --- One-time safety net (optional but recommended) ---
git switch main                      # or: git checkout main
git pull --ff-only                   # ensure local main is up to date
git tag -a pre-webui -m "Baseline before web UI"   # easy fallback
# (or create a backup branch: git branch backup/pre-webui main)

# --- Start a feature branch for web UI ---
git switch -c web-ui                 # or: git checkout -b web-ui
git push -u origin web-ui            # publish & set upstream

# --- Stage & commit frequently ---
git status                           # see what changed
git add <file> ...                   # stage specific files
git add -p                           # stage hunks interactively
git commit -m "feat(ui): message"    # commit staged changes
git commit --amend --no-edit         # amend last commit (msg unchanged)

# --- Keep your branch fresh with main (choose one style) ---
git fetch origin
git rebase origin/main               # linear history (preferred by many)
# or:
git merge origin/main                # merge main into your branch

# --- Merge web-ui back into main when ready ---
git fetch origin
git switch main
git pull --ff-only                   # update main locally
git merge --no-ff web-ui -m "Merge web-ui"   # create explicit merge commit
# Resolve conflicts if any:
#   edit files -> git add <resolved files> -> git merge --continue
# Abort a bad merge attempt:
#   git merge --abort

# --- Push the new main (this updates remote HEAD to the new tip) ---
git push origin main

# --- Make a “new head” easy to reference (tag the release) ---
git tag -a vX.Y.Z -m "UI ready"
git push origin main --tags

# --- If you need to move HEAD locally (advanced/reset) ---
git reset --soft HEAD~1              # move HEAD back 1 commit, keep changes staged
git reset --mixed HEAD~1             # keep changes in working tree (default)
git reset --hard <commit>            # WARNING: discard local changes

# --- Cleanups ---
git branch -d web-ui                 # delete local branch (after merge)
git push origin :web-ui              # delete remote branch
git stash                            # stash WIP
git stash pop                        # restore stashed WIP
```

quick flow you can follow:

1. tag current `main` (`pre-webui`), 2) `git switch -c web-ui`, 3) commit as you go, rebasing or merging `origin/main` into `web-ui` to stay current, 4) switch to `main` and `git merge --no-ff web-ui`, 5) push `main`, 6) tag the release (`vX.Y.Z`).

Shotgun approach to .gitignore

# .gitignore

# --- Dev, MVP docs, IDE environment and Tests

/tests/*
/MVP_docs/*
pyproject.toml
pyrightconfig.json
*.sublime-*
.cache/
*.zip

# --- Virtual Environment ---

/bin/
/include/
/lib
/lib64
/pyvenv.cfg
env/
.pyenv/
pip-wheel-metadata/
pip-log.txt

# --- Python / build ---

__pycache__/
*.py[cod]
*.pyd
*.so
*.egg*
.eggs/
dist/
build/

# --- Databases (SQLite etc.) ---

*.sqlite
*.sqlite3
*.db
*.db-*
/var
instance/*
!instance/.gitkeep

# --- Logs (DEV-ONLY JSONL, keep dirs) ---

logs/**
!logs/.gitkeep
app/logs/*.log
!app/logs/.gitkeep

# --- Runtime/output dirs (not versioned) ---

archive/**
!archive/.gitkeep
exports/**

# --- Secrets & local config ---

.env
.env.*
!.env.example
