"""Fantasy Scoring Calculator for FantasyPros Integration.

This module provides fantasy points calculation for NFL players
supporting multiple scoring formats: PPR, Half-PPR, and Standard.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class ScoringFormat(Enum):
    """Supported fantasy scoring formats."""

    PPR = "ppr"
    HALF_PPR = "half_ppr"
    STANDARD = "standard"


@dataclass
class PlayerStats:
    """Container for player statistical performance."""

    passing_yards: float = 0
    passing_tds: int = 0
    passing_ints: int = 0
    rushing_yards: float = 0
    rushing_tds: int = 0
    receptions: int = 0
    receiving_yards: float = 0
    receiving_tds: int = 0
    fumbles: int = 0
    two_point_conversions: int = 0

    @classmethod
    def from_dict(cls, stats: Dict) -> "PlayerStats":
        """Create PlayerStats from a dictionary."""
        return cls(
            passing_yards=stats.get("passing_yards", 0) or stats.get("yards", 0)
            if stats.get("passing_tds")
            else 0,
            passing_tds=stats.get("passing_tds", 0),
            passing_ints=stats.get("passing_ints", 0) or stats.get("ints", 0),
            rushing_yards=stats.get("rushing_yards", 0),
            rushing_tds=stats.get("rushing_tds", 0) or stats.get("tds", 0),
            receptions=stats.get("receptions", 0) or stats.get("rec", 0),
            receiving_yards=stats.get("receiving_yards", 0),
            receiving_tds=stats.get("receiving_tds", 0),
            fumbles=stats.get("fumbles", 0),
            two_point_conversions=stats.get("two_point_conversions", 0),
        )


class FantasyScoringCalculator:
    """Calculates fantasy points based on various scoring formats.

    Default scoring rules (configurable):
    - Passing: 0.04 pts per yard, 4 pts per TD, -2 per INT
    - Rushing: 0.1 pts per yard, 6 pts per TD
    - Receiving: 0.1 pts per yard, 6 pts per TD
    - PPR: 1 pt per reception (0.5 for Half-PPR, 0 for Standard)
    - Fumbles: -2 pts
    - 2-PT Conversions: 2 pts
    """

    def __init__(
        self,
        passing_yards_multiplier: float = 0.04,
        passing_td_multiplier: float = 4.0,
        passing_int_multiplier: float = -2.0,
        rushing_yards_multiplier: float = 0.1,
        rushing_td_multiplier: float = 6.0,
        receiving_yards_multiplier: float = 0.1,
        receiving_td_multiplier: float = 6.0,
        fumble_multiplier: float = -2.0,
        two_point_multiplier: float = 2.0,
    ):
        self.passing_yards_multiplier = passing_yards_multiplier
        self.passing_td_multiplier = passing_td_multiplier
        self.passing_int_multiplier = passing_int_multiplier
        self.rushing_yards_multiplier = rushing_yards_multiplier
        self.rushing_td_multiplier = rushing_td_multiplier
        self.receiving_yards_multiplier = receiving_yards_multiplier
        self.receiving_td_multiplier = receiving_td_multiplier
        self.fumble_multiplier = fumble_multiplier
        self.two_point_multiplier = two_point_multiplier

    def calculate_points(
        self, stats: PlayerStats, format: ScoringFormat = ScoringFormat.PPR
    ) -> float:
        """Calculate total fantasy points for a player.

        Args:
            stats: Player statistical performance
            format: Scoring format (PPR, Half-PPR, or Standard)

        Returns:
            Total fantasy points
        """
        points = 0.0

        # Passing
        points += stats.passing_yards * self.passing_yards_multiplier
        points += stats.passing_tds * self.passing_td_multiplier
        points += stats.passing_ints * self.passing_int_multiplier

        # Rushing
        points += stats.rushing_yards * self.rushing_yards_multiplier
        points += stats.rushing_tds * self.rushing_td_multiplier

        # Receiving
        points += stats.receiving_yards * self.receiving_yards_multiplier
        points += stats.receiving_tds * self.receiving_td_multiplier

        # Reception scoring based on format
        if format == ScoringFormat.PPR:
            points += stats.receptions * 1.0
        elif format == ScoringFormat.HALF_PPR:
            points += stats.receptions * 0.5
        # Standard: 0 points per reception

        # Fumbles and 2-point conversions
        points += stats.fumbles * self.fumble_multiplier
        points += stats.two_point_conversions * self.two_point_multiplier

        return round(points, 2)

    def calculate_points_breakdown(
        self, stats: PlayerStats, format: ScoringFormat = ScoringFormat.PPR
    ) -> Dict[str, float]:
        """Calculate detailed fantasy points breakdown by category.

        Args:
            stats: Player statistical performance
            format: Scoring format

        Returns:
            Dictionary with points breakdown by category
        """
        breakdown = {
            "passing": round(
                stats.passing_yards * self.passing_yards_multiplier
                + stats.passing_tds * self.passing_td_multiplier
                + stats.passing_ints * self.passing_int_multiplier,
                2,
            ),
            "rushing": round(
                stats.rushing_yards * self.rushing_yards_multiplier
                + stats.rushing_tds * self.rushing_td_multiplier,
                2,
            ),
            "receiving": round(
                stats.receiving_yards * self.receiving_yards_multiplier
                + stats.receiving_tds * self.receiving_td_multiplier,
                2,
            ),
            "receptions": round(
                stats.receptions
                * (
                    1.0
                    if format == ScoringFormat.PPR
                    else 0.5
                    if format == ScoringFormat.HALF_PPR
                    else 0
                ),
                2,
            ),
            "fumbles": round(stats.fumbles * self.fumble_multiplier, 2),
            "two_point": round(
                stats.two_point_conversions * self.two_point_multiplier, 2
            ),
        }

        breakdown["total"] = round(
            sum(v for k, v in breakdown.items() if k != "total"), 2
        )
        return breakdown

    def calculate_delta(
        self,
        old_stats: PlayerStats,
        new_stats: PlayerStats,
        format: ScoringFormat = ScoringFormat.PPR,
    ) -> Dict:
        """Calculate fantasy points delta between two stat states.

        Args:
            old_stats: Previous player statistics
            new_stats: Updated player statistics
            format: Scoring format

        Returns:
            Dictionary with delta information including:
            - previous_points
            - current_points
            - points_delta
            - breakdown_delta
            - significant_change (bool)
        """
        previous_points = self.calculate_points(old_stats, format)
        current_points = self.calculate_points(new_stats, format)
        points_delta = round(current_points - previous_points, 2)

        old_breakdown = self.calculate_points_breakdown(old_stats, format)
        new_breakdown = self.calculate_points_breakdown(new_stats, format)

        breakdown_delta = {
            category: round(
                new_breakdown.get(category, 0) - old_breakdown.get(category, 0), 2
            )
            for category in new_breakdown.keys()
        }

        return {
            "previous_points": previous_points,
            "current_points": current_points,
            "points_delta": points_delta,
            "breakdown_delta": breakdown_delta,
            "significant_change": abs(points_delta) >= 0.5,  # Significant if >= 0.5 pts
        }


def _sport_stat_weights(sport: str) -> Dict[str, float]:
    # Conservative defaults for cross-sport demo support.
    if sport == "nba":
        return {
            "points": 1.0,
            "rebounds": 1.2,
            "assists": 1.5,
            "steals": 3.0,
            "blocks": 3.0,
            "turnovers": -1.0,
            "three_pointers_made": 0.5,
        }
    if sport == "mlb":
        return {
            "hits": 3.0,
            "doubles": 5.0,
            "triples": 8.0,
            "home_runs": 10.0,
            "rbi": 2.0,
            "runs": 2.0,
            "walks": 2.0,
            "stolen_bases": 5.0,
            "innings_pitched": 2.0,
            "strikeouts": 2.0,
            "wins": 6.0,
            "saves": 8.0,
            "earned_runs": -2.0,
        }
    if sport == "nhl":
        return {
            "goals": 6.0,
            "assists": 4.0,
            "shots_on_goal": 0.9,
            "blocked_shots": 1.0,
            "saves": 0.2,
            "wins": 6.0,
            "shutouts": 4.0,
        }
    return {}


def _calculate_generic_sport_points(stats: Dict, sport: str) -> float:
    weights = _sport_stat_weights(sport)
    total = 0.0
    for stat_name, weight in weights.items():
        total += float(stats.get(stat_name, 0) or 0) * weight
    return round(total, 2)


def _calculate_generic_sport_delta(
    old_stats: Dict, new_stats: Dict, sport: str
) -> Dict:
    previous_points = _calculate_generic_sport_points(old_stats, sport)
    current_points = _calculate_generic_sport_points(new_stats, sport)
    points_delta = round(current_points - previous_points, 2)

    breakdown_delta = {}
    for stat_name, weight in _sport_stat_weights(sport).items():
        old_val = float(old_stats.get(stat_name, 0) or 0)
        new_val = float(new_stats.get(stat_name, 0) or 0)
        breakdown_delta[stat_name] = round((new_val - old_val) * weight, 2)

    breakdown_delta["total"] = points_delta
    return {
        "previous_points": previous_points,
        "current_points": current_points,
        "points_delta": points_delta,
        "breakdown_delta": breakdown_delta,
        "significant_change": abs(points_delta) >= 0.5,
    }


# Convenience functions for common use cases


def calculate_fantasy_points(
    stats: Dict,
    format: str = "ppr",
    sport: str = "nfl",
    **scoring_overrides,
) -> float:
    """Quick function to calculate fantasy points from a stats dictionary.

    Args:
        stats: Dictionary with player statistics
        format: Scoring format ("ppr", "half_ppr", "standard")
        **scoring_overrides: Optional scoring rule overrides

    Returns:
        Total fantasy points
    """
    if sport and sport.lower() != "nfl":
        return _calculate_generic_sport_points(stats, sport.lower())

    player_stats = PlayerStats.from_dict(stats)
    scoring_format = ScoringFormat(format.lower())
    calculator = FantasyScoringCalculator(**scoring_overrides)
    return calculator.calculate_points(player_stats, scoring_format)


def calculate_fantasy_delta(
    old_stats: Dict,
    new_stats: Dict,
    format: str = "ppr",
    sport: str = "nfl",
    **scoring_overrides,
) -> Dict:
    """Quick function to calculate fantasy points delta.

    Args:
        old_stats: Previous player statistics dictionary
        new_stats: Updated player statistics dictionary
        format: Scoring format
        **scoring_overrides: Optional scoring rule overrides

    Returns:
        Delta information dictionary
    """
    if sport and sport.lower() != "nfl":
        return _calculate_generic_sport_delta(old_stats, new_stats, sport.lower())

    old_player_stats = PlayerStats.from_dict(old_stats)
    new_player_stats = PlayerStats.from_dict(new_stats)
    scoring_format = ScoringFormat(format.lower())
    calculator = FantasyScoringCalculator(**scoring_overrides)
    return calculator.calculate_delta(
        old_player_stats, new_player_stats, scoring_format
    )


# FantasyPros-specific signal generation


def generate_start_sit_signal(
    delta: Dict, player_projected_points: float, threshold_percent: float = 0.15
) -> Optional[str]:
    """Generate start/sit signal based on performance vs projection.

    Args:
        delta: Fantasy points delta from calculate_fantasy_delta
        player_projected_points: Pre-game projected fantasy points
        threshold_percent: Percentage threshold for signal generation (default 15%)

    Returns:
        Signal string or None if no significant signal
    """
    if not player_projected_points:
        return None

    current_points = delta["current_points"]
    variance = (current_points - player_projected_points) / player_projected_points

    if variance >= threshold_percent:
        return f"EXCEEDING PROJECTION (+{variance:.1%}) - Strong START"
    elif variance <= -threshold_percent:
        return f"BELOW PROJECTION ({variance:.1%}) - Consider alternatives"

    return None


def format_fantasy_update(
    player_name: str,
    delta: Dict,
    format: str = "ppr",
    projected_points: Optional[float] = None,
) -> str:
    """Format a fantasy points update for display.

    Args:
        player_name: Player name
        delta: Fantasy delta dictionary
        format: Scoring format
        projected_points: Optional projection for context

    Returns:
        Formatted update string
    """
    points_delta = delta["points_delta"]
    current = delta["current_points"]

    emoji = "📈" if points_delta > 0 else "📉" if points_delta < 0 else "➡️"

    update = f"{emoji} {player_name}: {current:.1f} pts"

    if points_delta != 0:
        sign = "+" if points_delta > 0 else ""
        update += f" ({sign}{points_delta:.1f})"

    if projected_points:
        variance = current - projected_points
        if variance > 0:
            update += f" | vs proj +{variance:.1f} ✅"
        elif variance < 0:
            update += f" | vs proj {variance:.1f} ⚠️"

    return update
