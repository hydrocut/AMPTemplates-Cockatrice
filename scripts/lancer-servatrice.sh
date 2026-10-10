#!/bin/bash
# lancer-servatrice.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Arguments : <port du jeu> <port WebSocket>
#
# 1. ecrit servatrice.ini a partir des reglages d'AMP (ecrire_config.py) ;
# 2. en mode comptes :
#    - base integree : lance une MariaDB privee a l'instance (dossier base/, socket
#      Unix hors du dossier, aucun port reseau) et la sauvegarde en .sql.gz ;
#    - base integree ou externe : cree les tables si la base est vide, passe les
#      migrations si Servatrice a change de schema, applique administrateurs et
#      moderateurs choisis dans AMP, puis commande.sql s'il existe ;
# 3. lance Servatrice, journal dans la console d'AMP ;
# 4. a l'arret demande par AMP (SIGTERM) : arrete Servatrice, sauvegarde et arrete
#    la base integree, rend le code 0.
cd "$(dirname "$0")" || exit 1
PORT="${1:-4747}"
PORT_WS="${2:-4748}"
ICI="$PWD"
BIN="$ICI/servatrice/usr/bin/servatrice"
SQL="$ICI/servatrice/usr/share/servatrice/servatrice.sql"
PILOTE=/usr/lib/x86_64-linux-gnu/qt6/plugins/sqldrivers/libqsqlmysql.so
# Fichiers de passage (identifiants compris) : hors du dossier de l'instance, que les
# sauvegardes d'AMP copient ; droits 600 ; effaces des que la base est prete.
RUN="${XDG_RUNTIME_DIR:-/tmp}"
PREFIXE="$RUN/servatrice-$PORT"
DONNEES="$ICI/base"
SOCKET="$PREFIXE-db.sock"
SAUVEGARDE="$ICI/sauvegarde-base.sql.gz"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

if [ ! -x "$BIN" ]; then
  echo "ERREUR : $BIN absent. Lance Update : il telecharge Servatrice depuis GitHub (Cockatrice/Cockatrice)."
  exit 1
fi

python3 -I "$ICI/ecrire_config.py" reglages-amp.txt servatrice.ini "$PORT" "$PORT_WS" "$PREFIXE" || exit 1
BASE=$(cat "$PREFIXE.base" 2>/dev/null)
CNF="$PREFIXE.cnf"
PID_DB=""
M=(mariadb --defaults-extra-file="$CNF" --connect-timeout=10 -N -B)

nettoyer() { rm -f "$CNF" "$PREFIXE.roles.sql"; }

arreter_base() {
  [ -n "$PID_DB" ] || return 0
  if kill -0 "$PID_DB" 2>/dev/null; then
    kill -TERM "$PID_DB" 2>/dev/null
    for _ in $(seq 1 60); do kill -0 "$PID_DB" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$PID_DB" 2>/dev/null && kill -KILL "$PID_DB" 2>/dev/null
    wait "$PID_DB" 2>/dev/null
    echo "TeamKit : base integree arretee."
  fi
  PID_DB=""
}

base_erreur() {
  echo "ERREUR (base MariaDB) : $1"
  nettoyer
  arreter_base
  exit 1
}

sauvegarder() {
  # Copie coherente de la base integree (les fichiers de base/ copies a chaud par une
  # sauvegarde AMP peuvent etre incoherents ; ce .sql.gz, lui, ne l'est jamais).
  [ "$BASE" = integree ] || return 0
  if mariadb-dump --defaults-extra-file="$CNF" --single-transaction --routines servatrice 2>"$PREFIXE.dump.err" \
      | gzip -c > "$SAUVEGARDE.tmp" && [ -s "$SAUVEGARDE.tmp" ] && ! [ -s "$PREFIXE.dump.err" ]; then
    mv -f "$SAUVEGARDE.tmp" "$SAUVEGARDE"
    echo "TeamKit : base sauvegardee dans sauvegarde-base.sql.gz ($1)."
  else
    rm -f "$SAUVEGARDE.tmp"
    echo "TeamKit : ATTENTION, sauvegarde de la base ratee : $(head -c 300 "$PREFIXE.dump.err")"
  fi
  rm -f "$PREFIXE.dump.err"
}

demarrer_base_integree() {
  command -v mariadbd >/dev/null || base_erreur "mariadbd absent (paquet mariadb-server-core). L'instance doit tourner en conteneur ; recree le conteneur si le template a change."
  local opts=(--no-defaults --datadir="$DONNEES" --socket="$SOCKET" --skip-networking
    --pid-file="$PREFIXE-db.pid" --log-error="$DONNEES/erreurs-mariadb.log"
    --sql-mode=NO_ENGINE_SUBSTITUTION --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    --innodb-buffer-pool-size=16M --innodb-log-file-size=8M --innodb-log-buffer-size=2M
    --key-buffer-size=1M --aria-pagecache-buffer-size=1M --table-open-cache=200 --thread-cache-size=4
    --max-connections=30 --performance-schema=OFF --skip-log-bin)
  # Une base restee ouverte (lanceur tue net) : on la ferme avant d'en relancer une.
  if [ -f "$PREFIXE-db.pid" ]; then
    local ancien
    ancien=$(cat "$PREFIXE-db.pid" 2>/dev/null)
    if [ -n "$ancien" ] && kill -0 "$ancien" 2>/dev/null && grep -q mariadbd "/proc/$ancien/cmdline" 2>/dev/null; then
      echo "TeamKit : une ancienne base integree tourne encore (pid $ancien), on l'arrete."
      kill -TERM "$ancien"
      for _ in $(seq 1 60); do kill -0 "$ancien" 2>/dev/null || break; sleep 0.5; done
    fi
  fi
  if [ ! -d "$DONNEES/mysql" ]; then
    echo "TeamKit : premiere fois en mode comptes, creation de la base integree (dossier base/)..."
    mkdir -p "$DONNEES"
    mariadb-install-db --no-defaults --datadir="$DONNEES" --auth-root-authentication-method=normal \
      --skip-test-db --innodb-log-file-size=8M > "$DONNEES/installation.log" 2>&1 \
      || base_erreur "mariadb-install-db a echoue, voir base/installation.log."
  fi
  setpriv --pdeathsig TERM -- mariadbd "${opts[@]}" &
  PID_DB=$!
  for _ in $(seq 1 120); do
    kill -0 "$PID_DB" 2>/dev/null || base_erreur "MariaDB s'est arretee au demarrage, voir base/erreurs-mariadb.log."
    mariadb --defaults-extra-file="$CNF" -e 'SELECT 1' >/dev/null 2>&1 && break
    sleep 0.25
  done
  mariadb --defaults-extra-file="$CNF" -e "CREATE DATABASE IF NOT EXISTS servatrice CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" \
    || base_erreur "la base integree ne repond pas, voir base/erreurs-mariadb.log."
  M=(mariadb --defaults-extra-file="$CNF" --database=servatrice --connect-timeout=10 -N -B)
  echo "TeamKit : base integree demarree (MariaDB $(mariadb --defaults-extra-file="$CNF" -N -e 'SELECT VERSION()' | cut -d- -f1), socket prive, aucun port ouvert)."
}

preparer_base() {
  [ -f "$PILOTE" ] || base_erreur "pilote MySQL de Qt absent ($PILOTE, paquet libqt6sql6-mysql). L'instance doit tourner en conteneur ; recree le conteneur si le template a change."
  command -v mariadb >/dev/null || base_erreur "client mariadb absent (paquet mariadb-client)."
  [ -f "$SQL" ] || base_erreur "$SQL absent : relance Update."
  local attendu version sortie n mode
  attendu=$(grep -a -o -m1 'INSERT INTO cockatrice_schema_version VALUES *( *[0-9]*' "$SQL" | grep -o '[0-9]*$')
  [ -n "$attendu" ] || base_erreur "version du schema introuvable dans servatrice.sql."
  if [ "$BASE" = externe ]; then
    mode=$("${M[@]}" -e 'SELECT @@GLOBAL.sql_mode' 2>&1) || base_erreur "connexion impossible. Message de MariaDB : $mode"
    case ",$mode," in
      *,STRICT_TRANS_TABLES,*|*,STRICT_ALL_TABLES,*)
        base_erreur "le serveur MariaDB est en mode strict (sql_mode global : $mode). Servatrice refuse de s'en servir. Il faut retirer STRICT_TRANS_TABLES et STRICT_ALL_TABLES du sql_mode GLOBAL de ce serveur (cela touche toutes ses bases), ou choisir la base integree." ;;
    esac
  fi
  if ! sortie=$("${M[@]}" -e 'SELECT version FROM cockatrice_schema_version' 2>&1); then
    case "$sortie" in
      *"ERROR 1146"*)
        n=$("${M[@]}" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name LIKE 'cockatrice\\_%'" 2>&1) \
          || base_erreur "$n"
        [ "$n" = 0 ] || base_erreur "la base contient deja $n table(s) cockatrice_ mais pas cockatrice_schema_version : a verifier a la main, le lanceur n'y touche pas."
        echo "TeamKit : base vide, creation des tables de Servatrice (servatrice.sql, schema $attendu)..."
        # servatrice.sql commence par un BOM UTF-8 : on le retire.
        sed '1s/^\xEF\xBB\xBF//' "$SQL" | "${M[@]}" 2>&1 || base_erreur "creation des tables refusee (l'utilisateur doit avoir tous les droits sur la base)."
        version=$("${M[@]}" -e 'SELECT version FROM cockatrice_schema_version' 2>&1) || base_erreur "$version"
        ;;
      *) base_erreur "connexion impossible. Message de MariaDB : $sortie" ;;
    esac
  else
    version="$sortie"
  fi
  [[ "$version" =~ ^[0-9]+$ ]] || base_erreur "version du schema illisible : '$version'."
  if [ "$version" -gt "$attendu" ]; then
    base_erreur "la base est au schema $version, plus recent que celui de ce Servatrice ($attendu). Remets la version de Servatrice qui l'a cree (reglage Version de Servatrice)."
  fi
  if [ "$version" -lt "$attendu" ]; then
    local tag v fichier url
    tag=$(cut -f1 "$ICI/servatrice/VERSION-TEAMKIT" 2>/dev/null)
    [ -n "$tag" ] || base_erreur "version de Servatrice inconnue (servatrice/VERSION-TEAMKIT) : relance Update."
    sauvegarder "avant migration"
    echo "TeamKit : schema de la base $version, Servatrice $tag attend $attendu : migrations."
    for ((v = version; v < attendu; v++)); do
      fichier=$(printf 'servatrice_%04d_to_%04d.sql' "$v" "$((v + 1))")
      url="https://raw.githubusercontent.com/Cockatrice/Cockatrice/$tag/servatrice/migrations/$fichier"
      sortie=$(curl -fsSL --max-time 60 "$url") || base_erreur "migration $fichier introuvable ($url)."
      printf '%s\n' "$sortie" | sed '1s/^\xEF\xBB\xBF//' | "${M[@]}" 2>&1 || base_erreur "migration $fichier refusee par MariaDB."
      echo "TeamKit : migration $fichier passee."
    done
  else
    echo "TeamKit : base MariaDB prete (schema $version)."
  fi
  # Administrateurs et moderateurs choisis dans AMP (les comptes doivent exister :
  # le joueur s'inscrit d'abord depuis le jeu).
  if [ -f "$PREFIXE.roles.sql" ]; then
    "${M[@]}" < "$PREFIXE.roles.sql" 2>&1 || base_erreur "mise a jour des administrateurs et moderateurs refusee."
    sortie=$("${M[@]}" -e "SELECT CONCAT(name, IF(admin & 1, ' (administrateur)', ' (moderateur)')) FROM cockatrice_users WHERE admin & 3 ORDER BY name" 2>&1)
    echo "TeamKit : staff du serveur : $(printf '%s' "${sortie:-personne}" | tr '\n' ',' | sed 's/,$//; s/,/, /g')."
  fi
  # commande.sql (depose avec le gestionnaire de fichiers d'AMP) : passe une fois, puis renomme.
  if [ -f "$ICI/commande.sql" ]; then
    local fait
    fait="$ICI/commande.sql.fait-$(date +%Y%m%d-%H%M%S)"
    echo "TeamKit : commande.sql trouve, execution :"
    if "${M[@]}" -t < "$ICI/commande.sql" > "$fait.resultat" 2>&1; then
      cat "$fait.resultat"
      echo "TeamKit : commande.sql passe, renomme en $(basename "$fait")."
    else
      cat "$fait.resultat"
      echo "TeamKit : ATTENTION, commande.sql a echoue (voir ci-dessus), renomme quand meme en $(basename "$fait")."
    fi
    mv -f "$ICI/commande.sql" "$fait"
  fi
  return 0
}

if [ -n "$BASE" ]; then
  [ "$BASE" = integree ] && demarrer_base_integree
  preparer_base
  sauvegarder "au demarrage"
  rm -f "$PREFIXE.roles.sql"
  [ "$BASE" = externe ] && rm -f "$CNF"
fi

# --pdeathsig : si ce script est tue net (SIGKILL), Servatrice recoit SIGTERM au lieu
# de rester orphelin sur le port. --log-to-console : journal dans la console d'AMP.
# MYSQL_UNIX_PORT : socket de la base integree (Servatrice s'y connecte en localhost).
MYSQL_UNIX_PORT="$SOCKET" setpriv --pdeathsig TERM -- "$BIN" --config "$ICI/servatrice.ini" --log-to-console &
PID=$!

# Base integree : une sauvegarde par heure tant que le serveur tourne.
if [ "$BASE" = integree ]; then
  (
    # Verifie chaque minute que Servatrice et ce lanceur tournent encore : la boucle ne
    # survit pas a un lanceur tue net.
    LANCEUR=$$
    trap 'kill $! 2>/dev/null; exit 0' TERM
    minutes=0
    while :; do
      sleep 60 &
      wait $!
      kill -0 "$PID" 2>/dev/null && kill -0 "$LANCEUR" 2>/dev/null || exit 0
      minutes=$((minutes + 1))
      if [ "$minutes" -ge 60 ]; then
        minutes=0
        sauvegarder "sauvegarde horaire"
      fi
    done
  ) &
  HORAIRE=$!
fi

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, fermeture de Servatrice."
  kill -TERM "$PID" 2>/dev/null
}
trap arreter TERM INT

# Le SIGTERM d'AMP interrompt ce "wait" : on attend une seconde fois la fin de Servatrice.
wait "$PID"
CODE=$?
[ "$ARRET" = 1 ] && wait "$PID" 2>/dev/null
[ -n "$HORAIRE" ] && kill "$HORAIRE" 2>/dev/null
if [ "$BASE" = integree ]; then
  sauvegarder "a l'arret"
  arreter_base
fi
nettoyer
if [ "$ARRET" = 1 ]; then
  echo "TeamKit : Servatrice arrete."
  exit 0
fi
if [ "$CODE" != 0 ]; then
  echo "TeamKit : Servatrice s'est arrete (code $CODE). Port deja pris, base injoignable ou reglage de perso.ini : voir les lignes au-dessus."
fi
exit "$CODE"
