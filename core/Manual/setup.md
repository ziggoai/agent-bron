# Setup commands

Every setup change is made with one of these commands, from the vault folder. Add `--preview` first: it shows a plain summary and changes nothing (`--show-files` also shows the exact text). Run it again without `--preview` after the user's yes. Each command writes the files, refreshes the setup and checks it; if anything fails, everything is put back as it was.

| Command | What it does |
|---|---|
| `.bron/bin/bron agent create --name '<Name>' --role '<role>' [--model '<model>'] [--reports-to '<Name>'] [--connections '<connections>'] [--ask-before '<entry>'] [--instructions-file <path>]` | New team member, with safety defaults |
| `.bron/bin/bron agent set '<Name>' [--role …] [--model …] [--runs-in …] [--add-connection …] [--remove-connection …] [--add-ask …] [--remove-ask …] [--reports-to …] [--instructions-file …]` | Change a team member or Bron |
| `.bron/bin/bron agent rename '<Name>' '<NewName>'` | Rename, updating every reference |
| `.bron/bin/bron agent retire '<Name>' [--hand-to '<Name>']` | Hand over its work and archive it in `System/Archive/Agents/` |
| `.bron/bin/bron agent restore '<Name>'` | Bring a retired agent back |
| `.bron/bin/bron project new '<Name>' [--goal '<goal>']` | `Projects/<Name>/` with a README |
| `.bron/bin/bron routine create --name '<Name>' --file <path>` | A routine from a drafted runbook |
| `.bron/bin/bron skill new <skill-name> --description '<description>' --file <path> [--agent '<Name>']` | A reusable skill |
| `.bron/bin/bron connections add --name '<Name>' --command '<command>' [--args '<args>']` | A tool that runs on this Mac |
| `.bron/bin/bron connections add --name '<Name>' --url '<url>'` | A tool at a web address |
| `.bron/bin/bron settings set [--name '<user name>'] [--role '<user role>'] [--company '<company>'] [--default-cli <cli>] [--tone '<tone>'] [--preferences '<preferences>']` | Your settings |

Safety defaults: a new agent asks before deleting files, pushing to git, and sending, sharing or posting through any of its connectors. Read-only connectors add nothing. Add `--no-defaults` only when the user asks.
