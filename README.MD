# hs-core

Management Core des Homeserver Managers, läuft auf dem Raspberry Pi (`hs-core`).
Namen und Begriffe: siehe `docs/nomenklatur.md`.

| Ordner | Inhalt |
| --- | --- |
| `hs_api/` | Management API (`hs-api`) |
| `migrations/` | SQL-Migrationen, nummeriert, nie nachträglich ändern |
| `deploy/` | systemd-Units |
| `scripts/` | Hilfsskripte für den Mac |

## Migrationen einspielen (vom Mac/PC)

```bash
scripts/push-migration.sh            # Auswahlmenü
scripts/push-migration.sh 004_x.sql  # direkt
```

Voraussetzung: SSH-Zugang zum Pi (Host per `HS_PI_HOST`, Standard `hs-core`) und auf dem Pi
eine `~/.pgpass` mit dem Passwort von `hs_owner`. Jede Migration steht in `BEGIN; … COMMIT;`
und trägt sich am Ende selbst in `schema_migrations` ein.

## Installation auf dem Pi

```bash
sudo apt install -y python3-venv
sudo git clone <repo-url> /opt/hs-core
sudo chown -R homeserver:homeserver /opt/hs-core
sudo -u homeserver python3 -m venv /opt/hs-core/.venv
sudo -u homeserver /opt/hs-core/.venv/bin/pip install -r /opt/hs-core/requirements.txt
```

`/etc/homeserver/secrets.env` nach Vorlage `.env.example` befüllen, dann:

```bash
sudo cp /opt/hs-core/deploy/hs-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hs-api
journalctl -u hs-api -f
```

Die API-Doku ist dann unter `http://hs-core:8000/api/v1/docs` erreichbar.

## Token für eine Komponente anlegen

```bash
sudo -u homeserver bash -c 'set -a; . /etc/homeserver/secrets.env; cd /opt/hs-core; \
  .venv/bin/python -m hs_api.tools.create_component host_agent hs-host-agent@pve01 --resource pve01'
```

Das Token wird nur einmal angezeigt. Erneuter Aufruf mit demselben Namen erzeugt ein neues Token.

## Update

```bash
cd /opt/hs-core && sudo -u homeserver git pull
sudo -u homeserver .venv/bin/pip install -r requirements.txt
sudo systemctl restart hs-api
```
