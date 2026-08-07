# Self-hosting BIMtrieval

Provider-neutral. Anything that runs Docker Compose runs this: a laptop, a
workstation under a desk, a VM at any cloud provider, a NAS.

## The boundary

There is a deliberate line between two things that are easy to conflate:

| | The public repository | Your instance |
| --- | --- | --- |
| What it is | Source, specs, benchmark, screenshots | A running system with your data |
| Building models | None. `ifc/*.ifc` is git-ignored | Your IFC files, on your disk |
| OpenAI key | None, ever | Yours, in your local `.env` |
| Who pays for a query | Nobody — nothing runs | You |
| Reachable from the internet | No | Only if you choose to expose it |

**There is no hosted demo, and this is a decision rather than an omission.**
A public endpoint answering BIM questions would spend the author's OpenAI tokens
on every visitor's query, with no cap that survives contact with a crawler. The
alternative — asking visitors to paste their own key into a web page — trains
people to hand API keys to strangers' websites. The repository shows the system
through screenshots, a recorded demo, and a published benchmark; running it
requires your own key, and the key never leaves your machine.

## Prerequisites

- Docker Engine 24+ with the Compose plugin (or Docker Desktop)
- ~8 GB free disk: the images, the embedding model weights, and your database
- An OpenAI API key
- At least one IFC file

No Python, Node, PostgreSQL, or CUDA on the host. The images are CPU-only.

## Setup

```bash
git clone https://github.com/daegeun-kim/BIMtrieval.git
cd BIMtrieval
cp .env.example .env
```

Edit `.env`. For the production profile, the database credentials are
**mandatory** — Compose refuses to start without them rather than defaulting to
a password that is published in a public repository:

```dotenv
POSTGRES_USER=bimtrieval
POSTGRES_PASSWORD=<a long random string>
POSTGRES_DB=bimtrieval
OPENAI_API_KEY=sk-...
```

Generate a password with `openssl rand -base64 32`.

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Then put an IFC file in `ifc/` and import it:

```bash
docker compose -f compose.yaml -f compose.prod.yaml \
  run --rm import "My Building.ifc"
```

Open **http://localhost:5173**.

## What the production profile changes

| | Default | Production |
| --- | --- | --- |
| Database credentials | Local dev default | Required; startup fails without them |
| Restart policy | `unless-stopped` | `always` — survives a host reboot |
| Root filesystem | Writable | **Read-only**, with tmpfs for `/tmp` and logs |
| Linux capabilities | Default set | **All dropped** |
| Privilege escalation | Allowed | `no-new-privileges` |
| Memory / CPU | Unbounded | Bounded per service |
| Dev endpoints | Off by default | Explicitly off |

Ports bind to `127.0.0.1` in both profiles. PostgreSQL is not published at all.

## Exposing it beyond localhost

Not done for you, on purpose. BIMtrieval has **no authentication** — it is a
single-user local tool, and `POST /api/query` costs money to call. Publishing it
on `0.0.0.0` gives anyone who finds it the ability to spend your OpenAI budget.

If you need remote access, put it behind something that authenticates:

1. A reverse proxy (Caddy, nginx, Traefik) terminating TLS with auth in front.
2. A private network — Tailscale, WireGuard, or an SSH tunnel — which is simpler
   and is what most single-user cases actually want.

Then set `CORS_ALLOW_ORIGINS` to your real origin, and rebuild the frontend with
`VITE_API_BASE_URL` pointing at the proxied backend.

## Your data stays yours

- **Database** — the `pgdata` named volume on your host. Not in any image.
- **IFC files** — `ifc/`, git-ignored, mounted **read-only** into the import
  container, which therefore cannot modify your source models.
- **Generated artifacts** — `model_assets/` and `model_semantics/`, on your host.
- **Model weights** — the `hfcache` volume, so they are downloaded once.

Nothing but the question text and retrieved evidence leaves your machine, and
that goes to one place: OpenAI's API, called by the backend with your key. The
frontend never contacts OpenAI, never sees the key, and never asks for one.

## Backup

```bash
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```

Or copy the volume. Nothing is stored outside PostgreSQL and the two artifact
folders, so those are the whole state.

## Running without a key

The stack starts and stays inspectable: the API responds, the model catalog
loads, the 3D viewer and floor plans work, and question answering reports that
no key is configured. It tells you what is missing instead of fabricating an
answer.

Same with no imported model — the catalog is simply empty, and the UI says so.

## Upgrading

```bash
git pull
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

`bim-db-init` runs on every start, applies any pending migration, and records it
in `schema_migrations`. It is idempotent, so an unchanged schema is a no-op. Your
database volume is untouched by a rebuild — only `docker compose down -v`
deletes it.

## Cost

You pay OpenAI directly, per question. From the published benchmark, a question
used a median of ~9,400 tokens and a maximum of ~31,000, dominated by the model
manifest sent to the binder. Rates change, so multiply by current pricing rather
than trusting a number written here.

Idle cost is zero: no query, no call. Startup, the viewer, floor plans, model
loading, and clicking through evidence make **no** model calls at all.
