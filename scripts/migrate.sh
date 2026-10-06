#!/usr/bin/env bash
# Spielt eine Migration aus migrations/ in die lokale Datenbank ein. Läuft auf dem Pi.
#
#   scripts/migrate.sh                 -> Auswahlmenü
#   scripts/migrate.sh 004_xyz.sql     -> direkt diese Datei
#
# Voraussetzung: ~/.pgpass des aufrufenden Benutzers enthält das Passwort von hs_owner.
set -euo pipefail

PSQL=(psql -X -q -h localhost -U hs_owner -d homeserver -v ON_ERROR_STOP=1)
MIGRATIONS_DIR="$(cd "$(dirname "$0")/../migrations" && pwd)"

# Verfügbare Migrationen sammeln
files=()
for f in "$MIGRATIONS_DIR"/*.sql; do
    [[ -e "$f" ]] && files+=("$(basename "$f")")
done
if [[ ${#files[@]} -eq 0 ]]; then
    echo "Keine .sql-Dateien in $MIGRATIONS_DIR gefunden." >&2
    exit 1
fi

# Bereits eingespielte Migrationen (leer, solange es die Tabelle nicht gibt)
applied="$("${PSQL[@]}" -At -c 'SELECT filename FROM schema_migrations' 2>/dev/null || true)"

is_applied() { grep -qxF "$1" <<<"$applied"; }

if [[ $# -ge 1 ]]; then
    file="$(basename "$1")"
    if [[ ! -f "$MIGRATIONS_DIR/$file" ]]; then
        echo "Datei $file gibt es in $MIGRATIONS_DIR nicht." >&2
        exit 1
    fi
else
    echo "Migrationen:"
    i=1
    for f in "${files[@]}"; do
        if is_applied "$f"; then mark="eingespielt"; else mark="OFFEN"; fi
        printf '  %2d) %-40s %s\n' "$i" "$f" "$mark"
        i=$((i + 1))
    done
    echo
    read -rp "Nummer wählen (Enter = abbrechen): " choice
    if [[ -z "$choice" ]]; then
        exit 0
    fi
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#files[@]} )); then
        echo "Ungültige Auswahl." >&2
        exit 1
    fi
    file="${files[$((choice - 1))]}"
fi

if is_applied "$file"; then
    echo "Achtung: $file ist laut schema_migrations bereits eingespielt."
fi
if ! grep -q "schema_migrations" "$MIGRATIONS_DIR/$file"; then
    echo "Hinweis: $file trägt sich nicht selbst in schema_migrations ein."
fi

read -rp "$file einspielen? [j/N] " ok
if ! [[ "$ok" =~ ^[jJyY]$ ]]; then
    echo "Abgebrochen."
    exit 0
fi

if "${PSQL[@]}" -f "$MIGRATIONS_DIR/$file"; then
    echo "Fertig: $file eingespielt."
else
    echo "FEHLER: $file wurde nicht eingespielt (es wurde nichts verändert, sofern die Datei in BEGIN/COMMIT steht)." >&2
    exit 1
fi