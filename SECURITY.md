# Security

## What BIMtrieval is, security-wise

A **single-user local tool**. It has no authentication, no authorization, and no
rate limiting, and it is not built to have them. Read this before deciding where
to run it.

`POST /api/query` calls OpenAI with your key. Anyone who can reach that endpoint
can spend your money. The default Compose stack therefore publishes only to
`127.0.0.1`, and PostgreSQL is not published at all.

**Do not expose this on `0.0.0.0` or the public internet.** If you need remote
access, put it behind a reverse proxy that authenticates, or reach it over a
private network such as Tailscale, WireGuard, or an SSH tunnel. See
[`docs/self-hosting.md`](docs/self-hosting.md).

## Design decisions that limit blast radius

These are properties of the implementation, not aspirations, and each is covered
by a test:

- **The backend cannot write BIM data.** It connects through a dedicated
  read-only PostgreSQL role (`bim_rag_query_ro`), so a malformed or hostile
  query structurally cannot corrupt the model corpus. Statement and result
  limits are enforced on top of that.
- **Your key never reaches the browser.** No file under `frontend/src` mentions
  `OPENAI_API_KEY` or contacts OpenAI. Only the backend does.
- **No secret enters an image.** `.dockerignore` excludes `.env`, `ifc/`, and
  `*.ifc`; no Dockerfile copies any of them; `.env` is read by Compose at
  runtime for variable substitution only.
- **Secrets are typed as `SecretStr`** so they cannot appear in `repr()`/`str()`
  output, and logs are redacted for key- and DSN-shaped strings.
- **Database errors are sanitized** before logging or reporting, so credentials
  cannot leak through an error path.
- **Your IFC files are mounted read-only** into the import container, which
  therefore cannot modify a source model.
- **The LLM cannot select data.** The final model call expresses
  already-adjudicated evidence; its factual claims are validated against the
  answer packet before the user sees them.

## Data handling

Nothing leaves your machine except the question text and the retrieved evidence,
and that goes to one place: OpenAI's API, called by your backend with your key.
Your models, database, and generated artifacts stay on local volumes.

The semantic manifest sent to the model describes your building's *schema* —
class names, property names, storey names, observed values. If your model names
are themselves confidential, that is the surface to consider.

## Reporting a vulnerability

Open a GitHub issue for anything non-sensitive.

For something that should not be public first, use GitHub's private
[security advisory](https://github.com/daegeun-kim/BIMtrieval/security/advisories/new)
form on this repository.

This is a personal project maintained by one person, not a product with an
on-call rotation. Expect a considered reply rather than a fast one, and no
guaranteed patch timeline.

## Supported versions

The latest release on `main`. There are no backported security fixes for earlier
tags.
