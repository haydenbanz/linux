#!/usr/bin/env drgn
#
# Copyright (C) 2024 Kemeng Shi <shikemeng@huaweicloud.com>
# Copyright (C) 2024 Huawei Inc

"""
This drgn script monitors writeback information on backing devices, based on
wq_monitor.py. For more information on drgn, visit https://github.com/osandov/drgn.

Metrics:
  - writeback(kB):     Amount of dirty pages currently being written back to disk.
  - reclaimable(kB):   Amount of pages currently reclaimable.
  - dirtied(kB):       Amount of pages that have been dirtied.
  - written(kB):       Amount of dirty pages written back to disk.
  - avg_wb(kBps):      Estimated average write bandwidth for writing dirty pages back to disk.
"""

import signal
import re
import time
import json

import drgn
from drgn.helpers.linux.list import list_for_each_entry

import argparse

# Argument parsing
parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('bdi', metavar='REGEX', nargs='*',
                    help='Target backing device name patterns (all if empty)')
parser.add_argument('-i', '--interval', metavar='SECS', type=float, default=1,
                    help='Monitoring interval (0 to print once and exit)')
parser.add_argument('-j', '--json', action='store_true',
                    help='Output in JSON format')
parser.add_argument('-c', '--cgroup', action='store_true',
                    help='Show writeback of bdi in cgroup')
args = parser.parse_args()

# Global variables
bdi_list = prog['bdi_list']
WB_RECLAIMABLE = prog['WB_RECLAIMABLE']
WB_WRITEBACK = prog['WB_WRITEBACK']
WB_DIRTIED = prog['WB_DIRTIED']
WB_WRITTEN = prog['WB_WRITTEN']
NR_WB_STAT_ITEMS = prog['NR_WB_STAT_ITEMS']
PAGE_SHIFT = prog['PAGE_SHIFT']

exit_req = False

def K(x):
    """Convert pages to kilobytes."""
    return x << (PAGE_SHIFT - 10)

class Stats:
    """Base class for collecting and displaying statistics."""
    
    @staticmethod
    def table_header_str():
        """Return formatted table header string."""
        return f'{"":>16} {"writeback":>10} {"reclaimable":>12} ' \
               f'{"dirtied":>9} {"written":>9} {"avg_bw":>9}'

    def dict(self, now):
        """Return a dictionary representation of the statistics."""
        return {
            'timestamp': now,
            'name': self.name,
            'writeback': self.stats[WB_WRITEBACK],
            'reclaimable': self.stats[WB_RECLAIMABLE],
            'dirtied': self.stats[WB_DIRTIED],
            'written': self.stats[WB_WRITTEN],
            'avg_wb': self.avg_bw,
        }

    def table_row_str(self):
        """Return formatted table row string."""
        return f'{self.name[-16:]:16} ' \
               f'{self.stats[WB_WRITEBACK]:10} ' \
               f'{self.stats[WB_RECLAIMABLE]:12} ' \
               f'{self.stats[WB_DIRTIED]:9} ' \
               f'{self.stats[WB_WRITTEN]:9} ' \
               f'{self.avg_bw:9} '

    @staticmethod
    def show_header():
        """Display table header if in table format."""
        if Stats.table_fmt:
            print()
            print(Stats.table_header_str())

    def show_stats(self):
        """Display statistics in either table or JSON format."""
        if Stats.table_fmt:
            print(self.table_row_str())
        else:
            print(self.dict(Stats.now))

class WbStats(Stats):
    """Class for collecting and displaying per-writeback statistics."""
    
    def __init__(self, wb):
        bdi_name = wb.bdi.dev_name.string_().decode()
        ino = "1" if wb == wb.bdi.wb.address_of_() else str(wb.memcg_css.cgroup.kn.id.value_())
        self.name = f"{bdi_name}_{ino}"
        self.stats = [int(K(wb.stat[i].count)) if wb.stat[i].count >= 0 else 0 for i in range(NR_WB_STAT_ITEMS)]
        self.avg_bw = int(K(wb.avg_write_bandwidth))

class BdiStats(Stats):
    """Class for collecting and displaying per-backing-device statistics."""
    
    def __init__(self, bdi):
        self.name = bdi.dev_name.string_().decode()
        self.stats = [0] * NR_WB_STAT_ITEMS
        self.avg_bw = 0

    def collectStats(self, wb_stats):
        """Accumulate statistics from writeback statistics."""
        for i in range(NR_WB_STAT_ITEMS):
            self.stats[i] += wb_stats.stats[i]
        self.avg_bw += wb_stats.avg_bw

def sigint_handler(signr, frame):
    """Handle SIGINT to allow clean script exit."""
    global exit_req
    exit_req = True

def main():
    """Main monitoring loop."""
    Stats.table_fmt = not args.json
    interval = args.interval
    cgroup = args.cgroup

    re_str = '|'.join(args.bdi) if args.bdi else None
    filter_re = re.compile(re_str) if re_str else None

    # Register signal handler
    signal.signal(signal.SIGINT, sigint_handler)

    # Monitoring loop
    while not exit_req:
        Stats.now = time.time()
        Stats.show_header()

        for bdi in list_for_each_entry('struct backing_dev_info', bdi_list.address_of_(), 'bdi_list'):
            bdi_stats = BdiStats(bdi)
            if filter_re and not filter_re.search(bdi_stats.name):
                continue

            for wb in list_for_each_entry('struct bdi_writeback', bdi.wb_list.address_of_(), 'bdi_node'):
                wb_stats = WbStats(wb)
                bdi_stats.collectStats(wb_stats)
                if cgroup:
                    wb_stats.show_stats()

            bdi_stats.show_stats()
            if cgroup and Stats.table_fmt:
                print()

        if interval == 0:
            break
        time.sleep(interval)

if __name__ == "__main__":
    main()
