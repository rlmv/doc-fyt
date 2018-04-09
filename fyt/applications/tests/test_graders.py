from model_mommy import mommy

from fyt.applications.models import (
    CrooApplicationGrade,
    LeaderApplicationGrade,
    Score,
    Grader
)
from fyt.applications.views.graders import _old_get_graders
from fyt.test import FytTestCase


class GraderViewsTestCase(FytTestCase):

    def setUp(self):
        self.init_trips_year()
        self.init_old_trips_year()
        self.make_user()
        self.grader = Grader.objects.from_user(self.make_grader())

    def test_for_year_only_returns_graders(self):
        mommy.make(Score, trips_year=self.trips_year, grader=self.grader)
        self.assertQsEqual(Grader.objects.for_year(self.trips_year),
                           [self.grader])

    def test_for_year_returns_distinct_queryset(self):
        mommy.make(Score, 2, trips_year=self.trips_year, grader=self.grader)
        self.assertQsEqual(Grader.objects.for_year(self.trips_year),
                           [self.grader])

    def test_for_year_filters_trips_year(self):
        new_score = mommy.make(Score, trips_year=self.trips_year)
        old_score = mommy.make(Score, trips_year=self.old_trips_year)
        self.assertQsEqual(Grader.objects.for_year(self.trips_year),
                           [new_score.grader])

    def test_for_year_averages_only_include_scores_from_this_year(self):
        mommy.make(
            Score,
            trips_year=self.trips_year,
            grader=self.grader,
            leader_score=1,
            croo_score=2,
        )
        mommy.make(
            Score,
            trips_year=self.old_trips_year,
            grader=self.grader,
            leader_score=3,
            croo_score=4
        )
        graders = Grader.objects.for_year(self.trips_year)
        self.assertEqual(len(graders), 1)
        self.assertEqual(graders[0].score_count, 1)
        self.assertEqual(graders[0].avg_leader_score, 1)
        self.assertEqual(graders[0].avg_croo_score, 2)

    def test_for_year_score_histogram(self):
        mommy.make(
            Score,
            trips_year=self.trips_year,
            grader=self.grader,
            leader_score=1,
            croo_score=2,
        )
        mommy.make(
            Score,
            trips_year=self.trips_year,
            grader=self.grader,
            leader_score=4,
            croo_score=4
        )
        graders = Grader.objects.for_year(self.trips_year)

        self.assertEqual(graders[0].leader_score_histogram, {
            1: 1,
            1.5: 0,
            2: 0,
            2.5: 0,
            3: 0,
            3.5: 0,
            4: 1,
            4.5: 0,
            5: 0,
        })
        self.assertEqual(graders[0].croo_score_histogram, {
            1: 0,
            1.5: 0,
            2: 1,
            2.5: 0,
            3: 0,
            3.5: 0,
            4: 1,
            4.5: 0,
            5: 0,
        })


# Tests for deprecated grade objects
# Only apply in production to years 2015 & 2016
class OldGraderViewsTestCase(FytTestCase):

    def test_old_get_graders_returns_only_people_who_have_submitted_grades(self):
        trips_year = self.init_trips_year()
        grade = mommy.make(CrooApplicationGrade, trips_year=trips_year)
        grader = grade.grader
        random_other_user = self.make_user()
        graders = _old_get_graders(trips_year)
        self.assertIn(grader, graders)
        self.assertNotIn(random_other_user, graders)

    def test_old_get_graders_returns_distinct_queryset(self):
        trips_year = self.init_trips_year()
        grader = self.make_grader()
        mommy.make(
            LeaderApplicationGrade, 2,
            trips_year=trips_year,
            grader=grader
        )
        graders = _old_get_graders(trips_year)
        self.assertIn(grader, graders)
        self.assertEqual(len(graders), 1)

    def test_old_get_graders_only_returns_graders_from_this_year(self):
        trips_year = self.init_trips_year()
        old_trips_year = self.init_old_trips_year()
        grader = self.make_grader()
        mommy.make(
            LeaderApplicationGrade,
            trips_year=old_trips_year,
            grader=grader
        )
        mommy.make(
            CrooApplicationGrade,
            trips_year=old_trips_year,
            grader=grader
        )
        self.assertEqual([], list(_old_get_graders(trips_year)))

    def test_old_get_graders_avgs_only_includes_grades_from_trips_year(self):
        trips_year = self.init_trips_year()
        old_trips_year = self.init_old_trips_year()
        grader = self.make_grader()
        mommy.make(
            LeaderApplicationGrade,
            trips_year=trips_year,
            grader=grader, grade=1
        )
        mommy.make(
            LeaderApplicationGrade,
            trips_year=old_trips_year,
            grader=grader, grade=2
        )
        mommy.make(
            CrooApplicationGrade,
            trips_year=trips_year,
            grader=grader, grade=1
        )
        mommy.make(
            CrooApplicationGrade,
            trips_year=old_trips_year,
            grader=grader, grade=2
        )
        graders = _old_get_graders(trips_year)
        self.assertEqual(len(graders), 1)
        self.assertEqual(graders[0].leader_grade_count, 1)
        self.assertEqual(graders[0].avg_leader_grade, 1)
        self.assertEqual(graders[0].croo_grade_count, 1)
        self.assertEqual(graders[0].avg_croo_grade, 1)
