import unittest
from datetime import datetime, timedelta
from analyze import cluster_sessions, lead_in_minutes, compute_hours

def t(mins):
    return datetime(2026, 6, 16, 9, 0) + timedelta(minutes=mins)

class TestSessions(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cluster_sessions([], 90), [])

    def test_single_commit(self):
        s = cluster_sessions([t(0)], 90)
        self.assertEqual(len(s), 1)
        self.assertEqual(len(s[0]), 1)

    def test_splits_on_large_gap(self):
        times = [t(0), t(30), t(200), t(210)]  # gap 170 > 90 splits
        s = cluster_sessions(times, 90)
        self.assertEqual([len(x) for x in s], [2, 2])

    def test_boundary_equal_gap_same_session(self):
        s = cluster_sessions([t(0), t(90)], 90)  # exactly 90 -> not > 90
        self.assertEqual(len(s), 1)

class TestLeadIn(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(lead_in_minutes(1, 0), 5)       # min clamp
        self.assertEqual(lead_in_minutes(5, 100000), 90) # max clamp
        self.assertTrue(5 <= lead_in_minutes(3, 500) <= 90)

class TestComputeHours(unittest.TestCase):
    def test_active_plus_leadin(self):
        # one session 60 min active, complexity 1 -> lead-in 5 min => 65 min
        sessions = [[t(0), t(60)]]
        complexities = {0: 1}
        diffsizes = {0: 0}
        hrs = compute_hours(sessions, complexities, diffsizes)
        self.assertAlmostEqual(hrs, (60 + 5) / 60.0, places=3)
