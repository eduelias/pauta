# Running on du7

Pauta runs on du7 (192.168.2.68) as the systemd unit `pauta`, on `127.0.0.1:8088` only.
Caddy puts it on the internet at https://pauta.genic.dev, next to dom.du7.dev.

```
phone ──https──▶ home router :443 ──▶ du7 192.168.2.68:443 (Caddy, TLS) ──▶ 127.0.0.1:8088 (pauta)
```

| What | Where |
|---|---|
| DNS | Squarespace, `genic.dev` → DNS → custom record `pauta` A `145.53.203.87` (the static home IP, same as `dom.du7.dev`) |
| Router | the existing TCP 443 → 192.168.2.68:443 forward (shared with dom.du7.dev; nothing new) |
| Caddy | `/etc/caddy/Caddyfile`, the `pauta.genic.dev` block from `deploy/Caddyfile.pauta`. Certificate via TLS-ALPN on 443 |
| Code | `~/reps/pauta` on du7 (an rsync copy, not a git checkout), venv in `.venv` |
| DB of record | `~/.local/share/pauta/pauta.db` (`PAUTA_STATE_DIR`): accounts, passkeys, invites, clients, requests |
| Backups | `pauta-backup.timer` nightly 03:40 → `~/backups/pauta` + `/media/nas/backups/pauta`, 30 days |
| Units | `/etc/systemd/system/pauta.service`, `pauta-backup.{service,timer}` (copies of `deploy/`) |

## Deploy from the Mac

```
rsync -a --delete --exclude .git --exclude .venv --exclude state --exclude '__pycache__' \
  --exclude .pytest_cache --exclude .ruff_cache --exclude .claude ./ esaleh@192.168.2.68:reps/pauta/
ssh esaleh@192.168.2.68 'cd ~/reps/pauta && .venv/bin/pip install -q -e . && sudo -n systemctl restart pauta'
curl -s https://pauta.genic.dev/api/me    # {"auth": true, "logged_in": false, ...}
```

First time only: `python3 -m venv .venv`, copy the three units to `/etc/systemd/system/`,
`systemctl enable --now pauta pauta-backup.timer`, append `Caddyfile.pauta` to the Caddyfile
and `systemctl reload caddy`.

## People

- The first admin: on du7, `cd ~/reps/pauta && PAUTA_STATE_DIR=~/.local/share/pauta
  .venv/bin/pauta invite --admin` prints a link (7 days, one person). The first account is
  always an admin.
- After that, admins invite from the app: Equipe → Convidar alguém (QR code, link, WhatsApp).
- `pauta users` lists accounts. Admins disable people or make them admin on the Equipe page.
- A lost phone: sign in on another device that has a passkey (iCloud/Google sync them), or
  ask an admin for a fresh invite and disable the old account.

## Rollback

`sudo systemctl stop pauta` takes it offline; remove the Caddy block and the `pauta` DNS
record to undo it completely. The DB stays in `~/.local/share/pauta`.
