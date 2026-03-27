from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from group9_network_scheduling import QueueClass, load_case


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_ROOT = PROJECT_ROOT / "tsn-test-cases-main" / "examples"


class LoaderTests(unittest.TestCase):
    def test_loads_example_case_and_maps_queues(self) -> None:
        case = load_case(EXAMPLES_ROOT / "test_case_1")

        self.assertEqual(len(case.streams), 10)
        self.assertEqual(case.queue_counts, {"A": 4, "B": 4, "BE": 2})
        self.assertEqual(case.streams[0].queue_class, QueueClass.A)
        self.assertEqual(case.streams[4].queue_class, QueueClass.B)
        self.assertEqual(case.streams[8].queue_class, QueueClass.BE)

    def test_computes_hops_and_latencies_from_routes(self) -> None:
        case = load_case(EXAMPLES_ROOT / "test_case_1")
        stream = case.streams[0]

        self.assertEqual(stream.route_signature, ("Link5", "Link2"))
        self.assertEqual(stream.hop_count, 2)
        self.assertAlmostEqual(stream.hops[0].transmission_time_us, 80.96, places=2)
        self.assertAlmostEqual(stream.end_to_end_transmission_time_us, 161.92, places=2)
        self.assertAlmostEqual(stream.end_to_end_propagation_delay_us, 13.04, places=3)

    def test_groups_streams_by_directional_route_signature(self) -> None:
        case = load_case(EXAMPLES_ROOT / "test_case_2")
        route_groups = case.route_groups

        self.assertEqual(len(route_groups), 2)
        self.assertEqual([len(group.streams) for group in route_groups], [5, 5])
        self.assertFalse(case.has_single_shared_route)

    def test_cli_emits_json_summary(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "group9_network_scheduling",
                "summarize",
                str(EXAMPLES_ROOT / "test_case_3"),
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["stream_count"], 10)
        self.assertEqual(summary["queue_counts"], {"A": 4, "B": 4, "BE": 2})
        self.assertEqual(summary["route_group_count"], 2)


if __name__ == "__main__":
    unittest.main()
