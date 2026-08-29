# Ajax Nieuws

Een lichte Nederlandstalige webapp die automatisch recent nieuws over AFC Ajax uit meerdere bronnen verzamelt, dubbele berichten zoveel mogelijk clustert en via GitHub Pages publiceert.

**Onafhankelijk project. Niet verbonden aan AFC Ajax.**

## Wat deze MVP doet

- haalt nieuws op uit Ajax-gerichte RSS-feeds en gerichte Google News-feeds;
- filtert op Ajax-relevantie;
- blokkeert kansspel-, advertorial- en andere ongewenste content;
- categoriseert berichten;
- clustert verschillende artikelen over hetzelfde nieuwsfeit;
- kiest een primaire bron op basis van betrouwbaarheid en actualiteit;
- toont aanvullende bronnen bij hetzelfde nieuwsfeit;
- schrijft `nieuws.json` voor de statische frontend;
- draait automatisch twee keer per uur;
- publiceert in dezelfde GitHub Action rechtstreeks naar GitHub Pages;
- heeft geen database, nieuwsbrief of API-key nodig.

## Bronnen in versie 1

Directe feeds:
- Voetbal International, Ajax-feed
- VoetbalPrimeur, Ajax-feed
- AT5, Ajax-feed
- Ajax.supporters.nl
- NOS Sport Voetbal

Gerichte Google News discovery:
- Ajax.nl
- ESPN
- Ajax Showtime
- De Telegraaf
- AD
- NU.nl
- Voetbalzone
- FCUpdate

Google News-links worden alleen gebruikt waar geen praktische directe clubfeed is opgenomen. De website vermeldt dat duidelijk.

## Online zetten

1. Maak op GitHub een nieuwe repository, bijvoorbeeld `ajax-nieuws`.
2. Zet alle bestanden uit deze map in de repository en push naar `main`.
3. Ga in GitHub naar **Settings > Pages**.
4. Kies bij **Build and deployment** als Source: **GitHub Actions**.
5. Ga naar **Actions > Ajax nieuws ophalen en publiceren** en kies **Run workflow**.
6. Na een succesvolle run staat de Pages-URL bij de deployment.

Daarna draait de collector automatisch om minuut `17` en `47` van ieder uur, in tijdzone `Europe/Amsterdam`.

## Geen secrets nodig

Versie 1 gebruikt geen betaalde AI-API. Er hoeft dus geen API-key in GitHub Secrets.

## Data

`kandidaten.json` bevat de technische artikelenlijst voor debugging.

`nieuws.json` is het publieke frontend-contract:

```json
{
  "meta": {"generated_at": "..."},
  "events": [
    {
      "id": "...",
      "title": "...",
      "category": "Transfers",
      "published": "...",
      "updated": "...",
      "source_count": 3,
      "official_confirmation": false,
      "primary_source": {"name": "...", "url": "..."},
      "related_sources": []
    }
  ]
}
```

## Clustering

De clustering is bewust zonder AI gebouwd. Hij gebruikt onder meer:
- inhoudelijke titelwoorden;
- zeldzame gedeelde woorden/namen;
- categorie;
- tijdsafstand;
- strengere regels voor wedstrijdartikelen dan voor transfer- en blessureberichten.

Dat is goedkoop, uitlegbaar en direct inzetbaar. Als praktijkdata laat zien dat er nog te veel dubbele transferberichten doorheen glippen, kan later een optionele semantische/LLM-laag bovenop `cluster_events()` worden gezet.

## Belangrijk voor commercieel gebruik

Controleer vóór advertenties, betaalde toegang of andere commerciële exploitatie altijd de actuele gebruiksvoorwaarden van iedere bron en RSS-feed. Deze MVP is opgezet als onafhankelijke nieuwsaggregator en neemt geen volledige artikelen over.
