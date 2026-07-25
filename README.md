# Vipyr Bot

A Discord bot for Vipyr

## Dragonfly queue status

The `/queue-status` command reports the cached queue snapshot from every configured
Dragonfly cluster. Configure each cluster with its own Cloudflare Access service
token:

```text
DRAGONFLY_QUEUE_CLUSTERS={"production":{"api_url":"https://dragonfly.vipyrsec.com","access_client_id":"...","access_client_secret":"..."},"staging":{"api_url":"https://dragonfly-staging.vipyrsec.com","access_client_id":"...","access_client_secret":"..."}}
```

If this setting is omitted, the command reports the existing `DRAGONFLY_API_URL` as
`production`. Queue snapshots are maintained by Mainframe; invoking the command does
not issue a metrics query against PostgreSQL.
