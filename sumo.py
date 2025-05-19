#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 sumo.py

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
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import starmap
from zoneinfo import ZoneInfo

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

SUMO_BASE_URL = "https://support.mozilla.org/"
SUMO_API_URL = f"{SUMO_BASE_URL}api/2/"

PRODUCTS = ("thunderbird", "thunderbird-android")

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


def parse_isoformat(date):
	return datetime.fromisoformat(date[:-1] + "+00:00" if date.endswith("Z") else date)


def get_languages():
	try:
		r = session.get("https://product-details.mozilla.org/1.0/languages.json", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		return {}
	except RequestException as e:
		print(e, file=sys.stderr)
		return {}

	return data


def get_questions(product, start_date):
	questions = []
	page = 1

	while True:
		print(f"\tPage {page} ({len(questions):n})", file=sys.stderr)

		try:
			r = session.get(
				f"{SUMO_API_URL}question",
				params={"product": product, "created__gt": f"{start_date:%Y-%m-%d}", "ordering": "+created", "page": page},
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

		questions.extend(data["results"])

		if not data["next"]:
			break

		page += 1

		time.sleep(0.25)

	return questions


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
	start_date = datetime(year - 5, 1, 1, tzinfo=timezone.utc)

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

	adir = os.path.join(f"{end_date:%Y-%m}", "support")

	os.makedirs(adir, exist_ok=True)

	file = os.path.join(f"{end_date:%Y-%m}", "languages.json")

	if not os.path.exists(file):
		languages = get_languages()

		with open(file, "w", encoding="utf-8") as f:
			json.dump(languages, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			languages = json.load(f)

	file = os.path.join(f"{end_date:%Y-%m}", "SUMO_questions.json")

	if not os.path.exists(file):
		questions = []

		starttime = time.perf_counter()

		for product in PRODUCTS:
			print(f"Processing product: {product}\n", file=sys.stderr)

			data = get_questions(product, start_date)
			questions.extend(data)

		endtime = time.perf_counter()
		print(f"Downloaded questions in {endtime - starttime:n} seconds.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(questions, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			questions = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	print("## 🆘 Mozilla Support Forum/SUMO (support.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	created = {}

	# https://github.com/rtanglao/rt-kits-api3/issues/1
	# https://github.com/thunderbird/github-action-thunderbird-aaq/blob/main/fix-kludged-time.rb
	LOS_ANGELES = ZoneInfo("America/Los_Angeles")

	for question in questions:
		date = parse_isoformat(question["created"]).replace(tzinfo=LOS_ANGELES).astimezone(timezone.utc)
		created.setdefault((date.year, date.month), []).append(question)

	labels = list(reversed(dates))
	created_status = {key: [] for key in ("Question", "Answered", "Solved")}
	created_product = {key: [] for key in PRODUCTS}

	with open(os.path.join(adir, "SUMO_questions.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", "Questions", "Answered", "Solved", *PRODUCTS))

		writer.writeheader()

		rows = []
		for date in reversed(dates):
			acreated = created[date.year, date.month]
			product_counts = Counter(question["product"] for question in acreated)
			questions_count = len(acreated)
			answered_count = sum(1 for question in acreated if question["num_answers"])  # len(question["involved"]) > 1
			solved_count = sum(1 for question in acreated if question["is_solved"])

			writer.writerow({
				"Date": f"{date:%B %Y}",
				"Questions": questions_count,
				"Answered": answered_count,
				"Solved": solved_count,
				**product_counts,
			})

			rows.append((
				f"{date:%B %Y}",
				f"{questions_count:n}",
				f"{answered_count:n} ({answered_count / questions_count:.4%})",
				f"{solved_count:n} ({solved_count / questions_count:.4%})",
				", ".join(f"{key}: {count:n}" for key, count in product_counts.most_common()),
			))

			created_status["Solved"].append(solved_count)
			created_status["Answered"].append(answered_count - solved_count)
			created_status["Question"].append(questions_count - answered_count)

			for key in PRODUCTS:
				created_product[key].append(product_counts[key])

	print('### Total Questions Created by Month\n\n(The lifecycle goes "Question" ⟶ "Answered" ⟶ "Solved".)\n')
	output_stacked_bar_graph(
		adir, labels, created_status, "SUMO Questions Created by Status and Month", "Date", "Total Created", "Status"
	)
	output_stacked_bar_graph(
		adir, labels, created_product, "SUMO Questions Created by Product and Month", "Date", "Total Created", "Product"
	)
	output_markdown_table(rows, ("Month", "Questions", "Answered", "Solved", "Products"), True)

	items = created[end_date.year, end_date.month]

	tag_counts = Counter((tag["slug"], tag["name"]) for item in items for tag in item["tags"])

	print(f"\n### Top Question Tags ({end_date:%B %Y})\n")

	output_markdown_table(
		[(f"{count:n}", f"{name} ({slug})" if name != slug else name) for (slug, name), count in tag_counts.most_common(15)],
		("Count", "Tag"),
	)

	locale_counts = Counter(item["locale"] for item in items)

	print(f"\n### Question Locales ({end_date:%B %Y})\n")

	output_markdown_table(
		[(f"{count:n}", key, languages[key]["English"] if key in languages else "") for key, count in locale_counts.most_common()],
		("Count", "Locale", "Name"),
	)

	solution_counts = Counter(
		(item["solved_by"]["username"], item["solved_by"]["display_name"]) for item in items if item["is_solved"]
	)

	print(f"\n### Top Question Solvers ({end_date:%B %Y})\n")

	output_markdown_table(
		[
			(f"{count:n}", f"{display_name!r} ({username})" if display_name and display_name != username else username)
			for (username, display_name), count in solution_counts.most_common(10)
		],
		("Solved", "User"),
	)

	solution_counts = Counter(
		(item["solved_by"]["username"], item["solved_by"]["display_name"]) for item in questions if item["is_solved"]
	)

	print(f"\n### Top Question Solvers (since {start_date:%B %Y})\n")

	output_markdown_table(
		[
			(f"{count:n}", f"{display_name!r} ({username})" if display_name and display_name != username else username)
			for (username, display_name), count in solution_counts.most_common(10)
		],
		("Solved", "User"),
	)

	print(f"\n### Top Questions by Total Votes ({end_date:%B %Y})\n")

	rows = []
	for i, item in enumerate(sorted(items, key=operator.itemgetter("num_votes"), reverse=True), 1):
		rows.append((f"{i:n}", f"{item['num_votes']:n}", item["product"], item["title"], f"{SUMO_BASE_URL}questions/{item['id']}"))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Votes", "Product", "Title", "URL"))

	print(f"\n### Top Questions by Total Answers ({end_date:%B %Y})\n")

	rows = []
	for i, item in enumerate(sorted(items, key=operator.itemgetter("num_answers"), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{item['num_answers']:n}",
			item["product"],
			item["title"],
			f"{SUMO_BASE_URL}questions/{item['id']}",
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Answers", "Product", "Title", "URL"))


if __name__ == "__main__":
	main()
