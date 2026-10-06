# Homeserver Manager – Nomenklatur

## Grundregeln
Dieses Dokument ist die verbindliche Quelle für alle Namen im Projekt: in Code, Datenbank, Repos, Discord und Doku. Was hier nicht steht, wird nach den Regeln dieses Abschnitts benannt und anschließend hier ergänzt.
Dokumentation und Kommentare sind auf *Deutsch*. Alles, was im Code oder in der Datenbank steht, ist *Englisch*. Die deutschen Begriffe im Glossar sind nur Erklärungen; im Code gilt immer der englische Bezeichner.

| Wofür                                             | Schreibweise                              | Beispiel                              
|                                                   |                                           |                                       
| Tabellen, Spalten, Python-Variablen und -Module   | snake_case                                | `scheduled_actions`, `relay_gpio_pin` 
| Python-Klassen                                    | PascalCase                                | `CommandStatus`                       
| Repos, Hostnamen, systemd-Units, Komponentennamen | kebab-case mit Präfix `hs-`               | `hs-host-agent`                       
| Actions und Events                                | `objekt.verb`, Punktnotation, snake_case  | `vm.force_stop`, `command.failed`     
| Status von Ressourcen und Komponenten             | GROSSBUCHSTABEN                           | `ON`, `RUNNING`                      
| Status von Commands und Scheduled Actions         | kleinbuchstaben                           | `pending`, `scheduled`                 
| Settings-Keys, Use-Case-Arten, Gründe             | snake_case                                | `idle_shutdown_after_minutes`         

Das Präfix `hs` steht für Homeserver und kennzeichnet alles, was zu diesem Projekt gehört. Die Datenbank heißt `homeserver`, ihre Rollen `hs_owner` und `hs_app`.

## Glossar
Die wichtigste Unterscheidung: 
    **Action**  =   eine Art von Aktion aus dem Katalog
    **Command** =   ein konkreter Auftrag, diese Action auszuführen. 
    
    „vm.start“ ist eine Action; „User 3 will VM 2 um 14:02 starten“ ist ein Command.

| Begriff               | Bezeichner            | Bedeutung 
|                       |                       | 
| Host                  | `host`                | Physischer PC mit Proxmox 
| VM                    | `vm`                  | Virtuelle Maschine auf einem Host 
| Service               | `service`             | Anwendung auf einer VM, z.B. Minecraft 
| Ressource             | `resource`            | Oberbegriff für Host, VM und Service. Alles, was einen Status hat und Ziel einer Action sein kann  
|                       |                       |
| Management System     | –                     | Gesamtheit der Software dieses Projekts 
| Management Core       | `core`                | Alle Komponenten auf dem Raspberry Pi 
| Komponente            | `component`           | Ein einzelnes laufendes Programm des Management Systems, z.B. ein Agent oder der Bot 
| Action                | `action`              | Art einer Aktion aus dem Katalog, z.B. `host.power_on` 
| Command               | `command`             | Konkreter Auftrag, eine Action an einer Ressource auszuführen 
| Event                 | `event`               | Tatsächlich eingetretenes Ereignis oder Zustandsänderung. Wird nie geändert 
| Scheduled Action      | `scheduled_action`    | Für einen Zeitpunkt geplante Action, z.B. Auto-Shutdown. Wird bei Fälligkeit zu einem Command 
| Use-Case              | `use_case`            | Aktive Nutzung einer Ressource, die einen laufenden Host erfordert 
|                       |                       |
| User                  | `user`                | Mensch, der das System nutzt
| Identity              | `identity`            | Ein externes Konto eines Users, z.B. seine Discord-ID
| Rolle                 | `role`                | Gruppe von Usern mit gemeinsamen Permissions
| Permission            | `permission`          | Regel: wer darf welche Action an welcher Ressource, mit welchen Einschränkungen
| Setting               | `setting`             | Globaler Konfigurationswert in der Datenbank

Das Wort „Aktion“ wird im Fließtext nur allgemein verwendet. Ist etwas Bestimmtes gemeint, wird Action, Command oder Scheduled Action geschrieben.

## Komponenten
Jede Komponente hat einen Namen, der gleichzeitig ihr systemd-Unit-Name ist. Das Python-Paket heißt genauso, nur mit Unterstrichen.

| Komponente            | `component_kind`      | Name / systemd-Unit   | Python-Paket          | Repo                  | Läuft auf 
|                       |                       |                       |                       |                       |           
| Management API        | `api`                 | `hs-api`              | `hs_api`              | `hs-core`             | Pi        
| Discord Bot           | `discord_bot`         | `hs-discord-bot`      | `hs_discord_bot`      | `hs-core`             | Pi        
| Power Controller      | `power_controller`    | `hs-power-controller` | `hs_power_controller` | `hs-core`             | Pi       
| Admin Dashboard       | `dashboard`           | `hs-dashboard`        | `hs_dashboard`        | `hs-core`             | Pi            
| Host Agent            | `host_agent`          | `hs-host-agent`       | `hs_host_agent`       | `hs-host-agent`       | Proxmox-Host 
| VM Agent              | `vm_agent`            | `hs-vm-agent`         | `hs_vm_agent`         | `hs-vm-agent`         | jede VM 
| Service Manager       | `service_manager`     | `hs-sm-<service_type>`| `hs_sm_<service_type>`| `hs-sm-<service_type>`| Service spezifischer VM

In der Tabelle `components` muss jeder Name eindeutig sein. Komponenten, die nur einmal existieren, heißen dort wie ihre Unit. Komponenten, die mehrfach laufen, bekommen die Ressource angehängt, auf der sie laufen: `hs-host-agent@pve01`, `hs-vm-agent@vm-minecraft`, `hs-sm-minecraft@minecraft`.

## Ressourcen und Hostnamen
Der technische Name einer Ressource (`resources.name`) ist kurz, kleingeschrieben und ändert sich nie. Für Anzeigen in Discord und Dashboard gibt es `display_name`, der frei wählbar ist.

| Ressource     | Muster für `name`                                 | Beispiel                              | `display_name`
|               |                                                   |                                       |
| Host          | `pve` + zweistellige Nummer                       | `pve01`                               | Homeserver
| VM            | `vm-` + Zweck                                     | `vm-minecraft`                        | Minecraft-VM
| Service       | `service_type`, bei mehreren Instanzen mit Zusatz | `minecraft`, `minecraft-creative`     | Minecraft

Der Name einer VM in Proxmox ist identisch mit ihrem `resources.name`, ebenso ihr Hostname im Netzwerk. Die Proxmox-VMID steht nur in `vms.proxmox_vmid` und wird sonst nirgends als Name verwendet.
Der Raspberry Pi ist keine Ressource, weil er nicht verwaltet wird, sondern verwaltet. Sein Hostname ist `hs-core`.

## Status
Es gibt vier Status-Familien. Großgeschriebene beschreiben einen Zustand, kleingeschriebene einen Bearbeitungsstand.

| Wofür                             | Werte 
|                                   |
| Ressourcen (Host, VM, Service)    | `ON`, `OFF`, `STARTING`, `STOPPING`, `RESTARTING`, `UNKNOWN`, `ERROR` 
| Komponenten                       | `RUNNING`, `DEAD`, `UNKNOWN`, `ERROR` 
| Commands                          | `pending`, `running`, `completed`, `failed`, `cancelled` 
| Scheduled Actions                 | `scheduled`, `executed`, `cancelled`, `failed` 

Für alle Familien gilt: `UNKNOWN` heißt „Zustand nicht feststellbar“, etwa weil keine Meldung kommt. `ERROR` heißt „erreichbar, aber in einem bekannten kritischen Fehlerzustand“. Bei Commands heißt `cancelled` „vor der Ausführung abgebrochen“, `failed` „Ausführung versucht, aber fehlgeschlagen“.

## Actions
Eine Action heißt `<ressourcenart>.<verb>`. Die Verben kommen aus einem festen Vokabular, damit gleiche Dinge überall gleich heißen.

| Verb          | Bedeutung                             | Ausgeführt über
|               |                                       |
| `status`      | Zustand abfragen, ändert nichts       | Datenbank
| `power_on`    | Strom an, physischer Tastendruck      | Relais
| `force_off`   | Strom hart aus, langer Tastendruck    | Relais
| `start`       | Software starten                      | Proxmox bzw. Service Manager
| `shutdown`    | Sauber herunterfahren                 | Betriebssystem bzw. Service Manager
| `restart`     | Sauber neu starten                    | Betriebssystem bzw. Service Manager
| `force_stop`  | Software hart beenden                 | Proxmox bzw. Service Manager

Die Faustregel: `power_on` und `force_off` gibt es nur beim Host, weil nur dort ein Relais sitzt. `start` und `force_stop` sind ihre Gegenstücke in Software.

**Aktueller Katalog:** 
    `host.status`, `host.power_on`, `host.shutdown`, `host.force_off`, `vm.status`, `vm.start`, `vm.shutdown`, `vm.restart`, `vm.force_stop`. 
    Für Services sind später `service.status`, `service.start`, `service.shutdown`, `service.restart`, `service.force_stop` vorgesehen.

### Operationen auf Scheduled Actions
Was ein User mit einer Action darf, heißt in Permissions, API und Discord-Buttons gleich:

| Operation     | Permission-Spalte | Bedeutung 
|               |                   |
| `request`     | `can_request`     | Action anfordern 
| `postpone`    | `can_postpone`    | Geplante Ausführung nach hinten schieben 
| `cancel`      | `can_cancel`      | Geplante Ausführung abbrechen 
| `execute_now` | `can_execute_now` | Geplante Ausführung sofort auslösen 

## Events
Ein Event heißt `<objekt>.<partizip>`, also immer in der Vergangenheitsform, weil es etwas beschreibt, das bereits passiert ist. Statusänderungen von Ressourcen laufen ausschließlich über `resource.status_changed`; es gibt also kein zusätzliches `host.started` oder `vm.stopped`. Neue Event-Typen werden hier eingetragen, bevor sie im Code auftauchen.

| Event                         | Wann 
|                               |
| `resource.status_changed`     | Status einer Ressource ändert sich (setzt die Datenbank automatisch)
| `component.registered`        | Komponente meldet sich zum ersten Mal an
| `component.status_changed`    | Komponente wird `RUNNING`, `DEAD` usw.
| `command.created`             | Command wurde angelegt
| `command.started`             | Command geht auf `running`
| `command.completed`           | Command erfolgreich beendet
| `command.failed`              | Command fehlgeschlagen
| `command.cancelled`           | Command vor der Ausführung abgebrochen
| `scheduled_action.created`    | Scheduled Action geplant
| `scheduled_action.announced`  | Ankündigung in Discord gepostet
| `scheduled_action.postponed`  | Aufgeschoben
| `scheduled_action.cancelled`  | Abgebrochen, durch User oder neuen Use-Case
| `scheduled_action.executed`   | Fällig geworden und als Command angelegt
| `use_case.started`            | Neue Nutzung erkannt
| `use_case.ended`              | Nutzung beendet oder nicht mehr gemeldet

## Weitere Vokabulare

**Use-Case-Arten** (`use_cases.kind`): 
    `ssh_session`
    `minecraft_player` (Weitere Service-spezifische Arten heißen `<service_type>_<was>`)
**Gründe für Scheduled Actions** (`scheduled_actions.reason`): 
    `auto_shutdown_idle` für den automatischen Shutdown bei Leerlauf
    `user_request` für von Usern geplante Aktionen
**Abbruchgründe** (`scheduled_actions.cancel_reason`): 
    `user` (von einem User abgebrochen) 
    `use_case_detected` (neue Nutzung erkannt)
    `superseded` (durch eine andere Planung ersetzt)
**Quellen von Commands** (`commands.source`):
    `discord`
    `dashboard`
    `system`
    `api`.
**NOTIFY-Kanäle:** 
    `commands`
    `events`.
**Settings-Keys:** 
    `timezone`
    `idle_shutdown_after_minutes`
    `shutdown_announce_minutes`
    `default_postpone_minutes`
    `use_case_stale_seconds`
    `discord_guild_id`
    `discord_announce_channel_id`
    
    Zeitangaben tragen ihre Einheit im Namen (`_seconds`, `_minutes`, `_ms`), IDs enden auf `_id`.

## Repositories
Ein Repo pro Installationsort: Auf jeder Maschine wird nur geklont, was dort läuft.

| Repo              | Inhalt                                                                                                        | Installiert auf
|                   |                                                                                                               |       
| `hs-core`         | API, Discord Bot, Power Controller, später Dashboard, dazu `migrations/` und diese Nomenklatur unter `docs/`  | Pi
| `hs-host-agent`   | Host Agent                                                                                                    | Proxmox-Host
| `hs-vm-agent`     | VM Agent                                                                                                      | jede VM
| `hs-sm-minecraft` | Service Manager Minecraft                                                                                     | Minecraft-VM

Alle Repos haben denselben Aufbau: Python-Paket im Ordner mit Paketnamen, eine `requirements.txt`, die systemd-Unit unter `deploy/`, und eine `README.md` mit den Installationsschritten. Installiert wird jeweils nach `/opt/<repo>` mit eigenem venv.

Ein gemeinsames Bibliotheks-Repo gibt es vorerst nicht. Die Komponenten verbinden sich nur über die API, und die paar gemeinsamen Werte (Status, Action-Keys) stehen in diesem Dokument. Wird die Duplizierung später lästig, kommt ein `hs-common` dazu, das per `pip install git+…` eingebunden wird.
