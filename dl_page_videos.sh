#!/usr/bin/env bash

#########################################################################
# Télécharge toutes les vidéos détectées sur une page web avec yt-dlp.
#
# Utilisation :
#   ./dl_page_videos.sh "https://site/page"
#
# Exemple :
#   ./dl_page_videos.sh "https://clients.chloebloom.com/replay-odyssee?sc=XXXX"
#########################################################################

set -u

URL="${1:-}"

if [ -z "$URL" ]; then
    echo "Usage : $0 <url>"
    exit 1
fi

check_dependency() {
    local command_name="$1"
    local install_hint="$2"

    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "[ERREUR] $command_name n'est pas installé."
        echo "Installation :"
        echo "$install_hint"
        exit 1
    fi
}

check_dependency "yt-dlp" "sudo apt update && sudo apt install -y yt-dlp"
check_dependency "ffmpeg" "sudo apt update && sudo apt install -y ffmpeg"

# Dossier de sortie horodaté
DATE=$(date +%Y%m%d_%H%M%S)
OUTDIR="downloads_${DATE}"

mkdir -p "$OUTDIR"

echo "========================================"
echo "URL       : $URL"
echo "Sortie    : $OUTDIR"
echo "========================================"
echo

echo "[INFO] Recherche des vidéos..."
echo

if yt-dlp \
    --yes-playlist \
    --continue \
    --ignore-errors \
    --merge-output-format mp4 \
    --embed-metadata \
    --write-description \
    --write-thumbnail \
    -N 4 \
    -o "$OUTDIR/%(playlist_index|00)s - %(title)s.%(ext)s" \
    "$URL"; then
    echo
    echo "========================================"
    echo "[OK] Téléchargement terminé"
    echo "Fichiers disponibles dans :"
    realpath "$OUTDIR"
    echo "========================================"
else
    echo
    echo "========================================"
    echo "[ERREUR] Le téléchargement a échoué"
    echo "Dossier de sortie :"
    realpath "$OUTDIR"
    echo "========================================"
    exit 1
fi
