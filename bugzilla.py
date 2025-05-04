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
session.mount("https://", requests.adapters.HTTPAdapter(max_retries=urllib3.util.Retry(3, backoff_factor=1)))
atexit.register(session.close)

BUGZILLA_BASE_URL = "https://bugzilla.mozilla.org/"
BUGZILLA_API_URL = f"{BUGZILLA_BASE_URL}rest/"
BUGZILLA_SHORT_URL = "https://bugzil.la/"

PRODUCTS = ((("Thunderbird", "MailNews Core", "Calendar", "Chat Core"), None), (("Webtools",), "ISPDB Database Entries"))

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

	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def parse_isoformat(date):
	return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)


def get_all_bugs(product, component, start_date=None):
	bugs = []
	seen = set()
	offset = 0

	while True:
		print(f"\tOffset {offset}", file=sys.stderr)

		try:
			r = session.get(
				f"{BUGZILLA_API_URL}bug",
				params={
					"product": product,
					"component": component,
					"include_fields": "product,component,votes,status,severity,cf_last_resolved,resolution,priority,is_confirmed,duplicates,comment_count,type,summary,creation_time,is_open,keywords,cc,whiteboard,id,blocks,depends_on,comments.reactions",
					# "last_change_time": f"{start_date:%Y-%m-%d}" if start_date is not None else start_date,
					"limit": LIMIT,
					"offset": offset,
				},
				timeout=30,
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


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	start_date = datetime(2015, 1, 1, tzinfo=timezone.utc)
	end_date = datetime.now(timezone.utc)
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
		print(f"Downloaded bugs in {endtime - starttime:n} seconds.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(bugs, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			bugs = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	items = {bug["id"]: bug for bug in bugs}

	print("## 🐞 Bugzilla/BMO (bugzilla.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	created = {}
	aopen = []
	closed = {}
	aclosed = []

	for bug in items.values():
		date = parse_isoformat(bug["creation_time"])
		created.setdefault((date.year, date.month), []).append(bug)

		if bug["is_open"]:
			aopen.append(bug)
		else:
			aclosed.append(bug)
			if bug["cf_last_resolved"]:
				date = parse_isoformat(bug["cf_last_resolved"])
				closed.setdefault((date.year, date.month), []).append(bug)

	open_count = len(aopen)
	counts = Counter(bug["product"] for bug in aopen)

	print(f"### Total Open Bugs: {open_count:n} / {len(items):n}\n")

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

	if VERBOSE:
		print("\n### Top Open Bug Keywords\n")

		output_markdown_table([(f"{count:n}", key) for key, count in keyword_counts.most_common(20)], ("Count", "Keyword"))

		print(f"\nDescriptions of keywords: {BUGZILLA_BASE_URL}describekeywords.cgi\n")
	else:
		print(f"""
* Regression Bugs: {keyword_counts.get("regression", 0):n}
* Dataloss Bugs: {keyword_counts.get("dataloss", 0):n}
* Crash Bugs: {keyword_counts.get("crash", 0):n}
* [Good First Bugs]({BUGZILLA_SHORT_URL}product:Thunderbird,%22MailNews%20Core%22,Calendar,%22Chat%20Core%22%20kw:good-first-bug): {keyword_counts.get("good-first-bug", 0):n}
""")

	closed_count = len(aclosed)
	resolution_counts = Counter(bug["resolution"] for bug in aclosed)

	print("### Closed Bugs\n")

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
				created_statuses[key].append(created_counts.get(key, 0))

			for key in RESOLUTIONS:
				closed_resolutions[key].append(closed_counts.get(key, 0))

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

	print("\n### Top Open Bugs by Total Reactions\n")

	rows = []
	for i, item in enumerate(
		sorted(aopen, key=lambda x: (sum(x["comments"][0]["reactions"].values()), x["votes"]), reverse=True), 1
	):
		comments = by_level(item, items, "comments")
		rows.append((
			f"{i:n}",
			f"""{sum(item["comments"][0]["reactions"].values()):n}{"".join(f" + {sum(acomment[0]['reactions'].values() for acomment in comment):n}" for comment in comments if any(acomment[0]["reactions"] for acomment in comment))}""",
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
			f"{sum(item['comments'][0]['reactions'].values()):n}",
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
