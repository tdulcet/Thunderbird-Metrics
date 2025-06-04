#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 bugzilla.py

import atexit
import base64
import csv
import io
import json
import locale
import operator
import os
import platform
import re
import statistics
import sys
import textwrap
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import starmap

import matplotlib.pyplot as plt
import requests
import urllib3
from requests.exceptions import HTTPError, RequestException

locale.setlocale(locale.LC_ALL, "")

session = requests.Session()
session.headers["User-Agent"] = (
	f"Thunderbird Metrics ({session.headers['User-Agent']} {platform.python_implementation()}/{platform.python_version()})"
)
session.mount("https://", requests.adapters.HTTPAdapter(max_retries=urllib3.util.Retry(5, backoff_factor=1)))
atexit.register(session.close)

BUGZILLA_BASE_URL = "https://bugzilla.mozilla.org/"
BUGZILLA_API_URL = f"{BUGZILLA_BASE_URL}rest/"
BUGZILLA_SHORT_URL = "https://bugzil.la/"

# Optional Bugzilla API key
BUGZILLA_KEY = None

HEADERS = {"X-BUGZILLA-API-KEY": BUGZILLA_KEY} if BUGZILLA_KEY is not None else None

PHABRICATOR_API_URL = "https://phabricator.services.mozilla.com/api/"

# Add Phabricator API token
PHABRICATOR_TOKEN = None

HG_API_URL = "https://hg.mozilla.org/"

PRODUCTS = ((("Thunderbird", "MailNews Core", "Calendar", "Chat Core"), None), (("Webtools",), "ISPDB Database Entries"))

REPOSITORY_PHID = "PHID-REPO-wsfeum6yaue6jsbo7mgm"
REPOSITORY = "comm-central"

STATUSES = ("UNCONFIRMED", "NEW", "ASSIGNED", "REOPENED", "RESOLVED", "VERIFIED", "CLOSED")

RESOLUTIONS = ("FIXED", "INVALID", "WONTFIX", "INACTIVE", "DUPLICATE", "WORKSFORME", "INCOMPLETE", "SUPPORT", "EXPIRED", "MOVED")

LIMIT = 1000

VERBOSE = False

# r"([]!#()*+.<>[\\_`{|}-])"
MARKDOWN_ESCAPE = re.compile(r"([]!#*<>[\\_`|])")


def output_markdown_table(rows, header, hide=False):
	rows.insert(0, header)
	rows = [[MARKDOWN_ESCAPE.sub(r"\\\1", col) for col in row] for row in rows]
	lens = [max(*map(len, col), 2) for col in zip(*rows)]
	rows.insert(1, ["-" * alen for alen in lens])
	aformat = " | ".join(f"{{:<{alen}}}" for alen in lens)

	if hide:
		print("<details>\n<summary>Click to show the table</summary>\n")

	print("\n".join(starmap(aformat.format, rows)))

	if hide:
		print("\n</details>")


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(12, 8))

	ax.margins(0.01)

	widths = [timedelta(26)] + [(labels[i] - labels[i + 1]) * 0.9 for i in range(len(labels) - 1)]
	cum = [0] * len(labels)

	for name, values in stacks.items():
		ax.bar(labels, values, width=widths, bottom=cum, label=name)
		for i in range(len(cum)):
			cum[i] += values[i]

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def output_line_graph(adir, labels, series, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(12, 8))

	ax.margins(0.01)
	ax.axhline(color="k")
	ax.grid()

	for name, values in series.items():
		ax.plot(labels, values, marker="o", label=name)

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def output_duration(delta):
	m, s = divmod(delta.seconds, 60)
	h, m = divmod(m, 60)
	y, d = divmod(delta.days, 365)
	text = []
	if y:
		text.append(f"{y:n} year{'s' if y != 1 else ''}")
	if y or d:
		text.append(f"{d:n} day{'s' if d != 1 else ''}")
	if y or d or h:
		text.append(f"{h:n} hour{'s' if h != 1 else ''}")
	if y or d or h or m:
		text.append(f"{m:n} minute{'s' if m != 1 else ''}")
	if y or d or h or m or s:
		text.append(f"{s:n} second{'s' if s != 1 else ''}")

	return ", ".join(text)


def parse_isoformat(date):
	return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)


def get_all_bugs(product, component, start_date=None):
	bugs = []
	seen = set()
	offset = 0

	while True:
		print(f"\tOffset {offset:n}", file=sys.stderr)

		try:
			r = session.get(
				f"{BUGZILLA_API_URL}bug",
				headers=HEADERS,
				params={
					"product": product,
					"component": component,
					# attachments.creation_time,attachments.last_change_time,attachments.id,attachments.file_name,attachments.content_type,attachments.is_obsolete,attachments.is_patch,attachments.creator
					"include_fields": "assigned_to,blocks,cc,cf_last_resolved,comment_count,component,creation_time,depends_on,duplicates,id,is_confirmed,is_open,keywords,priority,product,resolution,see_also,severity,status,summary,type,votes,whiteboard,comments.id,comments.text,comments.creator,comments.creation_time,comments.reactions",
					# "last_change_time": f"{start_date:%Y-%m-%d}" if start_date is not None else start_date,
					"limit": LIMIT,
					"offset": offset,
				},
				timeout=60,
			)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			print(e, r.text, file=sys.stderr)
			sys.exit(1)
		except RequestException as e:
			print(e, file=sys.stderr)
			sys.exit(1)

		dupes = [bug["id"] for bug in data["bugs"] if bug["id"] in seen or seen.add(bug["id"])]
		if dupes:
			print(f"Warning: Duplicate Bug ids: {len(dupes):n} ({', '.join(map(str, sorted(dupes)))})", file=sys.stderr)

		bugs.extend(data["bugs"])

		if len(data["bugs"]) < LIMIT:
			break

		offset += LIMIT

	return bugs


def phabricator_api_bmo(method, data):
	try:
		r = session.post(f"{PHABRICATOR_API_URL}{method}", data={"api.token": PHABRICATOR_TOKEN, **data}, timeout=30)
		r.raise_for_status()
		result = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return result["result"]


def phabricator_api(method, data):
	results = []
	offset = 0
	after = None

	while True:
		print(f"\tOffset {offset:n}", file=sys.stderr)

		try:
			r = session.post(
				f"{PHABRICATOR_API_URL}{method}", data={"api.token": PHABRICATOR_TOKEN, **data, "after": after}, timeout=30
			)
			r.raise_for_status()
			result = r.json()
		except HTTPError as e:
			print(e, r.text, file=sys.stderr)
			sys.exit(1)
		except RequestException as e:
			print(e, file=sys.stderr)
			sys.exit(1)

		results.extend(result["result"]["data"])

		after = result["result"]["cursor"]["after"]
		if not after:
			break

		offset += 100

	return results


def hg_get_revisions(repo):
	limit = 10000
	revisions = []
	node = None

	while True:
		print(f"\tnode {node} ({len(revisions):n})", file=sys.stderr)

		try:
			r = session.get(
				f"{HG_API_URL}{repo}/json-shortlog{f'/{node}' if node else ''}", params={"revcount": limit}, timeout=120
			)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			print(e, r.text, file=sys.stderr)
			sys.exit(1)
		except RequestException as e:
			print(e, file=sys.stderr)
			sys.exit(1)

		revisions.extend(data["changesets"][1:] if node else data["changesets"])

		if len(data["changesets"]) < limit:
			break

		node = data["changesets"][-1]["node"]

	print(len(revisions), data["changeset_count"], file=sys.stderr)

	return revisions


def by_level(root_item, items, key):
	seen = set()
	level = [aid for aid in root_item["duplicates"] if aid in items]
	levels = []

	while level:
		next_level = []
		level_votes = []
		for aid in level:
			seen.add(aid)
			level_votes.append(items[aid][key])
			next_level.extend(cid for cid in items[aid]["duplicates"] if cid in items and cid not in seen)
		levels.append(level_votes)
		level = next_level

	return levels


WHITEBOARD_RE = re.compile(r"\[([^\]]+)\]")

PHABRICATOR_RE = re.compile(r"https://hg\.mozilla\.org/([^/]+(?:/[^/]+)?)/rev/([0-9a-f]{12,})\b")

HG_RE = re.compile(r"Differential Revision: https://phabricator\.services\.mozilla\.com/D([0-9]+)\b", re.I)


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	if PHABRICATOR_TOKEN is None:
		print("Error: Phabricator API token required", file=sys.stderr)
		sys.exit(1)

	end_date = datetime.now(timezone.utc)
	year = end_date.year
	month = end_date.month - 1
	if month < 1:
		year -= 1
		month += 12
	start_date = datetime(year - 10, 1, 1, tzinfo=timezone.utc)

	dates = []
	date = start_date
	while date < end_date:
		dates.append(date)

		year = date.year
		month = date.month + 1
		if month > 12:
			year += 1
			month -= 12
		date = date.replace(year=year, month=month)

	dates.pop()
	end_date = dates[-1]

	adir = os.path.join(f"{end_date:%Y-%m}", "bugzilla")

	os.makedirs(adir, exist_ok=True)

	file = os.path.join(f"{end_date:%Y-%m}", "BMO_bugs.json")

	if not os.path.exists(file):
		bugs = []

		starttime = time.perf_counter()

		for product, component in PRODUCTS:
			print(f"Processing product(s): {product!r}\tcomponent(s): {component!r}\n", file=sys.stderr)

			data = get_all_bugs(product, component, start_date)
			bugs.extend(data)

		endtime = time.perf_counter()
		print(f"Downloaded bugs in {output_duration(timedelta(seconds=endtime - starttime))}.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(bugs, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			bugs = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	items = {bug["id"]: bug for bug in bugs}

	# bmo_users = {user["name"]: user for bug in items.values() for user in bug["cc_detail"] + [bug["assigned_to_detail"]]}
	bmo_user_ids = {f"{user['id']}": user for bug in items.values() for user in bug["cc_detail"] + [bug["assigned_to_detail"]]}

	file = os.path.join(f"{end_date:%Y-%m}", f"Phabricator_revisions_{REPOSITORY}.json")

	if not os.path.exists(file):
		print(f"Downloading Phabricator revisions: {REPOSITORY}\n", file=sys.stderr)

		starttime = time.perf_counter()

		revisions = phabricator_api(
			"differential.revision.search",
			{
				"constraints[repositoryPHIDs][0]": REPOSITORY_PHID,
				"attachments[reviewers]": 1,
				"attachments[subscribers]": 1,
				"order": "oldest",
			},
		)

		endtime = time.perf_counter()
		print(f"Downloaded revisions in {output_duration(timedelta(seconds=endtime - starttime))}.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(revisions, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			revisions = json.load(f)

	revision_ids = {revision["id"]: revision for revision in revisions}

	file = os.path.join(f"{end_date:%Y-%m}", f"HG_commits_{REPOSITORY}.json")

	if not os.path.exists(file):
		print(f"Downloading Mozilla HG commits: {REPOSITORY}\n", file=sys.stderr)

		starttime = time.perf_counter()

		commits = hg_get_revisions(REPOSITORY)

		endtime = time.perf_counter()
		print(f"Downloaded commits in {output_duration(timedelta(seconds=endtime - starttime))}.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(commits, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			commits = json.load(f)

	hg_commits = {commit["node"][:12]: commit for commit in commits}

	revision_dates = {}
	for bug in items.values():
		for comment in bug["comments"]:
			if comment["creator"] == "pulsebot@bmo.tld":
				for repo, checksum in PHABRICATOR_RE.findall(comment["text"]):
					assert len(checksum) == 12

					if repo == REPOSITORY:
						commit = hg_commits[checksum]
						hg_res = HG_RE.search(commit["desc"])
						if hg_res:
							revision = int(hg_res.group(1))
							revision_dates[revision] = commit["date"][0]

	missing1 = {int(revision) for commit in commits for revision in HG_RE.findall(commit["desc"])} - {
		revision["id"] for revision in revisions
	}
	print(f"Warning: Missing Phabricator revisions: {len(missing1):n} ({', '.join(map(str, sorted(missing1)))})", file=sys.stderr)
	missing2 = {int(revision) for commit in commits for revision in HG_RE.findall(commit["desc"])} - set(revision_dates)
	print(f"Warning: Missing revisions from BMO bug comments: {len(missing2):n}", file=sys.stderr)
	missing = missing2 - missing1
	print(
		f"Missing revisions from BMO bug comments - Missing Phabricator revisions: {len(missing):n} ({', '.join(map(str, sorted(missing)))})",
		file=sys.stderr,
	)

	file = os.path.join(f"{end_date:%Y-%m}", "Phabricator_users.json")

	if os.path.exists(file):
		with open(file, encoding="utf-8") as f:
			phab_users = json.load(f)
	else:
		phab_users = {}

	print("## 🐞 Bugzilla/BMO (bugzilla.mozilla.org) and Phabricator\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	created = {}
	aopen = []

	open_deltas = []
	closed_deltas = {}

	closed = {}
	aclosed = []

	for bug in items.values():
		created_date = parse_isoformat(bug["creation_time"])
		created.setdefault((created_date.year, created_date.month), []).append(bug)

		if bug["is_open"]:
			aopen.append(bug)
			open_deltas.append(date - created_date)
		else:
			aclosed.append(bug)
			if bug["cf_last_resolved"]:
				closed_date = parse_isoformat(bug["cf_last_resolved"])
				closed.setdefault((closed_date.year, closed_date.month), []).append(bug)
				closed_deltas.setdefault((closed_date.year, closed_date.month), []).append(closed_date - created_date)

	revisions_closed = {}
	arevisions_closed = []

	for aid, date in revision_dates.items():
		revision = revision_ids[aid]

		if revision["fields"]["status"]["value"] == "published":
			closed_date = datetime.fromtimestamp(date, timezone.utc)
			arevisions_closed.append(revision)
			revisions_closed.setdefault((closed_date.year, closed_date.month), []).append(revision)

	open_count = len(aopen)
	counts = Counter(bug["product"] for bug in aopen)

	missing = len(bugs) - len(items)

	print(f"### Total Open Bugs: {open_count:n} / {len(items):n}\n")

	if missing:
		print(f"(Missing bugs: {missing:n})\n")

	output_markdown_table(
		[(f"{counts[product]:n}", product, component or "(all)") for products, component in PRODUCTS for product in products],
		("Bugs", "Product", "Component"),
	)

	if VERBOSE:
		counts = Counter((bug["product"], bug["component"]) for bug in aopen)

		print("\n#### Top Open Bug Components\n")

		rows = [(f"{count:n}", product, component) for (product, component), count in counts.most_common(30)]
		rows.append(("…", "…", f"({len(counts):n} components total)"))
		output_markdown_table(rows, ("Bugs", "Product", "Component"))

	triaged = sum(1 for bug in aopen if bug["is_confirmed"] and bug["priority"] != "--")

	print(f"\n**Triaged Open Bugs** (is confirmed and has a priority): {triaged:n} / {open_count:n} ({triaged / open_count:.4%})\n")

	mean = sum(open_deltas, timedelta()) / len(open_deltas)

	print(
		f"**Open Bugs Duration**\n* Average/Mean: {output_duration(mean)}\n* Median: {output_duration(statistics.median(open_deltas))}\n"
	)

	status_counts = Counter(bug["status"] for bug in aopen)

	print("#### Open Bug Statuses\n")
	output_markdown_table(
		[(key, f"{count:n} / {open_count:n} ({count / open_count:.4%})") for key, count in status_counts.most_common()],
		("Status", "Count"),
	)

	type_counts = Counter(bug["type"] for bug in aopen)

	print("\n#### Open Bug Types\n")
	output_markdown_table(
		[(key, f"{count:n} / {open_count:n} ({count / open_count:.4%})") for key, count in type_counts.most_common()],
		("Type", "Count"),
	)

	keyword_counts = Counter(keyword for bug in aopen for keyword in bug["keywords"])
	whiteboard_counts = Counter(
		whiteboard.lower()
		for bug in aopen
		if bug["whiteboard"]
		for whiteboard in WHITEBOARD_RE.findall(bug["whiteboard"]) or (bug["whiteboard"],)
	)

	if VERBOSE:
		print("\n### Top Open Bug Keywords\n")

		output_markdown_table([(f"{count:n}", key) for key, count in keyword_counts.most_common(20)], ("Count", "Keyword"))

		print(f"\nDescriptions of keywords: {BUGZILLA_BASE_URL}describekeywords.cgi\n")

		print("### Top Open Bug Whiteboard\n")

		output_markdown_table([(f"{count:n}", key) for key, count in whiteboard_counts.most_common(10)], ("Count", "Whiteboard"))
	else:
		print(f"""
#### Selected Open Bug Keywords

* Regression: {keyword_counts["regression"]:n}
* Dataloss: {keyword_counts["dataloss"]:n}
* Crash: {keyword_counts["crash"]:n}
* Performace: {keyword_counts["perf"]:n}
* Parity Outlook: {keyword_counts["parity-Outlook"]:n}
* Help Wanted: {keyword_counts["helpwanted"]:n}
* [Good First Bugs]({BUGZILLA_SHORT_URL}product:Thunderbird,%22MailNews%20Core%22,Calendar,%22Chat%20Core%22%20kw:good-first-bug): {keyword_counts["good-first-bug"]:n}

Also see: https://codetribute.mozilla.org/projects/thunderbird

#### Selected Open Bug Whiteboard

* patchlove: {whiteboard_counts["patchlove"]:n}
* datalossy: {whiteboard_counts["datalossy"]:n}""")

	closed_count = len(aclosed)
	resolution_counts = Counter(bug["resolution"] for bug in aclosed)

	print("\n### Closed Bugs\n")

	print("#### Closed Bug Resolutions\n")
	output_markdown_table(
		[(key, f"{count:n} / {closed_count:n} ({count / closed_count:.4%})") for key, count in resolution_counts.most_common()],
		("Resolution", "Count"),
	)

	type_counts = Counter(bug["type"] for bug in aclosed)

	print("\n#### Closed Bug Types\n")
	output_markdown_table(
		[(key, f"{count:n} / {closed_count:n} ({count / closed_count:.4%})") for key, count in type_counts.most_common()],
		("Type", "Count"),
	)

	labels = list(reversed(dates))
	created_statuses = {key: [] for key in STATUSES}
	closed_resolutions = {key: [] for key in RESOLUTIONS}
	deltas = {key: [] for key in ("Mean", "Median")}
	differences = []

	with open(os.path.join(adir, "BMO_bugs_created.csv"), "w", newline="", encoding="utf-8") as csvfile1, open(
		os.path.join(adir, "BMO_bugs_closed.csv"), "w", newline="", encoding="utf-8"
	) as csvfile2, open(os.path.join(adir, "BMO_bugs_diff.csv"), "w", newline="", encoding="utf-8") as csvfile3:
		writer1 = csv.DictWriter(csvfile1, ("Date", "Total Created", *STATUSES))
		writer2 = csv.DictWriter(csvfile2, ("Date", "Total Closed", *RESOLUTIONS))
		writer3 = csv.writer(csvfile3)

		writer1.writeheader()
		writer2.writeheader()
		writer3.writerow(("Date", "Total Created", "Total Closed", "Difference"))

		rows1 = []
		rows2 = []
		rows3 = []
		for date in reversed(dates):
			adate = (date.year, date.month)

			created_counts = Counter(bug["status"] for bug in created[adate])
			created_count = len(created[adate])

			closed_counts = Counter(bug["resolution"] for bug in closed[adate])
			closed_count = len(closed[adate])

			mean = sum(closed_deltas[adate], timedelta()) / len(closed_deltas[adate])
			median = statistics.median(closed_deltas[adate])

			difference = created_count - closed_count

			writer1.writerow({"Date": f"{date:%B %Y}", "Total Created": created_count, **created_counts})
			writer2.writerow({"Date": f"{date:%B %Y}", "Total Closed": closed_count, **closed_counts})
			writer3.writerow((f"{date:%B %Y}", created_count, closed_count, difference))

			rows1.append((
				f"{date:%B %Y}",
				f"{created_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in created_counts.most_common()),
			))
			rows2.append((
				f"{date:%B %Y}",
				f"{closed_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in closed_counts.most_common()),
			))
			rows3.append((f"{date:%B %Y}", f"{created_count:n}", f"{closed_count:n}", f"{difference:n}"))

			for key in STATUSES:
				created_statuses[key].append(created_counts[key])

			for key in RESOLUTIONS:
				closed_resolutions[key].append(closed_counts[key])

			deltas["Mean"].append((mean.days * 24 * 60 * 60 + mean.seconds) / (365 * 24 * 60 * 60))
			deltas["Median"].append((median.days * 24 * 60 * 60 + median.seconds) / (365 * 24 * 60 * 60))

			differences.append(difference)

	print("\n### Total Created Bugs by Month\n")
	output_stacked_bar_graph(adir, labels, created_statuses, "Bugzilla Created Bugs by Month", "Date", "Total Created", "Status")
	output_markdown_table(rows1, ("Month", "Total Created", "Statuses"), True)

	print("\n### Total Closed Bugs by Month\n")
	output_stacked_bar_graph(
		adir, labels, closed_resolutions, "Bugzilla Closed Bugs by Month", "Date", "Total Closed", "Resolution"
	)
	output_markdown_table(rows2, ("Month", "Total Closed", "Resolutions"), True)

	print("\n### Total Created vs Total Closed Difference by Month\n\n(Positive numbers mean the backlog is increasing)\n")
	output_line_graph(
		adir, labels, {"Difference": differences}, "Bugzilla Created vs Closed Difference by Month", "Date", "Difference", None
	)
	output_markdown_table(rows3, ("Month", "Total Created", "Total Closed", "Difference"), True)

	print("\n### Closed Bugs Total Duration by Month\n")
	output_line_graph(adir, labels, deltas, "Bugzilla Closed Bugs Total Duration by Month", "Date", "Duration (years)", None)

	patch_user_counts = Counter(revision["fields"]["authorPHID"] for revision in arevisions_closed)
	apatch_user_counts = Counter(revision["fields"]["authorPHID"] for revision in revisions_closed[end_date.year, end_date.month])
	bug_counts = {}
	for revision in revisions_closed[end_date.year, end_date.month]:
		bug_counts.setdefault(revision["fields"]["bugzilla.bug-id"], []).append(revision)
	user_counts = Counter(
		author
		for revisions in bug_counts.values()
		for author in {
			revision["fields"]["authorPHID"] for revision in revisions if revision["fields"]["status"]["value"] == "published"
		}
	)
	print(f"\n### Revisions by User ({end_date:%B %Y})\n")

	rows = []
	changed = False
	for user, count in apatch_user_counts.most_common():
		if user not in phab_users:
			data = phabricator_api_bmo("bugzilla.account.search", {"phids[0]": user})
			if data:
				phab_users[user] = data[0]
				changed = True

		bmo_user = bmo_user_ids[phab_users[user]["id"]]
		if bmo_user["name"] not in phab_users:
			adata = phabricator_api("user.search", {"constraints[phids][0]": user})
			if adata:
				phab_users[bmo_user["name"]] = adata[0]
				changed = True

		phab_user = phab_users[bmo_user["name"]]
		rows.append((
			f"{count:n}",
			f"{user_counts[user]:n}",
			"🌟" if not patch_user_counts[user] - count else "",
			phab_user["fields"]["username"],
			phab_user["fields"]["realName"],
			bmo_user["nick"],
			bmo_user["real_name"],
		))

	output_markdown_table(rows, ("Revisions", "Bugs", "", "Phabricator User", "Name", "BMO User", "Name"))
	print(
		"\n🌟 = First time contributor\n\n(The numbers are smaller than Magnus’s e-mail as this is only looking at public Phabricator revisions.)"
	)

	if changed:
		with open(file, "w", encoding="utf-8") as f:
			json.dump(phab_users, f, ensure_ascii=False, indent="\t")

	print("\n### Top Open Bugs by Total Reactions\n")

	rows = []
	for i, item in enumerate(
		sorted(
			aopen, key=lambda x: (sum(x["comments"][0]["reactions"].values()) if x["comments"] else 0, x["votes"]), reverse=True
		),
		1,
	):
		comments = by_level(item, items, "comments")
		rows.append((
			f"{i:n}",
			f"""{sum(item["comments"][0]["reactions"].values()) if item["comments"] else 0:n}{"".join(f" + {sum(acomment[0]['reactions'].values() for acomment in comment):n}" for comment in comments if any(acomment[0]["reactions"] for acomment in comment))}""",
			f"{item['votes']:n}",
			# f"{item['id']}",
			item["type"],
			item["product"],
			item["component"],
			textwrap.shorten(item["summary"], 80, placeholder="…"),
			f"{BUGZILLA_SHORT_URL}{item['id']}",
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Reactions", "Votes", "Type", "Product", "Component", "Summary", "URL"))

	print("\n### Top Open Bugs by Total Votes\n")

	rows = []
	for i, item in enumerate(sorted(aopen, key=operator.itemgetter("votes"), reverse=True), 1):
		votes = by_level(item, items, "votes")
		rows.append((
			f"{i:n}",
			f"{item['votes']:n}{''.join(f' + {sum(vote):n}' for vote in votes if any(vote))}",
			f"{sum(item['comments'][0]['reactions'].values()) if item['comments'] else 0:n}",
			# f"{item['id']}",
			item["type"],
			item["product"],
			item["component"],
			textwrap.shorten(item["summary"], 80, placeholder="…"),
			f"{BUGZILLA_SHORT_URL}{item['id']}",
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Votes", "Reactions", "Type", "Product", "Component", "Summary", "URL"))

	# Change your votes: {BUGZILLA_BASE_URL}page.cgi?id=voting/user.html
	print(
		f"\nSee full list: {BUGZILLA_SHORT_URL}product:Thunderbird,%22MailNews%20Core%22,Calendar,%22Chat%20Core%22%20votes%3E=20"
	)

	print("\nWhen possible, users should prioritize adding kudos to Mozilla Connect ideas instead of voting on Bugzilla.")

	print("\n### Top Open Bugs by Total CCed\n")

	rows = []
	for i, item in enumerate(sorted(aopen, key=lambda x: len(x["cc"]), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{len(item['cc']):n}",
			# f"{item['id']}",
			item["type"],
			item["product"],
			item["component"],
			textwrap.shorten(item["summary"], 80, placeholder="…"),
			f"{BUGZILLA_SHORT_URL}{item['id']}",
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "CCed", "Type", "Product", "Component", "Summary", "URL"))

	print(
		f"\nSee full list: {BUGZILLA_SHORT_URL}product:Thunderbird,%22MailNews%20Core%22,Calendar,%22Chat%20Core%22%20cc_count%3E=20"
	)

	print("\n### Top Bugs by Total Duplicates\n")

	rows = []
	for i, item in enumerate(
		sorted(
			(bug for bug in items.values() if bug["is_open"] or bug["resolution"] in {"INVALID", "WONTFIX"}),
			key=lambda x: len(x["duplicates"]),
			reverse=True,
		),
		1,
	):
		duplicates = by_level(item, items, "duplicates")
		rows.append((
			f"{i:n}",
			f"{len(item['duplicates']):n}{''.join(f' + {sum(map(len, duplicate)):n}' for duplicate in duplicates if any(duplicate))}",
			# f"{item['id']}",
			item["status"],
			item["resolution"],
			item["type"],
			item["product"],
			item["component"],
			textwrap.shorten(item["summary"], 80, placeholder="…"),
			f"{BUGZILLA_SHORT_URL}{item['id']}",
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Duplicates", "Status", "Resolution", "Type", "Product", "Component", "Summary", "URL"))

	print("\n### Top Open Bugs by Total Comments\n")

	rows = []
	for i, item in enumerate(sorted(aopen, key=operator.itemgetter("comment_count"), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{item['comment_count']:n}",
			# f"{item['id']}",
			item["type"],
			item["product"],
			item["component"],
			textwrap.shorten(item["summary"], 80, placeholder="…"),
			f"{BUGZILLA_SHORT_URL}{item['id']}",
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Comments", "Type", "Product", "Component", "Summary", "URL"))


if __name__ == "__main__":
	main()
