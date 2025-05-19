#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 code_coverage.py

import atexit
import base64
import csv
import io
import locale
import os
import platform
import statistics
import sys
from datetime import datetime, timezone
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

CODE_COVERAGE_BASE_URL = "https://coverage.thunderbird.net/"
CODE_COVERAGE_API_URL = f"{CODE_COVERAGE_BASE_URL}v2/"


def output_markdown_table(rows, header):
	rows.insert(0, header)
	# rows = [[MARKDOWN_ESCAPE.sub(r"\\\1", col) for col in row] for row in rows]
	lens = [max(*map(len, col), 2) for col in zip(*rows)]
	rows.insert(1, ["-" * alen for alen in lens])
	aformat = " | ".join(f"{{:<{alen}}}" for alen in lens)

	print("\n".join(starmap(aformat.format, rows)))


def fig_to_data_uri(fig):
	with io.BytesIO() as buf:
		fig.savefig(buf, format="svg", bbox_inches="tight")
		plt.close(fig)

		# "data:image/svg+xml," + quote(buf.getvalue())
		return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def output_line_graph(adir, labels, series, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(10, 6))

	ax.margins(0.01)
	ax.set_ylim(top=100)
	ax.grid()

	for name, values in series.items():
		ax.plot(labels, values, marker="o", label=name)
		# for l, v in zip(labels, values):
		# 	ax.annotate(v, (l, v))

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def get_path(path=None):
	try:
		r = session.get(f"{CODE_COVERAGE_API_URL}path", params={"path": path}, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


def get_history(start, path=None):
	try:
		r = session.get(
			f"{CODE_COVERAGE_API_URL}history",
			# https://github.com/mozilla/code-coverage/issues/852
			params={"path": path},  # "start": f"{int(start.timestamp())}"
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

	return data


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	end_date = datetime.now(timezone.utc)
	# start_date = datetime(end_date.year - 5, 1, 1, tzinfo=timezone.utc)
	start_date = datetime(end_date.year - 1, end_date.month, 1, tzinfo=timezone.utc)
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

	# dates.pop()
	end_date = dates[-2]

	adir = os.path.join(f"{end_date:%Y-%m}", "bugzilla")

	os.makedirs(adir, exist_ok=True)

	data = get_path()

	paths = {data["path"]: data["name"]}
	paths.update((child["path"], child["name"]) for child in data["children"])

	histories = {path: {} for path in paths}

	for path, counts in histories.items():
		print(f"Processing path: {paths[path]} ({path!r})\n", file=sys.stderr)

		history = get_history(start_date, path)
		for item in history:
			if item["coverage"]:
				date = datetime.fromtimestamp(item["date"])
				counts.setdefault((date.year, date.month), []).append(item["coverage"])

		print(f"\tGot {sum(map(len, counts.values())):n} data points\n", file=sys.stderr)

	print("## 📈 Thunderbird Code Coverage (coverage.thunderbird.net)\n")

	print(f"Data as of: {end_date:%Y-%m-%d %H:%M:%S%z}\n")

	labels = list(reversed(dates))
	coverages = {path or "Root": [] for path in paths}

	with open(os.path.join(adir, "Code Coverage.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", *paths))

		writer.writeheader()

		rows = []
		for date in reversed(dates):
			adate = (date.year, date.month)
			acoverages = {
				path: statistics.median_high(counts[adate]) if adate in counts else None for path, counts in histories.items()
			}
			coverage = acoverages[data["path"]]

			writer.writerow({
				"Date": f"{date:%B %Y}",
				**{path: acoverage if acoverage is not None else "" for path, acoverage in acoverages.items()},
			})

			rows.append((
				f"{date:%B %Y}",
				f"{coverage:n}%" if coverage is not None else "-",
				", ".join(
					f"{paths[path]}: {f'{acoverage:n}%' if acoverage is not None else '-'}"
					for path, acoverage in acoverages.items()
					if path != data["path"]
				),
			))

			for path, acoverage in acoverages.items():
				coverages[path or "Root"].append(acoverage if acoverage is not None else 0)

	print("### Code Coverage by Month (past year)\n")
	output_line_graph(adir, labels, coverages, "Thunderbird Code Coverage by Month", "Date", "Coverage %", "Path")
	output_markdown_table(rows, ("Month", "Coverage %", "Path Coverage %"))

	print(f"\nPlease see {CODE_COVERAGE_BASE_URL} for more information.")


if __name__ == "__main__":
	main()
