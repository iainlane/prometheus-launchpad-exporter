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

import concurrent.futures
import threading
from collections import defaultdict

import lazr.restfulclient.errors

from .launchpad import LP


class SourcePackage:
    """An upload of a source package to a series"""

    def __init__(self, log, name, series_name):
        self.log = log.bind(source=name, series=series_name)

        self._name = name
        self._series_name = series_name

        self._last_time_checked = {}
        self._build_status = defaultdict(lambda: defaultdict(str))

    @property
    def name(self):
        return self._name

    def _any_builds_not_successful(self, pocket):
        return any(
            state != "Successfully built"
            for _, state in self._build_status[pocket].values()
        )

    def get_failed_builds(self):
        return {
            pocket: {
                arch: (version, state)
                for arch, (version, state) in builds.items()
                if state == "Failed to build"
            }
            for pocket, builds in self._build_status.items()
        }

    def _fetch_latest_build_status_pocket(self, pocket, local):
        log = self.log.bind(pocket=pocket)
        lp = local.lp
        series = lp.get_series(self._series_name)
        try:
            latest_spph = lp.get_published_sources(
                pocket,
                self._name,
                series,
                self._last_time_checked.get(pocket, None),
            )[0]
        except IndexError:
            log.debug("No published sources found")
            return

        # If we've already seen this one, and all of the builds were successful,
        # we're done. Otherwise, it might have succeeded since we last checked,
        if latest_spph.date_created == self._last_time_checked.get(
            pocket, None
        ) and not self._any_builds_not_successful(pocket):
            log.debug("all builds successful, skipping")
            return

        self._last_time_checked[pocket] = latest_spph.date_created

        try:
            build_records = latest_spph.getBuilds()
        except lazr.restfulclient.errors.Unauthorized:
            log.warning("Unauthorized to fetch builds")
            return

        # if this package was built in this series (wasn't copied forward), then
        # there will be build records
        # (https://bugs.launchpad.net/launchpad/+bug/783613)...
        if len(build_records) > 0:
            log.debug("found build records", count=len(build_records))
            for record in build_records:
                arch = record.arch_tag
                state = record.buildstate
                log.debug(
                    "got build status",
                    arch=arch,
                    version=latest_spph.source_package_version,
                    state=state,
                )
                self._build_status[pocket][arch] = (
                    latest_spph.source_package_version,
                    state,
                )
            return

        # ... if it wasn't then there won't be: the way is to go through binary
        # publications to find the build
        bpphs = latest_spph.getPublishedBinaries()

        seen_arches = set()

        log.debug("no build records, looking through bpphs")

        for bpph in bpphs:
            build = bpph.build
            arch = build.arch_tag

            if arch in seen_arches:
                continue

            state = build.buildstate

            seen_arches.add(arch)

            log.debug(
                "got build status",
                arch=arch,
                version=latest_spph.source_package_version,
                state=state,
            )
            self._build_status[pocket][arch] = (
                latest_spph.source_package_version,
                state,
            )
            if state != "Successfully built":
                log.info(
                    "build not successful",
                    arch=arch,
                    version=latest_spph.source_package_version,
                    state=state,
                )

    def fetch_latest_build_status(self, local):
        for pocket in ("Backports", "Proposed", "Release", "Security", "Updates"):
            self._fetch_latest_build_status_pocket(pocket, local)

        return self._build_status

    @property
    def has_any_builds(self):
        return len(self._build_status) > 0


class UbuntuMetrics:
    def __init__(self, log, series, packagesets):
        self._local = threading.local()

        self.log = log

        self._series = series
        self._packagesets = packagesets

        self._series_queue_count_map = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self._series_packageset_source_map = defaultdict(lambda: defaultdict(set))
        self._series_source_map = defaultdict(dict)

    def series_to_consider(self, lp):
        return self._series if self._series else lp.all_current_series_names

    def packagesets_to_consider_for_series(self, lp, series_name):
        return (
            self._packagesets
            if self._packagesets
            else [
                packageset.name
                for packageset in lp.get_all_packagesets_for_series(series_name)
            ]
        )

        return self._packagesets

    def fetch_packageset_for_series(
        self,
        packageset_name,
        series_name,
        lock,
        local,
    ):
        lp = local.lp

        log = self.log.bind(series=series_name, packageset=packageset_name)

        series = lp.get_series(series_name)
        packageset = lp.get_packagesets_by_name(series, packageset_name)
        sources = lp.get_packageset_sources(packageset)

        source_map = {}
        packageset_source_map = defaultdict(set)

        log.info("processing packageset", n_sources=len(sources))
        for source in sources:
            with lock:
                sp = self._series_source_map[series_name].get(
                    source, source_map.get(source)
                )
                if sp is None:
                    log = log.bind(source_name=source)
                    log.debug("creating source package")
                    sp = SourcePackage(log, source, series_name)
                source_map[source] = sp
                packageset_source_map[packageset_name].add(sp)

        return (source_map, packageset_source_map)

    def make_lp(self, local):
        try:
            lp = local.lp
            self.log.debug("reusing existing LP connection")
            return lp
        except AttributeError:
            self.log.debug("making new LP")
            local.lp = LP(self.log)
            return local.lp

    def populate_packageset_maps(self):
        lock = threading.Lock()

        series_source_map = defaultdict(dict)
        series_packageset_source_map = defaultdict(lambda: defaultdict(set))

        local = threading.local()

        lp = self.make_lp(local)

        for series_name in self.series_to_consider(lp):
            self.log.info("fetching packagesets", series=series_name)

            packageset_names = self.packagesets_to_consider_for_series(lp, series_name)

            self.log.info(
                "got packagesets",
                series=series_name,
                packagesets=" ".join(packageset_names),
            )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=10, initializer=self.make_lp, initargs=(local,)
            ) as executor:
                for (source_map, packageset_source_map) in executor.map(
                    lambda packageset_name: self.fetch_packageset_for_series(
                        packageset_name,
                        series_name,
                        lock,
                        local,
                    ),
                    packageset_names,
                ):
                    series_source_map[series_name].update(source_map)
                    series_packageset_source_map[series_name].update(
                        packageset_source_map
                    )

        self._series_source_map = series_source_map
        self._series_packageset_source_map = series_packageset_source_map

        self.log.info("done fetching packagesets")
        for series_name in self._series_source_map:
            self.log.debug(
                "series packages",
                series=series_name,
                n_packages=len(self._series_source_map[series_name]),
            )

        return self._series_source_map

    def fetch_queues(self):
        local = threading.local()
        lp = self.make_lp(local)
        # series -> queue -> n_packages
        ret = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for series_name in self.series_to_consider(lp):
            series = lp.get_series(series_name)
            self.log.info("fetching queues", series=series_name)
            for status in ("New", "Unapproved"):
                for pocket in (
                    "Release",
                    "Security",
                    "Updates",
                    "Proposed",
                    "Backports",
                ):
                    queue = lp.get_queue(series, status, pocket)
                    self.log.debug(
                        "got queue",
                        series=series_name,
                        status=status,
                        pocket=pocket,
                        n_queue_items=len(queue),
                    )
                    ret[series_name][pocket][status] = len(queue)
            self.log.info("done fetching queues", series=series_name)

        self._series_queue_count_map = ret

    def fetch_build_statuses(self, series_name):
        self.log.info("fetching build statuses", series=series_name)
        all_sources = [
            source
            for _, sources in self._series_packageset_source_map[series_name].items()
            for source in sources
        ]

        local = threading.local()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=10, initializer=self.make_lp, initargs=(local,)
        ) as executor:
            for source in all_sources:
                executor.submit(source.fetch_latest_build_status, local)

        self.log.info("done fetching build statuses", series=series_name)

    @property
    def series_packageset_source_map(self):
        """series -> packageset -> source_package.
        Only returns sources that are in the series. Packagesets can contain
        sources that are not in the series."""
        return {
            series: {
                packageset: [source for source in sources if source.has_any_builds]
                for packageset, sources in self._series_packageset_source_map[
                    series
                ].items()
            }
            for series in self._series_packageset_source_map
        }

    @property
    def series_queue_count_map(self):
        return self._series_queue_count_map
