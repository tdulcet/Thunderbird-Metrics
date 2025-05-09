#!/bin/bash

# Copyright © Teal Dulcet

# Run: bash generate.sh

set -e

if [[ $# -ne 0 ]]; then
	echo "Usage: $0" >&2
	exit 1
fi

REPOSITORY='https://github.com/tdulcet/Thunderbird-Metrics'

date=$(date -d "$(date +%Y-%m-15) -1 month" +%s)
printf -v date1 '%(%Y-%m)T' "$date"
printf -v date2 '%(%B %Y)T' "$date"

mkdir -p "$date1"/{bugzilla,github,mozilla_connect,addons,support,localization}

# {
# 	echo -e '---\n'
# 	for script in bugzilla.py github.py mozilla_connect.py stats.py crash_stats.py code_coverage.py addons.py sumo.py discourse.py pontoon.py weblate.py topicbox.py; do
# 		echo "$script" >&2
# 		python3 -X dev "$script"
# 		echo -e '\n---\n'
# 	done
# } >"$date1/email.md"
# exit

echo -e "Bugzilla/BMO, Crash Stats and Thunderbird Code Coverage\n"

cat <<EOF >"$date1/bugzilla/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): Bugzilla, Crash Stats and Code Coverage

Hello Thunderbird Community,

Welcome to the Thunderbird Community Metrics, which are designed to complement Magnus’s existing “Thunderbird Metrics” e-mail, while providing data from additional sources. There are a total of six e-mails, covering 12 sources:

1. Bugzilla/BMO, Crash Stats and Thunderbird Code Coverage
2. GitHub
3. Thunderbird Stats and Mozilla Connect
4. Thunderbird Add-ons/ATN
5. Support (Mozilla Support/SUMO, Mozilla Discourse and Topicbox)
6. Localization (Pontoon and Weblate)

This is e-mail 1 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO bugzilla.py)


$(time python3 -OO crash_stats.py)


$(time python3 -OO code_coverage.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF

echo -e "\nGitHub\n"

cat <<EOF >"$date1/github/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): GitHub

Hello Thunderbird Community,

This is e-mail 2 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO github.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF

echo -e "\nThunderbird Stats and Mozilla Connect\n"

cat <<EOF >"$date1/mozilla_connect/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): Stats and Mozilla Connect

Hello Thunderbird Community,

This is e-mail 3 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO stats.py)

$(time python3 -OO mozilla_connect.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF

echo -e "\nThunderbird Add-ons/ATN\n"

cat <<EOF >"$date1/addons/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): Add-ons (extensions and themes)

Hello Thunderbird Community,

This is e-mail 4 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO addons.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF

echo -e "\nSupport (Mozilla Support/SUMO, Mozilla Discourse and Topicbox)\n"

cat <<EOF >"$date1/support/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): Support (Mozilla Support, Mozilla Discourse and Topicbox)

Hello Thunderbird Community,

This is e-mail 5 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO sumo.py)


$(time python3 -OO discourse.py)


$(time python3 -OO topicbox.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF

echo -e "\nLocalization (Pontoon and Weblate)\n"

cat <<EOF >"$date1/localization/email.md"
Subject: Thunderbird Community Metrics $date2 ($date1): Localization (Pontoon and Weblate)

Hello Thunderbird Community,

This is e-mail 6 of 6 of the Thunderbird Community Metrics. It includes graphs, so viewing the HTML version is recommended. Tables are included as a fallback and hidden by default when viewing the HTML version. Note that the SVG graphs may not display correctly in other e-mail clients (e.g. Gmail, Topicbox website). PNG versions of the graphs are also attached, as well as the raw CSV data.

🙋 We are looking for a volunteer Mozilla or MZLA employee to run these scripts and send the e-mails each month. If you might be interested, please send us a message.

---

# 📊 Thunderbird Community Metrics $date2 ($date1)

$(time python3 -OO pontoon.py)


$(time python3 -OO weblate.py)

---

Feedback is welcome. The scripts used to generate these e-mails are open source: $REPOSITORY, so contributions are welcome as well!

-Teal
EOF
