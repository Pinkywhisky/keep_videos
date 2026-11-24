# keep_videos

`keep_videos` est un petit outil Bash pour donner une URL de page web à `yt-dlp` et télécharger les vidéos détectées.

Le script crée un dossier de sortie, conserve une archive des éléments déjà téléchargés et écrit un journal d'exécution.

## Installation

Sur Debian/Ubuntu :

```bash
sudo apt update
sudo apt install -y ffmpeg curl pipx
pipx install yt-dlp
```

Le paquet `yt-dlp` d'apt est souvent ancien, et les sites changent régulièrement : un yt-dlp dépassé est la première cause d'échec. Avec pipx, la mise à jour se fait par :

```bash
pipx upgrade yt-dlp
```

Le script vous prévient si votre yt-dlp a plus de 6 mois.

Rendre le script exécutable si nécessaire :

```bash
chmod +x dl_page_videos.sh
```

## Utilisation simple

```bash
./dl_page_videos.sh "https://site/page"
```

Par défaut, le script crée un dossier horodaté :

```text
downloads_YYYYMMDD_HHMMSS/
```

Ce dossier contient les vidéos, les miniatures, les descriptions, le fichier `.downloaded.txt` utilisé par `yt-dlp` pour éviter les doublons, et `download.log`.

Les fichiers sont nommés `NN - Titre [id].ext`, où `NN` suit l'ordre de la playlist ou, à défaut, l'ordre des vidéos trouvées sur la page.

Avant d'appeler `yt-dlp`, le script lit la page avec `curl` et cherche les vidéos intégrées dans le HTML : balises `<video>`/`<source>`, iframes YouTube, Vimeo, Dailymotion, Bunny Stream, fichiers `.mp4`, `.webm`, `.mov`, `.m3u8`, `.mpd`. Les URLs trouvées sont transmises à `yt-dlp`, avec la page comme `Referer`. Si rien n'est trouvé, ou si `curl` ou Python 3 manquent, l'URL est transmise directement à `yt-dlp`.

Les URLs de YouTube, Vimeo, Dailymotion, Bunny et les liens directs vers un média sont toujours confiés directement à `yt-dlp`.

## Options

```text
-o, --output DIR                 Choisir le dossier de sortie
-n, --concurrent N               Fragments HLS/DASH téléchargés en parallèle pour chaque vidéo, défaut 4
    --cookies-from-browser NAME  Utiliser les cookies d'un navigateur : firefox, chrome, chromium, brave, edge, opera, vivaldi
                                 (profil précis : firefox:/chemin/du/profil)
    --cookies FILE               Utiliser un fichier cookies.txt
    --dry-run                    Afficher les vidéos détectées sans télécharger
    --no-thumbnail               Ne pas écrire les miniatures
    --no-description             Ne pas écrire les descriptions
    --audio-only                 Extraire uniquement l'audio
    --keep-html                  Conserver .page.html et .candidate_urls.txt pour le diagnostic
-h, --help                       Afficher l'aide
```

## Exemples

Choisir le dossier de sortie :

```bash
./dl_page_videos.sh -o videos_page "https://site/page"
```

Limiter ou augmenter le nombre de fragments téléchargés en parallèle (flux HLS/DASH ; les vidéos elles-mêmes sont traitées une par une) :

```bash
./dl_page_videos.sh -n 2 "https://site/page"
```

Utiliser les cookies Firefox pour une page à laquelle vous avez accès :

```bash
./dl_page_videos.sh --cookies-from-browser firefox "https://site/page"
```

Utiliser un fichier cookies exporté :

```bash
./dl_page_videos.sh --cookies cookies.txt "https://site/page"
```

Analyser ce que `yt-dlp` détecte sans télécharger :

```bash
./dl_page_videos.sh --dry-run "https://site/page"
```

Télécharger uniquement l'audio :

```bash
./dl_page_videos.sh --audio-only "https://site/page"
```

Ne pas écrire les miniatures ni les descriptions :

```bash
./dl_page_videos.sh --no-thumbnail --no-description "https://site/page"
```

## Archive et logs

Chaque dossier de sortie contient :

- `.downloaded.txt` : archive `yt-dlp` des vidéos déjà récupérées dans ce dossier.
- `download.log` : pour chaque exécution, la date, l'URL, les URLs vidéo détectées, la commande lancée et la sortie complète de `yt-dlp`. Le journal est cumulatif : les exécutions successives dans un même dossier s'ajoutent à la suite.

La page récupérée (`.page.html`) et la liste des URLs détectées (`.candidate_urls.txt`) sont supprimées à la fin, car elles peuvent contenir des données de compte et des liens signés. Ajoutez `--keep-html` pour les conserver lors d'un diagnostic. Les URLs détectées restent visibles dans `download.log` : ne partagez pas ce journal tel quel si les liens sont signés.

Si vous relancez le script avec le même dossier via `-o`, les vidéos déjà présentes dans `.downloaded.txt` ne sont pas retéléchargées.

Le code retour vaut `0` en cas de succès, `1` si au moins une vidéo a échoué ou si rien n'a été téléchargé, et `2` en cas d'option invalide.

## Cookies

Ne versionnez jamais de cookies ou d'identifiants.

Le fichier `.gitignore` ignore les fichiers du type `cookies*.txt`, mais il reste préférable de les garder hors du dépôt.

Avec `--cookies-from-browser`, le script exporte les cookies du navigateur dans un fichier temporaire privé pour que `curl` lise la page connectée, puis supprime ce fichier à la fin, y compris après un Ctrl-C. Si l'export échoue, la page est lue sans connexion et `yt-dlp` utilise quand même les cookies du navigateur.

Sous WSL, le navigateur Windows n'est pas trouvé automatiquement. Pour Firefox, indiquez le chemin du profil :

```bash
./dl_page_videos.sh --cookies-from-browser "firefox:/mnt/c/Users/NOM/AppData/Roaming/Mozilla/Firefox/Profiles/xxxx.default-release" "https://site/page"
```

Les cookies de Chrome, Edge et Brave sous Windows sont chiffrés par Windows et ne peuvent pas être lus depuis WSL : exportez-les alors en `cookies.txt` avec une extension de navigateur et utilisez `--cookies FILE`.

## Tests

```bash
python3 -m unittest discover -s tests
```

Les tests de `tests/test_detection.py` simulent `curl`, `yt-dlp` et `ffmpeg` et n'utilisent pas le réseau. Ceux de `tests/test_local_download.py` lancent de vrais téléchargements depuis un serveur HTTP local ; ils sont ignorés si `curl`, `yt-dlp` ou `ffmpeg` manquent.

## Avertissement

Utilisez ce script uniquement pour des contenus auxquels vous avez légitimement accès et dans le respect des conditions d'utilisation des sites concernés.

Ce projet n'est pas destiné à contourner des DRM ou des protections fortes.
