Run the full audit pipeline locally using Claude Code subscription auth (no API key needed) and push the generated report to GitHub Pages.

## Usage

```
/run-audit [data_version]
```

- `data_version` — optional, defaults to `v5`. Options: `v5`, `v3`, `v2`, `v1`

## Steps

1. Unset `ANTHROPIC_API_KEY` so the pipeline uses Claude Code subscription auth
2. Verify `claude` CLI is authenticated
3. Run `run_local.sh` with the specified data version
4. Report the GitHub Pages URL when done

## Instructions

Run the following bash command, substituting `$ARGUMENTS` for the data version (default `v5`):

```bash
bash run_local.sh ${ARGUMENTS:-v5}
```

Stream the output to the user as it runs. When complete, show the GitHub Pages URL:
https://sushantgawali.github.io/agentic-ai-timesheet/
