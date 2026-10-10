# -*- coding: utf-8 -*-
# ecrire_config.py - pose par le template AMP TeamKit (recree a chaque Update).
#
#   python3 -I ecrire_config.py <reglages-amp.txt> <servatrice.ini> <port> <port_websocket> <prefixe>
#
# AMP ecrit les reglages de l'onglet Configuration tels quels dans reglages-amp.txt
# (une ligne cle=valeur, rendue depuis AMP_reglages.txt). Ce script en fait le
# servatrice.ini que lit Servatrice (format INI de Qt, QSettings) :
#   - chaque texte est ecrit entre guillemets, avec \ et " echappes : sans guillemets,
#     une virgule fait du texte une LISTE et Servatrice lit un texte vide (essai du
#     10/10/2026 : salon « Salon, avec virgule » -> nom vide) ;
#   - les types de parties (liste separee par des virgules) deviennent le tableau
#     roomlist\1\game_types de Qt ;
#   - perso.ini, s'il existe, est recopie a la fin : une cle repetee plus bas
#     l'emporte (essai du 10/10/2026), donc perso.ini peut tout remplacer.
# En mode « comptes », il ecrit aussi, pour le lanceur, hors du dossier de l'instance :
#   <prefixe>.base       « integree » ou « externe »
#   <prefixe>.cnf        options du client mariadb (droits 600, efface par le lanceur)
#   <prefixe>.roles.sql  administrateurs et moderateurs choisis dans AMP
# et garde dans staff-amp.json (dossier de l'instance) la liste du staff donnee par AMP.
# Dans les autres modes, il supprime ces fichiers.
# Code de sortie 1 = reglage impossible, message en francais dans la console.
import io
import json
import os
import sys

TYPES_DEFAUT = 'Partie libre'
# Avertissements que les moderateurs envoient depuis le jeu (mode comptes) : la liste
# officielle de servatrice.ini.example, traduite. « |n » = niveau d'intervention conseille.
# Pas de virgule dans un avertissement : la virgule les separe.
AVERTISSEMENTS = [
    'Langage injurieux|1', "Interpellation d'un joueur|1", 'Provocation ou drama|1', 'Triche|2',
    'Manque de respect envers le staff|1', "Perturbation d'un draft|1", 'Avatar inapproprié|3',
    'Nom de partie inapproprié|1', 'Exclusion de partie sans raison valable|1', 'Spam|1',
    'Harcèlement ciblé|2',
]
MODES = ('ouvert', 'comptes', 'prive')
BASES = ('integree', 'externe')
BASE_INTEGREE = 'servatrice'
avertis = []


def dire(texte):
    print('TeamKit : ' + texte, flush=True)


def refuser(texte):
    print('ERREUR : ' + texte, flush=True)
    print("Corrige ce reglage dans l'onglet Configuration d'AMP, puis relance.", flush=True)
    sys.exit(1)


def lire_reglages(chemin):
    if not os.path.isfile(chemin):
        refuser('%s absent : AMP l ecrit au demarrage a partir de AMP_reglages.txt (lance Update).' % chemin)
    with io.open(chemin, encoding='utf-8-sig', errors='replace') as f:
        lignes = f.read().splitlines()
    valeurs = {}
    for ligne in lignes:
        ligne = ligne.rstrip('\r')
        if not ligne or ligne.startswith('#') or '=' not in ligne:
            continue
        cle, val = ligne.split('=', 1)
        valeurs[cle.strip()] = val
    return valeurs


def texte(v):
    """Valeur texte au format INI de Qt : toujours entre guillemets."""
    v = ''.join(c if c >= ' ' else ' ' for c in v)  # pas de caractere de controle
    if v.startswith('@'):
        v = '@' + v  # Qt lit @Variant(...), @ByteArray(...)... ; @@ = un @ litteral
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'


def booleen(v):
    return 'true' if v else 'false'


def oui(v, defaut=False):
    v = (v or '').strip().lower()
    if v in ('oui', 'true', '1', 'yes'):
        return True
    if v in ('non', 'false', '0', 'no'):
        return False
    return defaut


def entier(valeurs, cle, defaut, mini, maxi, nom):
    brut = (valeurs.get(cle) or '').strip()
    if brut == '':
        return defaut
    try:
        n = int(brut)
    except ValueError:
        refuser("%s : '%s' n'est pas un nombre entier." % (nom, brut))
    if n < mini or n > maxi:
        refuser('%s : %d, il faut entre %d et %d.' % (nom, n, mini, maxi))
    return n


def port(brut, nom):
    try:
        n = int(brut)
    except ValueError:
        refuser("%s invalide : '%s'." % (nom, brut))
    if not 1 <= n <= 65535:
        refuser('%s invalide : %d.' % (nom, n))
    return n


def liste(brut):
    vus = []
    for morceau in (brut or '').split(','):
        m = morceau.strip()
        if m and m.lower() not in [x.lower() for x in vus]:
            vus.append(m)
    return vus


def option_mariadb(v):
    # Fichier d'options du client mariadb : entre guillemets, \ et " echappes
    # (essai du 10/10/2026 : espaces, #, ;, apostrophe, guillemet, antislash, accents).
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'


def chaine_sql(v):
    return "'" + v.replace('\\', '\\\\').replace("'", "\\'") + "'"


def ecrire_prive(chemin, contenu):
    ancien = os.umask(0o077)
    try:
        with io.open(chemin, 'w', encoding='utf-8', newline='\n') as f:
            f.write(contenu)
    finally:
        os.umask(ancien)
    os.chmod(chemin, 0o600)


def effacer(*chemins):
    for c in chemins:
        if os.path.exists(c):
            os.remove(c)


def main(argv):
    if len(argv) != 6:
        print('usage : ecrire_config.py <reglages-amp.txt> <servatrice.ini> <port> <port_websocket> <prefixe>')
        sys.exit(2)
    _, source, cible, port_tcp, port_ws, prefixe = argv
    f_base, f_cnf, f_roles = prefixe + '.base', prefixe + '.cnf', prefixe + '.roles.sql'
    effacer(f_base, f_cnf, f_roles)
    v = lire_reglages(source)
    port_tcp = port(port_tcp, 'Port du jeu')
    port_ws = port(port_ws, 'Port WebSocket')
    if port_tcp in (80, 443, 4748, 8080):
        refuser('le port du jeu est %d : le jeu Cockatrice passe en WebSocket sur 80, 443, 4748 et 8080 '
                'et ne pourrait pas se connecter. Donne un autre port au « Port du jeu » (4747 par defaut).' % port_tcp)
    if port_tcp == port_ws:
        refuser('le port du jeu et le port WebSocket sont identiques (%d).' % port_tcp)

    mode = (v.get('comptes') or 'ouvert').strip()
    if mode not in MODES:
        refuser("mode des comptes '%s' inconnu (ouvert, comptes ou prive)." % mode)
    base = (v.get('base_comptes') or 'integree').strip()
    if base not in BASES:
        refuser("base des comptes '%s' inconnue (integree ou externe)." % base)

    nom = v.get('nom_serveur', '').strip() or 'Cockatrice TeamKit'
    accueil = v.get('message_accueil', '').strip()
    s1_nom = v.get('salon1_nom', '').strip()
    if not s1_nom:
        s1_nom = 'Salon francophone'
        avertis.append('nom du salon principal vide : « Salon francophone » utilise.')
    s1_desc = v.get('salon1_description', '').strip()
    s2_nom = v.get('salon2_nom', '').strip()
    s2_desc = v.get('salon2_description', '').strip()
    if s2_nom and s2_nom.lower() == s1_nom.lower():
        refuser('les deux salons ont le meme nom (%s).' % s1_nom)
    types = liste(v.get('types_parties'))
    if not types:
        types = [TYPES_DEFAUT]
        avertis.append('aucun type de partie : « %s » utilise.' % TYPES_DEFAUT)

    max_joueurs = entier(v, 'max_joueurs', 100, 1, 5000, 'Nombre maximum de joueurs')
    par_ip = entier(v, 'connexions_par_ip', 4, 0, 100, 'Connexions par adresse IP')
    parties = entier(v, 'parties_par_joueur', 5, -1, 100, 'Parties par joueur')
    websocket = oui(v.get('websocket'), True)
    inscription_obligatoire = oui(v.get('inscription_obligatoire'), False)
    admins = liste(v.get('administrateurs'))
    modos = [m for m in liste(v.get('moderateurs')) if m.lower() not in [a.lower() for a in admins]]

    L = []
    a = L.append
    a('; servatrice.ini - ECRIT PAR LE LANCEUR TeamKit a chaque demarrage, a partir des')
    a("; reglages de l'onglet Configuration d'AMP. Ne le modifie pas a la main : pour un")
    a('; reglage en plus, ecris-le dans perso.ini (meme format), il est recopie a la fin.')
    a('')
    a('[server]')
    a('name=' + texte(nom))
    a('id=1')
    a('host=any')
    a('port=%d' % port_tcp)
    a('number_pools=1')
    a('websocket_number_pools=%d' % (1 if websocket else 0))
    a('websocket_host=any')
    a('websocket_port=%d' % port_ws)
    # En mode comptes : etat du serveur en base toutes les 5 min (une ligne par releve
    # dans cockatrice_uptime ; 15 s par defaut = 5 760 lignes par jour). Sans base : jamais.
    a('statusupdate=%d' % (300000 if mode == 'comptes' else 0))
    # Le journal passe par la console d'AMP (--log-to-console) ; Servatrice n'ecrit dans
    # la console que s'il a un fichier de journal ouvert : /dev/null, rien sur le disque.
    a('writelog=1')
    a('logfile=' + texte('/dev/null'))
    a('logfilters=""')
    a('clientkeepalive=1')
    a('max_player_inactivity_time=15')
    a('requireclientid=false')
    a('requiredfeatures=""')
    a('officialwarnings=' + texte(','.join(AVERTISSEMENTS)))
    a('idleclienttimeout=3600')
    a('')
    a('[authentication]')
    if mode == 'ouvert':
        a('method=none')
        a('regonly=false')
    elif mode == 'prive':
        mdp = v.get('mot_de_passe_prive', '')
        if not mdp:
            refuser('mode « serveur prive » sans mot de passe : remplis « Mot de passe du serveur prive ».')
        a('method=password')
        a('password=' + texte(mdp))
        a('regonly=false')
    else:
        a('method=sql')
        a('regonly=' + booleen(inscription_obligatoire))
    a('')
    a('[users]')
    a('minnamelength=3')
    a('maxnamelength=20')
    a('allowlowercase=true')
    a('allowuppercase=true')
    a('allownumerics=true')
    a('allowedpunctuation=' + texte('_.-'))
    a('allowpunctuationprefix=false')
    a('disallowedwords=' + texte('admin,moderat,teamkit'))
    a('disallowedregexp=""')
    a('minpasswordlength=6')
    a('')
    a('[registration]')
    a('enabled=' + booleen(mode == 'comptes'))
    a('requireemail=false')
    a('requireemailactivation=false')
    a('maxaccountsperemail=0')
    a('')
    a('[forgotpassword]')
    a('enable=false')
    a('')
    a('[smtp]')
    a('enableinternalsmtpclient=false')
    a('')
    a('[database]')
    socket = prefixe + '-db.sock'
    if mode == 'comptes' and base == 'integree':
        # MariaDB lancee par le lanceur dans le conteneur, socket prive : Servatrice s'y
        # connecte en « localhost » (socket Unix), chemin donne par MYSQL_UNIX_PORT.
        a('type=mysql')
        a('prefix=cockatrice')
        a('hostname=' + texte('localhost'))
        a('database=' + texte(BASE_INTEGREE))
        a('user=' + texte('root'))
        a('password=""')
        cnf = '[client]\nuser=root\nsocket=%s\n' % option_mariadb(socket)
        bdd = BASE_INTEGREE
    elif mode == 'comptes':
        hote = v.get('bdd_hote', '').strip()
        bdd = v.get('bdd_nom', '').strip()
        util = v.get('bdd_utilisateur', '').strip()
        mdp = v.get('bdd_mot_de_passe', '')
        for val, quoi in ((hote, 'MariaDB externe : adresse'), (bdd, 'MariaDB externe : nom de la base'),
                          (util, 'MariaDB externe : utilisateur'), (mdp, 'MariaDB externe : mot de passe')):
            if not val:
                refuser('base externe : « %s » est vide.' % quoi)
        if ':' in hote:
            refuser("adresse MariaDB '%s' : l'adresse seule, sans :port (Servatrice se connecte au port 3306)." % hote)
        a('type=mysql')
        a('prefix=cockatrice')
        a('hostname=' + texte(hote))
        a('database=' + texte(bdd))
        a('user=' + texte(util))
        a('password=' + texte(mdp))
        cnf = '[client]\nhost=%s\nuser=%s\npassword=%s\ndatabase=%s\n' % (
            option_mariadb(hote), option_mariadb(util), option_mariadb(mdp), option_mariadb(bdd))
    else:
        a('type=none')
    a('')
    a('[rooms]')
    a('method=config')
    salons = [(s1_nom, s1_desc, True, accueil)]
    if s2_nom:
        salons.append((s2_nom, s2_desc, False, ''))
    a('roomlist\\size=%d' % len(salons))
    for i, (s_nom, s_desc, auto, msg) in enumerate(salons, 1):
        p = 'roomlist\\%d\\' % i
        a(p + 'name=' + texte(s_nom))
        a(p + 'description=' + texte(s_desc))
        a(p + 'permissionlevel=none')
        a(p + 'privilegelevel=none')
        a(p + 'autojoin=' + booleen(auto))
        a(p + 'joinmessage=' + texte(msg))
        a(p + 'chathistorysize=100')
        a(p + 'game_types\\size=%d' % len(types))
        for j, t in enumerate(types, 1):
            a(p + 'game_types\\%d\\name=' % j + texte(t))
    a('')
    a('[game]')
    a('max_game_inactivity_time=120')
    a('store_replays=' + booleen(mode == 'comptes'))
    a('allow_create_as_judge=false')
    a('')
    a('[security]')
    a('enable_max_user_limit=true')
    a('max_users_total=%d' % max_joueurs)
    a('max_users_tcp=%d' % max_joueurs)
    a('max_users_websocket=%d' % max_joueurs)
    a('max_users_per_address=%d' % par_ip)
    a('trusted_sources=' + texte('127.0.0.1,::1'))
    a('message_counting_interval=10')
    a('max_message_size_per_interval=1000')
    a('max_message_count_per_interval=10')
    a('max_games_per_user=%d' % parties)
    a('command_counting_interval=10')
    a('max_command_count_per_interval=20')
    a('')
    a('[logging]')
    a('enablelogquery=false')
    a('')
    a('[servernetwork]')
    a('active=0')

    perso_utile = False
    if os.path.isfile('perso.ini'):
        with io.open('perso.ini', encoding='utf-8-sig', errors='replace') as f:
            perso = f.read().splitlines()
        perso_utile = any(l.strip() and not l.lstrip().startswith(';') for l in perso)
        a('')
        a('; ---- perso.ini (recopie tel quel, une cle repetee ici remplace celle du dessus) ----')
        L.extend(perso)
    else:
        with io.open('perso.ini', 'w', encoding='utf-8', newline='\n') as f:
            f.write('; perso.ini - reglages Servatrice en plus, au format de servatrice.ini.\n'
                    '; Recopie a la fin de servatrice.ini a chaque demarrage : une cle ecrite ici\n'
                    '; remplace celle du template. Mets le nom de la section, par exemple :\n'
                    ';   [game]\n'
                    ';   allow_create_as_judge=true\n'
                    '; Un texte avec une virgule DOIT etre entre guillemets. Le template ne touche\n'
                    '; jamais ce fichier. Liste des reglages : servatrice/usr/share/servatrice/servatrice.ini.example\n')

    tmp = cible + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(L) + '\n')
    os.replace(tmp, cible)

    if mode == 'comptes':
        ecrire_prive(f_base, base + '\n')
        ecrire_prive(f_cnf, cnf)
        # Bits 1 (administrateur) et 2 (moderateur) de cockatrice_users.admin. Le lanceur
        # ne retire que les droits que la liste d'AMP avait donnes (memorises dans
        # staff-amp.json) : une nomination faite depuis le jeu par un administrateur reste.
        avant = {'administrateurs': [], 'moderateurs': []}
        try:
            with io.open('staff-amp.json', encoding='utf-8') as f:
                lu = json.load(f)
            avant = {k: [str(n) for n in lu.get(k, [])] for k in avant}
        except (OSError, ValueError, AttributeError):
            pass
        bas = lambda noms: {n.lower() for n in noms}
        sql = []
        for noms, operation in ((admins, 'admin | 1'), (modos, 'admin | 2'),
                                ([n for n in avant['administrateurs'] if n.lower() not in bas(admins)], 'admin & 14'),
                                ([n for n in avant['moderateurs'] if n.lower() not in bas(modos)], 'admin & 13')):
            if noms:
                sql.append('UPDATE cockatrice_users SET admin = %s WHERE name IN (%s);'
                           % (operation, ', '.join(chaine_sql(n) for n in noms)))
        ecrire_prive(f_roles, '\n'.join(sql) + '\n')
        with io.open('staff-amp.json', 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'administrateurs': admins, 'moderateurs': modos}, f, ensure_ascii=False, indent=1)

    for t in avertis:
        dire('ATTENTION, ' + t)
    if mode == 'comptes':
        libelle = 'comptes (base %s%s), inscription depuis le jeu%s' % (
            'integree' if base == 'integree' else 'externe ',
            '' if base == 'integree' else v.get('bdd_hote', '').strip(),
            ', obligatoire' if inscription_obligatoire else '')
    else:
        libelle = {'ouvert': 'ouvert (pseudo libre, sans compte)', 'prive': 'serveur prive (mot de passe commun)'}[mode]
    dire('servatrice.ini ecrit : %s ; salon(s) : %s ; %d joueurs max ; WebSocket %s.'
         % (libelle, ', '.join(s[0] for s in salons), max_joueurs,
            ('port %d' % port_ws) if websocket else 'coupe'))
    if mode != 'comptes' and (admins or modos):
        dire('les administrateurs et moderateurs ne servent qu en mode comptes : ignores.')
    if perso_utile:
        dire('perso.ini recopie a la fin de servatrice.ini.')


if __name__ == '__main__':
    main(sys.argv)
