#!/usr/bin/env python3

# Copyright © Teal Dulcet

# Run: python3 stats.py

import atexit
import base64
import io
import json
import locale
import operator
import os
import platform
import sys
from collections import Counter
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

THUNDERBIRD_STATS_URL = "https://stats.thunderbird.net/"

FIREFOX_DATA_API = "https://data.firefox.com/datasets/"


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


def output_line_graph1(adir, series, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(14, 8))

	ax.margins(0.01)
	ax.grid()

	for name, (x, y) in series.items():
		ax.plot(x, y, marker=".", label=name)

	ax.set_ylim(bottom=0)
	ax.ticklabel_format(axis="y", style="plain", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


def output_line_graph2(adir, labels, series, title, xlabel, ylabel, legend):
	fig, ax = plt.subplots(figsize=(14, 8))

	ax.margins(0.01)
	ax.grid()

	for name, values in series.items():
		ax.plot(labels, values, marker=".", label=name)

	ax.set_ylim(bottom=0)
	ax.ticklabel_format(axis="y", style="plain", useLocale=True)
	ax.set_xlabel(xlabel)
	ax.set_ylabel(ylabel)
	ax.set_title(title)
	ax.legend(title=legend)

	fig.savefig(os.path.join(adir, f"{title.replace('/', '-')}.png"), dpi=300, bbox_inches="tight")

	print(f"\n![{title}]({fig_to_data_uri(fig)})\n")


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


def get_stats(file):
	try:
		r = session.get(f"{THUNDERBIRD_STATS_URL}{file}", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


def get_data(file):
	try:
		r = session.get(f"{FIREFOX_DATA_API}{file}", timeout=30)
		r.raise_for_status()
		data = r.json()
	except HTTPError as e:
		print(e, r.text, file=sys.stderr)
		sys.exit(1)
	except RequestException as e:
		print(e, file=sys.stderr)
		sys.exit(1)

	return data


OPERATING_SYSTEMS = {
	# Thunderbird
	"Windows_NT10.0": "Windows 10 / 11",
	"Windows_NT6.4": "Windows 10",
	"Windows_NT6.3": "Windows 8.1",
	"Windows_NT6.2": "Windows 8",
	"Windows_NT6.1": "Windows 7",
	"Windows_NT6.0": "Windows Vista",
	"Windows_NT5.2": "Windows XP x64",
	"Windows_NT5.1": "Windows XP",
	"Windows_NT5.0": "Windows 2000",
	"Windows_984.10": "Windows 98",
	"Windows_954.0": "Windows 95",
	"Darwin": "macOS",
	"Linux": "Linux",
	# Firefox: https://github.com/mozilla/ensemble-transposer/issues/208
	"Darwin-24.x": "macOS Sequoia",
	"Darwin-23.x": "macOS Sonoma",
	"Darwin-22.x": "macOS Ventura",
	"Darwin-21.x": "macOS Monterey",
	"Darwin-20.x": "macOS Big Sur",
	"Darwin-19.x": "macOS Catalina",
	"Darwin-18.x": "macOS Mojave",
	"Darwin-17.x": "macOS High Sierra",
	"Darwin-16.x": "macOS Sierra",
	"Darwin-15.x": "macOS El Capitan",
	"Darwin-14.x": "macOS Yosemite",
}


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
	end_date = datetime(year, month, 1, tzinfo=timezone.utc)

	adir = os.path.join(f"{end_date:%Y-%m}", "mozilla_connect")

	os.makedirs(adir, exist_ok=True)

	tb_users = get_stats("thunderbird_ami.json")
	atb_users = dict(sorted(tb_users.items()))

	tb_locales = get_stats("locales.json")
	atb_locales = dict(sorted(tb_locales.items()))

	tb_oss = get_stats("platforms.json")
	atb_oss = dict(sorted(tb_oss.items()))

	tb_addons = get_stats("addon_stats.json")
	atb_addons = dict(sorted(tb_addons.items()))

	ff_users = get_data("desktop/user-activity/Worldwide/MAU/index.json")
	aff_users = sorted((value["x"], value["y"]) for value in ff_users["data"]["populations"]["default"])

	ff_locales = get_data("desktop/usage-behavior/Worldwide/locale/index.json")

	ff_oss = get_data("desktop/hardware/default/osName/index.json")

	ff_addons = get_data("desktop/usage-behavior/Worldwide/pct_addon/index.json")
	aff_addons = sorted((value["x"], value["y"]) for value in ff_addons["data"]["populations"]["default"])

	file = os.path.join(f"{end_date:%Y-%m}", "languages.json")

	if not os.path.exists(file):
		languages = get_languages()

		with open(file, "w", encoding="utf-8") as f:
			json.dump(languages, f, ensure_ascii=False, indent="\t")
	else:
		with open(file, encoding="utf-8") as f:
			languages = json.load(f)

	print("## 📈 Thunderbird Stats (stats.thunderbird.net)\n")

	print(f"Data as of: {date:%Y-%m-%d %H:%M:%S%z}\n")

	tb_date, tb_users_item = next(reversed(atb_users.items()))
	ff_date, ff_users_item = max((value["x"], value["y"]) for value in ff_users["data"]["populations"]["default"])

	print("### Monthly Active Users/Installations by Week\n")
	output_line_graph2(
		adir,
		[datetime.fromisoformat(adate).astimezone(timezone.utc) for adate in atb_users],
		{"Thunderbird": [value["ami"] for value in atb_users.values()]},
		"Thunderbird Monthly Active Users by Week",
		"Date",
		"Users",
		None,
	)
	print(f"Thunderbird Monthly Active Users: {tb_users_item['ami']:n} as of: {tb_date}")

	output_line_graph1(
		adir,
		{"Firefox": tuple(zip(*((datetime.fromisoformat(key).astimezone(timezone.utc), value) for key, value in aff_users)))},
		"Firefox Monthly Active Users by Week",
		"Date",
		"Users",
		None,
	)
	print(
		f"Firefox Monthly Active Users: {ff_users_item:n} ({ff_users_item / tb_users_item['ami']:n}× Thunderbird users) as of: {ff_date}"
	)

	print(f"\nAlso see: {THUNDERBIRD_STATS_URL}#ami\n\nDescription from Firefox:\n> {ff_users['description'][0]}")

	tb_locale_counts = Counter()
	for value in atb_locales.values():
		tb_locale_counts.update(value["versions"])
	tb_date, tb_locales_item = next(reversed(atb_locales.items()))

	tb_stats = {alocale: [] for alocale, _ in tb_locale_counts.most_common(12)}

	for value in atb_locales.values():
		for alocale, avalue in tb_stats.items():
			avalue.append((value["versions"].get(alocale, 0) / value["count"]) * 100)

	print("\n### Top Locales by Week\n")
	output_line_graph2(
		adir,
		[datetime.fromisoformat(adate).astimezone(timezone.utc) for adate in atb_locales],
		{languages[key]["English"] if key in languages else key: value for key, value in tb_stats.items()},
		"Thunderbird Top Locales by Week",
		"Date",
		"Users %",
		"Locale",
	)

	ff_stats = {}
	for key, value in ff_locales["data"]["populations"].items():
		for item in value:
			ff_stats.setdefault(item["x"], {})[key] = item["y"]
	ff_date = max(ff_stats)
	ff_locales_item = ff_stats[ff_date]

	rows = [[""] * 6 for _ in range(min(15, max(len(tb_locales_item["versions"]), len(ff_locales_item))))]

	for row, (key, count) in zip(rows, Counter(tb_locales_item["versions"]).most_common(15)):
		row[:3] = (f"{count / tb_locales_item['count']:.4%}", key, languages[key]["English"] if key in languages else "")

	for row, (key, count) in zip(rows, sorted(ff_locales_item.items(), key=operator.itemgetter(1), reverse=True)):
		row[3:] = (f"{count:.4f}%", key, languages[key]["English"] if key in languages else "")

	output_markdown_table(rows, ("Thunderbird %", "Locale", "Name", "Firefox %", "Locale", "Name"))

	print(f"\nAlso see: {THUNDERBIRD_STATS_URL}#platlang\n\nDescription from Firefox:\n> {ff_locales['description'][0]}")

	print(f"\nData from: Thunderbird: {tb_date}, Firefox: {ff_date}")

	tb_os_counts = Counter()
	for value in atb_oss.values():
		tb_os_counts.update(value["versions"])
	tb_date, tb_oss_item = next(reversed(atb_oss.items()))

	tb_stats = {aos: [] for aos, _ in tb_os_counts.most_common(12)}

	for value in atb_oss.values():
		for aos, avalue in tb_stats.items():
			avalue.append((value["versions"].get(aos, 0) / value["count"]) * 100)

	print("\n### Top Operating Systems/Platforms by Week\n")
	output_line_graph2(
		adir,
		[datetime.fromisoformat(adate).astimezone(timezone.utc) for adate in atb_oss],
		{OPERATING_SYSTEMS.get(key, key): value for key, value in tb_stats.items()},
		"Thunderbird Top Operating Systems by Week",
		"Date",
		"Users %",
		"Operating System",
	)

	ff_stats = {}
	for key, value in ff_oss["data"]["populations"].items():
		for item in value:
			ff_stats.setdefault(item["x"], {})[key] = item["y"]
	ff_date = max(ff_stats)
	ff_os_item = ff_stats[ff_date]

	rows = [[""] * 5 for _ in range(max(len(tb_oss_item["versions"]), len(ff_os_item)))]

	for row, (key, count) in zip(rows, Counter(tb_oss_item["versions"]).most_common()):
		row[:3] = (f"{count / tb_oss_item['count']:%}", key, OPERATING_SYSTEMS.get(key, ""))

	for row, (key, count) in zip(rows, sorted(ff_os_item.items(), key=operator.itemgetter(1), reverse=True)):
		row[3:] = (f"{count:f}%", OPERATING_SYSTEMS.get(key, key))

	output_markdown_table(rows, ("Thunderbird %", "Platform", "Operating System", "Firefox %", "Operating System"))

	print(f"\nAlso see: {THUNDERBIRD_STATS_URL}#platlang\n\nDescription from Firefox:\n> {ff_oss['description']}")

	print(f"\nData from: Thunderbird: {tb_date}, Firefox: {ff_date}")

	labels = [datetime.fromisoformat(adate).astimezone(timezone.utc) for adate in atb_addons]
	stats = {"Thunderbird": [], "Thunderbird (w/o top 10 add-ons)": []}

	for value in atb_addons.values():
		stats["Thunderbird"].append((value["addon_count"] / value["total"]) * 100)
		stats["Thunderbird (w/o top 10 add-ons)"].append((value["minustop10_count"] / value["total"]) * 100)

	print("\n### Users Who Have an Add-on Installed by Week\n")
	output_line_graph1(
		adir,
		{
			**{key: (labels, value) for key, value in stats.items()},
			"Firefox": tuple(zip(*((datetime.fromisoformat(key).astimezone(timezone.utc), value) for key, value in aff_addons))),
		},
		"Users Who Have an Add-on Installed by Week",
		"Date",
		"Users %",
		None,
	)

	print(f"\nAlso see: {THUNDERBIRD_STATS_URL}#addons\n\nDescription from Firefox:\n> {ff_addons['description'][0]}")

	# https://whattrainisitnow.com/api/firefox/chemspills/
	# https://www.mozilla.org/security/known-vulnerabilities/thunderbird/
	adate = datetime(2025, 5, 20, tzinfo=timezone.utc)

	print(f"""
### ☢️ Last Chemspill (critical 0-day security vulnerability)

{adate:%Y-%m-%d} ({(date - adate).days:n} days ago): Thunderbird 138.0.2 and 128.10.2.

Also see: https://wiki.mozilla.org/Release_Management/Chemspill""")

	print("""
### ❓ Thunderbird related Areweyet pages

* Are We ESMified Yet?
	* Thunderbird: https://jfx2006.github.io/thunderbird-ci-docs/areweesmifiedyet/
	* Firefox: https://spidermonkey.dev/areweesmifiedyet/
* Are we OMEMO yet?: https://omemo.top/#Thunderbird%20(Chat%20Core)
* Are we fast yet?
	* Firefox: https://arewefastyet.com
* Are We Fluent Yet?
	* Firefox: https://www.arewefluentyet.com
* Are we Glean yet?
	* Firefox: https://arewegleanyet.com
* Are we Design Tokens yet?
	* Firefox: https://firefoxux.github.io/arewedesigntokensyet/
* What Train is it now? (Release Calendar)
	* Thunderbird: https://jfx2006.github.io/thunderbird-ci-docs/
	* Firefox: https://whattrainisitnow.com

Also see: https://wiki.mozilla.org/Areweyet""")


if __name__ == "__main__":
	main()
