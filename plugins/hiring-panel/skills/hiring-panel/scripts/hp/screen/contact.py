"""Contact details (ATS spec 8). Search order: the top block, then the body, then the header/footer.

Phone and location patterns accept non-US formats ("+44 7700 900123", "030 1234567", "Berlin,
Germany", "Toronto, ON", UK postcodes). Values are reported as found; display code masks them.
"""
import re

from ..util import EMAIL_RE, GITHUB_RE, LINKEDIN_RE, PHONE_INTL_RE, PHONE_US_RE, URL_RE
from .constants import TOP_LINES_FOR_CONTACT
from .textutil import PHONE_NATIONAL_RE

_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",   # Canada
              "NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT"}                               # Australia
_PROVINCE_NAMES = {"ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan",
                   "nova scotia", "new brunswick", "newfoundland", "new south wales", "victoria",
                   "queensland", "tasmania", "england", "scotland", "wales", "northern ireland"}
_COUNTRY_SHORT = {"usa", "us", "u.s.", "u.s.a.", "uk", "u.k.", "uae"}
_CITY = r"[^\W\d_](?:[^\W\d_]|[.'’-])*(?:\s+[^\W\d_](?:[^\W\d_]|[.'’-])*){0,3}"
_LOC_RE = re.compile(r"^(?P<city>%s),\s*(?P<region>[^\W\d_][^\W\d_ .]{1,30}?)\.?(?:\s+\d{4,5}(?:-\d{4})?)?$" % _CITY)
_UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
_REMOTE_RE = re.compile(r"(?i)^remote(?:\s*\([^)]{1,30}\))?$")
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-z]+\.?\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|"
    r"Ct|Court|Way|Pl|Place|Ter|Terrace|Pkwy|Parkway|Cir|Circle|Hwy|Highway)\b\.?")
_SPLIT_RE = re.compile(r"\s*(?:\||•|·|;|/\s|\s{2,}|\t)\s*")
_NAME_TOKEN_RE = re.compile(r"^[^\W\d_][^\W\d_'’.-]*\.?$")
_NAME_STOP = {"resume", "cv", "curriculum", "vitae", "profile", "contact", "summary", "my", "the", "and",
              "of", "for", "with", "about", "to", "a", "an", "in", "at", "on", "me", "i"}
# Words that make a top line a headline or job title, not a name ("Aspiring Data Analyst"). Kept to
# words that are rarely surnames.
ROLE_WORDS = set((
    "aspiring future student undergraduate graduate postgraduate candidate freshman sophomore "
    "intern interns internship apprentice trainee analyst analysts engineer engineering "
    "manager management developer development designer design specialist assistant associate coordinator "
    "nurse nursing technician tech consultant representative rep scientist administrator director officer "
    "executive teacher tutor instructor educator professor researcher research cashier barista server "
    "accountant accounting bookkeeper auditor recruiter strategist planner advisor adviser counselor "
    "therapist pharmacist paralegal programmer operator agent supervisor clerk volunteer professional "
    "marketing marketer sales finance financial business data software web product operations "
    "communications healthcare medical clinical pre-med premed pre-nursing entry-level level experienced "
    "seeking objective portfolio headline").split())


def _emails(text):
    """Email matches, searched token by token so a long run of dots and letters stays fast."""
    if "@" not in text:
        return []
    out = []
    for tok in text.split():
        if "@" in tok and len(tok) <= 254:
            out.extend(m.group(0) for m in EMAIL_RE.finditer(tok))
    return out


def _strip_emails(text):
    for e in _emails(text):
        text = text.replace(e, " ")
    return text


def _first(rx, text, needle):
    """rx.search on short text that contains `needle` (cheap guard against pathological lines)."""
    if needle not in text.lower():
        return None
    for tok in text.split():
        if needle in tok.lower() and len(tok) <= 300:
            m = rx.search(tok)
            if m:
                return m.group(0)
    return None


def _urls(text):
    out = []
    for tok in text.split():
        if len(tok) <= 200 and "." in tok:
            out.extend(m.group(0) for m in URL_RE.finditer(tok))
    return out


def _phones(text, national):
    out = []
    text = text[:300]
    for rx in (PHONE_US_RE, PHONE_INTL_RE) + ((PHONE_NATIONAL_RE,) if national else ()):
        for m in rx.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 7 <= len(digits) <= 15:
                out.append(m.group(0).strip())
    return out


def _location_in(text, lex):
    for part in _SPLIT_RE.split(text):
        part = part.strip(" ,")
        if not part or "@" in part:
            continue
        if _REMOTE_RE.match(part):
            return part
        m = _LOC_RE.match(part)
        if m and m.group("city")[0].isupper():
            region = m.group("region").strip()
            rcf = region.casefold().rstrip(".")
            if (region.upper() in lex.us_states and region.isupper()) or region in _PROVINCES \
                    or rcf in lex.us_state_names or rcf in lex.countries or rcf in _PROVINCE_NAMES \
                    or rcf in _COUNTRY_SHORT:
                return part
        if _UK_POSTCODE_RE.search(part) and len(part) <= 60:
            return part
    return None


def _name_word_ok(x):
    w = x.lower().strip(".")
    return bool(_NAME_TOKEN_RE.match(x)) and w not in _NAME_STOP and w not in ROLE_WORDS


def _name_in(text):
    t = re.sub(r"(?i)^name\s*:\s*", "", text).strip()
    toks = t.split()
    if not (2 <= len(toks) <= 4) or len(t) > 50:
        return None
    if not all(_name_word_ok(x) for x in toks):
        return None
    return t


def _stacked_name(top_lines):
    """A name printed one word per line at the very top ("JORDAN" / "ALVAREZ"): join 2 to 4
    consecutive one-word capitalized lines. Returns None when the top does not look like that."""
    toks = []
    for rl in top_lines[:4]:
        t = rl.text.strip()
        if rl.heading or len(t.split()) != 1 or not t[:1].isupper() or not _name_word_ok(t) or len(t) > 25:
            break
        toks.append(t)
    return " ".join(toks) if 2 <= len(toks) <= 4 else None


def extract_contact(lines, hf, top_count, lex, locale):
    """Find contact details. `lines` are RLines, `hf` header/footer dicts, `top_count` the number of
    lines before the first heading. Returns (contact dict, details dict for issue checks)."""
    top = lines[:max(top_count, 0)]
    first12 = lines[:TOP_LINES_FOR_CONTACT]
    body_nonref = [rl for rl in lines if rl.section != "references"]
    national = True
    found = {"email": None, "phone": None, "linkedin": None, "github": None}
    where = {"email": None, "phone": None}
    emails = []

    def note_where(kind, rl):
        if where[kind] is not None:
            return
        if rl is None:
            where[kind] = "header_footer"
        elif rl.where in ("table", "textbox"):
            where[kind] = "text_box_or_table"
        elif rl in first12:
            where[kind] = "body_top"
        else:
            where[kind] = "body_elsewhere"

    # emails: every distinct address outside a references section, in reading order
    seen = set()
    for t in [rl.text for rl in body_nonref] + [h["text"] for h in hf]:
        for e in _emails(t):
            if e.casefold() not in seen:
                seen.add(e.casefold())
                emails.append(e)
    # Search order per ATS spec 8: top block, then body, then header/footer. Each detail's location
    # is recorded with the same preference order.
    ordered = top + [rl for rl in body_nonref if rl not in top]
    top_ids = set(id(rl) for rl in top) | set(id(rl) for rl in first12)
    for src, t in [(rl, rl.text) for rl in ordered] + [(None, h["text"]) for h in hf]:
        if found["email"] is None:
            es = _emails(t)
            if es:
                found["email"] = es[0]
                note_where("email", src)
        if found["phone"] is None:
            ph = _phones(_strip_emails(t), national and (src is None or id(src) in top_ids))
            if ph:
                found["phone"] = ph[0]
                note_where("phone", src)
        if found["linkedin"] is None:
            found["linkedin"] = _first(LINKEDIN_RE, t, "linkedin")
        if found["github"] is None:
            found["github"] = _first(GITHUB_RE, t, "github")
    # location and street address: only the top lines and the header/footer (a school's city in the
    # Education section is not the candidate's location)
    loc_lines = [rl.text for rl in (top if top else first12)][:TOP_LINES_FOR_CONTACT] + [h["text"] for h in hf]
    location = None
    street = False
    for t in loc_lines:
        if location is None:
            location = _location_in(t, lex)
        if _STREET_RE.search(t):
            street = True
    portfolio = None
    for t in loc_lines:
        t2 = _strip_emails(t)
        for u in _urls(t2):
            u = u.rstrip(".,;")
            low = u.lower()
            if "linkedin.com" in low or "github.com" in low or u.isupper():
                continue
            portfolio = u
            break
        if portfolio:
            break
    # Name: only from the first lines, never a headline or job title; when unsure, None (the report
    # then leaves the name out instead of showing a wrong one).
    head = (top if top else first12)
    name = _stacked_name(head)
    for rl in head[:3] if name is None else []:
        if "@" in rl.text or len(rl.text) > 60 or _urls(rl.text) or rl.heading:
            continue
        name = _name_in(rl.text)
        if name:
            break
    if name is None:
        for h in hf[:3]:
            name = _name_in(h["text"])
            if name:
                break
    # Where the contact block as a whole was found (email first, else phone).
    prefs = ["body_top", "body_elsewhere", "text_box_or_table", "header_footer"]
    places = [where[k] for k in ("email", "phone") if where[k]]
    if not places:
        found_in = "missing"
    else:
        best = sorted(places, key=prefs.index)[0]
        found_in = "header_footer_only" if best == "header_footer" else best
    contact = {
        "name": name, "email": found["email"], "phone": found["phone"], "location": location,
        "linkedin": found["linkedin"], "github": found["github"], "portfolio": portfolio,
        "found_in": found_in, "street_address_present": street, "emails_found": len(emails),
    }
    details = {"where": where, "emails": emails}
    return contact, details
