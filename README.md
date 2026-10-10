# AMPTemplates-Cockatrice — Servatrice (Cockatrice server) for AMP

**AMP Generic Module** template for **Servatrice**, the official server of **Cockatrice**
(<https://cockatrice.github.io/>, source <https://github.com/Cockatrice/Cockatrice>), the free and
open-source virtual tabletop for Magic: The Gathering and other collectible card games (client
translated into French). Written for TeamKit, a free French game host, on 10 Oct 2026.
CubeCoders ships no Cockatrice template, and no community one was found.

> Résumé en français à la fin du fichier.

## What gets installed, and why that way

Servatrice is **not in Debian** (no `servatrice` package in any suite). Each stable Cockatrice
release on GitHub ships a server-only package, `…-Servatrice_Debian12.deb` (1.1 MB). It **cannot be
installed with apt/dpkg on Debian 13** (the `cubecoders/ampbase:debian` image): CPack declares
`qt6-websockets-abi (= 6.4.2)` (Debian 13 has Qt 6.8.2) and the desktop client's dependencies
(`libqt6multimedia6`, `libqt6svg6`, `qt6-qpa-plugins`…). The binary itself only uses public
`Qt_6.4` symbols and runs fine with Debian 13's Qt 6.8 (`ldd`: nothing missing; tested). So the
Update **extracts** the package (`dpkg-deb -x`, no root) into `cockatrice/servatrice/`, and the
runtime libraries come from `Meta.ExtraContainerPackages`. Container mode is **required**.

`installer-servatrice.sh` (last Update stage):

- asks the GitHub API for the most recent **stable** release that has a `-Servatrice_Debian12.deb`
  (or a future `Debian13`) asset — not every release has one: 3.1.0 (3 Oct 2026) had none;
- or takes the exact release named in *Version de Servatrice* (betas included), and fails the
  Update if it does not exist or has no server package (the installed version is kept);
- checks size and the SHA-256 digest published by GitHub, extracts, checks `ldd`, swaps folders,
  writes `servatrice/VERSION-TEAMKIT`; does nothing when already up to date;
- keeps the installed version if GitHub is unreachable (anonymous API limit: 60 requests/hour/IP).

Tested on 10 Oct 2026 with **Servatrice 3.1.1** (released that day). Client and server protocol
version is **14** in 3.1.1 and already was in 2.9.0 (2023): players need no exact version match.

## Files

| File | Role |
|---|---|
| `cockatrice.kvp`, `cockatrice*.json`, `manifest.json` | the AMP template |
| `scripts/AMP_reglages.txt` | settings model; AMP renders it to `reglages-amp.txt` (`ConfigType: template`), one raw `key=value` per line |
| `scripts/ecrire_config.py` | turns `reglages-amp.txt` into `servatrice.ini` (Qt INI), with escaping |
| `scripts/lancer-servatrice.sh` | start script (below) |
| `scripts/installer-servatrice.sh` | downloads/extracts Servatrice (above) |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

All four `scripts/` files are fetched from this repository (raw.githubusercontent.com, branch
`main`) at each Update, so **the repository must be public**.

## Why AMP does not write `servatrice.ini` directly

`servatrice.ini` is read by Qt's `QSettings` (INI format). AMP writes values verbatim, and:

- an **unquoted value containing a comma is read as a list**, and Servatrice then gets an
  **empty string** (tested: a room named `Salon, avec virgule` came out nameless);
- inside quotes, `\` and `"` must be escaped; a value starting with `@` can be taken for
  `@Variant(…)`/`@ByteArray(…)`;
- game types are a Qt array (`roomlist\1\game_types\size`, `…\1\name`, …).

So AMP renders a trivial `key=value` file and `ecrire_config.py` writes `servatrice.ini` with every
text quoted and escaped. Tested end to end with real Servatrice: accents, `—`, commas, `;`, `#`,
`{}`, `"`, `\`, leading `@`. `perso.ini` (created once, never overwritten) is appended at the end:
a key repeated later wins (tested), so it can override anything.

## Accounts: the three modes, and the choice

| Setting *Comptes des joueurs* | Servatrice | For | Against |
|---|---|---|---|
| **Ouvert** (default) | `authentication/method=none`, no database | type a nickname and play; nothing to set up | **no ban, no moderators**, names not protected (a duplicate gets `_1`), no replays, no buddy list |
| **Comptes** | `method=sql`, registration on, **no e-mail** (`requireemail=false`, no activation) | protected names, bans (name/IP), moderators, buddy/ignore lists, replays, deck sharing | needs MariaDB; no "forgot password" (no SMTP) |
| **Privé** | `method=password`, one shared password | private group | same nickname twice = the first one is logged out |

**Why "Ouvert" by default:** it works at once with nothing to create, which is what a new TeamKit
server needs to find its first players; the Cockatrice client handles it natively (the password
field is simply ignored). Its real weakness is moderation, so **"Comptes" is ready** for the day it
matters, without any database work: by default it uses an **integrated MariaDB** (below). In
"Comptes", guests can still play under a free nickname (not a registered one) unless *Inscription
obligatoire* is ticked.

Facts that shaped this (from the 3.1.1 source):

- **No SQLite**: Servatrice only knows `none` and `mysql` (`QMYSQL` driver).
- The login **message of the day only comes from the database** (`cockatrice_servermessages`), so
  the TeamKit welcome text is the main room's `joinmessage` (shown to everyone entering it; the
  room is auto-joined).
- Servatrice **refuses a MariaDB whose GLOBAL `sql_mode` contains `STRICT_TRANS_TABLES` or
  `STRICT_ALL_TABLES`** (`SELECT @@GLOBAL.sql_mode`) — and strict mode is MariaDB's default
  (Debian 13's MariaDB 11.8 included). Using a shared MariaDB would mean changing its global mode.

### Integrated database (default for "Comptes")

`lancer-servatrice.sh` runs `mariadbd` (package `mariadb-server-core`) inside the container, as the
AMP user: data in `cockatrice/base/`, **Unix socket only** (`--skip-networking`, socket in
`$XDG_RUNTIME_DIR`), `--sql-mode=NO_ENGINE_SUBSTITUTION`, small buffers (86–91 MB RSS measured).
Servatrice connects to `localhost` and finds the socket through `MYSQL_UNIX_PORT` (honoured by
libmariadb; tested). First start: `mariadb-install-db`, then the tables from `servatrice.sql`
(shipped in the package). `sauvegarde-base.sql.gz` (`mariadb-dump --single-transaction`) is written
at start, every hour and at stop: copying `base/` while it runs may give an inconsistent backup,
the dump never does. Stop: Servatrice first, then a clean MariaDB shutdown.

**External database** (*Base des comptes = externe*): host (no port: Servatrice always uses 3306),
database, user, password. The start script checks the global `sql_mode` and explains if it is strict.

For both: empty database → tables created; older schema → the matching
`servatrice/migrations/servatrice_NNNN_to_MMMM.sql` are fetched from the installed release's tag
and applied (a dump is taken first). Tested with a database created by Servatrice 2.10.2
(schema 34 → 37, existing account kept).

### Staff

*Administrateurs* / *Modérateurs* (comma-separated nicknames, registered first in the game) are
applied at each start (`cockatrice_users.admin` bits 1 and 2). The script remembers what the list
granted (`staff-amp.json`) and only removes that: moderators appointed in-game by an admin stay.
Moderators warn, kick and ban from the client (right-click a user); admins also get the
administration tab. Warning reasons offered to moderators are translated into French.

`commande.sql` dropped in the instance folder (AMP file manager) is run once against the database
at the next start, then renamed `commande.sql.fait-<date>` with its output next to it — e.g. to
delete an account whose password was forgotten (`DELETE FROM cockatrice_users WHERE name='X';`).

## How the server is started

`/bin/bash lancer-servatrice.sh <game port> <websocket port>`:

1. `ecrire_config.py` writes `servatrice.ini` (and, in "Comptes", the client option file and the
   staff SQL in `$XDG_RUNTIME_DIR`, mode 600 — never in the instance folder that backups copy);
2. "Comptes": starts/prepares the database as above;
3. runs `servatrice --config <absolute path> --log-to-console` under `setpriv --pdeathsig TERM`;
4. on SIGTERM (AMP stop): stops Servatrice, dumps and stops the integrated database, exits 0.

Killing the script with SIGKILL takes Servatrice and MariaDB down with it (tested).

## Settings exposed in AMP (French UI)

| AMP setting | Servatrice | Default |
|---|---|---|
| Port du jeu (Network tab) | `server/port` | **4747/TCP** (client default) |
| Port WebSocket (Network tab) | `server/websocket_port` | 4748/TCP |
| Nom du serveur | `server/name` | `Cockatrice FR — TeamKit` |
| Message d'accueil | main room `joinmessage` | TeamKit message with the Discord link |
| Salon principal : nom / description | room 1 (auto-join) | `Salon francophone` / French description |
| Types de parties | room `game_types` (comma list) | Commander, Standard, Modern, Pioneer, Pauper, Legacy, Limité (draft ou scellé), Autre jeu de cartes |
| Second salon : nom / description | room 2 (optional, not auto-join) | empty = one room |
| Comptes des joueurs | `authentication/method` | Ouvert |
| Mot de passe du serveur privé | `authentication/password` | empty |
| Inscription obligatoire | `authentication/regonly` | no |
| Base des comptes | integrated / external | integrated |
| Administrateurs, Modérateurs | `cockatrice_users.admin` | empty |
| MariaDB externe : adresse, base, utilisateur, mot de passe | `database/*` | 172.17.0.1, servatrice, servatrice, — |
| Nombre maximum de joueurs (`$MaxUsers`) | `security/max_users_*` | 100 |
| Connexions par adresse IP | `security/max_users_per_address` | 4 (Servatrice default) |
| Parties ouvertes par joueur | `security/max_games_per_user` | 5 |
| Accepter les connexions WebSocket | `websocket_number_pools` | yes |
| Version de Servatrice | installer | empty = latest stable |

Fixed by the template: username rules in "Comptes" (3–20 characters, `_.-`, no `admin`,
`moderat`, `teamkit`), no e-mail and no SMTP, replays only with a database, status rows every
5 minutes instead of 15 s (one row per tick in `cockatrice_uptime`), no ISL network.

**Port trap.** The desktop client switches to WebSocket when the port is **80, 443, 4748 or 8080**
(`remote_client.cpp`). A TCP game port among those would be unreachable, so the script refuses it.
Players type 4747 (TCP); the WebSocket port serves a future Webatrice web client, or desktop
clients that type 4748 (TCP is marked "will be removed in the future" in `servatrice.ini.example`).

**Per-IP limit.** `Incoming connection: <ip>` is shown in the console. If every player shows up with
the same Docker address (172.17.x.1), set *Connexions par adresse IP* to 0. Note that even local
connections count (`::ffff:127.0.0.1` is not in `trusted_sources`).

## Console and player list

Servatrice has **no console of its own** (no stdin commands): `HasWriteableConsole=False`.
Only with a log file open does it print its log to the console, so `writelog=1` with
`logfile=/dev/null` (nothing on disk).

Real lines (3.1.1):

```
Server initialized.                                                                  <- AppReadyRegex
Sat Oct 10 17:52:50 2026 Server::loginUser: TcpServerSocketInterface(0x56330ef4bf00) name= "Kévin"   <- UserJoinRegex
Sat Oct 10 17:52:54 2026 Server::removeClient: name= "Kévin"                          <- UserLeaveRegex
```

`ThrowawayMessageRegex` drops: every command dump (`… 20 bytes [Command_RoomSay.ext] {…}`) — that is
**every chat line, private message and game action, with its content**, so dropping it is both a
privacy and a flood matter (≈ 20 lines per player connection otherwise); the "Driver not loaded"
lines that the open mode prints at each login (no database configured); and other bookkeeping.
Kept: connections with IP, logins, departures, real database errors, start-up summary.

## How a player connects

The server is **not in the client's list**: the "refresh" button only loads Cockatrice's curated
`https://cockatrice.github.io/public-servers.json` (5 servers). In the French client:

1. **Cockatrice → Connecter…** opens *Se connecter au serveur*;
2. tick **Nouvel hôte**, give a name (e.g. `TeamKit FR`), **Hôte** = the server address, **Port** =
   `4747`, **Nom du joueur** = a nickname (and **Mot de passe** in "Comptes"/"Privé");
3. **Connecter**. The server is then saved under **Hôtes connus**.

In "Comptes": **Cockatrice → S'enregistrer sur le serveur…** first (same address and port, a
nickname, a password; e-mail can stay empty).

## Resources (measured, 10 Oct 2026)

| | Ouvert / Privé | Comptes, integrated base |
|---|---|---|
| RAM | Servatrice 32–34 MB idle, 36–37 MB with 50 players; +4 MB bash | + MariaDB 86–91 MB |
| Disk | 3.3 MB | + 58 MB (`base/`) + a few KB of dump |
| Start | < 1 s | ~2 s (4 s the first time) |
| CPU | negligible: clients run the game, the server relays | |

Profile: 128 MB in Ouvert/Privé, 256 MB in Comptes.

## Before pushing

```
python verifier.py
```

Must print `Tout est bon.`: JSON, includes, ports, complete `Console.*`/`Limits.*`, package list,
every setting from AMP to the model to the generator, a round trip through the real
`ecrire_config.py` read back as Qt and mariadb would (empty, spaces, accents, commas, quotes,
backslashes, leading `@`), refusal of impossible settings, staff SQL escaping and removal,
download URLs, LF/ASCII scripts, `bash -n`, console regexes on real lines.

## Install in AMP

ADS → Configuration → Instance Deployment → **Configuration Repositories**: add
`hydrocut/AMPTemplates-Cockatrice:main`, save, **Fetch latest**. Create Instance →
**Cockatrice - Servatrice (TeamKit)** → **Update** (must end with `Bibliotheques de servatrice :
toutes presentes.`) → **Start** (ready on `Server initialized.`).

Remember that a later *Fetch latest* does not update `App.*`/`Console.*` of existing instances.

## Credits

Cockatrice and Servatrice are free software (GPL-2.0) by the Cockatrice team. This repository only
contains the template; Servatrice is downloaded from the project's GitHub releases.

---

## Résumé en français

Template AMP pour **Servatrice**, le serveur officiel de **Cockatrice** (Magic et autres jeux de
cartes, gratuit, libre, jeu en français). Servatrice n'est pas dans Debian : l'Update télécharge le
paquet `.deb` du serveur seul publié avec chaque version stable de Cockatrice et l'**extrait** (il ne
s'installe pas avec apt sur Debian 13, mais le programme tourne avec ses bibliothèques). Conteneur
obligatoire. Testé avec Servatrice **3.1.1**.

- **Ports** : **4747 en TCP** (celui que tapent les joueurs) et 4748 en TCP (WebSocket, pour plus
  tard). Ne jamais mettre 80, 443, 4748 ou 8080 comme port du jeu : le jeu passerait en WebSocket.
- **Comptes** : **Ouvert** par défaut (pseudo libre, rien à créer, mais ni bannissement ni
  modérateurs) ; **Comptes** (inscription depuis le jeu sans e-mail, pseudos protégés, modérateurs,
  bannissements, replays) avec une **MariaDB intégrée à l'instance**, sans port ni réglage, ou une
  MariaDB externe (à condition qu'elle ne soit pas en mode strict) ; **Privé** (mot de passe commun).
  Administrateurs et modérateurs se choisissent dans AMP.
- **Message d'accueil TeamKit** dans le « Salon francophone » (Servatrice ne sait afficher un message
  de connexion que depuis une base) ; types de parties en français ; second salon facultatif.
- **Le serveur n'apparaît pas dans la liste du jeu** : Cockatrice → Connecter… → Nouvel hôte → adresse
  + port 4747 → pseudo → Connecter. Il reste ensuite dans « Hôtes connus ».
- **Console** : joueurs visibles dans AMP ; le contenu du chat, des messages privés et des parties
  n'est pas affiché (vie privée, et bien trop de lignes).
- **Mesuré** : 32 à 37 Mo de RAM (50 joueurs), + 90 Mo avec la base intégrée.
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
