# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de Wesnoth, Dominions 6, Unciv).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp : fichiers inclus, Ref des ports passés au lanceur, bloc Console.* / Limits.*
   complet, conteneur obligatoire et paquets attendus, arrêt par SIGTERM ;
3. chaque réglage exposé dans AMP arrive dans le modèle scripts/AMP_reglages.txt (ou dans
   l'Update pour la version), chaque {{...}} a son réglage, chaque clé du modèle est lue par
   ecrire_config.py, les choix proposés sont ceux qu'il accepte ;
4. aller-retour : modèle rendu comme AMP (remplacement brut) -> le vrai ecrire_config.py ->
   servatrice.ini relu comme QSettings (format INI de Qt) : valeur vide, espaces, accents,
   virgules, guillemets, antislash, @ en tête... doivent revenir identiques ; idem pour le
   fichier d'options du client mariadb et la liste du staff ; les réglages impossibles
   doivent être refusés avec un message ;
5. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest ;
6. les scripts : LF, ASCII, sans {{, `bash -n`, et les points qui ont coûté un essai ;
7. les regex de console sur de vraies lignes de Servatrice 3.1.1 (relevées le 10 oct. 2026
   dans un conteneur jetable cubecoders/ampbase:debian) et pas sur les autres.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'cockatrice'
MODELE = 'scripts/AMP_reglages.txt'
GENERATEUR = 'scripts/ecrire_config.py'
LANCEUR = 'scripts/lancer-servatrice.sh'
INSTALLEUR = 'scripts/installer-servatrice.sh'
soucis = []


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def ok(quoi, detail):
    print('ok   %-26s %s' % (quoi, detail))


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        ok(nom, 'JSON valide')
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref']: p for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond à aucun port')
cmd = cles.get('App.CommandLineArgs', '')
if cmd != '"{{$FullBaseDir}}lancer-servatrice.sh" {{$ServerPort}} {{$WebSocketPort}}':
    soucis.append('ligne de commande inattendue : %s' % cmd)
for r in re.findall(r'\{\{\$(\w+)\}\}', cmd):
    if r not in refs and r != 'FullBaseDir':
        soucis.append('{{$%s}} : aucun port ne porte ce Ref' % r)
if any(p['Protocol'] != 'TCP' for p in ports) or refs.get('ServerPort', {}).get('Port') != 4747 \
        or refs.get('WebSocketPort', {}).get('Port') != 4748:
    soucis.append('ports attendus : ServerPort 4747/TCP (défaut du jeu) et WebSocketPort 4748/TCP')
ok('ports', ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex',
             'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex',
             'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex',
             'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex',
             'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart',
             'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    ok('kvp complet', 'les %d clés Console/Limits sont là' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') == 'RegexMatch' and not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch sans AppReadyRegex : l’instance ne serait jamais déclarée prête')
ATTENDU_KVP = {
    'App.ExitMethod': 'SIGTERM',              # le lanceur arrête Servatrice puis la base intégrée
    'App.ExecutableLinux': '/bin/bash',
    'App.HasWriteableConsole': 'False',       # Servatrice ne lit pas son entrée standard
    'Meta.ContainerPolicy': 'Required',
    'Meta.DockerRequired': 'True',
    'Meta.SpecificDockerImage': 'cubecoders/ampbase:debian',
    'App.RootDir': './cockatrice/',
    'App.BaseDirectory': './cockatrice/',
}
for cle, val in ATTENDU_KVP.items():
    if cles.get(cle) != val:
        soucis.append('%s devrait valoir %s (vaut %r)' % (cle, val, cles.get(cle)))
if cles.get('Meta.URL') != data['manifest.json']['url']:
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')
# Relevés le 10/10/2026 : ldd de servatrice 3.1.1 (Qt 6 + protobuf), pilote QMYSQL, client
# mariadb (+ mariadb-dump), serveur mariadbd + mariadb-install-db. Un seul nom faux et
# l'image AMP n'installe RIEN (un seul apt-get install pour toute la liste).
PAQUETS = ['libqt6core6t64', 'libqt6network6', 'libqt6sql6', 'libqt6websockets6', 'libprotobuf32t64',
           'libqt6sql6-mysql', 'mariadb-client', 'mariadb-server-core']
if json.loads(cles.get('Meta.ExtraContainerPackages', '[]')) != PAQUETS:
    soucis.append('ExtraContainerPackages : attendu %s' % PAQUETS)
else:
    ok('paquets du conteneur', '%d paquets Debian 13 vérifiés' % len(PAQUETS))
try:
    if int(cles.get('App.MaxUsers', '0')) != int([c for c in config if c['FieldName'] == '$MaxUsers'][0]['DefaultValue']):
        soucis.append('App.MaxUsers doit valoir le défaut du réglage $MaxUsers')
except (IndexError, ValueError):
    soucis.append('réglage $MaxUsers absent')

# ── 3. réglages <-> modèle <-> générateur ────────────────────────────────────
modele = lire(MODELE)
generateur = lire(GENERATEUR)
dans_modele = re.findall(r'\{\{([A-Za-z0-9_]+)\}\}', modele)
dans_update = set(re.findall(r'\{\{([A-Za-z]\w*)\}\}', json.dumps(updates)))
params = {}
for c in config:
    p = c['ParamFieldName']
    if p in params:
        soucis.append('réglage en double : %s' % p)
    params[p] = c
    if c['FieldName'] != p and not (c['FieldName'] == '$MaxUsers' and p == 'max_joueurs'):
        soucis.append('%s : FieldName et ParamFieldName différents (%s)' % (p, c['FieldName']))
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit être false (tout passe par le modèle)' % p)
    if p in dans_update:
        continue
    if dans_modele.count(p) != 1:
        soucis.append('réglage %s : attendu une fois dans %s (%d)' % (p, MODELE, dans_modele.count(p)))
    elif not re.search(r'^%s=\{\{%s\}\}$' % (p, p), modele, re.M):
        soucis.append('%s doit s’écrire %s={{%s}} seul sur sa ligne' % (p, p, p))
    if not re.search(r"""(?:v\.get\(|v\[|entier\(v, )'%s'""" % p, generateur):
        soucis.append('%s : jamais lu par ecrire_config.py' % p)
    ev, d = c.get('EnumValues') or {}, c.get('DefaultValue')
    if c['InputType'] == 'enum' and d not in ev:
        soucis.append('%s : DefaultValue %r absente de la liste' % (p, d))
    if c['InputType'] == 'checkbox' and (d not in ev.values() or set(ev.values()) != {'oui', 'non'}):
        soucis.append('%s : la case doit donner oui/non, défaut compris' % p)
    if c['InputType'] == 'number' and not re.fullmatch(r'-?\d+', str(d)):
        soucis.append('%s : valeur par défaut non numérique' % p)
orphelins = (set(dans_modele) | dans_update) - set(params)
if orphelins:
    soucis.append('{{...}} sans réglage dans AMP : %s' % ', '.join(sorted(orphelins)))
if 'version_servatrice' not in dans_update:
    soucis.append('le réglage version_servatrice doit être passé à l’étape d’installation')
for champ, constante in (('comptes', 'MODES'), ('base_comptes', 'BASES')):
    m = re.search(r'^%s = \(([^)]*)\)' % constante, generateur, re.M)
    acceptes = set(re.findall(r"'(\w+)'", m.group(1))) if m else set()
    if set(params[champ]['EnumValues']) != acceptes:
        soucis.append('%s : AMP propose %s, ecrire_config.py accepte %s' % (champ, sorted(params[champ]['EnumValues']), sorted(acceptes)))
meta = data[NOM + 'metaconfig.json']
if meta != [{'ConfigFile': 'reglages-amp.txt', 'ConfigType': 'template', 'AutoMap': True,
             'ConfigFileTemplate': 'cockatrice/AMP_reglages.txt'}]:
    soucis.append('metaconfig : attendu reglages-amp.txt rendu depuis cockatrice/AMP_reglages.txt')
if 'reglages-amp.txt servatrice.ini' not in lire(LANCEUR):
    soucis.append('le lanceur ne passe pas reglages-amp.txt (rendu par AMP) à ecrire_config.py')
accueil = params['message_accueil']['DefaultValue']
if 'TeamKit.fr' not in accueil or 'discord.gg/EuAjGMYPHY' not in accueil:
    soucis.append('le message d’accueil par défaut doit citer TeamKit.fr et le Discord')
if not soucis:
    ok('réglages', '%d réglages : modèle, générateur et Update d’accord' % len(params))


# ── 4. aller-retour AMP -> ecrire_config.py -> lecture QSettings ─────────────
def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


def qsettings(texte_ini):
    """Lecteur minimal du format INI de Qt 6 (QSettingsPrivate::iniUnescapedStringList) :
    texte entre guillemets avec \\ \" \\n..., virgule hors guillemets = liste, ; = commentaire,
    une clé répétée plus bas l'emporte, @@ en tête = @."""
    res, section = {}, ''
    for ligne in texte_ini.splitlines():
        s = ligne.strip()
        if not s or s[0] in ';#':
            continue
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1]
            continue
        cle, brut = s.split('=', 1)
        cle = (section + '/' if section != 'General' else '') + cle.strip().replace('\\', '/')
        morceaux, cur, dans, i, quote_vu = [], '', False, 0, False
        while i < len(brut):
            ch = brut[i]
            if dans:
                if ch == '"':
                    dans = False
                elif ch == '\\' and i + 1 < len(brut):
                    i += 1
                    cur += {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', "'": "'", '?': '?',
                            'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v'}.get(brut[i], brut[i])
                else:
                    cur += ch
            elif ch == '"':
                dans, quote_vu = True, True
            elif ch == ',':
                morceaux.append(cur.strip() if not quote_vu else cur)
                cur, quote_vu = '', False
            elif ch == ';':
                break
            else:
                cur += ch
            i += 1
        morceaux.append(cur if quote_vu else cur.strip())
        val = morceaux if len(morceaux) > 1 else morceaux[0]
        if isinstance(val, str) and val.startswith('@@'):
            val = val[1:]
        res[cle] = val
    return res


def option_mariadb_lue(brut):
    # Lecture d'une valeur du fichier d'options mariadb entre guillemets (\\ et \").
    assert brut.startswith('"') and brut.endswith('"'), brut
    return re.sub(r'\\(.)', r'\1', brut[1:-1])


defauts = {c['ParamFieldName']: str(c.get('DefaultValue', '')) for c in config}
dossier = tempfile.mkdtemp(prefix='verif-cockatrice-')


def generer(changes, port='4747', port_ws='4748', perso=None):
    for f in os.listdir(dossier):
        os.remove(os.path.join(dossier, f))
    vals = dict(defauts, **changes)
    with io.open(os.path.join(dossier, 'reglages-amp.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(rendre(vals))
    if perso is not None:
        with io.open(os.path.join(dossier, 'perso.ini'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(perso)
    prefixe = os.path.join(dossier, 'run')
    p = subprocess.run([sys.executable, '-I', os.path.join(ICI, GENERATEUR), 'reglages-amp.txt', 'servatrice.ini',
                        port, port_ws, prefixe], cwd=dossier, capture_output=True)
    sortie = p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')
    ini = None
    if os.path.exists(os.path.join(dossier, 'servatrice.ini')):
        with io.open(os.path.join(dossier, 'servatrice.ini'), encoding='utf-8') as f:
            ini = f.read()
    annexes = {}
    for ext in ('base', 'cnf', 'roles.sql'):
        chemin = prefixe + '.' + ext
        if os.path.exists(chemin):
            with io.open(chemin, encoding='utf-8') as f:
                annexes[ext] = f.read()
    return p.returncode, sortie, ini, annexes


PIEGES = ['', 'avec des espaces', 'Serveur francophone hébergé gratuitement par TeamKit.fr — Discord : discord.gg/EuAjGMYPHY',
          "Le \"Club\" \\ des cartes, l'été ; #1 {ok} 100 %", '@arobase en tête', '@Invalid()', 'fin par antislash \\',
          '  espaces autour  ']
n = 0
try:
    for v in PIEGES:
        for champ, cle_ini in (('nom_serveur', 'server/name'), ('message_accueil', 'rooms/roomlist/1/joinmessage'),
                               ('salon1_description', 'rooms/roomlist/1/description')):
            code, sortie, ini, _ = generer({champ: v})
            n += 1
            attendu = v.strip() or ('Cockatrice TeamKit' if champ == 'nom_serveur' else '')
            lu = qsettings(ini or '').get(cle_ini) if code == 0 else None
            if lu != attendu:
                soucis.append('aller-retour %s : écrit %r, Servatrice lirait %r\n%s' % (champ, v, lu, sortie))
        code, sortie, ini, ann = generer({'comptes': 'prive', 'mot_de_passe_prive': v or 'x'})
        n += 1
        if code != 0 or qsettings(ini).get('authentication/password') != (v or 'x'):
            soucis.append('aller-retour mot de passe privé %r : %r' % (v, qsettings(ini or '').get('authentication/password')))
        code, sortie, ini, ann = generer({'comptes': 'comptes', 'base_comptes': 'externe', 'bdd_mot_de_passe': v or 'x',
                                          'bdd_hote': '172.17.0.1'})
        n += 1
        lu = qsettings(ini or '').get('database/password')
        cnf = dict(l.split('=', 1) for l in ann.get('cnf', '').splitlines() if '=' in l)
        if code != 0 or lu != (v or 'x') or option_mariadb_lue(cnf.get('password', '""')) != (v or 'x'):
            soucis.append('aller-retour mot de passe MariaDB %r : ini %r, cnf %r' % (v, lu, cnf.get('password')))
    # les types de parties et les deux salons
    code, sortie, ini, _ = generer({'types_parties': 'Commander, commander , Draft ,, Pauper "PDH", Limité (draft ou scellé)',
                                    'salon2_nom': '@Commander, 4 joueurs', 'salon2_description': 'à 4 ; 1v1 interdit'})
    q = qsettings(ini)
    types = [q.get('rooms/roomlist/1/game_types/%d/name' % i) for i in range(1, int(q['rooms/roomlist/1/game_types/size']) + 1)]
    n += 1
    if types != ['Commander', 'Draft', 'Pauper "PDH"', 'Limité (draft ou scellé)'] or q.get('rooms/roomlist/size') != '2' \
            or q.get('rooms/roomlist/2/name') != '@Commander, 4 joueurs' or q.get('rooms/roomlist/2/autojoin') != 'false' \
            or q.get('rooms/roomlist/1/autojoin') != 'true' or q.get('rooms/roomlist/2/description') != 'à 4 ; 1v1 interdit':
        soucis.append('salons / types de parties : %r %r' % (types, {k: v for k, v in q.items() if 'roomlist/2' in k}))
    # aucune valeur ne doit devenir une liste (virgule hors guillemets)
    for cle, val in q.items():
        if isinstance(val, list):
            soucis.append('servatrice.ini : %s serait lu comme une liste (virgule hors guillemets)' % cle)
    if len(q.get('server/officialwarnings', '').split(',')) != 11:
        soucis.append('les 11 avertissements traduits doivent rester 11 (pas de virgule dedans)')
    # perso.ini : une clé répétée plus bas l'emporte
    code, sortie, ini, _ = generer({}, perso='[game]\nallow_create_as_judge=true\n')
    n += 1
    if qsettings(ini).get('game/allow_create_as_judge') != 'true' or 'perso.ini recopie' not in sortie:
        soucis.append('perso.ini n’est pas recopié à la fin de servatrice.ini')
    # valeurs par défaut : mode ouvert, sans base, sans fichier annexe
    code, sortie, ini, ann = generer({})
    q = qsettings(ini)
    n += 1
    if code or q.get('authentication/method') != 'none' or q.get('database/type') != 'none' or ann \
            or q.get('server/port') != '4747' or q.get('server/websocket_port') != '4748' \
            or q.get('security/max_users_total') != defauts['max_joueurs'] or q.get('server/logfile') != '/dev/null' \
            or q.get('server/writelog') != '1' or q.get('rooms/roomlist/1/name') != defauts['salon1_nom']:
        soucis.append('valeurs par défaut inattendues : %s %s' % (sortie, ann))
    # base intégrée : socket privé, root sans mot de passe, staff échappé
    code, sortie, ini, ann = generer({'comptes': 'comptes', 'administrateurs': "Kevin42, O'Neil, kevin42",
                                      'moderateurs': 'Marine, O\'Neil, Modo\\1'})
    q = qsettings(ini)
    n += 1
    if code or q.get('database/hostname') != 'localhost' or q.get('database/user') != 'root' \
            or ann.get('base') != 'integree\n' or 'socket="%s' % os.path.join(dossier, 'run-db.sock').replace('\\', '\\\\') not in ann.get('cnf', '') \
            or q.get('registration/enabled') != 'true' or q.get('registration/requireemail') != 'false' \
            or q.get('game/store_replays') != 'true':
        soucis.append('base intégrée : %s %s' % (sortie, ann))
    roles = ann.get('roles.sql', '')
    if "SET admin = admin | 1 WHERE name IN ('Kevin42', 'O\\'Neil');" not in roles \
            or "SET admin = admin | 2 WHERE name IN ('Marine', 'Modo\\\\1');" not in roles:
        soucis.append('staff mal écrit en SQL :\n%s' % roles)
    with io.open(os.path.join(dossier, 'staff-amp.json'), encoding='utf-8') as f:
        memo = json.load(f)
    # Démarrage suivant (generer() vide le dossier : on remet la mémoire du staff à la main) :
    # O'Neil retiré des administrateurs perd le bit 1, Modo\1 retiré des modérateurs perd le
    # bit 2, Kevin42 et Marine gardent les leurs.
    for f in os.listdir(dossier):
        os.remove(os.path.join(dossier, f))
    with io.open(os.path.join(dossier, 'staff-amp.json'), 'w', encoding='utf-8') as f:
        json.dump(memo, f)
    with io.open(os.path.join(dossier, 'reglages-amp.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(rendre(dict(defauts, comptes='comptes', administrateurs='Kevin42', moderateurs='Marine')))
    subprocess.run([sys.executable, '-I', os.path.join(ICI, GENERATEUR), 'reglages-amp.txt', 'servatrice.ini', '4747',
                    '4748', os.path.join(dossier, 'run')], cwd=dossier, capture_output=True)
    with io.open(os.path.join(dossier, 'run.roles.sql'), encoding='utf-8') as f:
        roles = f.read()
    n += 1
    if "SET admin = admin & 14 WHERE name IN ('O\\'Neil');" not in roles \
            or "SET admin = admin & 13 WHERE name IN ('Modo\\\\1');" not in roles or roles.count('UPDATE') != 4:
        soucis.append('retrait du staff : O\'Neil doit perdre le bit 1 et Modo\\1 le bit 2, rien d’autre :\n%s' % roles)
    # réglages impossibles : refus clair, rien d'écrit pour la base
    for titre, changes, ports_essai in [
            ('port du jeu 4748 (le jeu passerait en WebSocket)', {}, ('4748', '4749')),
            ('port du jeu 443', {}, ('443', '4748')),
            ('ports identiques', {}, ('4747', '4747')),
            ('privé sans mot de passe', {'comptes': 'prive'}, ('4747', '4748')),
            ('base externe sans mot de passe', {'comptes': 'comptes', 'base_comptes': 'externe'}, ('4747', '4748')),
            ('base externe avec :port', {'comptes': 'comptes', 'base_comptes': 'externe', 'bdd_hote': 'x:3307',
                                         'bdd_mot_de_passe': 'a'}, ('4747', '4748')),
            ('nombre de joueurs non numérique', {'max_joueurs': 'cent'}, ('4747', '4748')),
            ('nombre de joueurs 0', {'max_joueurs': '0'}, ('4747', '4748')),
            ('mode inconnu', {'comptes': 'autre'}, ('4747', '4748')),
            ('salons de même nom', {'salon2_nom': 'salon FRANCOPHONE'}, ('4747', '4748'))]:
        code, sortie, ini, ann = generer(changes, *ports_essai)
        n += 1
        if code != 1 or 'ERREUR' not in sortie or ann:
            soucis.append('réglage impossible accepté : %s (code %s)\n%s' % (titre, code, sortie))
finally:
    shutil.rmtree(dossier, ignore_errors=True)
if not [s for s in soucis if 'aller-retour' in s or 'salon' in s or 'staff' in s or 'refus' in s or 'accepté' in s]:
    ok('aller-retour', '%d cas par le vrai ecrire_config.py, relus comme Qt et mariadb' % n)

# ── 5. fichiers téléchargés à l'Update ───────────────────────────────────────
depot = data['manifest.json']['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu or e.get('UpdateSourceTarget') != '{{$FullBaseDir}}' \
            or e.get('OverwriteExistingFiles') is not True:
        soucis.append('étape FetchURL inattendue pour %s' % e['UpdateSourceArgs'])
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
attendus = {'AMP_reglages.txt', 'ecrire_config.py', 'lancer-servatrice.sh', 'installer-servatrice.sh'}
if {e['UpdateSourceArgs'] for e in fetch} != attendus or set(os.listdir(os.path.join(ICI, 'scripts'))) - {'__pycache__'} != attendus:
    soucis.append('l’Update doit déposer exactement %s (tous présents dans scripts/)' % sorted(attendus))
dernier = updates[-1]
if dernier.get('UpdateSource') != 'Executable' or dernier.get('UpdateSourceArgs') != \
        '"{{$FullBaseDir}}installer-servatrice.sh" "{{version_servatrice}}"' or dernier.get('SkipOnFailure') is not False:
    soucis.append('la dernière étape doit lancer installer-servatrice.sh avec la version, sans SkipOnFailure')
else:
    ok('Update', '%d fichiers depuis %s, puis installation' % (len(fetch), depot))

# ── 6. scripts ───────────────────────────────────────────────────────────────
for nom in (LANCEUR, INSTALLEUR, GENERATEUR, MODELE):
    brut = lire(nom, binaire=True)
    if b'\r' in brut:
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
    if nom.endswith('.sh') and any(o > 127 for o in brut):
        soucis.append('%s : caractères non ASCII' % nom)
    if nom != MODELE and b'{{' in brut:
        soucis.append('%s contient {{ : AMP pourrait le remplacer' % nom)
lanceur, installeur = lire(LANCEUR), lire(INSTALLEUR)
for texte_script, nom, besoins in [
    (lanceur, LANCEUR, [
        ('python3 -I "$ICI/ecrire_config.py" reglages-amp.txt servatrice.ini "$PORT" "$PORT_WS" "$PREFIXE"', 'appel du générateur'),
        ('--log-to-console', 'journal dans la console d’AMP'),
        ('setpriv --pdeathsig TERM -- "$BIN"', 'Servatrice ne doit pas survivre au lanceur'),
        ('setpriv --pdeathsig TERM -- mariadbd', 'la base intégrée non plus'),
        ('MYSQL_UNIX_PORT="$SOCKET"', 'socket de la base intégrée pour Servatrice'),
        ('--sql-mode=NO_ENGINE_SUBSTITUTION', 'Servatrice refuse une base en mode strict (essai du 10/10)'),
        ('--skip-networking', 'la base intégrée n’ouvre aucun port'),
        ('SELECT @@GLOBAL.sql_mode', 'contrôle du mode strict de la base externe'),
        ("sed '1s/^\\xEF\\xBB\\xBF//'", 'servatrice.sql commence par un BOM'),
        ('servatrice_%04d_to_%04d.sql', 'noms des migrations'),
        ('mariadb-dump --defaults-extra-file="$CNF" --single-transaction', 'sauvegarde cohérente'),
        ('RUN="${XDG_RUNTIME_DIR:-/tmp}"', 'identifiants et socket hors du dossier de l’instance')]),
    (installeur, INSTALLEUR, [
        ("MOTIF='-Servatrice_Debian1[23][.]deb$'", 'paquet du serveur seul'),
        ('dpkg-deb -x', 'extraction sans apt (dépendances Debian 12 impossibles sur Debian 13)'),
        ('select((.draft | not) and (.prerelease | not))', 'versions stables seulement'),
        ('sha256sum', 'empreinte du paquet'),
        ('ldd "$BIN"', 'contrôle des bibliothèques')])]:
    for besoin, pourquoi in besoins:
        if besoin not in texte_script:
            soucis.append('%s : %s (%s)' % (nom, besoin, pourquoi))
bash = None
for c in (r'C:\Program Files\Git\bin\bash.exe', r'C:\Program Files\Git\usr\bin\bash.exe', '/bin/bash'):
    if os.path.isfile(c):
        bash = c
        break
if bash:
    for nom in (LANCEUR, INSTALLEUR):
        r = subprocess.run([bash, '-n', os.path.join(ICI, nom)], capture_output=True, text=True)
        if r.returncode:
            soucis.append('bash -n %s : %s' % (nom, r.stderr.strip()))
    ok('bash -n', 'lanceur et installeur')
else:
    print('---  bash -n                  pas de bash ici, syntaxe non vérifiée')
m = re.search(r"^MOTIF='([^']*)'$", installeur, re.M)
if m:
    motif = re.compile(m.group(1))
    for nom_paquet, attendu in [('Cockatrice-Reality-Check-3.1.1-Servatrice_Debian12.deb', True),
                                ('Cockatrice-3.1.1-beta.2-Servatrice_Debian12.deb', True),
                                ('Cockatrice-Reality-Check-3.1.1-Servatrice_Debian13.deb', True),
                                ('Cockatrice-Reality-Check-3.1.1-Debian13.deb', False),
                                ('Cockatrice-Reality-Check-3.1.1-Servatrice_Debian12xdeb', False)]:
        if bool(motif.search(nom_paquet)) != attendu:
            soucis.append('motif du paquet : %s %s' % (nom_paquet, 'refusé' if attendu else 'accepté'))

# ── 7. regex de console (Servatrice 3.1.1, 10/10/2026) ───────────────────────
D = 'Sat Oct 10 17:52:50 2026 '
GARDER = [
    ('Console.AppReadyRegex', 'Server initialized.', {}),
    ('Console.UserJoinRegex', D + 'Server::loginUser: TcpServerSocketInterface(0x56330ef4bf00) name= "Kévin"', {'username': 'Kévin'}),
    ('Console.UserJoinRegex', 'Sat Oct  4 09:02:03 2026 Server::loginUser: WebsocketServerSocketInterface(0x5633) name= "Jean Luc"', {'username': 'Jean Luc'}),
    ('Console.UserJoinRegex', D + 'Server::loginUser: TcpServerSocketInterface(0x5607) name= "Kévin_1"', {'username': 'Kévin_1'}),
    ('Console.UserLeaveRegex', D + 'Server::removeClient: name= "Kévin"', {'username': 'Kévin'}),
]
for cle, ligne, attendu in GARDER:
    m = py(cles.get(cle) or '^$').search(ligne)
    if not m or any(m.group(k) != v for k, v in attendu.items()):
        soucis.append('%s ne reconnaît pas : %r' % (cle, ligne))
JETER = [
    D + '56330ef4bf00 219 bytes [Command_Login.ext] { user_name: "K\\303\\251vin" clientid: "x" }',
    D + '56330ef4bf00 20 bytes [Command_RoomSay.ext] { message: "Bonjour \\303\\240 tous" }',
    D + '562a64774190 38 bytes [Command_Register.ext] { user_name: "Kevin42" password: " ---value expunged--- " }',
    D + 'QSqlQuery::prepare: database not open',
    D + '"pool 0" Error executing query: "Driver not loaded Driver not loaded"',
    D + 'pool 0 Opening database...',
    D + '"pool 0" Error opening database: "Driver not loaded Driver not loaded"',
    D + 'Pool utilisation: 13',
    D + 'session id: 18446744073709551615',
    D + 'closed session id: -1',
    D + 'Server::removeClient: removed 0x56330ef4bf00 ; 0 clients;  0 users left',
    D + '56330ef4bf00 TcpServerSocketInterface destructor',
    D + 'Socket error: QAbstractSocket::RemoteHostClosedError',
    'QIODevice::seek (QFile, "/dev/null"): Cannot call seek on a sequential device',
]
GARDER_AUSSI = [
    D + '56330ef4bf00 Incoming connection: ::ffff:127.0.0.1',
    D + 'Server::loginUser: TcpServerSocketInterface(0x56330ef4bf00) name= "Kévin"',
    D + 'Server::removeClient: name= "Kévin"',
    D + '"main" Error opening database: MySQL/MariaDB strict mode is enabled, which breaks most Servatrice database operations.',
    D + 'Failed to open database',
    D + 'Got register command for user: "Kevin42"',
    D + 'Socket error: QAbstractSocket::NetworkError',
    D + 'Starting server on host "0.0.0.0" port 4747',
    'Server initialized.',
    'TeamKit : base MariaDB prete (schema 37).',
    'ERREUR (base MariaDB) : connexion impossible.',
]
jet = py(cles['Console.ThrowawayMessageRegex'])
for ligne in JETER:
    if not jet.search(ligne):
        soucis.append('ThrowawayMessageRegex laisse passer : %r' % ligne)
for ligne in GARDER_AUSSI:
    if jet.search(ligne):
        soucis.append('ThrowawayMessageRegex jette une ligne utile : %r' % ligne)
for cle in ('Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.AppReadyRegex'):
    for ligne in JETER + ['TeamKit : Servatrice arrete.', D + 'Server listening.']:
        if py(cles[cle]).search(ligne):
            soucis.append('%s attrape une ligne qui n’est pas pour lui : %r' % (cle, ligne))
if not [s for s in soucis if 'Regex' in s]:
    ok('console', '%d lignes reconnues, %d jetées, %d gardées' % (len(GARDER), len(JETER), len(GARDER_AUSSI)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
