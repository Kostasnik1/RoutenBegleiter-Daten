"""
Schutz vor kaputten Daten: Eine neue Datei wird nur veröffentlicht, wenn sie nicht drastisch kleiner ist als die
bisherige im Release "data" (z. B. weil eine Behörde ihr Format geändert hat und nur noch die Hälfte erkannt wird).
Lieber ein paar Stunden alte, aber vollständige Daten als frische, kaputte.
"""
import gzip, json, os, urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "Kostasnik1/RoutenBegleiter-Daten")


def previous(name):
    """Bisherige Fassung aus dem Release "data" (oder None)."""
    url = f"https://github.com/{REPO}/releases/download/data/{name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RoutenBegleiter-Daten"})
        b = urllib.request.urlopen(req, timeout=90).read()
        if b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
        return json.loads(b)
    except Exception:
        return None


def plausible(name, new_count, count, min_ratio=0.6):
    """(ok, Text) – ok=False, wenn die neue Datei weniger als min_ratio der bisherigen Einträge hat."""
    prev = previous(name)
    if prev is None:
        return True, f"{new_count} (keine Vorversion)"
    try:
        old = count(prev)
    except Exception:
        return True, f"{new_count} (Vorversion unlesbar)"
    if old and new_count < old * min_ratio:
        return False, f"nur {new_count} statt bisher {old} – Format geändert?"
    return True, f"{new_count} (bisher {old})"
