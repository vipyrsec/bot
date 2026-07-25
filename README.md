# Vipyr Bot

A Discord bot for Vipyr

## Dragonfly queue status

The `/queue-status` command reports the cached queue snapshot from the bot's existing
`DRAGONFLY_API_URL`. Staging and production bots therefore report only their own
environment using their existing environment-specific Cloudflare Access service
token. Queue snapshots are maintained by Mainframe; invoking the command does not
issue a metrics query against PostgreSQL.
