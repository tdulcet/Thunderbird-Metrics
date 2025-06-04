#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 pontoon.py

import atexit
import base64
import csv
import io
import locale
import operator
import os
import platform
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

PONTOON_BASE_URL = "https://pontoon.mozilla.org/"
PONTOON_API_URL = f"{PONTOON_BASE_URL}graphql"

FF_PROJECTS = ("firefox", "firefox-for-android", "firefox-for-ios")
PROJECTS = ("thunderbird", "thunderbirdnet")


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


def output_stacked_bar_graph(adir, labels, stacks, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(16, 6))

	ax.margins(0.01)
	ax.grid()

	cum = [0] * len(labels)

	for name, values in stacks.items():
		ax.bar(labels, values, bottom=cum, label=name)
		for i in range(len(cum)):
			cum[i] += values[i]

	ax.ticklabel_format(axis="y", useLocale=True)
	ax.tick_params("x", rotation=90)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def get_locales():
	try:
		r = session.get(PONTOON_API_URL, params={"query": "{locales{code,name,population}}"}, timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data["data"]["locales"]


def get_ff_project(slug):
	try:
		r = session.get(
			PONTOON_API_URL, params={"query": '{project(slug:"' + slug + '"){name,localizations{locale{code,name}}}}'}, timeout=30
		)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data["data"]["project"]


def get_project(slug):
	try:
		r = session.get(
			PONTOON_API_URL,
			params={
				"query": '{project(slug:"'
				+ slug
				+ '"){name,localizations{locale{code,name}totalStrings,missingStrings,complete,approvedStrings,unreviewedStrings}missingStrings,totalStrings,approvedStrings,unreviewedStrings}}'
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

	return data["data"]["project"]


def main():
	if len(sys.argv) != 1:
		print(f"Usage: {sys.argv[0]}", file=sys.stderr)
		sys.exit(1)

	date = datetime.now(timezone.utc)
	year = date.year
	month = date.month - 1
	if month < 1:
		year -= 1
		month += 12
	start_date = datetime(year, month, 1, tzinfo=timezone.utc)

	adir = os.path.join(f"{start_date:%Y-%m}", "localization")

	os.makedirs(adir, exist_ok=True)

	print("## 🔠 Pontoon Localization (pontoon.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	locales = get_locales()
	languages = {alocale["code"].split("-", 1)[0] for alocale in locales}

	print(f"### Total languages / locales: {len(languages):n} / {len(locales):n}\n")

	ff_locales = set()

	for slug in FF_PROJECTS:
		data = get_ff_project(slug)

		print(f"* {data['name']} localizations: {len(data['localizations']):n}")

		ff_locales.update(alocale["locale"]["code"] for alocale in data["localizations"])

	print(f"\n**Total Firefox localizations**: {len(ff_locales):n}\n")

	for slug in PROJECTS:
		data = get_project(slug)
		alocales = {alocale["locale"]["code"] for alocale in data["localizations"]}

		print(f"### {data['name']} ({slug})\n\n{PONTOON_BASE_URL}projects/{slug}/\n")

		localizations_count = len(data["localizations"])
		complete = sorted(
			(alocale["locale"] for alocale in data["localizations"] if alocale["complete"]), key=operator.itemgetter("name")
		)
		complete_count = len(complete)

		print(f"#### Localizations: {localizations_count:n}\n")
		print(
			f"#### Localizations Complete: {complete_count:n} / {localizations_count:n} ({complete_count / localizations_count:.4%})\n"
		)
		print("\n".join(f"* {alocale['name']!r} ({alocale['code']})" for alocale in complete))

		labels = []
		localizations = {key: [] for key in ("Approved", "Unreviewed")}

		with open(os.path.join(adir, f"Pontoon_{slug}.csv"), "w", newline="", encoding="utf-8") as csvfile:
			writer = csv.writer(csvfile)

			writer.writerow(("name", "code", "approved", "unreviewed", "total"))

			for item in sorted(data["localizations"], key=operator.itemgetter("approvedStrings"), reverse=True):
				writer.writerow((
					item["locale"]["name"],
					item["locale"]["code"],
					item["approvedStrings"],
					item["unreviewedStrings"],
					item["totalStrings"],
				))

				labels.append(item["locale"]["name"])

				localizations["Approved"].append(item["approvedStrings"])
				localizations["Unreviewed"].append(item["unreviewedStrings"])

		output_stacked_bar_graph(
			adir,
			labels,
			localizations,
			f"Pontoon {data['name']} Localizations by Translated",
			"Localization",
			"Total Strings",
			"Strings",
		)

		print("\n#### Other Top Localizations by percentage Translated\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(alocale for alocale in data["localizations"] if not alocale["complete"]),
				key=operator.itemgetter("approvedStrings"),
				reverse=True,
			),
			1,
		):
			rows.append((
				f"{item['approvedStrings'] / item['totalStrings']:.4%} ({item['approvedStrings']:n} / {item['totalStrings']:n})",
				f"{item['locale']['name']!r} ({item['locale']['code']})",
			))
			if i >= 10:
				break

		output_markdown_table(rows, ("Approved %", "Locale"))

		print(
			f"\n**Total Translated Strings**: {data['approvedStrings']:n} / {data['totalStrings']:n} ({data['approvedStrings'] / data['totalStrings']:.4%})\n"
		)

		print("#### Localizations with the most Unreviewed Strings\n")

		rows = []
		for i, item in enumerate(sorted(data["localizations"], key=operator.itemgetter("unreviewedStrings"), reverse=True), 1):
			rows.append((f"{item['unreviewedStrings']:n}", f"{item['locale']['name']!r} ({item['locale']['code']})"))
			if i >= 5:
				break

		output_markdown_table(rows, ("Unreviewed", "Locale"))

		print(
			f"\n**Total Unreviewed Strings**: {data['unreviewedStrings']:n} / {data['totalStrings']:n} ({data['unreviewedStrings'] / data['totalStrings']:.4%})\n"
		)

		print("#### Top Missing Locales by Population (number of native speakers)\n")

		rows = []
		for i, item in enumerate(
			sorted(
				(
					alocale
					for alocale in locales
					# Japanese (ja) is supported, but does not use Pontoon
					if alocale["code"] in ff_locales and alocale["code"] not in alocales and alocale["code"] != "ja"
				),
				key=operator.itemgetter("population"),
				reverse=True,
			),
			1,
		):
			rows.append((f"{i:n}", f"{item['population']:n}", f"{item['name']!r} ({item['code']})"))
			if i >= 10:
				break

		output_markdown_table(rows, ("#", "Population", "Locale"))

		diff = ff_locales - alocales

		print(
			f"\n**Total Missing localizations**: {len(diff):n}\n\n(Missing meaning it is supported by Firefox, but not yet by Thunderbird.)\n"
		)


if __name__ == "__main__":
	main()
