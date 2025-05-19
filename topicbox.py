#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 topicbox.py

import atexit
import base64
import csv
import io
import locale
import os
import platform
import re
import sys
import textwrap
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

TOPICBOX_BASE_URL = "https://thunderbird.topicbox.com/"
TOPICBOX_API_URL = f"{TOPICBOX_BASE_URL}jmap"
ACCOUNT_ID = "d9235ee6-1811-11e8-a2b4-c45ae5388869"

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


def output_isoformat(date):
	output = date.isoformat()
	return output[:-6] + "Z" if output.endswith("+00:00") else output


def jmap(method_calls):
	try:
		r = session.post(
			TOPICBOX_API_URL,
			json={"using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"], "methodCalls": method_calls},
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

	return data["methodResponses"]


def main():
	end_date = datetime.now(timezone.utc)
	year = end_date.year
	month = end_date.month - 1
	if month < 1:
		year -= 1
		month += 12
	start_date = max(datetime(year - 10, 1, 1, tzinfo=timezone.utc), datetime(2018, 8, 1, tzinfo=timezone.utc))

	dates = []
	current_start = start_date
	while current_start < end_date:
		year = current_start.year
		month = current_start.month + 1
		if month > 12:
			year += 1
			month -= 12
		next_start = current_start.replace(year=year, month=month)

		dates.append((current_start, next_start))
		current_start = next_start

	dates.pop()
	end_date, _ = dates[-1]

	adir = os.path.join(f"{end_date:%Y-%m}", "support")

	os.makedirs(adir, exist_ok=True)

	print("## 📧 Topicbox Mailing Lists (thunderbird.topicbox.com)\n")

	print(f"Data as of: {end_date:%Y-%m-%d %H:%M:%S%z}\n")

	data = jmap([["Group/get", {"accountId": ACCOUNT_ID, "ids": None}, "grp"]])

	adata = data[0][1]["list"]
	mailbox_ids = [g["archiveMailboxId"] for g in adata]
	mailboxs = {g["archiveMailboxId"]: g for g in adata}

	print("### Mailing Lists Overview\n")
	output_markdown_table(
		[
			(
				f"{parse_isoformat(g['created']):%Y-%m-%d}",
				g["name"],
				textwrap.shorten(g["description"], 80, placeholder="…"),
				f"{TOPICBOX_BASE_URL}groups/{g['identifier']}",
			)
			for g in mailboxs.values()
		],
		("Created", "Name", "Description", "URL"),
	)

	method_calls = []
	for i, mb_id in enumerate(mailbox_ids):
		date = parse_isoformat(mailboxs[mb_id]["created"])
		for j, (start, end) in enumerate(dates):
			if end > date:
				method_calls.append([
					"Email/query",
					{
						"accountId": ACCOUNT_ID,
						"filter": {"inMailbox": mb_id, "after": output_isoformat(start), "before": output_isoformat(end)},
						"collapseThreads": True,
						"limit": 0,
					},
					f"g{i:02d}m{j:02d}",
				])

	threads = {(date.year, date.month): Counter() for date, _ in dates}

	data = jmap(method_calls)

	for _name, result, call_id in data:
		if result["total"]:
			mb_id = mailbox_ids[int(call_id[1:3])]
			date, _ = dates[int(call_id[4:6])]
			threads[date.year, date.month][mb_id] = result["total"]

	labels = [date for date, _ in reversed(dates)]
	created_mailbox = {g["name"]: [] for g in mailboxs.values()}

	with open(os.path.join(adir, "Topicbox.csv"), "w", newline="", encoding="utf-8") as csvfile:
		writer = csv.DictWriter(csvfile, ("Date", "Total Threads", *(g["name"] for g in mailboxs.values())))

		writer.writeheader()

		rows = []
		for date, _ in reversed(dates):
			thread_counts = threads[date.year, date.month]
			count = sum(thread_counts.values())

			writer.writerow({
				"Date": f"{date:%B %Y}",
				"Total Threads": count,
				**{mailboxs[key]["name"]: value for key, value in thread_counts.items()},
			})

			rows.append((
				f"{date:%B %Y}",
				f"{count:n}",
				", ".join(f"{mailboxs[key]['name']}: {value:n}" for key, value in thread_counts.most_common(5)),
			))

			for g in mailboxs.values():
				created_mailbox[g["name"]].append(thread_counts[g["archiveMailboxId"]])

	print("\n### Total Email Threads by Month\n")
	output_stacked_bar_graph(
		adir, labels, created_mailbox, "Topicbox Email Threads by Month", "Date", "Total Created", "Mailing List"
	)
	output_markdown_table(rows, ("Month", "Threads", "Mailing Lists (top 5)"), True)


if __name__ == "__main__":
	main()
