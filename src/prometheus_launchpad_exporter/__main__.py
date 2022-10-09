#!/usr/bin/env python3

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

import argparse
import asyncio
import logging
import sys
from signal import SIGINT, SIGTERM

import structlog

from .metrics import Metrics


async def main():
    parser = argparse.ArgumentParser(description="Prometheus exporter for Launchpad")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--series",
        action="append",
        help="Series to export metrics for",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(),
            structlog.processors.LogfmtRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if args.debug else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log = structlog.get_logger()
    log.debug("Running in debug mode")

    m = Metrics(log, args.series)
    await m.start()

    try:
        await asyncio.Event().wait()
    finally:
        await m.stop()

    app = Metrics(log)

    loop = asyncio.get_event_loop()

    for signal_enum in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal_enum, asyncio.ensure_future(app.stop))

    await app.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
