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

from collections import defaultdict

from .launchpad import LP


class UbuntuMetrics:
    def __init__(self, log, series):
        self.log = log

        self._series = series

        self._lp = LP(log)

        self._series_queue_count_map = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self._series_packageset_source_map = defaultdict(lambda: defaultdict(list))
        self._source_packageset_map = defaultdict(set)

    def series_to_consider(self):
        if self._series:
            return [self._lp.get_series(s) for s in self._series]

        return self._lp.all_current_series

    def populate_packageset_maps(self):
        for series in self.series_to_consider():
            self.log.info("fetching packagesets", series=series.name)
            for packageset in self._lp.get_packagesets(series):
                self.log.debug(
                    "got packageset", packageset=packageset.name, series=series.name
                )
                sources = self._lp.get_packageset_sources(packageset)
                for source in sources:
                    self._source_packageset_map[source].add(packageset.name)
                    self._series_packageset_source_map[series.name][
                        packageset.name
                    ].append(source)

        self.log.info("done fetching packagesets")

        return self._source_packageset_map

    def fetch_queues(self):
        # series -> queue -> n_packages
        ret = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for series in self.series_to_consider():
            self.log.info("fetching queues", series=series.name)
            for status in ("New", "Unapproved"):
                for pocket in (
                    "Release",
                    "Security",
                    "Updates",
                    "Proposed",
                    "Backports",
                ):
                    queue = series.getPackageUploads(status=status, pocket=pocket)
                    self.log.debug(
                        "got queue",
                        series=series.name,
                        status=status,
                        pocket=pocket,
                        n_queue_items=len(queue),
                    )
                    ret[series.name][pocket][status] = len(queue)

        self._series_queue_count_map = ret

    def get_all_series(self):
        return self._lp.all_current_series

    @property
    def source_packageset_map(self):
        return self._source_packageset_map

    @property
    def series_packageset_source_map(self):
        return self._series_packageset_source_map

    @property
    def series_queue_count_map(self):
        return self._series_queue_count_map
