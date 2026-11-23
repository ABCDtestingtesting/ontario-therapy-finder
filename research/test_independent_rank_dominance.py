"""Fail-closed independent therapist ranking dominance tests."""
import unittest
from research.reconcile_independent_zero_audit import strict_dominance_check

def area(index, density, completed=True):
    return {
        'fsa':f'R{index:03}', 'completed_source_feed':completed,
        'population_5km_estimate_2021':10000,
        'google_listings_per_10000_residents_or_lower_bound':density,
    }

class StrictDominanceTests(unittest.TestCase):
    def test_unverified_high_clinical_density_is_safely_dominated(self):
        completed=[area(i,2.0) for i in range(60)]
        bounded=area(60,3.0,False)
        ranking, cutoff, pending=strict_dominance_check(completed+[bounded])
        self.assertEqual(len(ranking),60)
        self.assertEqual(cutoff,2.0)
        self.assertEqual(pending,[])

    def test_unverified_low_density_must_not_be_removed(self):
        completed=[area(i,2.0) for i in range(60)]
        uncertain=area(60,1.0,False)
        _, cutoff, pending=strict_dominance_check(completed+[uncertain])
        self.assertEqual(cutoff,2.0)
        self.assertEqual(pending,[uncertain])

    def test_equal_density_must_stay_uncertain(self):
        completed=[area(i,2.0) for i in range(60)]
        tied=area(60,2.0,False)
        _, _, pending=strict_dominance_check(completed+[tied])
        self.assertEqual(pending,[tied])

    def test_fewer_than_60_completions_never_certifies(self):
        completed=[area(i,2.0) for i in range(59)]
        uncertain=area(59,3.0,False)
        ranking,cutoff,pending=strict_dominance_check(completed+[uncertain])
        self.assertEqual(len(ranking),59)
        self.assertIsNone(cutoff)
        self.assertEqual(pending,[uncertain])

if __name__=='__main__':
    unittest.main()
