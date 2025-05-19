#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 discourse.py

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

DISCOURSE_BASE_URL = "https://discourse.mozilla.org/"

SLUG = "thunderbird"

LIMIT = 100

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


def get_categories():
	try:
		r = session.get(f"{DISCOURSE_BASE_URL}categories.json", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data["category_list"]["categories"]


def get_category(aid):
	try:
		r = session.get(f"{DISCOURSE_BASE_URL}c/{aid}/show.json", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data["category"]


def get_topics(slug, aid):
	users = {}
	topics = []
	page = 0

	while True:
		print(f"\tPage {page} ({len(topics):n})", file=sys.stderr)

		try:
			r = session.get(f"{DISCOURSE_BASE_URL}c/{slug}/{aid}.json", params={"per_page": LIMIT, "page": page}, timeout=30)
			r.raise_for_status()
			data = r.json()
		except HTTPError as e:
			print(e, r.text, file=sys.stderr)
			sys.exit(1)
		except RequestException as e:
			print(e, file=sys.stderr)
			sys.exit(1)

		users.update((user["id"], user) for user in data["users"])
		topics.extend(data["topic_list"]["topics"])

		if "more_topics_url" not in data["topic_list"]:
			break

		page += 1

	return {"users": users, "topics": topics}


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
	start_date = max(datetime(year - 10, 1, 1, tzinfo=timezone.utc), datetime(2017, 10, 1, tzinfo=timezone.utc))

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

	categories = get_categories()

	category_ids = []
	for category in categories:
		if category["slug"] == SLUG:
			# print(f"{category['name']!r}", file=sys.stderr)

			category_ids.append(category["id"])
			category_ids.extend(category["subcategory_ids"])

			break
	else:
		print(f"Error: Could not find {SLUG!r}", file=sys.stderr)
		sys.exit(1)

	file = os.path.join(f"{end_date:%Y-%m}", "Discourse_topics.json")

	if not os.path.exists(file):
		starttime = time.perf_counter()

		data = get_topics(SLUG, category_ids[0])

		endtime = time.perf_counter()
		print(f"Downloaded topics in {endtime - starttime:n} seconds.", file=sys.stderr)

		with open(file, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			data = json.load(f)

	date = datetime.fromtimestamp(os.path.getmtime(file), timezone.utc)

	print("## 💬 Mozilla Discourse (discourse.mozilla.org)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	users = {int(key): value for key, value in data["users"].items()}
	topics = data["topics"]

	categories = {}
	for aid in category_ids:
		category = get_category(aid)

		categories[aid] = category

	print("### Categories Overview\n")

	output_markdown_table(
		[
			(
				f"{category['topic_count']:n} / {category['post_count']:n}",
				category["name"],
				textwrap.shorten(category["description_text"], 80, placeholder="…"),
				f"{DISCOURSE_BASE_URL}c/{category['slug']}/{category['id']}",
			)
			for category in categories.values()
		],
		("Topics / Posts", "Category", "Description", "URL"),
	)

	created = {}

	for topic in topics:
		date = parse_isoformat(topic["created_at"])
		created.setdefault((date.year, date.month), []).append(topic)

	labels = list(reversed(dates))
	created_status = {key: [] for key in ("Topic", "Answered", "Solved")}
	created_category = {category["name"]: [] for category in categories.values()}

	with open(os.path.join(adir, "Discourse_topics.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(
			csvfile, ("Date", "Topics", "Answered", "Solved", *(category["name"] for category in categories.values()))
		)

		writer.writeheader()

		rows = []
		for date in reversed(dates):
			acreated = created.get((date.year, date.month), [])
			category_counts = Counter(topic["category_id"] for topic in acreated)
			topics_count = len(acreated)
			answered_count = sum(1 for topic in acreated if topic["posts_count"] > 1)  # len(topic["posters"]) > 1
			solved_count = sum(1 for topic in acreated if topic["has_accepted_answer"])
			# posts_count = sum(topic["posts_count"] for topic in acreated)

			writer.writerow({
				"Date": f"{date:%B %Y}",
				"Topics": topics_count,
				"Answered": answered_count,
				"Solved": solved_count,
				**{categories[key]["name"]: count for key, count in category_counts.items()},
			})

			rows.append((
				f"{date:%B %Y}",
				f"{topics_count:n}",
				f"{answered_count:n} ({answered_count / topics_count:.4%})" if topics_count else "",
				f"{solved_count:n} ({solved_count / topics_count:.4%})" if topics_count else "",
				", ".join(f"{categories[key]['name']}: {count:n}" for key, count in category_counts.most_common()),
			))

			created_status["Solved"].append(solved_count)
			created_status["Answered"].append(answered_count - solved_count)
			created_status["Topic"].append(topics_count - answered_count)

			for category in categories.values():
				created_category[category["name"]].append(category_counts[category["id"]])

	print('\n### Total Topics Created by Month\n\n(The lifecycle goes "Topic" ⟶ "Answered" ⟶ "Solved".)\n')
	output_stacked_bar_graph(
		adir, labels, created_status, "Mozilla Discourse Topics Created by Status and Month", "Date", "Total Created", "Status"
	)
	output_stacked_bar_graph(
		adir,
		labels,
		created_category,
		"Mozilla Discourse Topics Created by Category and Month",
		"Date",
		"Total Created",
		"Category",
	)
	output_markdown_table(rows, ("Month", "Topics", "Answered", "Solved", "Categories"), True)

	items = created.get((end_date.year, end_date.month))

	tag_counts = Counter(tag for item in topics for tag in item["tags"])

	print("\n### Top Topic Tags (all time)\n")

	output_markdown_table([(f"{count:n}", key) for key, count in tag_counts.most_common(10)], ("Count", "Tag"))

	if items:
		answer_counts = Counter(user["user_id"] for item in items for user in item["posters"])

		print(f"\n### Top Topic Posters ({end_date:%B %Y})\n")

		output_markdown_table(
			[
				(
					f"{count:n}",
					f"{user['name']!r} ({user['username']})"
					if user["name"] and user["name"] != user["username"]
					else user["username"],
				)
				for user, count in ((users[key], count) for key, count in answer_counts.most_common(10))
			],
			("Posts", "User"),
		)

	answer_counts = Counter(user["user_id"] for item in topics for user in item["posters"])

	print("\n### Top Topic Posters (all time)\n")

	output_markdown_table(
		[
			(
				f"{count:n}",
				f"{user['name']!r} ({user['username']})" if user["name"] and user["name"] != user["username"] else user["username"],
			)
			for user, count in ((users[key], count) for key, count in answer_counts.most_common(10))
		],
		("Posts", "User"),
	)

	print("\n### Top Topics by Total Likes (all time)\n")

	rows = []
	for i, item in enumerate(sorted(topics, key=operator.itemgetter("like_count"), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{item['like_count']:n}",
			categories[item["category_id"]]["name"],
			item["title"],
			f"{DISCOURSE_BASE_URL}t/{item['slug']}/{item['id']}",
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Likes", "Category", "Title", "URL"))

	print("\n### Top Topics by Total Posts (all time)\n")

	rows = []
	for i, item in enumerate(sorted(topics, key=operator.itemgetter("posts_count"), reverse=True), 1):
		rows.append((
			f"{i:n}",
			f"{item['posts_count']:n}",
			categories[item["category_id"]]["name"],
			item["title"],
			f"{DISCOURSE_BASE_URL}t/{item['slug']}/{item['id']}",
		))
		if i >= 10:
			break

	output_markdown_table(rows, ("#", "Posts", "Category", "Title", "URL"))


if __name__ == "__main__":
	main()
