# keep_videos

Petit script Bash pour récupérer les vidéos détectées sur une page web avec `yt-dlp`.

## Prérequis

```bash
sudo apt update
sudo apt install -y yt-dlp ffmpeg
```

## Utilisation

```bash
./dl_page_videos.sh "https://site/page"
```

Chaque exécution crée un dossier horodaté du type `downloads_YYYYMMDD_HHMMSS`.

## Notes

- `yt-dlp` détecte les vidéos et playlists accessibles depuis l'URL fournie.
- `ffmpeg` est utilisé pour fusionner les flux, convertir en MP4 et intégrer les métadonnées.
- Les dossiers `downloads_*` sont ignorés par Git.
