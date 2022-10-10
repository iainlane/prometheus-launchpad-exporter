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
import time

from aioprometheus import Counter
from aioprometheus.service import Service

from .ubuntu import UbuntuMetrics


class Metrics:
    def __init__(self, log, series):
        self.log = log
        log.info("Starting prometheus-launchpad-exporter")

        self._series = series

        self._service = Service()
        self.packageset_number_packages = Counter(
            "packageset_number_packages",
            "Number of packages in a packageset",
        )
        self.queue_number_packages = Counter(
            "queue_number_packages",
            "Number of packages in a queue",
        )
        self._metrics_refresh_timer = None  # type: asyncio.Handle
        self._stop_thread_event = threading.Event()

    def fetch_metrics(self):
        log = self.log

        m = UbuntuMetrics(log, self._series)

        m.populate_packageset_maps()
        m.fetch_queues()

        for series, packagesets in m.series_packageset_source_map.items():
            for packageset, sources in packagesets.items():
                self.packageset_number_packages.set(
                    {"series": series, "packageset": packageset}, len(sources)
                )

        for series, queues in m.series_queue_count_map.items():
            for pocket, statuses in queues.items():
                for status, n_packages in statuses.items():
                    self.queue_number_packages.set(
                        {"series": series, "pocket": pocket, "status": status},
                        n_packages,
                    )

    def refresh_metrics_timer(self):
        while not self._stop_thread_event.is_set():
            if self._stop_thread_event.wait(60):
                return
            self.log.info("Refreshing metrics")
            self.fetch_metrics()

    async def start(self):
        # make sure the metrics are fetched once before we start
        self.fetch_metrics()

        self._metrics_refresh_timer = asyncio.to_thread(self.refresh_metrics_timer)

        # refresh every minute
        await asyncio.gather(
            self._metrics_refresh_timer,
            self._service.start(addr="0.0.0.0", port=8000),
        )

    # XXX: this could work better
    # we still need to add a lot of event checking inside of fetch_metrics() to
    # interrupt it. It works now but the interrupt doesn't happen until the sync
    # calls finish
    def stop(self):
        self.log.info("Stopping prometheus-launchpad-exporter")
        self._stop_thread_event.set()
        self._metrics_refresh_timer = None
