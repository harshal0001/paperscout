"""Europe PMC REST search: PubMed (SRC:MED) + preprints (SRC:PPR), no API key."""
import html
import re
import time

import httpx

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SOURCES = "(SRC:MED OR SRC:PPR)"
_TAG = re.compile(r"<[^>]+>")


class SearchError(RuntimeError):
    pass


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def search(query, page_size=25, client=None, retries=2, backoff=1.5):
    """Raw Europe PMC results for one query. Retries only 503 (observed transient); other errors raise with the body."""
    client = client or httpx.Client(timeout=30)
    params = {"query": f"({query}) AND {SOURCES}", "format": "json", "resultType": "core", "pageSize": page_size}
    for attempt in range(retries + 1):
        r = client.get(BASE, params=params)
        if r.status_code == 503 and attempt < retries:
            time.sleep(backoff * (attempt + 1))
            continue
        if r.status_code != 200:
            raise SearchError(f"Europe PMC HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if "resultList" not in body:
            raise SearchError(f"Europe PMC unexpected body: {r.text[:200]}")
        return body["resultList"].get("result", [])


def normalize(r):
    """Flatten one Europe PMC record into the paper shape the app uses."""
    source, rid = r.get("source", ""), r.get("id", "")
    doi = r.get("doi")
    journal = (r.get("journalInfo") or {}).get("journal", {}).get("title") or r.get("journalTitle") or (
        "Preprint" if source == "PPR" else "")
    authors = r.get("authorString") or ""
    return {
        "key": (f"pmid:{r['pmid']}" if r.get("pmid") else f"doi:{doi.lower()}" if doi else f"{source}:{rid}"),
        "id": rid,
        "source": source,
        "pmid": r.get("pmid"),
        "pmcid": r.get("pmcid"),
        "doi": doi,
        "title": clean(r.get("title")),
        "abstract": clean(r.get("abstractText")),
        "authors": authors if len(authors) <= 120 else authors[:117].rsplit(",", 1)[0] + ", et al.",
        "journal": journal,
        "year": int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
        "cited_by": r.get("citedByCount") or 0,
        "open_access": r.get("isOpenAccess") == "Y",
        "pub_types": (r.get("pubTypeList") or {}).get("pubType", []),
        "preprint": source == "PPR",
        "url": f"https://europepmc.org/article/{source}/{rid}",
    }
