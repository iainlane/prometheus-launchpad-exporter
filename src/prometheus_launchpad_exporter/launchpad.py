# This file is part of prometheus-launchpad-exporter.
#
# Copyright (C) 2022 Iain Lane <iain@orangesquash.org.uk>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

import cachetools.func
from launchpadlib.launchpad import Launchpad


class LP:
    def __init__(self, log, cache_dir=None):
        self.log = log

        self.series_cache = cachetools.LRUCache(maxsize=512)
        self.packageset_cache = cachetools.TTLCache(maxsize=512, ttl=10 * 60)
        self.packageset_sources_cache = cachetools.TTLCache(maxsize=512, ttl=60 * 60)
        # 1 minute expiry on the queues, they move fast
        self.queue_cache = cachetools.TTLCache(maxsize=512, ttl=1 * 60)

        self.cache_dir = cache_dir
        if cache_dir is None:
            cache_dir = self._default_cache_dir()
        self.login()

    def _default_cache_dir(self):
        import xdg.BaseDirectory

        return os.path.join(
            xdg.BaseDirectory.xdg_cache_home, "prometheus_launchpad_exporter"
        )

    @property
    def all_current_series(self):
        return [
            self.get_series(series.name)
            for series in self.lp.distributions["ubuntu"].series
            if series.status
            in (
                "Active Development",
                "Current",
                "Future",
                "Pre-release Freeze",
                "Supported",
            )
        ]

    @cachetools.cachedmethod(lambda self: self.series_cache)
    def get_series(self, name):
        self.log.debug("getting series from LP", name=name)
        return self.lp.distributions["ubuntu"].getSeries(name_or_version=name)

    @cachetools.cachedmethod(
        lambda self: self.packageset_cache,
        key=lambda _, series: series.name,
    )
    def get_packagesets(self, series):
        self.log.debug("getting packagesets from LP", series=series.name)
        return self.lp.packagesets.getBySeries(distroseries=series)

    @cachetools.cachedmethod(
        lambda self: self.packageset_sources_cache,
        key=lambda _, packageset: f"{packageset.distroseries.name}/{packageset.name}",
    )
    def get_packageset_sources(self, packageset):
        self.log.debug("getting packageset sources from LP", packageset=packageset.name)
        return packageset.getSourcesIncluded()

    @cachetools.cachedmethod(
        lambda self: self.queue_cache,
        key=lambda _, series, status, pocket: f"{series.name}/{status}/{pocket}",
    )
    def get_queue(self, series, status, pocket):
        self.log.debug(
            "getting queues from LP", series=series.name, status=status, pocket=pocket
        )
        return series.getPackageUploads(status=status, pocket=pocket)

    def login(self):
        self.lp = Launchpad.login_anonymously(
            "prometheus-launchpad-exporter",
            "production",
            self.cache_dir,
            version="devel",
        )
