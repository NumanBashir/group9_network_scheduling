from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from group9_network_scheduling import (
    LOCAL_TEST_CASES_ROOT,
    QueueClass,
    analyze_case,
    import_case,
    load_case,
    load_reference_wcrts,
    simulate_case,
)


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

    def test_analysis_matches_reference_wcrts_for_example_case_1(self) -> None:
        case = load_case(EXAMPLES_ROOT / "test_case_1")
        analysis = analyze_case(case)
        reference = load_reference_wcrts(EXAMPLES_ROOT / "test_case_1")

        for stream_id in range(8):
            stream_analysis = analysis.by_stream_id[stream_id]
            self.assertTrue(stream_analysis.supported)
            self.assertAlmostEqual(stream_analysis.pure_wcd_us, reference[stream_id], places=2)

        self.assertFalse(analysis.by_stream_id[8].supported)
        self.assertIsNone(analysis.by_stream_id[8].pure_wcd_us)

    def test_simulation_stays_below_analytical_bound_for_avb_streams(self) -> None:
        case = load_case(EXAMPLES_ROOT / "test_case_1")
        analysis = analyze_case(case)
        simulation = simulate_case(case, cycles=3)

        for stream_id in range(8):
            self.assertLessEqual(
                simulation.by_stream_id[stream_id].observed_pure_wcd_us,
                analysis.by_stream_id[stream_id].pure_wcd_us + 1e-6,
            )
            self.assertGreater(simulation.by_stream_id[stream_id].frame_instances, 0)

    def test_import_case_copies_into_local_store_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_root = Path(temp_dir) / "cases"
            imported = import_case(
                EXAMPLES_ROOT / "test_case_2",
                destination_root=destination_root,
                case_name="copied_case",
            )
            self.assertTrue((imported / "topology.json").exists())
            self.assertTrue((imported / "streams.json").exists())
            self.assertTrue((imported / "routes.json").exists())

    def test_compare_cli_reports_reference_values(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "group9_network_scheduling",
                "compare",
                str(EXAMPLES_ROOT / "test_case_1"),
                "--cycles",
                "3",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        payload = json.loads(completed.stdout)
        first_stream = next(row for row in payload["streams"] if row["stream_id"] == 0)
        self.assertAlmostEqual(first_stream["analytical_pure_wcd_us"], 603.2, places=2)
        self.assertAlmostEqual(first_stream["reference_wcrt_us"], 603.2, places=2)


if __name__ == "__main__":
    unittest.main()
