#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
# Résoudre les liens symboliques : le script peut être lié depuis ~/bin.
SCRIPT_DIR="$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")"
DEFAULT_CONCURRENT=4
SUPPORTED_BROWSERS="firefox chrome chromium brave edge opera vivaldi"
# Au-delà, les extracteurs de yt-dlp risquent d'être cassés par les sites.
YTDLP_MAX_AGE_DAYS=180

URL=""
OUTDIR=""
CONCURRENT="$DEFAULT_CONCURRENT"
COOKIES_FROM_BROWSER=""
COOKIES_FILE=""
DRY_RUN=0
WRITE_THUMBNAIL=1
WRITE_DESCRIPTION=1
AUDIO_ONLY=0
KEEP_HTML=0
LOG_FILE=""
OUTDIR_ABS=""
# Dossier privé (0700) de l'exécution : cookies exportés, fichiers de suivi.
RUN_TMP=""
COMPLETED_FILE=""
RUN_OUTPUT_FILE=""
HTML_FILE=""
CANDIDATES_FILE=""
HTML_PAGE_URL=""

usage() {
    cat <<EOF
Usage :
  $SCRIPT_NAME [options] <url>

Télécharge toutes les vidéos détectées sur une page web avec yt-dlp.

Options :
  -o, --output DIR                 Choisir le dossier de sortie
  -n, --concurrent N               Fragments HLS/DASH téléchargés en parallèle pour chaque vidéo
                                   (défaut : $DEFAULT_CONCURRENT ; les vidéos restent traitées une par une)
      --cookies-from-browser NAME  Utiliser les cookies d'un navigateur : ${SUPPORTED_BROWSERS// /, }
                                   (profil précis : firefox:/chemin/du/profil)
      --cookies FILE               Utiliser un fichier cookies.txt
      --dry-run                    Afficher les vidéos détectées sans télécharger
      --no-thumbnail               Ne pas écrire les miniatures
      --no-description             Ne pas écrire les descriptions
      --audio-only                 Extraire uniquement l'audio
      --keep-html                  Conserver .page.html et .candidate_urls.txt pour le diagnostic
  -h, --help                       Afficher cette aide

Exemples :
  $SCRIPT_NAME "https://site/page"
  $SCRIPT_NAME -o videos --cookies-from-browser firefox "https://site/page"
  $SCRIPT_NAME --dry-run "https://site/page"
EOF
}

# Écrit sur la console et, dès qu'il existe, dans le journal.
log_line() {
    local line="$1"
    local fd="$2"

    printf '%s\n' "$line" >&"$fd"
    if [[ -n "$LOG_FILE" ]]; then
        printf '%s\n' "$line" >>"$LOG_FILE"
    fi
}

log_info() {
    log_line "[INFO] $1" 1
}

log_error() {
    log_line "[ERREUR] $1" 2
}

cleanup() {
    local exit_code=$?

    if [[ -n "$RUN_TMP" ]]; then
        rm -rf -- "$RUN_TMP"
    fi

    # La page peut contenir des données de compte et des liens signés.
    if (( ! KEEP_HTML )); then
        if [[ -n "$HTML_FILE" ]]; then
            rm -f -- "$HTML_FILE"
        fi
        if [[ -n "$CANDIDATES_FILE" ]]; then
            rm -f -- "$CANDIDATES_FILE"
        fi
    fi

    if [[ -n "$LOG_FILE" && -f "$LOG_FILE" ]]; then
        {
            printf '\n'
            printf 'Fin : %s\n' "$(date -Is)"
            printf 'Code retour : %s\n' "$exit_code"
        } >>"$LOG_FILE"
    fi
}

die() {
    local message="$1"
    local code="${2:-1}"

    log_error "$message"
    exit "$code"
}

check_dependencies() {
    local missing=()
    local cmd

    for cmd in yt-dlp ffmpeg; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log_error "$cmd n'est pas installé."
            missing+=("$cmd")
        fi
    done

    if (( ${#missing[@]} )); then
        printf 'Installation Debian/Ubuntu :\n' >&2
        printf '  sudo apt update\n' >&2
        printf '  sudo apt install -y %s\n' "${missing[*]}" >&2
        exit 127
    fi
}

# Outils optionnels de la détection HTML : leur absence n'est pas bloquante.
check_html_scan_dependencies() {
    if ! command -v curl >/dev/null 2>&1; then
        log_info "curl absent : détection HTML indisponible, utilisation directe de yt-dlp."
        return 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        log_info "Python 3 absent : détection HTML indisponible, utilisation directe de yt-dlp."
        return 1
    fi
}

configure_utf8_environment() {
    export PYTHONUTF8=1
    export PYTHONIOENCODING=UTF-8

    case "${LANG:-}" in
        *UTF-8*|*utf-8*|*UTF8*|*utf8*)
            ;;
        *)
            export LANG=C.UTF-8
            ;;
    esac

    case "${LC_ALL:-}" in
        *UTF-8*|*utf-8*|*UTF8*|*utf8*)
            ;;
        *)
            export LC_ALL=C.UTF-8
            ;;
    esac
}

validate_positive_integer() {
    local value="$1"
    local option_name="$2"

    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        die "$option_name doit être un entier positif." 2
    fi
}

validate_browser() {
    # Syntaxe yt-dlp : NAVIGATEUR[+TROUSSEAU][:PROFIL][::CONTENEUR].
    local browser="${1%%[+:]*}"

    if [[ " $SUPPORTED_BROWSERS " != *" $browser "* ]]; then
        die "--cookies-from-browser doit valoir : ${SUPPORTED_BROWSERS// /, }." 2
    fi
}

shell_quote_command() {
    printf '%q ' "$@"
}

log_command() {
    {
        printf 'Commande : '
        shell_quote_command "$@"
        printf '\n\n'
    } >>"$LOG_FILE"
}

prepare_output_dir() {
    if [[ -z "$OUTDIR" ]]; then
        OUTDIR="downloads_$(date +%Y%m%d_%H%M%S)"
    fi

    if ! mkdir -p -- "$OUTDIR" 2>/dev/null || [[ ! -w "$OUTDIR" ]]; then
        die "Impossible de créer ou d'écrire dans le dossier de sortie : $OUTDIR" 1
    fi

    OUTDIR_ABS="$(realpath -- "$OUTDIR")"
    RUN_TMP="$(mktemp -d "$OUTDIR/.run.XXXXXX")"
    COMPLETED_FILE="$RUN_TMP/completed.txt"
    RUN_OUTPUT_FILE="$RUN_TMP/yt-dlp-output.txt"
    : >"$COMPLETED_FILE"
    : >"$RUN_OUTPUT_FILE"
    # Le journal est cumulatif : chaque exécution est ajoutée à la suite.
    LOG_FILE="$OUTDIR/download.log"
}

write_log_header() {
    {
        if [[ -s "$LOG_FILE" ]]; then
            printf '\n========================================\n\n'
        fi
        printf 'keep_videos\n'
        printf 'Date : %s\n' "$(date -Is)"
        printf 'URL : %s\n' "$URL"
        printf 'Dossier de sortie : %s\n' "$OUTDIR_ABS"
        printf 'Mode : %s\n' "$([[ "$DRY_RUN" -eq 1 ]] && printf 'analyse' || printf 'téléchargement')"
        printf '\n'
    } >>"$LOG_FILE"
}

add_cookie_options() {
    local -n target_args="$1"

    if [[ -n "$COOKIES_FROM_BROWSER" ]]; then
        target_args+=(--cookies-from-browser "$COOKIES_FROM_BROWSER")
    fi

    if [[ -n "$COOKIES_FILE" ]]; then
        target_args+=(--cookies "$COOKIES_FILE")
    fi
}

build_common_yt_dlp_args() {
    local -n target_args="$1"

    target_args+=(
        --yes-playlist
        --no-abort-on-error
        --encoding utf-8
        --windows-filenames
        --trim-filenames 180
    )

    add_cookie_options "$1"
}

append_download_options() {
    local -n target_args="$1"
    local archive_file="$2"
    local output_template="$3"

    target_args+=(
        --continue
        --download-archive "$archive_file"
        --embed-metadata
        -N "$CONCURRENT"
        -o "$output_template"
        --print-to-file "after_move:%(filepath)s" "${COMPLETED_FILE//%/%%}"
    )

    if (( AUDIO_ONLY )); then
        target_args+=(--extract-audio --audio-format best)
    else
        target_args+=(--merge-output-format mp4)
    fi

    if (( WRITE_DESCRIPTION )); then
        target_args+=(--write-description)
    fi

    if (( WRITE_THUMBNAIL )); then
        target_args+=(--write-thumbnail)
    fi
}

append_dry_run_options() {
    local -n target_args="$1"

    target_args+=(
        --flat-playlist
        --simulate
        --print "%(title|Sans titre)s | %(id|sans-id)s | %(extractor|inconnu)s | %(webpage_url|)s"
    )
}

# Avertit si yt-dlp est ancien : sa version est une date AAAA.MM.JJ.
check_ytdlp_age() {
    local version release_epoch age_days

    version="$(yt-dlp --version 2>/dev/null)" || return 0
    if [[ ! "$version" =~ ^([0-9]{4})\.([0-9]{2})\.([0-9]{2}) ]]; then
        return 0
    fi

    release_epoch="$(date -d "${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}" +%s 2>/dev/null)" || return 0
    age_days=$(( ($(date +%s) - release_epoch) / 86400 ))
    if (( age_days > YTDLP_MAX_AGE_DAYS )); then
        log_info "yt-dlp $version date de $age_days jours : s'il échoue, mettez-le à jour (voir README)."
    fi
}

# Exporte les cookies du navigateur au format Netscape pour que curl lise
# la page connectée. Sans URL, yt-dlp charge les cookies, les enregistre
# dans --cookies en quittant, puis sort en erreur : ce code retour est attendu.
export_browser_cookies() {
    local cookies_file="$RUN_TMP/browser-cookies.txt"

    yt-dlp --ignore-config --cookies-from-browser "$COOKIES_FROM_BROWSER" \
        --cookies "$cookies_file" >/dev/null 2>>"$LOG_FILE" || true

    if [[ -s "$cookies_file" ]]; then
        printf '%s' "$cookies_file"
    else
        return 1
    fi
}

extract_video_candidates() {
    local html_file="$1"
    local candidates_file="$2"
    local page_url="$3"

    python3 "$SCRIPT_DIR/extract_video_candidates.py" "$html_file" "$page_url" >"$candidates_file"
}

# Les médias directs et les pages des plateformes connues sont laissés
# à l'extracteur natif de yt-dlp, plus fiable que l'analyse statique.
should_scan_html() {
    local url_lower="${URL,,}"
    local page_path="${url_lower%%[?#]*}"
    local host="${url_lower#*://}"

    case "$url_lower" in
        http://*|https://*) ;;
        *) return 1 ;;
    esac

    host="${host%%[/?#]*}"
    host="${host##*@}"
    host="${host%%:*}"
    case "$host" in
        youtube.com|*.youtube.com|youtube-nocookie.com|*.youtube-nocookie.com|youtu.be|\
        vimeo.com|*.vimeo.com|dailymotion.com|*.dailymotion.com|dai.ly|\
        iframe.mediadelivery.net|player.mediadelivery.net)
            return 1 ;;
    esac

    case "$page_path" in
        *.mp4|*.webm|*.mov|*.m3u8|*.mpd) return 1 ;;
    esac
}

# Télécharge la page avec curl et en extrait les URLs vidéo intégrées.
# Retourne 0 si des candidats ont été écrits dans CANDIDATES_FILE.
scan_html_for_videos() {
    local response_metadata content_type browser_cookies
    local curl_args=(-LfsS --connect-timeout 10 --max-time 30 --max-filesize 10485760)

    should_scan_html || return 1
    check_html_scan_dependencies || return 1

    # Toujours repartir de fichiers vides : pas de candidats d'une exécution précédente.
    CANDIDATES_FILE="$OUTDIR/.candidate_urls.txt"
    : >"$CANDIDATES_FILE"
    HTML_FILE="$OUTDIR/.page.html"
    : >"$HTML_FILE"

    log_info "Recherche de vidéos intégrées dans le HTML..."
    if [[ -n "$COOKIES_FILE" ]]; then
        curl_args+=(--cookie "$COOKIES_FILE")
    fi
    if [[ -n "$COOKIES_FROM_BROWSER" ]]; then
        if browser_cookies="$(export_browser_cookies)"; then
            curl_args+=(--cookie "$browser_cookies")
            log_info "Cookies $COOKIES_FROM_BROWSER utilisés pour lire la page."
        else
            log_info "Export des cookies $COOKIES_FROM_BROWSER impossible ; curl lit la page sans connexion."
        fi
    fi

    if ! response_metadata=$(curl "${curl_args[@]}" -o "$HTML_FILE" \
        --write-out $'%{url_effective}\n%{content_type}' -- "$URL" 2>>"$LOG_FILE"); then
        log_info "Récupération HTML impossible ; utilisation directe de yt-dlp."
        return 1
    fi

    HTML_PAGE_URL="${response_metadata%%$'\n'*}"
    HTML_PAGE_URL="${HTML_PAGE_URL:-$URL}"
    content_type="${response_metadata#*$'\n'}"

    case "${content_type,,}" in
        video/*|audio/*|*mpegurl*|*dash+xml*)
            log_info "L'URL renvoie un média ; utilisation directe de yt-dlp."
            return 1 ;;
    esac
    if [[ ! -s "$HTML_FILE" ]]; then
        log_info "HTML vide ; utilisation directe de yt-dlp."
        return 1
    fi
    if ! extract_video_candidates "$HTML_FILE" "$CANDIDATES_FILE" "$HTML_PAGE_URL" 2>>"$LOG_FILE"; then
        log_info "Échec de l'analyse HTML ; utilisation directe de yt-dlp."
        return 1
    fi
    if [[ ! -s "$CANDIDATES_FILE" ]]; then
        log_info "Aucune vidéo intégrée détectée ; utilisation directe de yt-dlp."
        return 1
    fi

    log_info "URLs vidéo détectées : $(wc -l <"$CANDIDATES_FILE")"
    {
        cat "$CANDIDATES_FILE"
        printf '\n'
    } | tee -a "$LOG_FILE"
}

# Nombre de médias signalés par yt-dlp et réellement présents sur le disque.
count_completed_media() {
    local completed_path
    local count=0

    if [[ -n "$COMPLETED_FILE" && -f "$COMPLETED_FILE" ]]; then
        while IFS= read -r completed_path; do
            if [[ -s "$completed_path" ]]; then
                count=$((count + 1))
            fi
        done <"$COMPLETED_FILE"
    fi

    printf '%s' "$count"
}

report_download_result() {
    local archive_file="$1"
    local completed_count

    completed_count="$(count_completed_media)"
    if (( completed_count > 0 )); then
        log_info "Traitement terminé : $completed_count média(s) vérifié(s) dans le dossier de sortie."
    elif [[ -s "$archive_file" ]] && grep -q 'has already been recorded in the archive' "$RUN_OUTPUT_FILE"; then
        log_info "Aucun nouveau média téléchargé ; vidéos déjà présentes dans l'archive."
    else
        die "Aucun média téléchargé ou confirmé. Consulte le journal : $OUTDIR_ABS/download.log" 1
    fi
}

run_download() {
    local archive_file="$OUTDIR/.downloaded.txt"
    # playlist_index pour une playlist, sinon autonumber (ordre des URLs détectées).
    local output_template="$OUTDIR/%(playlist_index,autonumber)02d - %(title)s [%(id)s].%(ext)s"
    local command=(yt-dlp)
    local completed_count

    build_common_yt_dlp_args command

    if (( DRY_RUN )); then
        append_dry_run_options command
    else
        append_download_options command "$archive_file" "$output_template"
    fi

    log_info "URL : $URL"
    log_info "Sortie : $OUTDIR_ABS"
    log_info "Journal : $OUTDIR_ABS/download.log"

    if (( DRY_RUN )); then
        log_info "Analyse des vidéos détectées..."
    else
        log_info "Téléchargement des vidéos détectées..."
        log_info "Archive : $OUTDIR_ABS/.downloaded.txt"
    fi

    if scan_html_for_videos; then
        command+=(--referer "$HTML_PAGE_URL" --batch-file "$CANDIDATES_FILE")
    else
        command+=(-- "$URL")
    fi
    log_command "${command[@]}"

    if ! "${command[@]}" 2>&1 | tee -a "$LOG_FILE" "$RUN_OUTPUT_FILE"; then
        printf '\n' >>"$LOG_FILE"
        completed_count="$(count_completed_media)"
        if (( completed_count > 0 )); then
            log_error "$completed_count média(s) téléchargé(s), mais certaines vidéos ont échoué."
        fi
        die "yt-dlp a échoué. Consulte le journal : $OUTDIR_ABS/download.log" 1
    fi
    printf '\n' >>"$LOG_FILE"

    if (( DRY_RUN )); then
        log_info "Analyse terminée."
    else
        report_download_result "$archive_file"
    fi
}

# Une seule URL positionnelle est acceptée.
set_url() {
    if [[ -n "$URL" ]]; then
        die "Une seule URL est attendue. Argument en trop : $1" 2
    fi
    URL="$1"
}

parse_args() {
    while (($#)); do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            -o|--output)
                [[ $# -ge 2 ]] || die "Option $1 : dossier manquant." 2
                OUTDIR="$2"
                shift 2
                ;;
            --output=*)
                OUTDIR="${1#*=}"
                shift
                ;;
            -n|--concurrent)
                [[ $# -ge 2 ]] || die "Option $1 : valeur manquante." 2
                CONCURRENT="$2"
                shift 2
                ;;
            --concurrent=*)
                CONCURRENT="${1#*=}"
                shift
                ;;
            --cookies-from-browser)
                [[ $# -ge 2 ]] || die "Option $1 : navigateur manquant." 2
                COOKIES_FROM_BROWSER="$2"
                shift 2
                ;;
            --cookies-from-browser=*)
                COOKIES_FROM_BROWSER="${1#*=}"
                shift
                ;;
            --cookies)
                [[ $# -ge 2 ]] || die "Option $1 : fichier manquant." 2
                COOKIES_FILE="$2"
                shift 2
                ;;
            --cookies=*)
                COOKIES_FILE="${1#*=}"
                shift
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --no-thumbnail)
                WRITE_THUMBNAIL=0
                shift
                ;;
            --no-description)
                WRITE_DESCRIPTION=0
                shift
                ;;
            --keep-html)
                KEEP_HTML=1
                shift
                ;;
            --audio-only)
                AUDIO_ONLY=1
                shift
                ;;
            --)
                shift
                break
                ;;
            -*)
                die "Option inconnue : $1" 2
                ;;
            *)
                set_url "$1"
                shift
                ;;
        esac
    done

    # Après « -- », tout est positionnel (URL commençant par un tiret).
    while (($#)); do
        set_url "$1"
        shift
    done
}

main() {
    trap cleanup EXIT
    # Ctrl-C / kill : passer par exit pour que cleanup supprime les cookies exportés.
    trap 'exit 130' INT
    trap 'exit 143' TERM

    parse_args "$@"

    if [[ -z "$URL" ]]; then
        usage >&2
        exit 2
    fi

    validate_positive_integer "$CONCURRENT" "--concurrent"

    if [[ -n "$COOKIES_FROM_BROWSER" ]]; then
        validate_browser "$COOKIES_FROM_BROWSER"
    fi

    if [[ -n "$COOKIES_FROM_BROWSER" && -n "$COOKIES_FILE" ]]; then
        die "Utilise soit --cookies-from-browser, soit --cookies, mais pas les deux." 2
    fi

    if [[ -n "$COOKIES_FILE" && ! -f "$COOKIES_FILE" ]]; then
        die "Fichier cookies introuvable : $COOKIES_FILE" 2
    fi

    configure_utf8_environment
    check_dependencies
    prepare_output_dir
    write_log_header
    check_ytdlp_age
    run_download
}

main "$@"
