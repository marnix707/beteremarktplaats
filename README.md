# BetereMarktplaats

Searches Marktplaats and Facebook Marketplace together, without ads, links to shops or accessories
("fiets" does not show "fietshelm"). Alarms re-run a search in the background and tell you about new results.

## Start

```
cp .env.example .env     # optional: fill in ntfy / e-mail
docker compose up --build -d
```

Open http://localhost:8765

## Facebook (once)

Click **Inloggen bij Facebook** on the site. A browser opens in a new tab (noVNC, port 6080, this computer only).
Log in, then click **Klaar** on the site. The login is kept in the `data` volume.

## Alarms

Search, then **Maak hiervan een alarm**. Choose how to be told:

- **Browser**: notification and sound while the site is open in a tab
- **ntfy**: push to your phone (set `NTFY_TOPIC` in `.env`, subscribe to it in the ntfy app)
- **E-mail**: set the `SMTP_*` values in `.env`

The first check only remembers what is there now; you are told about what appears after that.

## Develop

```
docker compose run --rm app pytest
```

Scraping these sites is against their terms of use. Keep it light and personal. If Facebook shows nothing,
its page layout probably changed: the selectors are in `app/facebook.py`.
