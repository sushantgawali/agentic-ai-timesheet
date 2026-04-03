Analyze all staged and unstaged changes, write a meaningful commit message,
ask the user to confirm, then commit and push.

## Instructions

### Step 1 — Gather git context

Run all of these via Bash:

```bash
git status
```

```bash
git diff HEAD
```

```bash
git log --oneline -5
```

```bash
git branch --show-current
```

### Step 2 — Analyze the changes

Read the output from Step 1 carefully. Identify:

- **What changed**: which files were added, modified, or deleted
- **Why it changed**: infer intent from the diff content (new feature, bug fix,
  refactor, docs, config, data, etc.)
- **Scope**: is this one logical change or multiple? If multiple, note it.

### Step 3 — Compose a commit message

Write a commit message following this format:

```
<type>(<scope>): <short summary under 72 chars>

<body — only if needed: explain WHY, not WHAT. Bullet points are fine.
Wrap at 72 chars. Leave blank if the subject line is self-explanatory.>
```

**Type values:** `feat`, `fix`, `docs`, `refactor`, `chore`, `data`, `test`

**Rules:**
- Subject line must be under 72 characters
- Use imperative mood ("add", "fix", "update" — not "added", "fixes")
- Do NOT add "Co-Authored-By" lines
- Body is optional — only include it if the subject line alone is not enough

### Step 4 — Stage all changes

Run:
```bash
git add -A
```

Then run `git status` again to show the user exactly what will be committed.

### Step 5 — Present the plan and ask for confirmation

Show the user:

1. A summary table of files being committed (from `git status`)
2. The proposed commit message (in a code block)
3. The target remote branch (current branch → origin)

Then ask:
> "Confirm commit and push? Reply **yes** to proceed, **edit** to change the
> commit message, or **no** to cancel."

Wait for the user's response before proceeding.

- If **yes** → go to Step 6
- If **edit** → ask the user to provide the new message, then re-confirm
- If **no** → run `git reset HEAD` to unstage and stop. Tell the user no changes were made.

### Step 6 — Commit and push

Run the commit:
```bash
git commit -m "<subject line>" -m "<body if any>"
```

Then push:
```bash
git push
```

If `git push` fails because the upstream is not set, run:
```bash
git push --set-upstream origin $(git branch --show-current)
```

### Step 7 — Confirm success

Print the final commit hash and message:
```bash
git log -1 --oneline
```

Tell the user: "Committed and pushed to origin/<branch>."
If push failed for any reason, report the error clearly and do not retry automatically.
