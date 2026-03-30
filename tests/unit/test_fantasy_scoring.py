from streaming.fantasy_scoring import calculate_fantasy_delta, calculate_fantasy_points


def test_nfl_scoring_unchanged_default_ppr():
    stats = {
        "passing_yards": 250,
        "passing_tds": 2,
        "passing_ints": 1,
        "receptions": 5,
        "receiving_yards": 40,
    }
    points = calculate_fantasy_points(stats, format="ppr")
    assert points == 25.0


def test_nba_scoring_supported():
    stats = {
        "points": 25,
        "rebounds": 10,
        "assists": 8,
        "steals": 2,
        "blocks": 1,
        "turnovers": 3,
        "three_pointers_made": 4,
    }
    points = calculate_fantasy_points(stats, sport="nba")
    assert points == 57.0


def test_mlb_delta_supported():
    old_stats = {"hits": 1, "runs": 0, "rbi": 0}
    new_stats = {"hits": 2, "runs": 1, "rbi": 2}
    delta = calculate_fantasy_delta(old_stats, new_stats, sport="mlb")

    assert delta["previous_points"] == 3.0
    assert delta["current_points"] == 12.0
    assert delta["points_delta"] == 9.0
    assert delta["significant_change"] is True
