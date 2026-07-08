# API Keys & Security Practices

These practices apply to all exchange API keys (OKX, OrangeX) used by the
bot, in any trading mode.

## Practices

- **No withdrawal permission** — API keys must never have withdrawal
  permission enabled on the exchange side, under any circumstances.
- **Env vars only** — keys are stored only via environment variables, never
  committed to source control. `.env` must be listed in `.gitignore`.
- **Separate keys per exchange** — OKX and OrangeX each use their own
  dedicated API key/secret pair; keys are never shared across exchanges.
- **Rotate keys periodically** — API keys should be rotated on a regular
  schedule, not left static indefinitely.
- **Never logged** — live API keys must never appear in logs, error
  messages, stack traces, or any other output.
- **Principle of least privilege** — keys should be scoped to only the
  permissions the bot actually needs (e.g. read market data + place/cancel
  orders), and nothing more.
- **IP allowlisting** — where supported by the exchange, restrict API key
  usage to an allowlisted set of IP addresses.

## Related

- `.env.example` at the repo root documents every required environment
  variable name (with empty/placeholder values) without ever containing
  real secrets.
