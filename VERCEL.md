# Publier Entre nous sur Vercel avec Supabase

Cette configuration utilise une fonction Python ASGI et PostgreSQL. Les deux clients interrogent périodiquement la même API HTTPS. Chaque mutation et chaque lecture d’un salon se déroulent dans une transaction PostgreSQL, avec un verrou sur la ligne du salon. Le moteur calcule l’état et construit une vue autorisée pour chaque participant. Le navigateur ne se connecte jamais à Supabase directement.

## Préparer la base

1. Créer un projet Supabase dédié et choisir une région proche de la fonction Vercel. Activer **Supabase Cron** dans les intégrations. Une base PostgreSQL compatible peut aussi convenir après adaptation des rôles système et de la tâche planifiée.
2. Exécuter une fois `deploy/supabase/install.sql` avec l’éditeur SQL du projet comme administrateur. Le script crée le schéma privé, un rôle de connexion distinct, les tables, les politiques RLS et le nettoyage périodique. Une collision avec un nom de rôle ou de schéma existant interrompt la transaction. Ne pas ajouter `entre_nous_private` aux schémas exposés par les API et ne pas ajouter les tables à une publication Realtime.
3. Depuis une connexion d’administration locale avec `psql`, utiliser **la commande interactive** `\password entre_nous_app` pour définir un mot de passe fort unique. Le terminal demande la valeur sans l’afficher.
4. Dans **Connect**, relever les coordonnées du **Transaction pooler** (port 6543). Former l’URL de connexion pour le rôle applicatif avec le nom d’utilisateur `entre_nous_app.REFERENCE_DU_PROJET`, la base `postgres` et le mot de passe du rôle encodé pour une URL. Tester la connexion avec ce rôle. Le runtime désactive les instructions préparées et exige TLS. Pour vérifier aussi l’identité du serveur, fournir une chaîne avec `sslmode=verify-full` et le certificat racine requis par le pooler.
5. Exécuter `deploy/supabase/check.sql` avec le compte d’administration. Cette vérification lève une erreur en cas de privilèges publics, d’absence de RLS, d’absence de purge planifiée ou de droits applicatifs incohérents.

Le serveur conserve une connexion au maximum par instance active. Il faut dimensionner la base et les quotas Vercel selon le nombre réel de participants et la fréquence d’interrogation, puis mesurer la latence depuis les régions ciblées.

## Paramétrer Vercel

1. Importer le dépôt dans un **nouveau projet**. Choisir **Other** et la racine contenant `vercel.json`. Conserver les paramètres de construction du dépôt. Le répertoire public est `public`. La fonction en `api/index.py` reçoit les routes `/api/create`, `/api/join`, `/api/state` et `/api/act`.
2. Choisir l’URL canonique HTTPS du projet. Définir dans les variables serveur de l’environnement de production `PUBLIC_ORIGIN` (origine exacte sans chemin), `DATABASE_URL` (URL du rôle applicatif) et `RATE_LIMIT_SECRET` (secret stable et indépendant d’au moins 32 caractères, générable avec `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Les secrets restent dans le gestionnaire du fournisseur.
3. Pour une préproduction, utiliser une autre base et son propre domaine canonique. Chaque origine a ses propres cookies. Le lien d’invitation doit utiliser le même domaine que le premier joueur.
4. Renseigner les informations réelles de l’éditeur et de l’hébergeur dans les mentions légales, vérifier les conditions du contrat d’hébergement et la région des données. Vérifier les réglages de collecte des journaux, de sauvegarde et de restauration avant d’ouvrir les inscriptions. Le consentement à Sans filtre repose sur une déclaration des deux joueurs.
5. Déployer, attendre la fin du build et effectuer les contrôles ci-dessous. Une prévisualisation protégée par une authentification Vercel demandera cette authentification aux deux testeurs.

## Contrôles sur l’URL réellement publiée

- Charger l’URL d’accueil, ouvrir les instructions, puis charger les icônes et le manifeste. Vérifier l’installation depuis Safari iOS et Chrome Android.
- Ouvrir deux profils navigateur indépendants. Créer puis rejoindre un salon depuis les deux appareils. Vérifier les deux modes avec des réponses et prédictions différentes, une reconnexion et une manche passée. Contrôler la révélation et le score sur les deux écrans.
- Consulter les en-têtes réseau des réponses API. Attendre `Cache-Control: no-store` ou `private, no-store`, ainsi qu’un cookie `HttpOnly; Secure; SameSite=Strict` lors de la création. Les réponses API ne doivent jamais être mises en cache par le service worker.
- Ouvrir `/api/state` depuis un troisième profil vierge. La réponse attendue est HTTP 401. Vérifier l’absence de choix privés dans les réponses inspectées avant révélation avec des données de test.
- Vérifier que les fichiers de travail privés (base, modules Python, catalogue serveur, scripts SQL, variables) ne sont pas accessibles dans la publication statique.
- Dans Supabase Cron, vérifier la réussite effective des exécutions de `entre-nous-purge-private-v1`. Tester la disparition d’un salon inactif après 30 minutes, en fermant les deux onglets pour interrompre les interrogations. La purge s’exécute chaque minute, les sièges sont effacés en cascade. La limite absolue de 6 heures s’applique même aux salons actifs.
- Vérifier les paramètres effectifs des fournisseurs. Les sauvegardes et les archives PostgreSQL peuvent conserver des versions anciennes jusqu’à leur propre échéance. Documenter cette durée et appliquer une nouvelle purge avant remise en service après une restauration. Éviter toute journalisation applicative des corps HTTP, des cookies ou des valeurs de paramètres SQL. Les limites d’entrée stockent un HMAC de l’adresse IP, supprimé après environ deux à trois minutes.

## Documentation des fournisseurs

- [Runtime Python de Vercel](https://vercel.com/docs/functions/runtimes/python)
- [Configuration de Vercel](https://vercel.com/docs/project-configuration/vercel-json)
- [Pooler PostgreSQL de Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase Cron](https://supabase.com/docs/guides/cron)
