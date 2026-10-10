from finagent.models import Company

class AmbiguousTicker(Exception):
    def __init__(self, text, candidates):
        super().__init__(f"ambiguous: {text}")
        self.text = text
        self.candidates = candidates

class TickerResolver:
    def __init__(self, sec):
        self._sec = sec
        self._rows = None

    def _index(self):
        if self._rows is None:
            self._rows = self._sec.get_ticker_index()
        return self._rows

    def candidates(self, text):
        t = text.strip().lower()
        out = []
        for row in self._index():
            if t == row["ticker"].lower() or t in row["title"].lower():
                out.append(Company(row["ticker"], int(row["cik"]), row["title"]))
        return out

    def resolve(self, text):
        for row in self._index():
            if text.strip().lower() == row["ticker"].lower():
                return Company(row["ticker"], int(row["cik"]), row["title"])
        c = self.candidates(text)
        if len(c) == 1:
            return c[0]
        raise AmbiguousTicker(text, c)
