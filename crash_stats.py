#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 crash_stats.py

import atexit
import base64
import csv
import io
import locale
import os
import platform
import re
import sys
from collections import Counter, namedtuple
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

CRASH_STATS_BASE_URL = "https://crash-stats.mozilla.org/"
CRASH_STATS_API_URL = f"{CRASH_STATS_BASE_URL}api/"

PRODUCTS = ("Thunderbird", "Firefox")
PRODUCT = "Thunderbird"

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

	widths = [timedelta(6)] + [(labels[i] - labels[i + 1]) * 0.9 for i in range(len(labels) - 1)]
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


def parse_isoformat(date):
	return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)


VERSION_PATTERN = re.compile(r"^([0-9]+)(?:\.([0-9]+)(?:\.([0-9]+)(?:\.([0-9]+))?)?)?(?:([ab])([0-9]+)?)?(?:(pre)([0-9])?)?")

Version = namedtuple("Version", ("major", "minor", "micro", "patch", "alpha_beta", "alpha_beta_ver", "pre", "pre_ver"))


def parse_version(version):
	version_res = VERSION_PATTERN.match(version)
	if not version_res:
		print(f"Error parsing version {version!r}", file=sys.stderr)
		return None

	major, minor, micro, patch, alpha_beta, alpha_beta_ver, pre, pre_ver = version_res.groups()
	return Version(
		int(major),
		int(minor) if minor else 0,
		int(micro) if micro else 0,
		int(patch) if patch else 0,
		alpha_beta,
		int(alpha_beta_ver) if alpha_beta_ver else 0,
		pre,
		int(pre_ver) if pre_ver else 0,
	)


def output_verion(version):
	aversion = parse_version(version)
	if not aversion:
		return version

	release = None
	if aversion.alpha_beta:
		if aversion.alpha_beta == "a":
			release = "Daily"
		elif aversion.alpha_beta == "b":
			release = "Beta"
	elif version.endswith("esr"):
		release = "ESR"

	return f"{aversion.major}{f' {release}' if release else ''}"


def get_histogram(start_date, end_date):
	try:
		r = session.get(
			f"{CRASH_STATS_API_URL}SuperSearch/",
			params={
				# "product": PRODUCT,
				"date": (f">={start_date:%Y-%m-%d}", f"<{end_date:%Y-%m-%d}"),
				"_results_number": 0,
				"_histogram.date": "product",
				"_histogram_interval.date": "1w",
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

	return data["facets"]["histogram_date"]


def get_aggregation(start_date, end_date):
	try:
		r = session.get(
			f"{CRASH_STATS_API_URL}SuperSearch/",
			params={
				"product": PRODUCT,
				"date": (f">={start_date:%Y-%m-%d}", f"<{end_date:%Y-%m-%d}"),
				"_results_number": 0,
				"_aggs.signature": "version",
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

	return data["facets"]["signature"]


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	date = datetime.now(timezone.utc)
	year = date.year
	month = date.month - 6
	if month < 1:
		year -= 1
		month += 12
	start_date = datetime(year, month, 1, tzinfo=timezone.utc)

	year = date.year
	month = date.month - 1
	if month < 1:
		year -= 1
		month += 12
	end_date = datetime(year, month, 1, tzinfo=timezone.utc)

	adir = os.path.join(f"{end_date:%Y-%m}", "bugzilla")

	os.makedirs(adir, exist_ok=True)

	data = get_histogram(start_date, date)

	print("## 💥 Crash Stats (crash-stats.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	labels = []
	stats = {product: [] for product in (PRODUCT,)}

	with open(os.path.join(adir, "Crash Stats.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", *PRODUCTS))

		writer.writeheader()

		rows = []
		for item in reversed(data):
			adate = parse_isoformat(item["term"])
			astats = {product["term"]: product for product in item["facets"]["product"]}

			writer.writerow({"Date": f"{adate:%Y-%m-%d}", **{product: astats[product]["count"] for product in PRODUCTS}})

			rows.append((f"{adate:%Y-%m-%d}", f"{astats[PRODUCT]['count']:n}", f"{astats['Firefox']['count']:n}"))

			labels.append(adate)
			stats[PRODUCT].append(astats[PRODUCT]["count"])

	print("### Thunderbird Crashes by Week (past six months)\n")
	output_stacked_bar_graph(adir, labels, stats, "Thunderbird Crashes by Week", "Date", "Crashes", None)
	output_markdown_table(rows, ("Week", "Thunderbird Crashes", "Firefox Crashes"), True)

	print(f"\nPlease see {CRASH_STATS_BASE_URL}search/?product=Thunderbird for more information.")

	items = get_aggregation(end_date, date)

	print(f"\n### Top Thunderbird Crash Signatures ({end_date:%B %Y})\n")

	rows = []
	for i, item in enumerate(items, 1):
		counts = Counter()
		for version in item["facets"]["version"]:
			counts.update({output_verion(version["term"]): version["count"]})

		rows.append((
			f"{i:n}",
			f"{item['count']:n}",
			item["term"],
			", ".join(f"{key}: {count:n}" for key, count in counts.most_common(5)),
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Crashes", "Signature", "Thunderbird Versions (top 5)"))


if __name__ == "__main__":
	main()
