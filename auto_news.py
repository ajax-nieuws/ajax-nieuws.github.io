#!/usr/bin/env python3
"""Ajax Nieuws collector.

Volautomatische, dependency-vrije nieuwscollector voor een statische Ajax-nieuwssite.

Pipeline:
    bronnen -> normaliseren -> Ajax-relevantie -> blokkades -> deduplicatie
    -> gebeurtenisclustering -> ranking -> nieuws.json + kandidaten.json

Het script gebruikt uitsluitend de Python standard library en heeft geen API-key nodig.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CANDIDATES_OUTPUT = ROOT / "kandidaten.json"
NEWS_OUTPUT = ROOT / "nieuws.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_AGE_HOURS = 96
EVENT_WINDOW_HOURS = 48
MAX_EVENTS = 60
MAX_PER_SOURCE = 24

# Directe feeds waar mogelijk. Google News site-search wordt gebruikt voor bronnen
# zonder praktische clubfeed en als discovery-laag voor de officiële clubsite.
SOURCES = [
    {
        "publisher": "Ajax.nl",
        "mode": "google_site",
        "domain": "ajax.nl",
        "weight": 4.0,
        "ajax_specific": True,
        "official": True,
    },
    {
        "publisher": "Voetbal International",
        "mode": "rss",
        "strict_title": False,
        "url": "https://www.vi.nl/feed/news.xml?tag=ajax",
        "weight": 3.6,
        "ajax_specific": True,
    },
    {
        "publisher": "VoetbalPrimeur",
        "mode": "rss",
        "strict_title": False,
        "url": "https://www.voetbalprimeur.nl/feed/news.xml?tag=ajax",
        "weight": 3.0,
        "ajax_specific": True,
    },
    {
        "publisher": "AT5",
        "mode": "rss",
        "strict_title": False,
        "url": "https://rss.at5.nl/rss/ajax",
        "weight": 3.1,
        "ajax_specific": True,
    },
    {
        "publisher": "Ajax.supporters.nl",
        "mode": "rss",
        "strict_title": False,
        "url": "https://ajax.supporters.nl/nieuws/rss.xml",
        "weight": 2.3,
        "ajax_specific": True,
    },
    {
        "publisher": "NOS",
        "mode": "rss",
        "strict_title": True,
        "url": "https://feeds.nos.nl/nosvoetbal",
        "weight": 3.7,
        "ajax_specific": False,
    },
    {
        "publisher": "ESPN",
        "mode": "google_site",
        "strict_title": True,
        "domain": "espn.nl",
        "weight": 3.5,
        "ajax_specific": True,
    },
    {
        "publisher": "Ajax Showtime",
        "mode": "google_site",
        "strict_title": True,
        "domain": "ajaxshowtime.com",
        "weight": 2.9,
        "ajax_specific": True,
    },
    {
        "publisher": "De Telegraaf",
        "mode": "google_site",
        "strict_title": True,
        "domain": "telegraaf.nl",
        "weight": 3.2,
        "ajax_specific": True,
    },
    {
        "publisher": "AD",
        "mode": "google_site",
        "strict_title": True,
        "domain": "ad.nl",
        "weight": 3.1,
        "ajax_specific": True,
    },
    {
        "publisher": "NU.nl",
        "mode": "google_site",
        "strict_title": True,
        "domain": "nu.nl",
        "weight": 2.9,
        "ajax_specific": True,
    },
    {
        "publisher": "Voetbalzone",
        "mode": "google_site",
        "strict_title": True,
        "domain": "voetbalzone.nl",
        "weight": 2.6,
        "ajax_specific": True,
    },
    {
        "publisher": "FCUpdate",
        "mode": "google_site",
        "strict_title": True,
        "domain": "fcupdate.nl",
        "weight": 2.5,
        "ajax_specific": True,
    },
]

STOPWORDS = {
    "ajax", "afc", "amsterdam", "amsterdammers", "ajacied", "ajacieden",
    "over", "voor", "naar", "van", "het", "een", "zijn", "haar", "hun",
    "met", "bij", "uit", "door", "dat", "dit", "die", "deze", "maar",
    "ook", "nog", "wel", "niet", "meer", "minder", "tegen", "rond", "na",
    "op", "om", "in", "en", "of", "als", "dan", "tot", "te", "er",
    "wordt", "worden", "heeft", "hebben", "kan", "kunnen", "moet", "wil",
    "laat", "maakt", "maakt", "komt", "gaan", "gaat", "nieuwe", "nieuw",
    "laatste", "voetbal", "club", "speler", "spelers", "trainer", "coach",
    "team", "ploeg", "duel", "wedstrijd", "eredivisie", "seizoen", "live",
    "update", "nieuws", "bericht", "zegt", "vertelt", "reactie", "volgens",
}

# Content die we bewust niet publiceren. Naast rommel wordt kansspelcontent hard geweerd.
BLOCK_TERMS = {
    "wedden", "weddenschap", "weddenschappen", "odds", "bookmaker", "casino",
    "jackpot", "gok", "gokken", "inzet", "betting", "bet365", "unibet", "toto",
    "50x je inzet", "quotering", "quoteringen", "winactie", "vacature", "stage lopen",
    "podcast luisteren", "advertorial", "sponsored", "partnercontent",
}

AJAX_TERMS = {
    "ajax", "afc ajax", "ajacied", "ajacieden", "amsterdammers", "de toekomst",
    "johan cruijff arena", "jong ajax", "ajax vrouwen",
}

# Koppen die in club/tag-feeds terecht kunnen komen terwijl Ajax slechts zijdelings
# wordt genoemd. Bij deze formats eisen we dat Ajax ook echt in de kop staat.
BROAD_ROUNDUP_TERMS = {
    "alle clubs op een rij", "rondje europa", "vi live", "zo kijk je",
    "coëfficiënten", "coefficienten", "europese loting met perspectief",
    "transferoverzicht", "transfercarrousel", "dit zijn alle transfers",
}

OTHER_CLUB_TERMS = {
    "psv", "feyenoord", "fc twente", "az", "nec", "fc utrecht", "heerenveen",
    "groningen", "pec zwolle", "sparta", "go ahead eagles", "fortuna", "nac",
}

CATEGORY_TERMS = {
    "Transfers": {
        "transfer", "transfers", "akkoord", "overgang", "contract", "contractverlenging",
        "verlengt", "verlenging", "tekent", "getekend", "huurt", "huur", "verkocht",
        "vertrekt", "vertrek", "komt", "komst", "interesse", "bod", "onderhandelingen",
        "transfervrij", "overgenomen", "zaakwaarnemer", "miljoen",
    },
    "Blessures": {
        "blessure", "geblesseerd", "blessures", "uitgeschakeld", "herstel", "revalidatie",
        "schorsing", "geschorst", "afwezig", "fit", "twijfelgeval", "haakt af",
    },
    "Wedstrijden": {
        "opstelling", "basiself", "basisplaats", "voorbeschouwing", "nabespreking", "uitslag",
        "wint", "wonnen", "verlies", "verliest", "gelijkspel", "doelpunt", "score", "beker",
        "eredivisie", "conference league", "europa league", "champions league", "uefa",
        "knvb", "kwalificatie", "play-off", "return", "thuisduel", "uitduel", "wedstrijd",
    },
    "Selectie": {
        "training", "selectie", "basis", "reserve", "debuut", "debuut", "aanvoerder",
        "keeper", "verdediger", "middenvelder", "aanvaller", "speeltijd", "positie",
    },
    "Club": {
        "bestuur", "directie", "directeur", "technisch directeur", "algemeen directeur",
        "financieel", "begroting", "aandeelhouder", "arena", "stadion", "supporters",
        "kaartverkoop", "sponsor", "beleid", "organisatie", "commissaris",
    },
    "Jong Ajax": {"jong ajax", "keuken kampioen divisie", "kkd", "ajax o21", "ajax ii"},
    "Ajax Vrouwen": {"ajax vrouwen", "vrouwenelftal", "eredivisie vrouwen", "women's champions league"},
    "Jeugd": {"jeugd", "o17", "o18", "o19", "onder 17", "onder 18", "onder 19", "academy"},
}

GENERIC_EVENT_WORDS = {
    "ajax", "afc", "amsterdam", "amsterdammers", "ajacied", "ajacieden", "voetbal",
    "transfer", "transfers", "wedstrijd", "duel", "club", "speler", "spelers", "trainer",
    "nieuws", "update", "live", "eredivisie", "seizoen", "miljoen", "euro", "volgens",
}


def clean(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node, names: set[str]) -> str:
    for child in list(node):
        if lname(child.tag) in names and child.text and child.text.strip():
            return clean(child.text)
    return ""


def node_link(node) -> str:
    for child in list(node):
        if lname(child.tag) == "link":
            href = child.attrib.get("href")
            if href and child.attrib.get("rel", "alternate") in ("alternate", ""):
                return href.strip()
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def parse_date(value: str | None):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_feed(raw: bytes):
    root = ET.fromstring(raw)
    items = []
    for node in root.iter():
        if lname(node.tag) not in ("item", "entry"):
            continue
        title = child_text(node, {"title"})
        url = node_link(node)
        summary = child_text(node, {"description", "summary", "content", "encoded"})
        published = parse_date(child_text(node, {"pubdate", "published", "updated", "date"}))
        feed_source = child_text(node, {"source"})
        if title and url:
            items.append({
                "title": title,
                "url": url,
                "summary": summary,
                "published": published,
                "feed_source": feed_source,
            })
    return items


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def google_site_feed(domain: str) -> str:
    q = f'Ajax voetbal site:{domain} when:4d'
    params = urllib.parse.urlencode({"q": q, "hl": "nl", "gl": "NL", "ceid": "NL:nl"})
    return f"https://news.google.com/rss/search?{params}"


def source_url(source: dict) -> str:
    if source["mode"] == "rss":
        return source["url"]
    if source["mode"] == "google_site":
        return google_site_feed(source["domain"])
    raise ValueError(f"Onbekende source mode: {source['mode']}")


def normurl(url: str) -> str:
    try:
        parsed = urlparse(url)
        # Trackingparameters zijn voor deduplicatie niet relevant.
        return (parsed.netloc.lower() + parsed.path.rstrip("/")).lower()
    except Exception:
        return url.lower().rstrip("/")


def strip_source_suffix(title: str, publisher: str) -> str:
    title = clean(title)
    # Google News zet meestal " - Bronnaam" achter de titel.
    for suffix in {publisher, "Ajax.nl", "Voetbal International", "VoetbalPrimeur", "ESPN", "AD", "NU.nl", "De Telegraaf"}:
        if suffix and title.lower().endswith((" - " + suffix).lower()):
            return title[: -(len(suffix) + 3)].rstrip()
    return title


def is_blocked(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(term in text for term in BLOCK_TERMS)


def title_mentions_ajax(title: str) -> bool:
    text = clean(title).lower()
    return any(term in text for term in AJAX_TERMS)


def is_ajax_relevant(title: str, summary: str, ajax_specific: bool, strict_title: bool = False) -> bool:
    title_text = clean(title).lower()
    text = clean(f"{title} {summary}").lower()
    if is_blocked(title, summary):
        return False
    if any(noise in text for noise in ("javascript ajax", "ajax request", "ajax call", "amsterdamsche football club ajax cricket")):
        return False

    title_has_ajax = title_mentions_ajax(title)
    body_has_ajax = any(term in text for term in AJAX_TERMS)

    # Brede feeds zoals NOS leveren alleen een item als Ajax expliciet in de kop staat.
    # Dit voorkomt algemene UEFA-, PSV- en Feyenoordberichten die Ajax alleen in de tekst noemen.
    if strict_title:
        return title_has_ajax

    if not ajax_specific:
        return title_has_ajax

    # In Ajax/tag-feeds mogen spelerkoppen zonder het woord Ajax blijven staan, maar
    # generieke roundups en multi-clubkoppen alleen als Ajax zelf in de titel staat.
    if not title_has_ajax:
        if any(term in title_text for term in BROAD_ROUNDUP_TERMS):
            return False
        other_club_hits = sum(1 for club in OTHER_CLUB_TERMS if club in title_text)
        if other_club_hits >= 2:
            return False
        # Een club/tag-feed is nuttig voor koppen als 'Tolu verovert Amsterdam'.
        # We verlangen dan wel dat Ajax in titel + omschrijving terugkomt.
        return body_has_ajax

    return True


def category_hint(title: str, summary: str) -> str:
    title_text = clean(title).lower()
    full_text = clean(f"{title} {summary}").lower()

    # Expliciete subteams eerst. Een samenvatting met transferwoorden mag een
    # Jong Ajax- of Ajax Vrouwen-kop niet onbedoeld naar Transfers trekken.
    if "jong ajax" in title_text or "ajax o21" in title_text:
        return "Jong Ajax"
    if "ajax vrouwen" in title_text or "vrouwenelftal" in title_text:
        return "Ajax Vrouwen"

    scores = {}
    for category, terms in CATEGORY_TERMS.items():
        # Woorden in de kop wegen drie keer zwaarder dan woorden die alleen in
        # de RSS-omschrijving voorkomen. Dat maakt de classificatie veel stabieler.
        title_score = sum(3 for term in terms if term in title_text)
        body_score = sum(1 for term in terms if term in full_text)
        score = title_score + body_score
        if score:
            scores[category] = score

    # Een expliciet transferwoord in de kop wint van selectiecontext in de teaser.
    if any(term in title_text for term in ("transfer", "transfers", "akkoord", "vertrek", "vertrekt", "interesse", "bod", "deal", "target")):
        scores["Transfers"] = scores.get("Transfers", 0) + 5

    if not scores:
        return "Overig"
    return max(scores, key=lambda c: (scores[c], -list(CATEGORY_TERMS).index(c)))


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9à-ÿ]+", clean(title).lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def subject_tokens(title: str) -> set[str]:
    return {w for w in title_tokens(title) if w not in GENERIC_EVENT_WORDS}


def article_id(source: str, title: str, url: str) -> str:
    raw = f"{source}|{title}|{url}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:14]


def hours_between(a: dict, b: dict) -> float:
    da = a.get("published_dt")
    db = b.get("published_dt")
    if not da or not db:
        return 0.0
    return abs((da - db).total_seconds()) / 3600


def weighted_similarity(a: dict, b: dict, df: Counter, total_docs: int) -> float:
    ta = subject_tokens(a["title"])
    tb = subject_tokens(b["title"])
    if not ta or not tb:
        return 0.0
    union = ta | tb
    intersection = ta & tb

    def weight(token: str) -> float:
        return 1.0 + math.log((total_docs + 1) / (df.get(token, 0) + 1))

    denom = sum(weight(t) for t in union)
    if not denom:
        return 0.0
    return sum(weight(t) for t in intersection) / denom


def same_event(a: dict, b: dict, df: Counter, total_docs: int) -> bool:
    if hours_between(a, b) > EVENT_WINDOW_HOURS:
        return False

    ta, tb = subject_tokens(a["title"]), subject_tokens(b["title"])
    overlap = ta & tb
    sim = weighted_similarity(a, b, df, total_docs)

    # Exact/near-exact titels.
    if sim >= 0.50:
        return True

    # Transfer- en blessureberichten hebben vaak sterk afwijkende koppen, maar dezelfde naam.
    if a["category"] == b["category"] and a["category"] in {"Transfers", "Blessures"}:
        rare_overlap = [t for t in overlap if df.get(t, 99) <= max(3, total_docs // 5)]
        # Eén zeldzame eigennaam is bij transfers/blessures vaak het onderwerp zelf.
        # Voorbeeld: "akkoord over Tsygankov" vs. "Tsygankov op weg naar Amsterdam".
        if any(len(token) >= 6 for token in rare_overlap) and sim >= 0.10:
            return True

    # Twee of meer inhoudelijke gedeelde tokens is meestal voldoende buiten wedstrijdanalyse.
    if len(overlap) >= 2 and a["category"] == b["category"] and sim >= 0.28:
        return True

    # Wedstrijdverslagen van exact hetzelfde duel hebben vaak totaal andere koppen.
    # Een zeldzame tegenstander + resultaatwoord binnen acht uur is genoeg om ze
    # als hetzelfde nieuwsfeit te behandelen. Analyses en opstellingen blijven los.
    if a["category"] == b["category"] == "Wedstrijden":
        result_words = {"wint", "winst", "zege", "verlies", "gelijkspel", "kwalificatie", "ticket", "goals", "doelpunten"}
        a_result = bool(title_tokens(a["title"]) & result_words)
        b_result = bool(title_tokens(b["title"]) & result_words)
        rare_overlap = [t for t in overlap if df.get(t, 99) <= max(4, total_docs // 6)]
        if hours_between(a, b) <= 8 and a_result and b_result and any(len(t) >= 4 for t in rare_overlap):
            return True
        return len(overlap) >= 3 and sim >= 0.36

    return False


def freshness_score(hours_old: float | None) -> float:
    if hours_old is None:
        return 0.0
    if hours_old <= 3:
        return 5.0
    if hours_old <= 12:
        return 4.0
    if hours_old <= 24:
        return 3.0
    if hours_old <= 48:
        return 1.8
    if hours_old <= 72:
        return 0.8
    return 0.0


def article_rank(item: dict) -> float:
    category_bonus = {
        "Transfers": 1.0,
        "Blessures": 0.7,
        "Wedstrijden": 0.6,
        "Club": 0.4,
        "Selectie": 0.2,
        "Jong Ajax": -0.7,
        "Ajax Vrouwen": -0.7,
        "Jeugd": -0.8,
        "Overig": 0.0,
    }.get(item["category"], 0.0)
    return item["source_weight"] * 3 + freshness_score(item["hours_old"]) + category_bonus + (2.5 if item.get("official") else 0)


def collect():
    now = datetime.now(timezone.utc)
    candidates = []
    errors = []
    seen_urls = set()
    per_source = Counter()

    for source in SOURCES:
        try:
            items = parse_feed(fetch(source_url(source)))
        except Exception as exc:
            errors.append(f"{source['publisher']}: {type(exc).__name__}: {exc}")
            continue

        for raw in items:
            if per_source[source["publisher"]] >= MAX_PER_SOURCE:
                break

            title = strip_source_suffix(raw["title"], source["publisher"])
            summary = clean(raw["summary"])
            if not is_ajax_relevant(title, summary, source.get("ajax_specific", False), source.get("strict_title", False)):
                continue

            published = raw["published"]
            age = None
            if published is not None:
                age = max(0.0, (now - published).total_seconds() / 3600)
                if age > MAX_AGE_HOURS:
                    continue

            key = normurl(raw["url"])
            if key in seen_urls:
                continue
            seen_urls.add(key)

            item = {
                "id": article_id(source["publisher"], title, raw["url"]),
                "source": source["publisher"],
                "title": title,
                "summary": summary[:500],
                "url": raw["url"],
                "published": published.isoformat() if published else None,
                "published_dt": published,
                "hours_old": round(age, 1) if age is not None else None,
                "category": category_hint(title, summary),
                "source_weight": source.get("weight", 1.0),
                "official": bool(source.get("official")),
                "discovery": source["mode"],
                "via_google_news": "news.google.com" in urlparse(raw["url"]).netloc.lower(),
            }
            candidates.append(item)
            per_source[source["publisher"]] += 1

    return candidates, errors


def cluster_events(items: list[dict]) -> list[list[dict]]:
    if not items:
        return []

    df = Counter()
    for item in items:
        df.update(subject_tokens(item["title"]))
    total_docs = len(items)

    # Beste/nieuwste artikelen eerst als clusteranker.
    pool = sorted(
        items,
        key=lambda x: (
            -article_rank(x),
            x["hours_old"] if x["hours_old"] is not None else 9999,
        ),
    )

    clusters: list[list[dict]] = []
    for item in pool:
        target = None
        best_score = 0.0
        for cluster in clusters:
            # Vergelijk met alle artikelen in het cluster. Dat vangt kopvarianten op
            # die inhoudelijk via een tweede bron aan hetzelfde nieuwsfeit hangen.
            cluster_score = 0.0
            matched = False
            for other in cluster:
                if same_event(item, other, df, total_docs):
                    matched = True
                    cluster_score = max(
                        cluster_score,
                        weighted_similarity(item, other, df, total_docs),
                    )
            if matched and cluster_score >= best_score:
                best_score = cluster_score
                target = cluster
        if target is None:
            clusters.append([item])
        else:
            target.append(item)
            target.sort(key=lambda x: -article_rank(x))
    return clusters


def event_from_cluster(cluster: list[dict]) -> dict:
    primary = max(cluster, key=article_rank)
    unique_by_source = {}
    for article in sorted(cluster, key=article_rank, reverse=True):
        unique_by_source.setdefault(article["source"], article)
    source_articles = list(unique_by_source.values())
    source_articles.sort(key=article_rank, reverse=True)

    dated = [x for x in cluster if x.get("published_dt")]
    earliest = min((x["published_dt"] for x in dated), default=None)
    latest = max((x["published_dt"] for x in dated), default=None)

    stable_basis = min((normurl(x["url"]) for x in cluster), default=primary["id"])
    event_id = hashlib.sha1(stable_basis.encode("utf-8")).hexdigest()[:14]

    related = [
        {
            "name": x["source"],
            "url": x["url"],
            "via_google_news": x["via_google_news"],
        }
        for x in source_articles[1:5]
    ]

    return {
        "id": event_id,
        "title": primary["title"],
        "category": primary["category"],
        "published": earliest.isoformat() if earliest else primary.get("published"),
        "updated": latest.isoformat() if latest else primary.get("published"),
        "source_count": len(source_articles),
        "official_confirmation": any(x.get("official") for x in cluster),
        "primary_source": {
            "name": primary["source"],
            "url": primary["url"],
            "via_google_news": primary["via_google_news"],
        },
        "related_sources": related,
    }


def event_sort_key(event: dict):
    stamp = event.get("updated") or event.get("published") or "1970-01-01T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        ts = dt.timestamp()
    except Exception:
        ts = 0
    corroboration = min(event.get("source_count", 1), 4) * 0.02
    return ts + corroboration


def write_outputs(candidates: list[dict], events: list[dict], errors: list[str]):
    generated = datetime.now(timezone.utc).isoformat()

    debug_candidates = []
    for item in sorted(candidates, key=lambda x: (x["hours_old"] if x["hours_old"] is not None else 9999)):
        copy = {k: v for k, v in item.items() if k != "published_dt"}
        copy["rank"] = round(article_rank(item), 2)
        debug_candidates.append(copy)

    candidates_data = {
        "meta": {
            "generated_at": generated,
            "generator": "Ajax Nieuws collector 1.1",
            "raw_candidates": len(candidates),
            "feed_errors": errors,
        },
        "candidates": debug_candidates,
    }
    CANDIDATES_OUTPUT.write_text(json.dumps(candidates_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    news_data = {
        "meta": {
            "generated_at": generated,
            "generator": "Ajax Nieuws collector 1.1",
            "article_count": len(candidates),
            "event_count": len(events),
            "source_count": len({x["source"] for x in candidates}),
            "feed_error_count": len(errors),
            "max_age_hours": MAX_AGE_HOURS,
            "note": "Onafhankelijke nieuwsaggregator. Niet verbonden aan AFC Ajax.",
        },
        "events": events[:MAX_EVENTS],
    }
    NEWS_OUTPUT.write_text(json.dumps(news_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    candidates, errors = collect()
    clusters = cluster_events(candidates)
    events = [event_from_cluster(cluster) for cluster in clusters]
    events.sort(key=event_sort_key, reverse=True)
    write_outputs(candidates, events, errors)

    print(f"Artikelen: {len(candidates)}")
    print(f"Gebeurtenissen: {len(events)}")
    print(f"Bronnen: {len({x['source'] for x in candidates})}")
    print(f"Bronfouten: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("Geschreven: kandidaten.json, nieuws.json")


if __name__ == "__main__":
    main()
