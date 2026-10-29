"""pauta serve | invite | users | backup | demo | onedrive"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from . import __version__, obs
from .auth import Auth
from .db import Store
from .onedrive import DriveError, OneDrive


def db_path() -> Path:
    state = os.environ.get("PAUTA_STATE_DIR")
    return Path(state) / "pauta.db" if state else Path("state") / "pauta.db"


def cmd_serve(args) -> None:
    from .server import make_handler

    store = Store(db_path())
    auth = Auth(store)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(store, auth))
    mode = f"passkeys on {auth.rp_id}" if auth.enabled else "open (no accounts)"
    print(f"pauta on http://{args.host}:{args.port} ({mode}), db {store.path}", flush=True)
    obs.setup_logging()
    obs.event("start", version=__version__, auth="passkeys" if auth.enabled else "open")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_invite(args) -> None:
    auth = Auth(Store(db_path()), enabled=True)
    token, expires = auth.create_invite(admin=args.admin, uses=args.uses, days=args.days)
    until = time.strftime("%Y-%m-%d %H:%M", time.localtime(expires))
    who = "admin" if args.admin else "member"
    print(f"{args.base_url.rstrip('/')}/#/entrar/{token}")
    print(f"({who}, {args.uses} use(s), valid until {until})", file=sys.stderr)


def cmd_users(args) -> None:
    store = Store(db_path())
    for m in store.members():
        flags = ("admin " if m["is_admin"] else "") + ("disabled" if m["disabled"] else "")
        print(f"{m['id']:>3}  {m['name']:<24} passkeys={m['passkeys']}  {flags}")


def cmd_backup(args) -> None:
    """One online backup into --dir as pauta-<stamp>.db, older ones pruned after --keep-days;
    --copy-to puts a second copy elsewhere (the NAS), pruned the same way."""
    name = f"pauta-{time.strftime('%Y%m%d-%H%M%S')}.db"
    out = Store(db_path()).backup(Path(args.dir) / name)
    print(out)
    dirs = [Path(args.dir)]
    if args.copy_to:
        try:
            dest = Path(args.copy_to)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, dest / name)
            dirs.append(dest)
            print(dest / name)
        except OSError as e:  # the NAS may be away; the local copy still counts
            print(f"copy to {args.copy_to} failed: {e}", file=sys.stderr)
    cutoff = time.time() - args.keep_days * 86400
    for d in dirs:
        for old in d.glob("pauta-*.db"):
            if old.stat().st_mtime < cutoff:
                old.unlink()


def cmd_demo(args) -> None:
    """Fill an empty database with made-up clients and requests, to see the app working."""
    store = Store(db_path())
    if store.clients() and not args.force:
        sys.exit("the database already has clients; --force to add demo data anyway")
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    clients = [
        ("Clínica Bem Estar", "Estética", "Ana", "(11) 98888-0000", "@clinicabemestar", "Liberado"),
        (
            "Padaria Trigo de Ouro",
            "Alimentação",
            "Seu Jorge",
            "(11) 97777-1212",
            "@trigodeouro",
            "Liberado",
        ),
        ("Studio Lume Pilates", "Saúde", "Carla", "(21) 99654-3321", "@studiolume", "Solicitado"),
        ("Ótica Visão Clara", "Varejo", "Marcos", "(31) 98123-4567", "@visaoclara", "Liberado"),
        (
            "Colégio Horizonte",
            "Educação",
            "Patrícia",
            "(41) 99111-2233",
            "@colegiohorizonte",
            "Pendente",
        ),
    ]
    ids = {}
    for name, seg, contact, wa, ig, access in clients:
        c = store.save_client(
            {
                "name": name,
                "segment": seg,
                "contact": contact,
                "whatsapp": wa,
                "instagram": ig,
                "ad_account": str(1000000000 + len(ids) * 7919),
                "access": access,
                "drive_url": "https://drive.google.com/",
                "since": d(-90 + len(ids) * 11),
                "state": "Ativo",
            }
        )
        ids[name] = c["id"]
    reqs = [
        (
            "Clínica Bem Estar",
            "Criar campanha",
            "Limpeza de pele com 20% de desconto em novembro",
            "Mensagens no WhatsApp",
            "Mulheres de 25 a 50 anos, interesse em estética",
            "Raio de 8 km da clínica",
            1500,
            "Tem saldo",
            d(1),
            "Alta",
            "doing",
        ),
        (
            "Padaria Trigo de Ouro",
            "Novos criativos",
            "Trocar os criativos do panetone: 3 posts e 2 stories com a foto nova da vitrine",
            "Visitas ao perfil",
            "Bairro e arredores",
            "Raio de 3 km",
            400,
            "Saldo baixo",
            d(-2),
            "Média",
            "todo",
        ),
        (
            "Studio Lume Pilates",
            "Criar campanha",
            "Aula experimental grátis para novos alunos",
            "Cadastros (formulário)",
            "Mulheres 30+, interesse em pilates e bem-estar",
            "Zona Sul do Rio",
            900,
            "Tem saldo",
            d(4),
            "Alta",
            "waiting",
        ),
        (
            "Ótica Visão Clara",
            "Ajustar verba",
            "Subir a verba da campanha de lentes para R$ 60/dia",
            "Vendas no site",
            "",
            "",
            1800,
            "Tem saldo",
            d(0),
            "Média",
            "todo",
        ),
        (
            "Colégio Horizonte",
            "Relatório",
            "Relatório de matrículas de outubro",
            "",
            "",
            "",
            None,
            "",
            d(6),
            "Baixa",
            "todo",
        ),
        (
            "Clínica Bem Estar",
            "Pausar campanha",
            "Pausar a campanha de botox até dezembro",
            "",
            "",
            "",
            None,
            "",
            d(-5),
            "Média",
            "done",
        ),
    ]
    for client, kind, what, goal, aud, region, budget, bal, due, prio, status in reqs:
        r = store.create_request(
            {
                "client": ids[client],
                "kind": kind,
                "what": what,
                "goal": goal,
                "audience": aud,
                "region": region,
                "budget": budget,
                "balance": bal,
                "due": due,
                "priority": prio,
                "creatives_url": "https://drive.google.com/",
            },
            None,
        )
        if status != "todo":
            extra = {"status": status}
            if status == "waiting":
                extra["missing"] = "Falta a liberação da conta de anúncios pelo cliente."
            store.update_request(r["id"], extra, None)
    store.comment(1, "Criativos aprovados pela Ana, subindo hoje à tarde.", None)
    print(f"demo data in {store.path}")


def cmd_onedrive(args) -> None:
    """status (account, folder, space), connect (the code flow, in the terminal) or
    disconnect. Uses the same token file as the service, next to the database."""
    drive = OneDrive.from_env(Store(db_path()).path)
    if not drive.enabled:
        sys.exit("PAUTA_ONEDRIVE_CLIENT_ID is not set; see deploy/README.md")
    try:
        if args.action == "disconnect":
            drive.disconnect()
            print("disconnected; the files stay in OneDrive")
            return
        if args.action == "connect":
            p = drive.start_connect()
            print(f"Open {p['verification_uri']} and enter the code {p['user_code']}", flush=True)
            while (state := drive.poll()) == "pending":
                time.sleep(args.poll)
            if state != "connected":
                sys.exit(f"not connected: {state}")
        st = drive.status(quota=True)
    except DriveError as e:
        sys.exit(f"onedrive: {e}")
    if not st["connected"]:
        sys.exit("not connected (pauta onedrive connect, or Equipe → OneDrive)")
    print(f"connected as {st['name']} <{st['account']}>")
    print(f"folder {st['folder']}, files up to {st['max_mb']} MB, token renewed {st['refreshed']}")
    q = st.get("quota") or {}
    if q.get("total"):
        print(f"space {q['used'] / 2**30:.1f} of {q['total'] / 2**30:.0f} GB used")
    elif st.get("used") is not None:
        print(f"pauta's folder holds {st['used'] / 2**20:.1f} MB")
    if st["error"]:
        sys.exit(f"problem: {st['error']}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pauta")
    p.add_argument("--version", action="version", version=f"pauta {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8088)
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("invite", help="make an invite link (the first one makes the admin)")
    s.add_argument("--admin", action="store_true")
    s.add_argument("--uses", type=int, default=1)
    s.add_argument("--days", type=float, default=7)
    s.add_argument("--base-url", default="https://pauta.genic.dev")
    s.set_defaults(fn=cmd_invite)
    s = sub.add_parser("users", help="list accounts")
    s.set_defaults(fn=cmd_users)
    s = sub.add_parser("backup", help="online SQLite backup into a directory")
    s.add_argument("--dir", default="backups")
    s.add_argument("--keep-days", type=int, default=30)
    s.add_argument("--copy-to")
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("demo", help="fill an empty database with made-up data")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("onedrive", help="the OneDrive that holds request files")
    s.add_argument("action", choices=["status", "connect", "disconnect"])
    s.add_argument("--poll", type=float, default=5, help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_onedrive)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
