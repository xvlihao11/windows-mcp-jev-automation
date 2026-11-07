import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from agent_watch import scan


class WatchTest(unittest.TestCase):
    def test_baseline_change_restart_and_deletion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, ignore_cleanup_errors=True) as directory:
            db, state = Path(directory) / 'agent.db', Path(directory) / 'state.json'
            with closing(sqlite3.connect(db)) as c, c:
                c.execute('CREATE TABLE daily(id,date,author,category,narrative,polished,blocks,updated_at)')
                c.execute('CREATE TABLE library(id,title,author,category,text,filepath,fmt,uploaded_at,doc_type)')
                c.execute("INSERT INTO daily VALUES('old','2026-10-17','Test','','','approved',NULL,'now')")
            self.assertEqual(scan(db, state)['status'], 'BASELINED')
            self.assertEqual(scan(db, state)['pending'], [])
            with closing(sqlite3.connect(db)) as c, c:
                c.execute("UPDATE daily SET polished='changed' WHERE id='old'")
                c.execute("INSERT INTO library VALUES('new','Report','Test','','body','','html','now','report')")
                c.execute("INSERT INTO library VALUES('other','Paper','Test','','body','','pdf','now','doc')")
            result = scan(db, state)
            self.assertEqual(len(result['pending']), 2)
            self.assertEqual({x['change'] for x in result['pending']}, {'new', 'updated'})
            self.assertEqual(len(scan(db, state)['pending']), 2)
            daily_version = next(x['version_key'] for x in result['pending'] if x['source'] == 'daily')
            with closing(sqlite3.connect(db)) as c, c:
                c.execute("UPDATE daily SET updated_at='later-reupload' WHERE id='old'")
            repeated = scan(db, state)
            self.assertEqual(len(repeated['pending']), 2)
            new_daily = next(x for x in repeated['pending'] if x['source'] == 'daily')
            self.assertNotEqual(daily_version, new_daily['version_key'])
            self.assertEqual(new_daily['sha256'], next(x['sha256'] for x in result['pending'] if x['source'] == 'daily'))
            self.assertEqual(scan(db, state)['pending'], repeated['pending'])
            with closing(sqlite3.connect(db)) as c, c:
                c.execute("DELETE FROM library WHERE id='new'")
            self.assertEqual(len(scan(db, state)['pending']), 1)
            with closing(sqlite3.connect(db)) as c, c:
                self.assertEqual(c.execute("SELECT polished FROM daily").fetchone()[0], 'changed')


if __name__ == '__main__':
    unittest.main()
