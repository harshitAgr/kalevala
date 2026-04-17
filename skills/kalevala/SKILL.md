---
name: kalevala
description: Use when the user types /kalevala to add a journal note, todo, look up a past day's journal entry, search for past work, or find a session to resume. Dispatches to the `kalevala` CLI installed on the user's system.
---

# Kalevala — daily journal helper

When the user invokes `/kalevala <subcommand> [args]`, run the corresponding `kalevala` CLI command via Bash and paste the output back into the conversation. Do not edit any files directly — the CLI handles all writes.

## Subcommands

| User invocation | Shell command |
|---|---|
| `/kalevala note <text>` | `kalevala note "<text>"` |
| `/kalevala todo <text>` | `kalevala todo "<text>"` |
| `/kalevala show` | `kalevala show` |
| `/kalevala show YYYY-MM-DD` | `kalevala show YYYY-MM-DD` |
| `/kalevala last` | `kalevala last` |
| `/kalevala search <query>` | `kalevala search "<query>"` |
| `/kalevala resume <query>` | `kalevala resume "<query>"` |
| `/kalevala drain` | `kalevala drain` |
| `/kalevala status` | `kalevala status` |

## Usage notes

- Always quote the `<text>` / `<query>` argument to preserve whitespace.
- If the CLI exits nonzero, surface stderr to the user — do not silently swallow errors.
- `note` and `todo` auto-commit to the journal repo; mention that to the user on success.
- Do NOT invent new subcommands. If the user types something not in the table above, respond: "Unknown kalevala subcommand; try one of: note, todo, show, last, search, resume, drain, status."
