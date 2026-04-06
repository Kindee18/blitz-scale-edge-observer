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


def test_nhl_scoring_supported():
    stats = {
        "goals": 1,
        "assists": 2,
        "shots_on_goal": 5,
        "blocked_shots": 3,
    }
    points = calculate_fantasy_points(stats, sport="nhl")
    # 6.0 + 8.0 + 4.5 + 3.0 = 21.5
    assert points == 21.5


def test_stat_correction_negative_delta():
    old_stats = {"passing_yards": 300, "passing_tds": 3}
    # Stat correction: touchdown removed, yards reduced
    new_stats = {"passing_yards": 280, "passing_tds": 2}
    delta = calculate_fantasy_delta(old_stats, new_stats, format="ppr")

    # old: 300*0.04 + 3*4 = 12 + 12 = 24.0
    # new: 280*0.04 + 2*4 = 11.2 + 8 = 19.2
    assert delta["previous_points"] == 24.0
    assert delta["current_points"] == 19.2
    assert delta["points_delta"] == -4.8
    assert delta["significant_change"] is True


def test_large_stat_update_nba():
    old_stats = {"points": 10, "rebounds": 2}
    new_stats = {"points": 50, "rebounds": 20, "assists": 10, "steals": 5}
    delta = calculate_fantasy_delta(old_stats, new_stats, sport="nba")

    # old: 10*1.0 + 2*1.2 = 12.4
    # new: 50*1.0 + 20*1.2 + 10*1.5 + 5*3.0 = 50 + 24 + 15 + 15 = 104.0
    assert delta["previous_points"] == 12.4
    assert delta["current_points"] == 104.0
    assert delta["points_delta"] == 91.6
