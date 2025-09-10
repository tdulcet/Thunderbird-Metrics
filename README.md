# Thunderbird Community Metrics
Mozilla Thunderbird Community Metrics

**This is the original repository. It has moved to https://github.com/thunderbird/Thunderbird-Metrics, where maintenance will continue.**

Copyright © 2025 Teal Dulcet

The Thunderbird Community Metrics are designed to complement @mkmelin’s existing “Thunderbird Metrics” e-mail, while providing data from additional sources. There are a total of six e-mails, covering 13 sources:

1. Bugzilla/BMO, Phabricator, Crash Stats and Thunderbird Code Coverage
2. GitHub
3. Thunderbird Stats and Mozilla Connect
4. Thunderbird Add-ons/ATN
5. Support (Mozilla Support/SUMO, Mozilla Discourse and Topicbox)
6. Localization (Pontoon and Weblate)

The e-mails are sent to the [Thunderbird Planning](https://thunderbird.topicbox.com/groups/planning) mailing list monthly.

❤️ Please visit [tealdulcet.com](https://www.tealdulcet.com/) to support this project and my other software development.

## Usage

Requires Python 3.7 or greater, as well as the [Requests library](https://pypi.org/project/requests/) and the [Matplotlib library](https://pypi.org/project/matplotlib/), which users can install with:
```bash
pip3 install requests matplotlib
# or
python3 -m pip install requests matplotlib
```
The SUMO script requires Python 3.9 or greater due to the dependency on the [zoneinfo module](https://docs.python.org/3/library/zoneinfo.html).

The Bugzilla/Phabricator script requires [an access token](https://phabricator.services.mozilla.com/settings/panel/apitokens/) for Phabricator.

It is recommended to provide an [an access token](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api) for the GitHub script, as otherwise would be very slow due to the strict rate limit of 60 requests/hour.

To generate all of the e-mails, run: `bash generate.sh`. The results are in a `YYYY-MM` directory for the previous month, with a subdirectory for each of the e-mails.

## Contributing

Pull requests welcome!
