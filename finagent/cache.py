import sqlite3, pathlib

class ResponseCache:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
        self._con.execute("CREATE TABLE IF NOT EXISTS http(url TEXT PRIMARY KEY, body TEXT)")
        self._con.commit()

    def get(self, url):
        row = self._con.execute("SELECT body FROM http WHERE url=?", (url,)).fetchone()
        return row[0] if row else None

    def set(self, url, body):
        self._con.execute("INSERT OR REPLACE INTO http(url, body) VALUES(?, ?)", (url, body))
        self._con.commit()
