#!/bin/bash
# installer-servatrice.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Argument : version voulue (vide ou "derniere" = la derniere version stable).
#
# Servatrice n'est pas dans les depots Debian. Cockatrice publie a chaque version
# stable un paquet .deb du serveur seul (Servatrice_Debian12). Il ne s'installe pas
# avec apt sur Debian 13 (il exige qt6-websockets-abi = 6.4.2, Debian 13 a Qt 6.8,
# et des paquets du client graphique), mais le programme lui-meme tourne avec les
# bibliotheques Qt 6 de Debian 13 (il n'utilise que les symboles Qt_6.4 publics ;
# essai du 10/10/2026). On EXTRAIT donc le paquet (dpkg-deb -x) dans servatrice/,
# sans root ; les bibliotheques viennent de Meta.ExtraContainerPackages.
cd "$(dirname "$0")" || exit 1
DEMANDE=$(printf '%s' "${1:-}" | tr -d '[:space:]')
API=https://api.github.com/repos/Cockatrice/Cockatrice
DOSSIER=servatrice
BIN="$DOSSIER/usr/bin/servatrice"
FICHE="$DOSSIER/VERSION-TEAMKIT"
# Paquet du serveur seul ; Debian13 prefere s'il apparait un jour.
MOTIF='-Servatrice_Debian1[23][.]deb$'

verifier() {
  if [ ! -x "$BIN" ]; then
    echo "ERREUR : $BIN absent."
    return 1
  fi
  local manque
  manque=$(ldd "$BIN" 2>/dev/null | grep "not found")
  if [ -n "$manque" ]; then
    echo "ERREUR : bibliotheques manquantes pour servatrice :"
    echo "$manque"
    echo "Cette instance doit tourner en conteneur : les bibliotheques Qt 6 sont installees par"
    echo "ExtraContainerPackages a la creation du conteneur (recree-le si le template a change)."
    return 1
  fi
  echo "Bibliotheques de servatrice : toutes presentes."
  if [ -f /usr/lib/x86_64-linux-gnu/qt6/plugins/sqldrivers/libqsqlmysql.so ]; then
    echo "Pilote MySQL/MariaDB de Qt : present (necessaire seulement en mode comptes)."
  else
    echo "Pilote MySQL/MariaDB de Qt : ABSENT (paquet libqt6sql6-mysql) - le mode comptes ne marchera pas."
  fi
  echo "Installe : $(cut -f1,2 "$FICHE" 2>/dev/null)"
  return 0
}

# garder <message> [echec] : on garde la version installee s'il y en a une. Avec
# "echec" (version demandee introuvable), l'Update echoue quand meme pour que ca se voie.
garder() {
  echo "$1"
  if [ -x "$BIN" ]; then
    echo "TeamKit : on garde la version deja installee."
    verifier || exit 1
    [ "$2" = echec ] && exit 1
    exit 0
  fi
  exit 1
}

if [ -z "$DEMANDE" ] || [ "$DEMANDE" = "derniere" ]; then
  echo "Recherche de la derniere version stable de Servatrice sur GitHub..."
  JSON=$(curl -fsSL --max-time 60 -H 'Accept: application/vnd.github+json' "$API/releases?per_page=30") \
    || garder "ERREUR : liste des versions de Cockatrice injoignable (GitHub limite a 60 demandes par heure et par adresse IP)."
  CHOIX=$(jq -r --arg m "$MOTIF" '
    [ .[] | select((.draft | not) and (.prerelease | not))
      | {tag: .tag_name, a: ([.assets[] | select(.name | test($m))] | sort_by(.name) | reverse | .[0])}
      | select(.a != null) ][0]
    | if . == null then empty else "\(.tag)\t\(.a.name)\t\(.a.browser_download_url)\t\(.a.size)\t\(.a.digest // "")" end' <<<"$JSON")
else
  echo "Version demandee : $DEMANDE"
  JSON=$(curl -fsSL --max-time 60 -H 'Accept: application/vnd.github+json' "$API/releases/tags/$DEMANDE") \
    || garder "ERREUR : version '$DEMANDE' introuvable sur GitHub (le reglage attend le nom exact de la version, ex. 2026-10-10-Release-3.1.1)." echec
  CHOIX=$(jq -r --arg m "$MOTIF" '
    {tag: .tag_name, a: ([.assets[] | select(.name | test($m))] | sort_by(.name) | reverse | .[0])}
    | select(.a != null) | "\(.tag)\t\(.a.name)\t\(.a.browser_download_url)\t\(.a.size)\t\(.a.digest // "")"' <<<"$JSON")
fi
if [ -z "$CHOIX" ]; then
  if [ -n "$DEMANDE" ] && [ "$DEMANDE" != "derniere" ]; then
    garder "ERREUR : la version $DEMANDE n'a pas de paquet Servatrice_Debian (.deb du serveur seul) : choisis-en une autre ou laisse le reglage vide." echec
  fi
  garder "ERREUR : aucune version stable recente n'a de paquet Servatrice_Debian (.deb du serveur seul)."
fi

IFS=$'\t' read -r TAG NOM URL TAILLE EMPREINTE <<<"$CHOIX"
echo "Version retenue : $TAG ($NOM, $TAILLE octets)"
if [ -x "$BIN" ] && [ "$(cut -f1 "$FICHE" 2>/dev/null)" = "$TAG" ] && [ "$(cut -f2 "$FICHE" 2>/dev/null)" = "$NOM" ]; then
  echo "TeamKit : Servatrice est deja a cette version."
  verifier
  exit $?
fi

TMP=".servatrice-telechargement"
rm -rf "$TMP" && mkdir -p "$TMP" || exit 1
if ! curl -fsSL --max-time 300 -o "$TMP/paquet.deb" "$URL"; then
  rm -rf "$TMP"
  garder "ERREUR : telechargement de $URL impossible."
fi
if [ "$(stat -c %s "$TMP/paquet.deb")" != "$TAILLE" ]; then
  rm -rf "$TMP"
  garder "ERREUR : taille du paquet inattendue (telechargement incomplet ?)."
fi
case "$EMPREINTE" in
  sha256:*)
    if [ "$(sha256sum "$TMP/paquet.deb" | cut -d' ' -f1)" != "${EMPREINTE#sha256:}" ]; then
      rm -rf "$TMP"
      garder "ERREUR : empreinte SHA-256 du paquet differente de celle annoncee par GitHub."
    fi
    echo "Empreinte SHA-256 du paquet : conforme a celle de GitHub."
    ;;
esac
if ! dpkg-deb -x "$TMP/paquet.deb" "$TMP/extrait" || [ ! -x "$TMP/extrait/usr/bin/servatrice" ]; then
  rm -rf "$TMP"
  garder "ERREUR : paquet illisible ou sans usr/bin/servatrice."
fi
printf '%s\t%s\t%s\n' "$TAG" "$NOM" "$URL" > "$TMP/extrait/VERSION-TEAMKIT"
rm -rf "$DOSSIER.ancien"
[ -d "$DOSSIER" ] && mv "$DOSSIER" "$DOSSIER.ancien"
mv "$TMP/extrait" "$DOSSIER" && rm -rf "$TMP" "$DOSSIER.ancien"
echo "TeamKit : Servatrice $TAG installe dans $DOSSIER/."
verifier
