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
| Uploads | Through Pauta: the browser posts the file and Pauta passes it on. Up to 4 MiB it goes whole, in one `PUT …:/content`; above that, through a Graph upload session in 5 MiB chunks. The page sends three files at a time (a request's first one alone: it makes the folder). With files this small the extra hop is cheap, the CSP stays `'self'`, and no browser-to-Microsoft CORS setup is needed. Limit `PAUTA_UPLOAD_MAX_MB` (200). See "What an upload costs" below |
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

## What an upload costs (measured 2026-11-15)

The week of 9 November had 38 uploads on production, median 3.8 s each and none under 300 ms,
and they come in batches: 17 files dropped at once took over a minute, one progress bar at a
time. Fitting time against size gave **3.2 s of fixed cost per file** and 0.45 s per MB: an
80 KB file took 3.5 s. So the bytes were never the problem.

The network was ruled out first (du7 reaches Graph in about 0.13 s, connection included; IPv6
is broken on du7 but IPv4 is tried first everywhere). What is slow is Graph itself on a
personal OneDrive: every call takes 0.7 to 1.5 s whatever it carries. Timed from du7 against
acceptance's own OneDrive:

| Step | Time |
|---|---|
| `createUploadSession` | 1.5 s (3.4 s when the folders are new) |
| `PUT` of the bytes to the session | 1.1 to 1.4 s |
| `PUT …:/content`, the file whole | 1.6 to 2.3 s |
| Thumbnail (its address, then its bytes) | 1.4 s |
| A download link | 0.7 to 1.4 s |

Hence the three changes of that day: one request instead of two for a small file, three files
at a time, and the thumbnail fetched as the upload ends instead of when the page asks. Seven
2 MB files, same machine, same OneDrive: **22.6 s before, 6.1 s after**; per file 3.3 s to
1.9 s. Three files sent at once into a folder that did not exist landed in one folder the one
time it was tried; the page still sends a new request's first file alone, because the client's
link opens a single folder and one clean trial is not a guarantee.

Not done, and where the next second is: answering the browser as soon as du7 has the bytes and
sending them to OneDrive afterwards would make an upload feel instant, at the price of a file
that can fail after the page said it was sent. And every download click costs one Graph call
for a link that stays good for about an hour: keeping it for a few minutes would make repeat
downloads free.
