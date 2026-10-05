"""Tests for the public listings sync. Run from the project root:

    python -m unittest discover -s tests -t . -v

Nothing here touches the network or the real database.
"""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import db
from listings import render, store
from listings.normalize import canonical_key, normalize_link
from listings.publishers import GitHubPublisher, LocalPublisher, PublishError, git_blob_sha
from listings.sync import build_universe, commit_message, run_sync
from scrapers.base import Job
from scrapers.companies import ScrapeReport
from scrapers.github_aggregator import COOP_LABEL, COOP_SOURCE
from scrapers.terms import earliest_term, normalize_term, parse_term, term_from_title

TZ = ZoneInfo("America/Toronto")


def at(day: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=TZ)


def job(company="Acme", title="Software Engineering Intern", url="https://acme.com/jobs/1", **kw) -> Job:
    kw.setdefault("location", "Toronto, ON, Canada")
    kw.setdefault("source", COOP_SOURCE)
    kw.setdefault("posted_at", "2026-10-01")
    return Job(company=company, title=title, url=url, **kw)


class TempDBTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_path = db.DATABASE_PATH
        db.DATABASE_PATH = str(Path(self._tmp.name) / "test.db")
        self.addCleanup(setattr, db, "DATABASE_PATH", self._old_path)
        db.init_db()


class NormalizeTests(unittest.TestCase):
    def test_tracking_params_ignored_but_identity_params_kept(self):
        base = "https://boards.example.com/acme/jobs?gh_jid=111"
        self.assertEqual(
            normalize_link(base),
            normalize_link("https://www.boards.example.com/acme/jobs/?gh_jid=111&utm_source=Simplify&ref=Simplify"),
        )
        self.assertNotEqual(normalize_link(base), normalize_link("https://boards.example.com/acme/jobs?gh_jid=222"))

    def test_key_ignores_case_and_punctuation_but_not_identity(self):
        a = canonical_key("Acme, Inc.", "SWE Intern (Summer 2027)", "https://x.com/a?id=1")
        b = canonical_key("acme inc", "swe intern - summer 2027", "http://X.com/a?id=1&utm_medium=x")
        self.assertEqual(a, b)
        self.assertNotEqual(a, canonical_key("Acme, Inc.", "SWE Intern (Summer 2027)", "https://x.com/a?id=2"))


class TermTests(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(parse_term("Summer 2027"), (2027, 1))
        self.assertEqual(term_from_title("2027 Fall Co-op, Backend"), "Fall 2027")
        self.assertEqual(term_from_title("Autumn 2026 Intern"), "Fall 2026")
        self.assertIsNone(term_from_title("Software Intern"))

    def test_earliest_of_several_and_na_ignored(self):
        self.assertEqual(earliest_term(["Winter 2027", "Fall 2026", "N/A"]), "Fall 2026")
        self.assertIsNone(earliest_term(["N/A"]))

    def test_only_winter_summer_fall_spring_folds_into_winter(self):
        self.assertEqual(parse_term("Spring 2027"), (2027, 0))
        self.assertEqual(term_from_title("Spring 2027 Co-op"), "Winter 2027")
        self.assertEqual(earliest_term(["Spring 2027"]), "Winter 2027")
        self.assertEqual(earliest_term(["Spring 2027", "Fall 2026"]), "Fall 2026")
        self.assertEqual(normalize_term("Spring 2027"), "Winter 2027")
        self.assertEqual(normalize_term("Unspecified"), "Unspecified")

    def test_stored_spring_rows_are_published_as_winter(self):
        files = render.render_files([row(term="Spring 2027")], date(2026, 10, 5),
                                    tracker_repo="r", interval_minutes=30, invite_url=None)
        self.assertEqual(json.loads(files["listings.json"])[0]["term"], "Winter 2027")
        self.assertIn("| Winter 2027 |", files["README.md"])
        self.assertNotIn("Spring", files["README.md"])


class StoreTests(TempDBTestCase):
    def listing(self, role="Intern", source=COOP_SOURCE, company="Acme"):
        link = f"https://{company.lower()}.com/{role.replace(' ', '-')}"
        return store.Listing(canonical_key(company, role, link), company, role, "Toronto", "Summer 2027",
                             link, "2026-10-01", source)

    def cycle(self, listings, complete, day="2026-10-05"):
        return store.apply_cycle({l.key: l for l in listings}, set(complete), day, f"{day}T12:00:00+00:00")

    def status_of(self, role):
        return next(r["status"] for r in store.all_rows() if r["role"] == role)

    def test_closes_only_after_three_consecutive_complete_misses(self):
        item = self.listing()
        self.assertEqual(self.cycle([item], {COOP_LABEL}).added, 1)
        for _ in range(2):
            self.cycle([], {COOP_LABEL})
            self.assertEqual(self.status_of("Intern"), "open")
        result = self.cycle([], {COOP_LABEL}, day="2026-10-06")
        self.assertEqual(result.closed, 1)
        row = store.all_rows()[0]
        self.assertEqual((row["status"], row["date_closed"], row["date_found"]), ("closed", "2026-10-06", "2026-10-05"))

    def test_reappearing_listing_resets_misses_and_reopens(self):
        item = self.listing()
        self.cycle([item], {COOP_LABEL})
        self.cycle([], {COOP_LABEL})
        self.cycle([item], {COOP_LABEL})  # back before closing: counter resets
        for _ in range(2):
            self.cycle([], {COOP_LABEL})
        self.assertEqual(self.status_of("Intern"), "open")
        self.cycle([], {COOP_LABEL})
        self.assertEqual(self.status_of("Intern"), "closed")
        self.assertEqual(self.cycle([item], {COOP_LABEL}).reopened, 1)
        self.assertEqual(self.status_of("Intern"), "open")

    def test_failed_or_partial_source_never_closes_anything(self):
        item = self.listing(source="workday", company="Manulife")
        self.cycle([item], {"workday:Manulife"})
        for _ in range(10):
            self.cycle([], set())  # source failed, or Workday board truncated: not in `complete`
        self.assertEqual(self.status_of("Intern"), "open")

    def test_other_sources_are_not_affected_by_one_sources_absence(self):
        a, b = self.listing("A"), self.listing("B", source="greenhouse", company="Hootsuite")
        self.cycle([a, b], {COOP_LABEL, "greenhouse:Hootsuite"})
        for _ in range(3):
            self.cycle([b], {COOP_LABEL, "greenhouse:Hootsuite"})
        self.assertEqual((self.status_of("A"), self.status_of("B")), ("closed", "open"))

    def test_guard_holds_closures_when_a_source_suddenly_shrinks(self):
        listings = [self.listing(f"Role {i}") for i in range(20)]
        self.cycle(listings, {COOP_LABEL})
        for _ in range(5):
            result = self.cycle(listings[:5], {COOP_LABEL})
        self.assertEqual(result.held_labels, (COOP_LABEL,))
        self.assertEqual(sum(1 for r in store.all_rows() if r["status"] == "closed"), 0)

    def test_import_rows_restores_history_and_skips_malformed(self):
        rows = [
            {"company": "Acme", "role": "Intern", "link": "https://a.com/1", "term": "Fall 2026",
             "date_found": "2026-09-01", "status": "closed", "date_closed": "2026-09-20", "location": "Toronto"},
            {"company": "NoLink"},
        ]
        self.assertEqual(store.import_rows(rows, "2026-10-05T00:00:00+00:00"), 1)
        row = store.all_rows()[0]
        self.assertEqual((row["date_found"], row["status"], row["date_closed"]), ("2026-09-01", "closed", "2026-09-20"))


def row(company="Acme", role="Intern", term="Summer 2027", status="open", posted="2026-10-01", closed=None,
        link="https://acme.com/1", location="Toronto, ON, Canada"):
    return {"company": company, "role": role, "location": location, "term": term, "link": link,
            "date_posted": posted, "date_found": "2026-10-02", "status": status, "date_closed": closed}


class RenderTests(unittest.TestCase):
    ARGS = dict(tracker_repo="Summer2027-Internships", interval_minutes=30, invite_url="https://discord.gg/x")

    def test_output_is_deterministic_and_has_no_timestamps(self):
        rows = [row(), row(role="B", term="Fall 2026"), row(role="C", status="closed", closed="2026-10-03")]
        first = render.render_files(rows, date(2026, 10, 5), **self.ARGS)
        second = render.render_files(list(reversed(rows)), date(2026, 10, 5), **self.ARGS)
        self.assertEqual(first, second)

    def test_newest_posting_first_regardless_of_term_and_closed_last(self):
        rows = [row(role="role-mid", term="Winter 2027", posted="2026-09-20"),
                row(role="role-closed", term="Fall 2026", posted="2026-10-04", status="closed", closed="2026-10-03"),
                row(role="role-new", term="Summer 2028", posted="2026-10-05"),
                row(role="role-old", term="Fall 2026", posted="2026-07-01"),
                row(role="role-none", term="Unspecified", posted="2026-09-30")]
        readme = render.render_files(rows, date(2026, 10, 5), **self.ARGS)["README.md"]
        names = ("role-new", "role-none", "role-mid", "role-old", "role-closed")
        order = [readme.index(name) for name in names]
        self.assertEqual(order, sorted(order))
        dates = [r["date_posted"] for r in json.loads(render.render_files(rows, date(2026, 10, 5), **self.ARGS)["listings.json"])]
        self.assertEqual(dates[:4], sorted(dates[:4], reverse=True))

    def test_single_table_with_term_column_and_no_term_sections(self):
        readme = render.render_files([row(term="Fall 2026"), row(role="B", term="Unspecified")],
                                     date(2026, 10, 5), **self.ARGS)["README.md"]
        self.assertIn("| Company | Role | Location | Apply | Date Posted | Term |", readme)
        self.assertEqual(readme.count("| --- | --- | --- | --- | --- | --- |"), 1)
        self.assertEqual([l for l in readme.splitlines() if l.startswith("## ")], [])
        self.assertIn("| 2026-10-01 | Fall 2026 |", readme)
        self.assertIn("| 2026-10-01 | – |", readme)

    def test_newest_posting_first_within_a_term(self):
        rows = [row(role="role-older", posted="2026-09-01"), row(role="role-newer", posted="2026-10-02")]
        readme = render.render_files(rows, date(2026, 10, 5), **self.ARGS)["README.md"]
        self.assertLess(readme.index("role-newer"), readme.index("role-older"))

    def test_closed_rows_marked_and_archived_after_30_days(self):
        rows = [row(role="recent", status="closed", closed="2026-09-20"),
                row(role="ancient", status="closed", closed="2026-08-01")]
        files = render.render_files(rows, date(2026, 10, 5), **self.ARGS)
        self.assertIn("🔒 recent", files["README.md"])
        self.assertNotIn("ancient", files["README.md"])
        self.assertEqual([r["role"] for r in json.loads(files["archive.json"])], ["ancient"])
        self.assertEqual([r["role"] for r in json.loads(files["listings.json"])], ["recent"])

    def test_json_schema_and_markdown_escaping(self):
        files = render.render_files([row(role="A | B <b>", link="https://a.com/x (1)")], date(2026, 10, 5), **self.ARGS)
        self.assertEqual(list(json.loads(files["listings.json"])[0]), list(render.JSON_FIELDS))
        self.assertIn("A \\| B &lt;b&gt;", files["README.md"])
        self.assertIn("https://a.com/x%20%281%29", files["README.md"])

    def test_many_locations_are_shortened_in_readme_only(self):
        loc = "; ".join(f"City{i}, ON, Canada" for i in range(6))
        files = render.render_files([row(location=loc)], date(2026, 10, 5), **self.ARGS)
        self.assertIn("+3 more", files["README.md"])
        self.assertEqual(json.loads(files["listings.json"])[0]["location"], loc)


class ReadmeIntroTests(unittest.TestCase):
    def render(self, rows, **extra):
        return render.render_files(rows, date(2026, 10, 5), tracker_repo="Summer2027-Internships",
                                   interval_minutes=30, invite_url=None, **extra)["README.md"]

    def test_coverage_line_uses_years_from_open_listings(self):
        rows = [row(term="Fall 2026"), row(role="b", term="Summer 2027"), row(role="c", term="Summer 2028"),
                row(role="d", term="Fall 2019", status="closed", closed="2026-10-01")]
        readme = self.render(rows)
        self.assertIn("Winter, Summer and Fall 2026, 2027 and 2028:", readme)
        self.assertIn("Toronto, Montreal, Vancouver, Ottawa", readme)
        self.assertIn("remote roles open to applicants in Canada", readme)
        self.assertIn("Winter, Summer and Fall 2027:", self.render([row(term="Summer 2027")]))

    def test_how_it_works_and_source_attribution(self):
        readme = self.render([row()])
        for text in ("<summary><b>How this list works</b></summary>", "Sorted by newest posting", "work term",
                     "🔒 means closed", "only if they're open to applicants in Canada",
                     "https://github.com/SimplifyJobs/Summer2027-Internships", "isn't affiliated with SimplifyJobs"):
            self.assertIn(text, readme)

    def test_creator_line_optional_linkedin_and_no_pr_talk(self):
        full = self.render([row()], creator_name="Jane Doe", creator_github_url="https://github.com/jane",
                           creator_linkedin_url="https://linkedin.com/in/jane")
        self.assertIn("Built and maintained by **Jane Doe** ([GitHub](https://github.com/jane) · "
                      "[LinkedIn](https://linkedin.com/in/jane))", full)
        self.assertIn("Star or 👀 watch", full)
        partial = self.render([row()], creator_name="Jane Doe", creator_github_url="https://github.com/jane")
        self.assertNotIn("LinkedIn", partial)
        self.assertNotIn("Built and maintained", self.render([row()]))
        for text in (full, partial):
            self.assertNotIn("pull request", text.lower())
            self.assertNotIn(" PR", text)


class CommitMessageTests(unittest.TestCase):
    def test_messages(self):
        old = json.dumps([row(role="a"), row(role="b"), row(role="c", status="closed", closed="2026-10-01")])
        new = json.dumps([row(role="a", status="closed", closed="2026-10-05"), row(role="b"), row(role="d"),
                          row(role="e"), row(role="c")])
        self.assertEqual(commit_message(old, new, date(2026, 10, 5)), "Add 2, close 1, reopen 1 listings (Oct 5)")
        self.assertEqual(commit_message(old, old, date(2026, 10, 5)), "Update listings (Oct 5)")
        one = json.dumps([row(role="a"), row(role="b"), row(role="c", status="closed", closed="2026-10-01"), row(role="z")])
        self.assertEqual(commit_message(old, one, date(2026, 10, 5)), "Add 1 listing (Oct 5)")
        self.assertEqual(commit_message(None, one, date(2026, 10, 5)), "Add 3 listings (Oct 5)")


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload, content
        self.text = content.decode() if content else json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Routes by (METHOD, path-after-/repos/owner/name) and records every call."""

    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def request(self, method, url, timeout=None, **kwargs):
        path = url.split("/repos/o/r", 1)[1]
        self.calls.append((method, path, kwargs))
        result = self.routes[(method, path)]
        result = result.pop(0) if isinstance(result, list) else result
        return result


class GitHubPublisherTests(unittest.TestCase):
    FILES = {"README.md": "# new\n", "listings.json": "[]\n", "archive.json": "[]\n"}

    def routes(self, existing):
        tree = [{"path": p, "type": "blob", "sha": git_blob_sha(t)} for p, t in existing.items()]
        return {
            ("GET", "/git/ref/heads/main"): FakeResponse(payload={"object": {"sha": "head1"}}),
            ("GET", "/git/commits/head1"): FakeResponse(payload={"tree": {"sha": "tree1"}}),
            ("GET", "/git/trees/tree1"): FakeResponse(payload={"tree": tree}),
            ("GET", "/contents/listings.json"): FakeResponse(404, {"message": "Not Found"}),
            ("POST", "/git/trees"): FakeResponse(payload={"sha": "tree2"}),
            ("POST", "/git/commits"): FakeResponse(payload={"sha": "commit2"}),
            ("PATCH", "/git/refs/heads/main"): FakeResponse(payload={}),
        }

    def publisher(self, routes):
        session = FakeSession(routes)
        return GitHubPublisher("secret-token", "o/r", session=session), session

    def test_known_git_blob_sha(self):
        self.assertEqual(git_blob_sha("hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_no_change_means_no_commit(self):
        publisher, session = self.publisher(self.routes(self.FILES))
        outcome = publisher.sync(self.FILES, lambda prev: "never used")
        self.assertFalse(outcome.committed)
        self.assertEqual({m for m, _, _ in session.calls}, {"GET"})

    def test_only_changed_files_go_into_one_commit(self):
        existing = {"README.md": "# old\n", "listings.json": "[]\n", "archive.json": "[]\n"}
        routes = self.routes(existing)
        publisher, session = self.publisher(routes)
        outcome = publisher.sync(self.FILES, lambda prev: "msg")
        self.assertEqual((outcome.changed, outcome.message), (["README.md"], "msg"))
        posted_tree = next(kw["json"] for m, p, kw in session.calls if (m, p) == ("POST", "/git/trees"))
        self.assertEqual([e["path"] for e in posted_tree["tree"]], ["README.md"])
        commit = next(kw["json"] for m, p, kw in session.calls if (m, p) == ("POST", "/git/commits"))
        self.assertEqual((commit["parents"], commit["tree"]), (["head1"], "tree2"))

    def test_retries_once_when_branch_moves_then_gives_up(self):
        routes = self.routes({})
        routes[("PATCH", "/git/refs/heads/main")] = [FakeResponse(422, {"message": "not ff"}), FakeResponse(payload={})]
        publisher, _ = self.publisher(routes)
        self.assertTrue(publisher.sync(self.FILES, lambda prev: "m").committed)

        routes = self.routes({})
        routes[("PATCH", "/git/refs/heads/main")] = [FakeResponse(422, {"message": "x"})] * 2
        publisher, _ = self.publisher(routes)
        with self.assertRaises(PublishError):
            publisher.sync(self.FILES, lambda prev: "m")

    def test_error_text_never_contains_the_token(self):
        routes = self.routes({})
        routes[("GET", "/git/ref/heads/main")] = FakeResponse(401, {"message": "Bad credentials"})
        publisher, _ = self.publisher(routes)
        with self.assertRaises(PublishError) as ctx:
            publisher.sync(self.FILES, lambda prev: "m")
        self.assertNotIn("secret-token", str(ctx.exception))


class SyncTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.publisher = LocalPublisher(self.out.name)

    def run_sync(self, jobs, complete=(COOP_LABEL,), day=5):
        return run_sync(self.publisher, now=at(day),
                        scrape=lambda include_new_grad: ScrapeReport(list(jobs), set(complete)))

    def test_universe_filters(self):
        jobs = [
            job(),
            job(company="Old", url="https://old.com/1", posted_at="2020-01-01"),  # age is irrelevant for the repo
            job(company="US", url="https://us.com/1", location="Austin, TX"),
            job(company="NG", url="https://ng.com/1", source="github_aggregator_newgrad"),
            job(company="Hoot", title="Senior Manager", url="https://h.com/1", source="greenhouse"),
            job(company="Hoot", title="Marketing Co-op", url="https://h.com/2", source="greenhouse"),
        ]
        self.assertEqual(sorted(l.company for l in build_universe(jobs).values()), ["Acme", "Hoot", "Old"])

    def test_term_comes_from_source_then_title_then_unspecified(self):
        jobs = [job(term="Fall 2026"), job(company="B", title="Summer 2027 Intern", url="https://b.com/1"),
                job(company="C", url="https://c.com/1")]
        self.assertEqual(sorted(l.term for l in build_universe(jobs).values()),
                         ["Fall 2026", "Summer 2027", "Unspecified"])

    def test_second_identical_run_changes_nothing(self):
        first = self.run_sync([job()])
        self.assertEqual(sorted(first.published), ["README.md", "archive.json", "listings.json"])
        self.assertEqual(first.message, "Add 1 listing (Oct 5)")
        second = self.run_sync([job()])
        self.assertEqual((second.published, second.message), ([], None))

    def test_failed_scrape_changes_nothing_and_never_publishes_empty(self):
        empty_first = self.run_sync([], complete=())
        self.assertEqual(empty_first.published, [])
        self.assertEqual(list(Path(self.out.name).iterdir()), [])
        self.run_sync([job()])
        after_failure = self.run_sync([], complete=())
        self.assertEqual(after_failure.published, [])
        self.assertEqual(json.loads((Path(self.out.name) / "listings.json").read_text())[0]["status"], "open")

    def test_closing_flows_through_to_the_files(self):
        self.run_sync([job()])
        for day in (6, 7):
            self.run_sync([], day=day)
        closing = self.run_sync([], day=8)
        self.assertEqual(closing.message, "Close 1 listing (Oct 8)")
        listing = json.loads((Path(self.out.name) / "listings.json").read_text())[0]
        self.assertEqual((listing["status"], listing["date_closed"]), ("closed", "2026-10-08"))
        self.assertIn("🔒", (Path(self.out.name) / "README.md").read_text())

    def test_empty_db_restores_published_history_instead_of_resetting_it(self):
        self.run_sync([job()])
        listings = Path(self.out.name) / "listings.json"
        data = json.loads(listings.read_text())
        data[0]["date_found"] = "2026-08-01"
        listings.write_text(json.dumps(data, indent=2) + "\n")

        db.DATABASE_PATH = str(Path(self._tmp.name) / "fresh.db")  # simulate a lost volume
        db.init_db()
        self.run_sync([job()], day=9)
        self.assertEqual(json.loads(listings.read_text())[0]["date_found"], "2026-08-01")


class LocalPublisherTests(unittest.TestCase):
    def test_writes_only_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = LocalPublisher(tmp)
            files = {"README.md": "a\n", "listings.json": "[]\n"}
            self.assertEqual(sorted(publisher.sync(files, lambda p: "m").changed), ["README.md", "listings.json"])
            self.assertEqual(publisher.sync(files, lambda p: "m").changed, [])
            self.assertEqual(publisher.sync({**files, "README.md": "b\n"}, lambda p: "m").changed, ["README.md"])


if __name__ == "__main__":
    unittest.main()
