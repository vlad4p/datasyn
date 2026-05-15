"""Boletín Oficial (Argentina): tercera sección — listado de avisos y descarga de PDF por ítem.

Sitio: https://www.boletinoficial.gob.ar/seccion/tercera — la rama *Contrataciones* de la
tercera sección se sirve en ``/seccion/tercera[/YYYYMMDD]``. Cada aviso enlaza a
``/detalleAviso/tercera/<id>/<YYYYMMDD>``. El PDF por aviso se obtiene vía POST JSON
(``pdfBase64``) como hace el sitio en ``/js/downloadPdf.js``.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BOA_BASE = "https://www.boletinoficial.gob.ar"
USER_AGENT = (
    "Mozilla/5.0 (compatible; DatacyberDatasyn/1.0; +https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

log = logging.getLogger("datasyn.boa")


@dataclass(frozen=True)
class BoletinTerceraItem:
    """Un aviso de contrataciones en la portada de la tercera sección."""

    rubro: str
    aviso_id: str
    fecha_publicacion_ymd: str
    organismo: str
    detalle: str
    detalle_url: str


def ymd_from_date(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


def section_url(ymd: str) -> str:
    return f"{BOA_BASE}/seccion/tercera/{ymd}"


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9",
        },
        timeout=httpx.Timeout(60.0),
        follow_redirects=True,
    )


_HREF_AVISO = re.compile(
    r"^/detalleAviso/tercera/(?P<id>\d+)/(?P<ymd>\d{8})$",
    re.I,
)


def parse_tercera_index(html: str) -> list[BoletinTerceraItem]:
    """Parsea la portada HTML de la tercera sección: rubros ``h5.seccion-rubro`` + enlaces a avisos."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div#avisosSeccionDiv") or soup.select_one("div.avisosSeccionDiv")
    if not root:
        log.warning("avisosSeccionDiv not found in BOA HTML")
        return []

    current_rubro = ""
    out: list[BoletinTerceraItem] = []

    for row in root.find_all("div", class_="row"):
        h5 = row.find("h5", class_=lambda c: bool(c) and "seccion-rubro" in c)
        if h5:
            current_rubro = h5.get_text(" ", strip=True)
            continue

        for a in row.find_all("a", href=True):
            href = str(a.get("href", "")).strip().split("#")[0].split("?")[0]
            m = _HREF_AVISO.match(href)
            if not m:
                continue
            aviso_id = m.group("id")
            ymd = m.group("ymd")
            org_el = row.select_one("p.item")
            det_el = row.select_one("p.item-detalle small")
            organismo = org_el.get_text(" ", strip=True) if org_el else ""
            detalle = det_el.get_text(" ", strip=True) if det_el else ""
            abs_url = urljoin(BOA_BASE, href)
            out.append(
                BoletinTerceraItem(
                    rubro=current_rubro,
                    aviso_id=aviso_id,
                    fecha_publicacion_ymd=ymd,
                    organismo=organismo,
                    detalle=detalle,
                    detalle_url=abs_url,
                )
            )

    # de-dup por (id, ymd) conservando el primero
    seen: set[tuple[str, str]] = set()
    uniq: list[BoletinTerceraItem] = []
    for it in out:
        k = (it.aviso_id, it.fecha_publicacion_ymd)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    return uniq


def fetch_section_index_html(*, ymd: str) -> str:
    url = section_url(ymd)
    with _http_client() as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def fetch_aviso_pdf_bytes(
    *,
    aviso_id: str,
    fecha_publicacion_ymd: str,
    seccion: str = "tercera",
) -> bytes:
    """POST ``/pdf/download_aviso`` → decodifica ``pdfBase64``."""
    url = f"{BOA_BASE}/pdf/download_aviso"
    with _http_client() as client:
        r = client.post(
            url,
            data={
                "nombreSeccion": seccion,
                "idAviso": aviso_id,
                "fechaPublicacion": fecha_publicacion_ymd,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        data = r.json()
    b64 = data.get("pdfBase64")
    if not b64:
        raise ValueError("missing pdfBase64 in BOA response")
    return base64.b64decode(b64)


def fetch_detalle_html(*, detalle_url: str) -> str:
    with _http_client() as client:
        r = client.get(detalle_url)
        r.raise_for_status()
        return r.text
