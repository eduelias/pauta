# 3. Files on requests, stored in OneDrive

- **Status:** proposed (2026-10-29), built in the PR that adds this file
- **Asked by:** Piero, who runs the campaigns

## Context

Creatives reach Pauta as links: the client's Drive folder (`drive_url`) and the request's
`creatives_url`, pointing at Google Drive and other drives. Piero wanted to upload files on
the request itself, keep them in the request's history, and use the 1 TB of OneDrive storage
he already pays for (Microsoft 365 Personal) instead of du7's disk or someone else's drive.
His answers to the open questions: a personal plan; mostly images of about 2.5 MB and a few
short videos; files belong to a request; clients may see them too.

## Decision

| Topic | Decision |
|---|---|
| Where the bytes live | That OneDrive, under `Apps/Pauta/<cliente>/Pedido <n>/`. du7 keeps only each file's OneDrive id, name, size, type, uploader and date (`file` table) |
| Permission | `Files.ReadWrite.AppFolder`: Pauta sees only its own app folder, never the rest of the drive. `PAUTA_ONEDRIVE_ROOT` can point it elsewhere, which asks for the whole drive instead |
| App registration | "Pauta" in du7@msn.com's own Entra directory, personal Microsoft accounts only. Not a work directory (it would belong to the employer) and not Piero's account (he only approves access) |
| Sign-in | Device code flow: an admin clicks Conectar on the Equipe page, the OneDrive's owner types the code at microsoft.com/link. No client secret to store or rotate, no redirect URL |
| Token | A file next to the DB (`pauta.db.onedrive-token`, mode 600), like the session key: never in the DB, so never in its backups. Refreshed on use; Microsoft rotates it |
| Uploads | Through Pauta: the browser posts the file, Pauta streams it to a Graph upload session in 5 MiB chunks. With files this small the extra hop is cheap, the CSP stays `'self'`, and no browser-to-Microsoft CORS setup is needed. Limit `PAUTA_UPLOAD_MAX_MB` (200) |
| Downloads | `/api/files/<id>` redirects to Graph's short-lived pre-signed link, so teammates never need access to the OneDrive. Thumbnails come through Pauta, fetched without the token |
| Clients | "Link para o cliente": a view-only link to the request's folder that anyone with it can open, sent by WhatsApp. Made on demand, revoked in OneDrive |
| Removing | Uploader or admin. The file goes to OneDrive's recycle bin (30 days). Deleting a request or client in Pauta leaves its files in OneDrive |
| No new dependency | Graph calls use stdlib `urllib` |

## Consequences

- The files depend on one person's account. If Piero stops paying, closes the account or
  leaves the team, the files go with it; Pauta's backups don't cover them. Moving to another
  OneDrive means copying the `Apps/Pauta` folder and reconnecting (the ids in the DB would
  then point at the old drive: a migration script, if it ever comes to that).
- The owner of the OneDrive can see and delete everything Pauta stores there.
- Uploads cross du7's home connection twice (in, then out). Fine for images and short
  videos; long videos would want browser-to-OneDrive uploads instead.
- A token unused for 90 days expires and someone has to reconnect; any upload or download
  renews it. `/metrics` reports the state for the watchdog.
- Microsoft shows "unverified publisher" when connecting; harmless for a team app.
- With one database per team (proposed, not decided), each team would connect its own
  OneDrive: the client id is shared, the token file sits next to each team's DB.
