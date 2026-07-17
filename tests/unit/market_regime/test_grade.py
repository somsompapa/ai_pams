from pams.market_regime.domain.grade import Grade


class TestGradeRank:
    def test_a_is_safest(self) -> None:
        assert Grade.A.rank == 0

    def test_e_is_riskiest(self) -> None:
        assert Grade.E.rank == 4

    def test_ordering_matches_alphabet(self) -> None:
        assert [g.rank for g in (Grade.A, Grade.B, Grade.C, Grade.D, Grade.E)] == [0, 1, 2, 3, 4]


class TestAtLeastAsSafeAs:
    def test_c_is_at_least_as_safe_as_c(self) -> None:
        assert Grade.C.at_least_as_safe_as(Grade.C) is True

    def test_b_is_at_least_as_safe_as_c(self) -> None:
        assert Grade.B.at_least_as_safe_as(Grade.C) is True

    def test_d_is_not_at_least_as_safe_as_c(self) -> None:
        assert Grade.D.at_least_as_safe_as(Grade.C) is False
