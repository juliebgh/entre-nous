# Entre Nous — Who Are You?

Application web multijoueur pour deux adultes.

## État

Version bêta : 30 questions, deux modes, deux écrans, création/rejoindre par code, révélation simultanée des réponses. La synchronisation est assurée par interrogation périodique de Supabase. Ne constitue pas encore la version finale du cahier des charges (240 questions, 90 défis, chronomètres, PWA hors-ligne et tests multi-appareils manquants).

## Publication GitHub Pages

1. Rendre le dépôt public dans **Settings → General → Danger Zone → Change repository visibility**.
2. Dans **Settings → Pages**, choisir **Deploy from a branch**, branche **main**, dossier **/(root)**, puis enregistrer.
3. Vérifier la disponibilité de `https://juliebgh.github.io/entre-nous/`.
4. Tester à partir de deux appareils différents, créer puis rejoindre une partie et vérifier la confidentialité avant la révélation.

## Architecture

- Interface statique : `index.html`.
- API : fonctions RPC du projet Supabase **WhoAreYou?**, distinct de B-Collection.
- Base : tables `en_rooms`, `en_players`, `en_answers`.
- Accès aux parties : jeton de joueur conservé localement. Ne partagez jamais ce jeton.

## Sécurité et limites

La clé publique Supabase intégrée au navigateur est prévue pour être publique. Les données de jeu sont protégées contre la lecture directe par des permissions et RLS, mais les fonctions RPC accessibles sans compte doivent faire l'objet d'une revue de sécurité et de limitations de débit avant une ouverture à grande échelle. Les réponses sont conservées dans la base sans suppression automatique à ce stade. Ne saisissez pas de données sensibles dans cette bêta.

Le dépôt public ne doit jamais contenir de clé `service_role` ni d'identifiants privés.
