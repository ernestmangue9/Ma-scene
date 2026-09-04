# 🎵 Ma Scène

Alertes automatiques de concerts basées sur tes playlists Spotify.

Quand un artiste que tu écoutes annonce un concert, le site t'alerte et te donne :
- Le **lieu** (salle, ville, pays)
- La **date**
- La **taille de la salle**
- Le **lien pour acheter tes billets**

## ⚙️ Installation

### 1. Créer une app Spotify

1. Va sur [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Clique sur **Create app**
3. Nomme-la (ex: "Ma Scène")
4. Dans **Redirect URIs**, ajoute : `http://localhost:3000/callback`
5. Note les **Client ID** et **Client Secret**

### 2. Configurer le projet

```bash
cd Ma-scene
pip install -r requirements.txt
cp .env.example .env
```

Puis ouvre `.env` et remplace les valeurs :
```
SPOTIFY_CLIENT_ID=ton_client_id
SPOTIFY_CLIENT_SECRET=ton_client_secret
```

### 3. Lancer

```bash
python server.py
```

Ouvre **http://localhost:3000**

## 🚀 Utilisation

1. **Se connecter** avec ton compte Spotify
2. **Sélectionner** une ou plusieurs playlists
3. **Analyser** pour extraire tous les artistes
4. Le site recherche les **concerts à venir** pour chaque artiste

## 🔗 APIs utilisées

- **Spotify API** — extraction des artistes depuis tes playlists
- **Bandsintown API** — recherche des concerts (gratuite)
- **Ticketmaster API** — recherche des concerts (clé optionnelle)

## 📝 Notes

- La taille de salle nécessite une clé **Songkick** (optionnelle)
- Aucune donnée perso n'est stockée côté serveur
- Les données du cache expirent après 30 minutes
