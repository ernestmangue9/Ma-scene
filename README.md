# 🎵 Concert Alert

Alertes automatiques de concerts basées sur tes playlists Spotify.

Quand un artiste que tu écoutes annonce un concert, le site t'alerte et te donne :
- 📍 Le **lieu** (salle, ville, pays)
- 📅 La **date**
- 👥 La **taille de la salle**
- 🎫 Le **lien pour acheter tes billets**

## ⚙️ Installation

### 1. Créer une app Spotify

1. Va sur [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Clique sur **Create app**
3. Nomme-la (ex: "Concert Alert")
4. Dans **Redirect URIs**, ajoute : `http://localhost:3000/callback`
5. Note les **Client ID** et **Client Secret**

### 2. Configurer le projet

```bash
cd concert-alert
npm install
cp .env.example .env
```

Puis ouvre `.env` et remplace les valeurs :
```
SPOTIFY_CLIENT_ID=ton_client_id
SPOTIFY_CLIENT_SECRET=ton_client_secret
```

Configure aussi ta ville pour filtrer les concerts proches :
```
USER_COUNTRY=France
USER_CITY=Paris
```

### 3. Lancer

```bash
npm start
```

Ouvre **http://localhost:3000**

## 🚀 Utilisation

1. **Se connecter** avec ton compte Spotify
2. **Sélectionner** une ou plusieurs playlists
3. **Analyser** pour extraire tous les artistes
4. Le site recherche les **concerts à venir** pour chaque artiste
5. Le site **vérifie toutes les 5 minutes** les nouveaux annonces et t'alerte par **notification navigateur** quand un nouveau concert apparaît

## 🔗 APIs utilisées

- **Spotify API** — extraction des artistes depuis tes playlists
- **Bandsintown API** — recherche des concerts (gratuite, sans clé requise)

## 📝 Notes

- La taille de salle nécessite une clé **Songkick** (optionnelle) : [https://www.songkick.com/api_keys](https://www.songkick.com/api_keys)
- Aucune donnée perso n'est stockée côté serveur
- Les données du cache expirent après 30 minutes
