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

import asyncio
import threading
from collections import defaultdict
from functools import partial

from aioprometheus import Gauge
from aioprometheus.service import Service

from .launchpad import LP
from .ubuntu import UbuntuMetrics


class Metrics:
    def __init__(self, log, series, packagesets):
        self.log = log
        log.info("Starting prometheus-launchpad-exporter")

        self._series = series
        self._packagesets = packagesets

        self._lp = LP(log)

        self._metrics = UbuntuMetrics(log, series)

        self._service = Service()
        self.packageset_number_packages = Gauge(
            "packageset_number_packages",
            "Number of packages in a packageset",
        )
        self.packageset_failed_builds = Gauge(
            "packageset_failed_builds",
            "Number of failed builds in a packageset",
        )
        self.queue_number_packages = Gauge(
            "queue_number_packages",
            "Number of packages in a queue",
        )
        self._stop_metrics_refresh_timer = threading.Event()
        self._stop_fetch_build_statuses_timer = threading.Event()

    def update_packageset_count_metrics(self):
        failed_builds = defaultdict(lambda: defaultdict(int))
        for series, packagesets in self._metrics.series_packageset_source_map.items():
            for packageset, sources in packagesets.items():
                self.packageset_number_packages.set(
                    {"series": series, "packageset": packageset}, len(sources)
                )
                for source in sources:
                    fbs = source.get_failed_builds()
                    for pocket in fbs:
                        for arch in fbs[pocket]:
                            failed_builds[pocket][arch] += 1

        for pocket, arches in failed_builds.items():
            for arch, count in arches.items():
                self.packageset_failed_builds.set(
                    {
                        "series": series,
                        "packageset": packageset,
                        "pocket": pocket,
                        "arch": arch,
                    },
                    count,
                )

    def update_queue_metrics(self):
        for series, queues in self._metrics.series_queue_count_map.items():
            for pocket, statuses in queues.items():
                for status, n_packages in statuses.items():
                    self.queue_number_packages.set(
                        {"series": series, "pocket": pocket, "status": status},
                        n_packages,
                    )

    def refresh_metrics_timer(self):
        while not self._stop_metrics_refresh_timer.is_set():
            if self._stop_metrics_refresh_timer.wait(60):
                return
            self.log.info("Refreshing metrics")

            self._metrics.populate_packageset_maps(self._packagesets)
            self._metrics.fetch_queues()

            self.update_packageset_count_metrics()
            self.update_queue_metrics()

    def fetch_build_statuses(self, series):
        while not self._stop_fetch_build_statuses_timer.is_set():
            if self._stop_fetch_build_statuses_timer.wait(60 * 5):
                return
            self._metrics.fetch_build_statuses(series)

    async def start(self):
        # make sure the metrics are fetched once before we start
        self._metrics.populate_packageset_maps(self._packagesets)
        self._metrics.fetch_queues()

        threads = []
        for series in self._metrics.series_to_consider(self._lp):
            t = threading.Thread(
                target=partial(self._metrics.fetch_build_statuses, series)
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.update_packageset_count_metrics()
        self.update_queue_metrics()

        metrics_refresh_timer = asyncio.to_thread(self.refresh_metrics_timer)

        # refresh every minute
        await asyncio.gather(
            *[
                asyncio.to_thread(partial(self.fetch_build_statuses, series))
                for series in self._metrics.series_to_consider(self._lp)
            ],
            metrics_refresh_timer,
            self._service.start(addr="0.0.0.0", port=8000),
        )

    # XXX: this could work better
    # we still need to add a lot of event checking inside of fetch_metrics() to
    # interrupt it. It works now but the interrupt doesn't happen until the sync
    # calls finish
    def stop(self):
        self.log.info("Stopping prometheus-launchpad-exporter")
        self._stop_metrics_refresh_timer.set()
        self._stop_fetch_build_statuses_timer.set()
