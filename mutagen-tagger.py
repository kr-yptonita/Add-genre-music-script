import os
import logging
import argparse
import time
import secrets  # Importing secrets.py
import mutagen
from mutagen.id3 import ID3, ID3NoHeaderError, TCON, COMM
from mutagen.flac import FLAC
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

SUPPORTED_EXTENSIONS = ('.mp3', '.flac')

# ---------------------------------------------------------------------------
# Genre providers
# ---------------------------------------------------------------------------

def get_genre_spotify(sp, artist, track):
    """Query Spotify for genres. Returns title-cased comma-separated string or None."""
    try:
        results = sp.search(q='artist:' + artist + ' track:' + track, type='track')
        items = results['tracks']['items']
        if items:
            track_id = items[0]['id']
            track_info = sp.track(track_id)
            artist_id = track_info['artists'][0]['id']
            artist_info = sp.artist(artist_id)
            genres = artist_info['genres']
            if genres:
                logging.debug(f"[Spotify] Genres for {artist} - {track}: {genres}")
                return ', '.join(g.title() for g in genres)
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 429:
            retry_after = int(e.headers.get('Retry-After', 1))
            logging.warning(f"[Spotify] Rate limiting, sleeping for {retry_after}s")
            time.sleep(retry_after)
            return get_genre_spotify(sp, artist, track)
        else:
            logging.error(f"[Spotify] API error: {e}")
    except Exception as e:
        logging.error(f"[Spotify] Error: {e}")
    return None


def get_genre_lastfm(network, artist, track):
    """Query Last.fm for top tags. Returns title-cased comma-separated string or None."""
    try:
        import pylast
        lastfm_track = network.get_track(artist, track)
        top_tags = lastfm_track.get_top_tags(limit=5)
        # Filter out generic/meta tags and keep meaningful genre tags
        skip = {'seen live', 'favorites', 'favourite', 'love', 'loved', 'awesome',
                'great', 'good', 'best', 'cool', 'amazing', 'beautiful', 'classic'}
        genres = [t.item.get_name() for t in top_tags
                  if t.item.get_name().lower() not in skip]
        if genres:
            logging.debug(f"[Last.fm] Genres for {artist} - {track}: {genres}")
            return ', '.join(g.title() for g in genres)
    except Exception as e:
        logging.debug(f"[Last.fm] No result for {artist} - {track}: {e}")
    return None


def get_genre_discogs(d_client, artist, track):
    """Query Discogs for genre/style. Returns title-cased comma-separated string or None."""
    try:
        results = d_client.search(f"{artist} {track}", type='release')
        page = results.page(1)
        if page:
            release = page[0]
            genres = getattr(release, 'genres', []) or []
            styles = getattr(release, 'styles', []) or []
            combined = genres + styles
            if combined:
                logging.debug(f"[Discogs] Genres for {artist} - {track}: {combined}")
                return ', '.join(g.title() for g in combined)
    except Exception as e:
        logging.debug(f"[Discogs] No result for {artist} - {track}: {e}")
    return None


def _fetch_wiki_genre(query):
    import wikipedia
    import requests
    from bs4 import BeautifulSoup
    import re

    try:
        search = wikipedia.search(query, results=3)
        if not search: return None
        
        title = search[0]
        url = f'https://en.wikipedia.org/wiki/{title.replace(" ", "_")}'
        headers = { 'User-Agent': 'Mozilla/5.0' }
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200: return None
        
        soup = BeautifulSoup(res.text, 'html.parser')
        infobox = soup.find('table', {'class': 'infobox'})
        if not infobox: return None
        
        for tr in infobox.find_all('tr'):
            th = tr.find('th')
            if th and 'genre' in th.get_text(strip=True).lower():
                td = tr.find('td')
                if not td: return None
                
                for sup in td.find_all('sup'):
                    sup.decompose()
                
                items = []
                lis = td.find_all('li')
                if lis:
                    for li in lis: items.append(li.get_text(strip=True))
                else:
                    text = td.get_text(separator=' | ')
                    items = re.split(r'[\|,]', text)
                    
                genres = [i.strip().title() for i in items if i.strip()]
                return ', '.join(genres)
        return None
    except Exception as e:
        logging.debug(f"[Wikipedia] Error for query '{query}': {e}")
        return None


def get_genre_wikipedia_track(client, artist, track):
    """Query Wikipedia for the song's genre."""
    query = f'{track} {artist} song'
    res = _fetch_wiki_genre(query)
    if res:
        logging.debug(f"[Wikipedia-Track] Genres for {artist} - {track}: {res}")
    return res


def get_genre_wikipedia_artist(client, artist, track):
    """Query Wikipedia for the artist's genre."""
    query = f'{artist} musician'
    res = _fetch_wiki_genre(query)
    if res:
        logging.debug(f"[Wikipedia-Artist] Genres for {artist}: {res}")
    return res


def get_genre(providers, artist, track):
    """
    Try each provider in order. Returns the first non-empty result.
    providers: list of (name, callable, client) tuples
    """
    for name, fn, client in providers:
        try:
            result = fn(client, artist, track)
            if result:
                logging.info(f"  Genre found via {name}: {result}")
                return result
        except Exception as e:
            logging.debug(f"[{name}] Exception: {e}")
    return None


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def output_metatdata(file_path):
    try:
        audiofile = mutagen.File(file_path, easy=False)
        if audiofile is not None:
            logging.info(f"\n\nSuccessfully read metadata for {file_path}")
            for key, value in audiofile.items():
                logging.info(f"{key}: {value}")
        else:
            logging.warning(f"\n\nNo metadata found for {file_path}")
        return audiofile
    except Exception as e:
        logging.error(f"\n\nError reading metadata for {file_path}: {e}")
        return None


def is_flac(file_path):
    return file_path.lower().endswith('.flac')


def extract_metadata(file_path):
    try:
        audiofile = mutagen.File(file_path, easy=True)
        if audiofile is not None:
            artist = audiofile.get('artist', [None])[0]
            title = audiofile.get('title', [None])[0]
            if is_flac(file_path):
                comments = audiofile.get('comment', [None])[0]
                genre = audiofile.get('genre', [None])[0]
            else:
                comments = audiofile.get('COMM::eng', [None])[0]
                genre = audiofile.get('TCON', [None])[0]
            if artist and title:
                return artist, title, comments, genre
            else:
                logging.warning("Artist or title tag not found.")
                return None, None, None, None
        else:
            logging.error(f"The file {file_path} is not a supported audio file or does not contain tags")
            return None, None, None, None
    except Exception as e:
        logging.error(f"An error occurred while extracting metadata: {e}")
        return None, None, None, None


def update_genre(file_path, genre):
    try:
        audiofile = mutagen.File(file_path, easy=True)
        if audiofile is not None:
            audiofile['genre'] = genre
            audiofile.save()
            logging.info(f"Genre updated to '{genre}' for {file_path}")
        else:
            logging.info(f"The file {file_path} is not a supported audio file or does not contain tags")
    except Exception as e:
        logging.error(f"An error occurred while updating the genre: {e}")


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_file(providers, file_path):
    """
    Process a single file. Returns (filename, final_genre_or_None).
    """
    filename = os.path.basename(file_path)
    artist, title, comments, genre = extract_metadata(file_path)

    if artist and title:
        if genre:
            logging.info(f"Genre already set to '{genre}' for {file_path}, skipping.\n")
            return filename, genre

        new_genre = get_genre(providers, artist, title)

        if new_genre:
            update_genre(file_path, new_genre)
            return filename, new_genre
        else:
            logging.warning(f"Genre for {artist} - {title} could not be determined.\n")
            return filename, None
    else:
        logging.warning("Either artist or title or both were not found in the file's metadata.\n")
        return filename, None


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Update genre metadata in MP3 and FLAC files.")
    parser.add_argument("-p", "--path", type=str,
                        help="Path to an audio file or directory containing audio files",
                        required=True)
    parser.add_argument("--no-recurse", action="store_true", help="Do not search in subdirectories")
    parser.add_argument("--no-spotify", action="store_true", help="Disable Spotify lookup")
    parser.add_argument("--no-lastfm",  action="store_true", help="Disable Last.fm lookup")
    parser.add_argument("--no-discogs", action="store_true", help="Disable Discogs lookup")
    parser.add_argument("--no-wikipedia", action="store_true", help="Disable Wikipedia lookup")
    parser.add_argument("--report", type=str, default=None,
                        help="Path to write the genre report file (default: genre_report.txt next to the audio path)")
    args = parser.parse_args()

    # Build provider chain ------------------------------------------------
    providers = []

    # Spotify
    if not args.no_spotify:
        try:
            ccm = SpotifyClientCredentials(
                client_id=secrets.CLIENT_ID,
                client_secret=secrets.CLIENT_SECRET
            )
            sp = spotipy.Spotify(client_credentials_manager=ccm)
            providers.append(('Spotify', get_genre_spotify, sp))
            logging.info("Spotify: enabled")
        except Exception as e:
            logging.warning(f"Spotify: disabled ({e})")

    # Last.fm
    if not args.no_lastfm:
        try:
            import pylast
            api_key = getattr(secrets, 'LASTFM_API_KEY', '')
            api_secret = getattr(secrets, 'LASTFM_API_SECRET', '')
            if api_key and api_secret:
                network = pylast.LastFMNetwork(api_key=api_key, api_secret=api_secret)
                providers.append(('Last.fm', get_genre_lastfm, network))
                logging.info("Last.fm: enabled")
            else:
                logging.info("Last.fm: disabled (no credentials in secrets.py)")
        except ImportError:
            logging.warning("Last.fm: disabled (pylast not installed)")

    # Discogs
    if not args.no_discogs:
        try:
            import discogs_client
            token = getattr(secrets, 'DISCOGS_USER_TOKEN', '')
            if token:
                d = discogs_client.Client('mutagen-tagger/1.0', user_token=token)
                providers.append(('Discogs', get_genre_discogs, d))
                logging.info("Discogs: enabled")
            else:
                logging.info("Discogs: disabled (no token in secrets.py)")
        except ImportError:
            logging.warning("Discogs: disabled (python3-discogs-client not installed)")

    # Wikipedia
    if not args.no_wikipedia:
        try:
            import wikipedia
            from bs4 import BeautifulSoup
            import requests
            # Add both providers. Client is None.
            providers.append(('Wikipedia (Track)', get_genre_wikipedia_track, None))
            providers.append(('Wikipedia (Artist)', get_genre_wikipedia_artist, None))
            logging.info("Wikipedia: enabled")
        except ImportError:
            logging.warning("Wikipedia: disabled (wikipedia or beautifulsoup4 not installed)")

    if not providers:
        logging.error("No genre providers are available. Add credentials to secrets.py.")
        return

    # Process files -------------------------------------------------------
    expanded_path = os.path.expanduser(args.path)
    results = []  # list of (filename, genre_or_None)

    if os.path.isdir(expanded_path):
        if args.no_recurse:
            for filename in sorted(os.listdir(expanded_path)):
                file_path = os.path.join(expanded_path, filename)
                if os.path.isfile(file_path) and filename.lower().endswith(SUPPORTED_EXTENSIONS):
                    logging.info('Found: ' + file_path)
                    results.append(process_file(providers, file_path))
        else:
            for root, _, files in os.walk(expanded_path):
                for filename in sorted(files):
                    if filename.lower().endswith(SUPPORTED_EXTENSIONS):
                        file_path = os.path.join(root, filename)
                        logging.info('Found: ' + file_path)
                        results.append(process_file(providers, file_path))
    elif os.path.isfile(expanded_path) and expanded_path.lower().endswith(SUPPORTED_EXTENSIONS):
        results.append(process_file(providers, expanded_path))
    else:
        logging.error(f"The specified path does not exist or is not a supported audio file: {expanded_path}\n")
        return

    # Write report --------------------------------------------------------
    if results:
        with_genre    = [(f, g) for f, g in results if g]
        without_genre = [(f, g) for f, g in results if not g]
        total = len(results)

        # Determine report path
        if args.report:
            report_path = os.path.expanduser(args.report)
        elif os.path.isdir(expanded_path):
            report_path = os.path.join(expanded_path, 'genre_report.txt')
        else:
            report_path = os.path.join(os.path.dirname(expanded_path), 'genre_report.txt')

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"Genre Report\n")
            f.write(f"{'=' * 60}\n")
            f.write(f"Total files processed : {total}\n")
            f.write(f"With genre tag        : {len(with_genre)} ({len(with_genre)*100//total}%)\n")
            f.write(f"Without genre tag     : {len(without_genre)} ({len(without_genre)*100//total}%)\n")
            f.write(f"{'=' * 60}\n\n")

            f.write(f"✔ WITH GENRE ({len(with_genre)} files)\n")
            f.write(f"{'-' * 60}\n")
            for fname, genre in with_genre:
                f.write(f"  {fname}\n")
                f.write(f"    → {genre}\n")

            f.write(f"\n✘ WITHOUT GENRE ({len(without_genre)} files)\n")
            f.write(f"{'-' * 60}\n")
            for fname, _ in without_genre:
                f.write(f"  {fname}\n")

        logging.info(f"\nReport written to: {report_path}")
        logging.info(f"Summary: {len(with_genre)}/{total} files have a genre tag.")


if __name__ == "__main__":
    main()