"""Parse a filed SEBI shareholding pattern PDF into promoter and public holders.

The filing is the primary source: exact names, exact share counts, every
quarter. Reading it directly removes the web agent from the critical path,
which is what makes an index-wide run practical.

SEBI's format is fixed. Table II holds the Promoter & Promoter Group, Table III
the Public shareholders, Table IV the Non-Promoter Non-Public holders. Each
data row is a name followed by a run of numeric columns:

    Mr. Shiv Nadar  Promoter  1  736  -  -  736  0.000%  736 ...
    name            role      (III) (IV) (V) (VI) (VII)  (VIII)

so the name is whatever precedes the numeric run, and the counts are read
positionally from it.
"""
import io
import re

# A numeric column: a count, a percentage, or a dash standing for nil.
_NUM = re.compile(r"^(?:-+|NA|N/?A|\d[\d,]*(?:\.\d+)?%?|\.\d+%?)$", re.I)
# The role column sits between the name and the numbers in Table II.
_ROLE = re.compile(r"\s+(?:Promoter Group|Promoter|Public|Trust)\s*$", re.I)
_MIN_NUMERIC = 4      # fewer columns than this is a caption, not a data row
_NUMBER_PREFIX = re.compile(r"^\s*[1-9]\d{0,2}\s+(?=[A-Za-z])")
_NUMBERED = re.compile(r"^\s*([1-9]\d{0,2})\s+[A-Z][A-Za-z]", re.M)


def _to_num(tok):
    if tok is None or re.fullmatch(r"-+|NA|N/?A", tok or "", re.I):
        return None
    try:
        return float(tok.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def split_row(line):
    """(name, numeric tokens) for a data row, else (None, [])."""
    toks = line.split()
    i = len(toks)
    while i > 0 and _NUM.match(toks[i - 1]):
        i -= 1
    name, nums = " ".join(toks[:i]).strip(), toks[i:]
    if len(nums) < _MIN_NUMERIC or not name:
        return None, []
    return _ROLE.sub("", name).strip(" .,-"), nums


def read_holding(nums):
    """(shares, percentage) from a row's numeric columns.

    Column positions are NOT stable across filings - Grasim puts fully paid-up
    shares in column (III) where HCLTech puts it in (IV) - so reading by index
    silently returns the wrong figure. What is stable is repetition: a filing
    restates the same holding as fully paid-up, as total, as voting rights and
    as dematerialised shares, and the same percentage two or three times, while
    the shareholder count appears once. So the most frequent value wins, and
    the largest breaks a tie.
    """
    ints, pcts = [], []
    for tok in nums:
        v = _to_num(tok)
        if v is None:
            continue
        if tok.endswith("%") or ("." in tok and 0 < v <= 100):
            pcts.append(round(v, 4))
        elif v == int(v) and v > 0:
            ints.append(int(v))

    def mode(vals):
        if not vals:
            return None
        best, seen = None, {}
        for v in vals:
            seen[v] = seen.get(v, 0) + 1
        top = max(seen.values())
        return max(v for v, n in seen.items() if n == top)

    shares = mode(ints)
    # A lone integer is the shareholder count, not a holding: a real holding is
    # restated across columns. Treat an unrepeated single value as nil.
    if shares is not None and len(ints) == 1 and shares < 1000:
        shares = 0
    return int(shares or 0), mode(pcts)


def _sections(text):
    """Split the document into its SEBI tables, keyed by roman numeral."""
    marks = [(m.start(), m.group(1).upper())
             for m in re.finditer(r"Table\s+(I{1,3}V?|IV|V)\s*[-–]", text)]
    out = {}
    for n, (pos, roman) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(text)
        # A table can be announced more than once (continuation pages); keep
        # the longest run so the body is not truncated at a repeat header.
        if roman not in out or end - pos > len(out[roman]):
            out[roman] = text[pos:end]
    return out


def _rows(section, clean_name):
    """Data rows of one table, with aggregate lines filtered out.

    A row does not always survive PDF extraction on one line. A long name wraps
    and the numbers land on their own line:

        Vama Sundari Investments (Delhi) Pvt.
        Ltd.
        Promoter
        1   1,200,361,516   -   -   1,200,361,516   44.234% ...

    so non-numeric lines are buffered and flushed against the next all-numeric
    line. Without this the largest promoter of several companies reads as nil.
    """
    got, buf = [], []

    def emit(name, nums):
        if numbered:
            name = _NUMBER_PREFIX.sub("", name)
        clean = clean_name(_ROLE.sub("", name).strip(" .,-"))
        if not clean:
            return
        shares, pct = read_holding(nums)
        got.append({"name": clean, "shares": shares, "pct": pct})

    # A filing numbers its promoter group members and PDF extraction carries
    # the index into the name column: "5 Birla Group Holdings Private Limited".
    # Stripping that per name would maul a company genuinely called "63 Moons
    # Technologies", so it is only stripped where the numbering is systematic -
    # several rows in one table, each with a different index.
    indices = _NUMBERED.findall(section)
    numbered = len(set(indices)) >= 3

    for raw in section.split("\n"):
        line = raw.strip()
        if not line:
            continue
        toks = line.split()
        name, nums = split_row(line)
        if name:
            emit(name, nums)
            buf = []
        elif len(toks) >= _MIN_NUMERIC and all(_NUM.match(t) for t in toks):
            if buf:
                emit(" ".join(buf), toks)
            buf = []
        else:
            # Part of a name that wrapped. Cap the buffer so a page header
            # cannot accumulate into a fake holder.
            buf = (buf + [line])[-4:]
    return got


_MIN_PUBLIC = 3     # below this the section boundaries are suspect


def parse_text(text, clean_name):
    """Returns {'promoters': [...], 'public': [...], 'non_public': [...]}.

    Section splitting relies on the table captions appearing in document order,
    which PDF text extraction does not guarantee: Grasim's filing prints the
    Table III caption and column headers, then Table IV's rows underneath. When
    the public section comes back implausibly thin, the whole document is
    rescanned and anything that is not already a promoter is taken as public.
    Rows recovered that way are marked so their weaker provenance is visible.
    """
    sec = _sections(text)
    promoters = _rows(sec.get("II", ""), clean_name)
    public = _rows(sec.get("III", ""), clean_name)
    non_public = _rows(sec.get("IV", ""), clean_name)

    if len(public) < _MIN_PUBLIC:
        known = {r["name"].lower() for r in promoters + public + non_public}
        for r in _rows(text, clean_name):
            if r["name"].lower() in known or not r["shares"]:
                continue
            known.add(r["name"].lower())
            public.append({**r, "recovered": True})
    return {"promoters": promoters, "public": public, "non_public": non_public}


def parse_pdf(data, clean_name):
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return parse_text(text, clean_name), text


def scrr_base(text):
    """The (A)+(B)+(C2) denominator, read off the Table I total row."""
    # The grand total including depository receipts is a different row; the
    # SCRR base is the one the percentages are struck on.
    m = re.search(r"Total\s*\(A\)\s*\+\s*\(B\)\s*\+\s*\(C2?\)[^\n]*", text, re.I)
    if not m:
        return None
    nums = [t for t in m.group(0).split() if _NUM.match(t)]
    vals = sorted({int(v) for v in (_to_num(t) or 0 for t in nums) if v > 1000})
    return int(vals[-1]) if vals else None
