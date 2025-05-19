#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 github.py

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
from urllib.parse import urlparse

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

GITHUB_BASE_URL = "https://github.com/"
GITHUB_API_URL = "https://api.github.com/"

# Add GitHub API token
GITHUB_TOKEN = None

HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN is not None else None

ORGANIZATIONS = ("thunderbird", "mozilla-comm", "thunderbird-council")

REPOSITORIES = (("mozilla", "releases-comm-central"),)

LIMIT = 100

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


suffix_power_char = ("", "K", "M", "G", "T", "P", "E", "Z", "Y", "R", "Q")


def output_unit(number, scale=False):
	scale_base = 1000 if scale else 1024

	power = 0
	while abs(number) >= scale_base:
		power += 1
		number /= scale_base

	anumber = abs(number)
	anumber += 0.0005 if anumber < 10 else 0.005 if anumber < 100 else 0.05 if anumber < 1000 else 0.5

	if number and anumber < 1000 and power > 0:
		strm = f"{number:.{sys.float_info.dig}g}"

		length = 5 + (number < 0)
		if len(strm) > length:
			prec = 3 if anumber < 10 else 2 if anumber < 100 else 1
			strm = f"{number:.{prec}f}"
	else:
		strm = f"{number:.0f}"

	# "k" if power == 1 and scale else
	strm += " " + (suffix_power_char[power] if power < len(suffix_power_char) else "(error)")

	if not scale and power > 0:
		strm += "i"

	return strm


def parse_isoformat(date):
	return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)


def github_api(url, params=None):
	try:
		r = session.get(url, headers=HEADERS, params=params, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	if not int(r.headers["x-ratelimit-remaining"]):
		sec = int(r.headers["x-ratelimit-reset"]) - time.time()
		print(f"Sleeping for {sec} seconds", file=sys.stderr)
		time.sleep(max(sec + 10, 60))

	return r, data


def get_repositories(org):
	repos = []
	page = 1

	while True:
		print(f"\tPage {page} ({len(repos):n})", file=sys.stderr)

		r, data = github_api(f"{GITHUB_API_URL}orgs/{org}/repos", {"per_page": LIMIT, "page": page})

		repos.extend(data)

		if "next" not in r.links:
			break

		page += 1

	return repos


def get_repository(org, repo):
	_, data = github_api(f"{GITHUB_API_URL}repos/{org}/{repo}")
	return data


def get_user(user):
	_, data = github_api(f"{GITHUB_API_URL}users/{user}")
	return data


def get_languages(org, repo):
	_, data = github_api(f"{GITHUB_API_URL}repos/{org}/{repo}/languages")
	return data


def get_all_issues(org, repo, start_date=None):
	issues = []
	page = 1

	while True:
		print(f"\tPage {page} ({len(issues):n})", file=sys.stderr)

		r, data = github_api(
			f"{GITHUB_API_URL}repos/{org}/{repo}/issues",
			{
				"state": "all",
				# "since": f"{start_date:%Y-%m-%d}" if start_date is not None else start_date,
				"per_page": LIMIT,
				"page": page,
			},
		)

		issues.extend(data)

		if "next" not in r.links:
			break

		page += 1

	return issues


def get_all_discussions(org, repo, start_date=None):
	discussions = []
	page = 1

	while True:
		print(f"\tPage {page} ({len(discussions):n})", file=sys.stderr)

		r, data = github_api(f"{GITHUB_API_URL}repos/{org}/{repo}/discussions", {"per_page": LIMIT, "page": page})

		discussions.extend(data)

		if "next" not in r.links:
			break

		page += 1

	return discussions


LANGUAGE_EMOJI = {
	"AIDL": "🤖",
	"BitBake": "🍞",
	"C": "🌊",
	"C++": "➕",
	"CSS": "🎨",
	"DIGITAL Command Language": "🖥️",
	"Dockerfile": "🐳",
	"Fluent": "🔤",
	"HCL": "⚙️",
	"HTML": "🌐",
	"IDL": "💬",
	"Java": "☕",
	"JavaScript": "📜",
	"Jinja": "🧞",
	"Kotlin": "🔷",
	"Less": "➖",
	"Makefile": "🛠️",
	"Mako": "🦈",
	"NSIS": "📦",
	"Objective-C++": "🎯",
	"PHP": "🐘",
	"Pawn": "♟️",
	"Python": "🐍",
	"R": "📊",
	"RenderScript": "🎞️",
	"Roff": "📄",
	"Ruby": "💎",
	"Rust": "🦀",
	"SCSS": "💅",
	"Shell": "🐚",
	"Smarty": "🤓",
	"Swift": "🐦",
	"TypeScript": "🟦",
	"Vue": "🖼️",
}


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
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

	adir = os.path.join(f"{end_date:%Y-%m}", "github")

	os.makedirs(adir, exist_ok=True)

	file = os.path.join(f"{end_date:%Y-%m}", "GitHub_repos.json")

	if not os.path.exists(file):
		repos = []

		print("Getting Repositories", file=sys.stderr)

		for org in ORGANIZATIONS:
			data = get_repositories(org)
			repos.extend(data)

		for org, repo in REPOSITORIES:
			data = get_repository(org, repo)
			repos.append(data)

		print("Repositories:", [repo["full_name"] for repo in repos], file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(repos, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			repos = json.load(f)

	file = os.path.join(f"{end_date:%Y-%m}", "GitHub_issues.json")

	if not os.path.exists(file):
		issues = []
		# discussions = []

		print("Getting Issues", file=sys.stderr)
		starttime = time.perf_counter()

		for repo in repos:
			print(f"\nRepository: {repo['full_name']!r}", file=sys.stderr)

			data = get_all_issues(repo["owner"]["login"], repo["name"], start_date)
			issues.extend(data)

			# data = get_all_discussions(repo["owner"]["login"], repo["name"], start_date)
			# discussions.extend(data)

		endtime = time.perf_counter()
		print(f"Downloaded issues in {output_duration(timedelta(seconds=endtime - starttime))}.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(issues, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			issues = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	file = os.path.join(f"{end_date:%Y-%m}", "GitHub_languages.json")

	if not os.path.exists(file):
		languages = {}

		print("Getting Languages", file=sys.stderr)
		starttime = time.perf_counter()

		for repo in repos:
			print(f"\nRepository: {repo['full_name']!r}", file=sys.stderr)

			languages[repo["full_name"]] = get_languages(repo["owner"]["login"], repo["name"])

		endtime = time.perf_counter()
		print(f"Downloaded languages in {output_duration(timedelta(seconds=endtime - starttime))}.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(languages, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			languages = json.load(f)

	file = os.path.join(f"{end_date:%Y-%m}", "GitHub_users.json")

	if os.path.exists(file):
		with open(file, encoding="utf-8") as f:
			users = json.load(f)
	else:
		users = {}

	print("## 🐙 GitHub\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	issues_created = {(adate.year, adate.month): [] for adate in dates}
	pr_created = {(adate.year, adate.month): [] for adate in dates}

	issues_closed = {(adate.year, adate.month): [] for adate in dates}
	pr_closed = {(adate.year, adate.month): [] for adate in dates}

	issues_open = []
	pr_open = []

	issues_open_deltas = []
	pr_open_deltas = []

	issues_closed_deltas = {(adate.year, adate.month): [] for adate in dates}
	# pr_closed_deltas = {(adate.year, adate.month): [] for adate in dates}

	aissues_closed = []
	apr_closed = []

	for issue in issues:
		created_date = parse_isoformat(issue["created_at"])
		if "pull_request" in issue:
			pr_created.setdefault((created_date.year, created_date.month), []).append(issue)
		else:
			issues_created.setdefault((created_date.year, created_date.month), []).append(issue)

		if issue["closed_at"]:
			closed_date = parse_isoformat(issue["closed_at"])
			if "pull_request" in issue:
				pr_closed.setdefault((closed_date.year, closed_date.month), []).append(issue)
				# pr_closed_deltas.setdefault((closed_date.year, closed_date.month), []).append(closed_date - created_date)
				apr_closed.append(issue)
			else:
				issues_closed.setdefault((closed_date.year, closed_date.month), []).append(issue)
				issues_closed_deltas.setdefault((closed_date.year, closed_date.month), []).append(closed_date - created_date)
				aissues_closed.append(issue)
		elif "pull_request" in issue:
			pr_open.append(issue)
			pr_open_deltas.append(date - created_date)
		else:
			issues_open.append(issue)
			issues_open_deltas.append(date - created_date)

	issue_counts = Counter(urlparse(issue["repository_url"]).path.split("/")[-2] for issue in issues_open)
	pr_counts = Counter(urlparse(issue["repository_url"]).path.split("/")[-2] for issue in pr_open)

	output_markdown_table(
		[
			(f"{issue_counts[organization]:n}", f"{pr_counts[organization]:n}", organization, repository or "(all)")
			for item in (((org, None) for org in ORGANIZATIONS), REPOSITORIES)
			for organization, repository in item
		],
		("Issues", "Pull Requests", "Organization", "Repository"),
	)

	issue_counts = Counter("/".join(urlparse(issue["repository_url"]).path.split("/")[-2:]) for issue in issues_open)
	issues_count = len(issues_open)
	triaged_issues = sum(
		1
		for issue in issues_open
		if issue["type"] or (issue["labels"] and not any(label["name"] == "unconfirmed" for label in issue["labels"]))
	)  # issue['assignee']

	print(f"\n### Total Open Issues: {issues_count:n} / {sum(1 for issue in issues if 'pull_request' not in issue):n}\n")

	rows = [(f"{count:n}", key) for key, count in issue_counts.most_common(10)]
	rows.append(("…", f"({len(issue_counts):n} repositories total)"))
	output_markdown_table(rows, ("Open Issues", "Repository"))

	print(f"\nSee all open Issues: {GITHUB_BASE_URL}search?q=org%3Athunderbird+state%3Aopen+type%3Aissue")

	print(f"\n**Triaged Open Issues**: {triaged_issues:n} / {issues_count:n} ({triaged_issues / issues_count:.4%})\n")
	print("Triaged meaning it has a type or at least one label and not the 'unconfirmed' label.\n")

	mean = sum(issues_open_deltas, timedelta()) / len(issues_open_deltas)

	print(
		f"**Open Issues Duration**\n* Average/Mean: {output_duration(mean)}\n* Median: {output_duration(statistics.median(issues_open_deltas))}\n"
	)

	label_counts = Counter(label["name"] for issue in issues_open for label in issue["labels"])

	print("#### Top Open Issue Labels:\n")

	output_markdown_table([(f"{count:n}", key) for key, count in label_counts.most_common(20)], ("Count", "Label"))

	print(f"\n* Good First Issues: {label_counts['good first issue']:n}\n")

	if VERBOSE:
		type_counts = Counter(issue["type"]["name"] for issue in issues_open if issue["type"])

		print("#### Open Issue Types:\n\n(Most issues do not yet have a type set.)\n")
		output_markdown_table(
			[(key, f"{count:n} / {issues_count:n} ({count / issues_count:.4%})") for key, count in type_counts.most_common()],
			("Type", "Count"),
		)

	reason_counts = Counter(issue["state_reason"] for issue in aissues_closed)
	reasons_count = len(aissues_closed)

	print("\n#### Closed Issue States:\n")
	output_markdown_table(
		[(key, f"{count:n} / {reasons_count:n} ({count / reasons_count:.4%})") for key, count in reason_counts.most_common()],
		("State", "Count"),
	)

	pr_counts = Counter("/".join(urlparse(issue["repository_url"]).path.split("/")[-2:]) for issue in pr_open)
	prs_count = len(pr_open)
	triaged_prs = sum(1 for issue in pr_open if issue["type"] or issue["labels"] or issue["assignee"])

	print(f"\n### Total Open Pull Requests: {prs_count:n} / {sum(1 for issue in issues if 'pull_request' in issue):n}\n")

	rows = [(f"{count:n}", key) for key, count in pr_counts.most_common(5)]
	rows.append(("…", f"({len(pr_counts):n} repositories total)"))
	output_markdown_table(rows, ("Open Pull Requests", "Repository"))

	print(f"\nSee all open Pull Requests: {GITHUB_BASE_URL}search?q=org%3Athunderbird+state%3Aopen+type%3Apr")

	print(f"\n**Triaged Open Pull Requests**: {triaged_prs:n} / {prs_count:n} ({triaged_prs / prs_count:.4%})\n")
	print("Triaged meaning it has a type, at least one label or an assignee.\n")

	mean = sum(pr_open_deltas, timedelta()) / len(pr_open_deltas)

	print(
		f"**Open Pull Requests Duration**\n* Average/Mean: {output_duration(mean)}\n* Median: {output_duration(statistics.median(pr_open_deltas))}\n"
	)

	state_counts = Counter("Merged" if issue["pull_request"]["merged_at"] else "Unmerged" for issue in apr_closed)
	states_count = len(apr_closed)

	print("#### Closed Pull Request States:\n")
	output_markdown_table(
		[(key, f"{count:n} / {states_count:n} ({count / states_count:.4%})") for key, count in state_counts.most_common()],
		("State", "Count"),
	)

	keys = ("Open", "Assigned", "Closed")
	issue_keys = [f"Issues {key}" for key in keys]
	pr_keys = [f"PRs {key}" for key in keys]

	labels = list(reversed(dates))
	created_state = {k: [] for key in zip(issue_keys, pr_keys) for k in key}
	closed_state = {key: [] for key in (*dict(reason_counts.most_common()), "Merged", "Unmerged")}
	deltas = {key: [] for key in ("Mean", "Median")}
	differences = []

	with open(os.path.join(adir, "GitHub_created.csv"), "w", newline="", encoding="utf-8") as csvfile1, open(
		os.path.join(adir, "GitHub_closed.csv"), "w", newline="", encoding="utf-8"
	) as csvfile2, open(os.path.join(adir, "GitHub_diff.csv"), "w", newline="", encoding="utf-8") as csvfile3:
		writer1 = csv.DictWriter(csvfile1, ("Date", "Issues Created", *issue_keys, "PRs Created", *pr_keys, "Total Created"))
		writer2 = csv.DictWriter(
			csvfile2, ("Date", "Issues Closed", "PRs Closed", "Total Closed", *reason_counts, "Merged", "Unmerged")
		)
		writer3 = csv.writer(csvfile3)

		writer1.writeheader()
		writer2.writeheader()
		writer3.writerow(("Date", "Total Created", "Total Closed", "Difference"))

		rows1 = []
		rows2 = []
		rows3 = []
		for date in reversed(dates):
			adate = (date.year, date.month)

			created_issues_count = len(issues_created[adate])
			# created_issue_counts = Counter(issue['type']['name'] if issue['type'] else 'unknown' for issue in issues_created[adate])
			created_issue_counts = Counter(
				"Closed" if issue["closed_at"] else "Assigned" if issue["assignee"] else "Open" for issue in issues_created[adate]
			)
			created_prs_count = len(pr_created[adate])
			# created_pr_counts = Counter(issue['type']['name'] if issue['type'] else 'unknown' for issue in pr_created[adate])
			created_pr_counts = Counter(
				"Closed" if issue["closed_at"] else "Assigned" if issue["assignee"] else "Open" for issue in pr_created[adate]
			)
			created_count = created_issues_count + created_prs_count

			closed_issues_count = len(issues_closed[adate])
			closed_issue_counts = Counter(issue["state_reason"] for issue in issues_closed[adate])
			closed_prs_count = len(pr_closed[adate])
			closed_pr_counts = Counter("Merged" if issue["pull_request"]["merged_at"] else "Unmerged" for issue in pr_closed[adate])
			closed_count = closed_issues_count + closed_prs_count

			mean = (
				sum(issues_closed_deltas[adate], timedelta()) / len(issues_closed_deltas[adate])
				if issues_closed_deltas[adate]
				else timedelta()
			)
			median = statistics.median(issues_closed_deltas[adate]) if issues_closed_deltas[adate] else timedelta()

			difference = created_count - closed_count

			writer1.writerow({
				"Date": f"{date:%B %Y}",
				"Issues Created": created_issues_count,
				**{f"Issues {key}": value for key, value in created_issue_counts.items()},
				"PRs Created": created_prs_count,
				**{f"PRs {key}": value for key, value in created_pr_counts.items()},
				"Total Created": created_count,
			})
			writer2.writerow({
				"Date": f"{date:%B %Y}",
				"Issues Closed": closed_issues_count,
				"PRs Closed": closed_prs_count,
				"Total Closed": closed_count,
				**closed_issue_counts,
				**closed_pr_counts,
			})
			writer3.writerow((f"{date:%B %Y}", created_count, closed_count, difference))

			rows1.append((
				f"{date:%B %Y}",
				f"{created_issues_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in created_issue_counts.most_common()),
				f"{created_prs_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in created_pr_counts.most_common()),
				f"{created_count:n}",
			))
			rows2.append((
				f"{date:%B %Y}",
				f"{closed_issues_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in closed_issue_counts.most_common()),
				f"{closed_prs_count:n}",
				", ".join(f"{key}: {count:n}" for key, count in closed_pr_counts.most_common()),
				f"{closed_count:n}",
			))
			rows3.append((f"{date:%B %Y}", f"{created_count:n}", f"{closed_count:n}", f"{difference:n}"))

			for key in keys:
				created_state[f"Issues {key}"].append(created_issue_counts[key])
			for key in keys:
				created_state[f"PRs {key}"].append(created_pr_counts[key])

			for key in reason_counts:
				closed_state[key].append(closed_issue_counts[key])
			for key in ("Merged", "Unmerged"):
				closed_state[key].append(closed_pr_counts[key])

			deltas["Mean"].append((mean.days * 24 * 60 * 60 + mean.seconds) / (365 * 24 * 60 * 60))
			deltas["Median"].append((median.days * 24 * 60 * 60 + median.seconds) / (365 * 24 * 60 * 60))

			differences.append(difference)

	print("\n### Total Created Issues and Pull Requests by Month\n")
	output_stacked_bar_graph(
		adir, labels, created_state, "GitHub Created Issues and Pull Requests by Month", "Date", "Total Created", "State"
	)
	output_markdown_table(
		rows1, ("Month", "Created Issues", "Created Issue State", "Created PRs", "Created PR State", "Total Created"), True
	)

	print("\n### Total Closed Issues and Pull Requests by Month\n")
	output_stacked_bar_graph(
		adir, labels, closed_state, "GitHub Closed Issues and Pull Requests by Month", "Date", "Total Closed", "State"
	)
	output_markdown_table(
		rows2, ("Month", "Closed Issues", "Closed Issue State", "Closed PRs", "Closed PR State", "Total Closed"), True
	)

	print("\n### Total Created vs Total Closed Difference by Month\n\n(Positive numbers mean the backlog is increasing)\n")
	output_line_graph(
		adir, labels, {"Difference": differences}, "GitHub Created vs Closed Difference by Month", "Date", "Difference", None
	)
	output_markdown_table(rows3, ("Month", "Total Created", "Total Closed", "Difference"), True)

	print("\n### Closed Issues Total Duration by Month\n")
	output_line_graph(adir, labels, deltas, "GitHub Closed Issues Total Duration by Month", "Date", "Duration (years)", None)

	pr_user_counts = Counter(
		item["user"]["login"] for item in apr_closed if item["pull_request"]["merged_at"] and item["user"]["type"] != "Bot"
	)
	apr_user_counts = Counter(
		(item["user"]["id"], item["user"]["login"], item["user"]["html_url"])
		for item in pr_closed[end_date.year, end_date.month]
		if item["pull_request"]["merged_at"] and item["user"]["type"] != "Bot"
	)
	print(f"\n### Merged Pull Requests by User, excluding Bots ({end_date:%B %Y})\n")

	rows = []
	changed = False
	for (_id, user, url), count in apr_user_counts.most_common():
		if user not in users:
			users[user] = get_user(user)
			changed = True

		auser = users[user]
		rows.append((
			f"{count:n}",
			f"{'🌟' if not pr_user_counts[user] - count else ''}{'🙋' if auser['hireable'] else ''}",
			user,
			auser["name"] or "-",
			auser["company"] or "-",
			textwrap.shorten(auser["bio"] or "", 60, placeholder="…"),
			url,
		))

	output_markdown_table(rows, ("PRs", "", "User", "Name", "Company", "Bio", "URL"))
	print("\n🌟 = First time contributor, 🙋 = Available for hire")

	if changed:
		with open(file, "w", encoding="utf-8") as f:
			json.dump(users, f, ensure_ascii=False, indent="\t")

	print("\n### Top Repositories by Stars\n")

	rows = []
	for i, item in enumerate(sorted(repos, key=operator.itemgetter("stargazers_count"), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{item['stargazers_count']:n}",
			f"{parse_isoformat(item['created_at']):%Y-%m-%d}",
			item["full_name"],
			textwrap.shorten(item["description"], 80, placeholder="…"),
			item["html_url"],
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Stars", "Created", "Repository", "Description", "URL"))

	# license_counts = Counter(repo['license']['name'] for repo in repos if repo['license'])

	print(f"\nTotal Stars: {sum(repo['stargazers_count'] for repo in repos):n}")

	language_counts = Counter()
	for language in languages.values():
		language_counts.update({lang: count for lang, count in language.items() if lang not in {"HTML", "Fluent"}})
	language_count = sum(language_counts.values())

	print("\n### Top Programming Languages by Bytes of Code, excluding HTML and Fluent\n")

	output_markdown_table(
		[
			(
				f"{count / language_count:.4%}",
				f"{output_unit(count)}B",
				f"{f'{LANGUAGE_EMOJI[key]} ' if key in LANGUAGE_EMOJI else ''}{key}",
			)
			for key, count in language_counts.most_common(15)
		],
		("%", "Bytes", "Language"),
	)

	repo_counts = Counter({repo: sum(language.values()) for repo, language in languages.items()})

	print("\n### Top Repositories by Bytes of Code\n")

	rows = []
	for key, count in repo_counts.most_common(15):
		language_counts = Counter(languages[key])
		language_count = sum(language_counts.values())
		rows.append((
			f"{output_unit(count)}B",
			key,
			", ".join(
				f"{f'{LANGUAGE_EMOJI[lang]} ' if lang in LANGUAGE_EMOJI else ''}{lang}: {acount / language_count:.2%}"
				for lang, acount in language_counts.most_common(5)
			),
		))

	output_markdown_table(rows, ("Bytes", "Repository", "Languages (top 5)"))

	print(f"\nTotal code: {output_unit(sum(repo_counts.values()))}B")

	print(
		"\nNote: The 'mozilla/releases-comm-central' repository is a GitHub mirror of comm-central, so the two tables above include all Thunderbird code"
	)

	print("\n### Top Open Issues and Pull Requests by Total Reactions\n")

	rows = []
	for i, item in enumerate(
		sorted((issue for issue in issues if not issue["closed_at"]), key=lambda x: x["reactions"]["total_count"], reverse=True), 1
	):
		url = urlparse(item["repository_url"])
		rows.append((
			f"{i:n}",
			f"{item['reactions']['total_count']:n}",
			url.path.split("/")[-1],
			item["type"]["name"] if item["type"] else ", ".join(label["name"] for label in item["labels"]),
			textwrap.shorten(item["title"], 80, placeholder="…"),
			item["html_url"],
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Reactions", "Repository", "Type/Labels", "Title", "URL"))

	print(f"\nSee full list: {GITHUB_BASE_URL}search?q=org%3Athunderbird+state%3Aopen+reactions%3A%3E10+sort%3Areactions")

	print(
		"\nWhen possible, users should prioritize adding kudos to Mozilla Connect ideas instead of adding thumbs up/+1 reactions on GitHub."
	)

	print("\n### Top Open Issues by Total Comments\n")

	rows = []
	for i, item in enumerate(sorted(issues_open, key=operator.itemgetter("comments"), reverse=True), 1):
		url = urlparse(item["repository_url"])
		rows.append((
			f"{i:n}",
			f"{item['comments']:n}",
			url.path.split("/")[-1],
			item["type"]["name"] if item["type"] else ", ".join(label["name"] for label in item["labels"]),
			textwrap.shorten(item["title"], 80, placeholder="…"),
			item["html_url"],
		))
		if i >= 20:
			break

	output_markdown_table(rows, ("#", "Comments", "Repository", "Type/Labels", "Title", "URL"))

	print(f"\nSee full list: {GITHUB_BASE_URL}search?q=org%3Athunderbird+state%3Aopen+comments%3A%3E10+sort%3Acomments")


if __name__ == "__main__":
	main()
