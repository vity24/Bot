"""Battle engine for hockey matches."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import List, Dict, Tuple

CURRENT_YEAR = 2024

RARITY_MULTIPLIER = {
    "common": 1.0,
    "rare": 1.05,
    "epic": 1.1,
    "legendary": 1.2,
}

TACTIC_MODIFIERS = {
    "aggressive": {"attack": 1.1, "defense": 0.9, "penalty": 1.3},
    "defensive": {"attack": 0.9, "defense": 1.1, "penalty": 1.0},
    "balanced": {"attack": 1.0, "defense": 1.0, "penalty": 1.0},
}

class BattleSession:
    def __init__(self, team1: List[Dict], team2: List[Dict], tactic1: str = "balanced", tactic2: str = "balanced", name1: str = "team1", name2: str = "team2"):
        self.team1 = [p.copy() for p in team1]
        self.team2 = [p.copy() for p in team2]
        self.tactic1 = tactic1 if tactic1 in TACTIC_MODIFIERS else "balanced"
        self.tactic2 = tactic2 if tactic2 in TACTIC_MODIFIERS else "balanced"
        self.name1 = name1
        self.name2 = name2
        self.log: List[str] = []
        self.score = {"team1": 0, "team2": 0}
        self.contribution = defaultdict(int)
        ids1 = {p["id"] for p in self.team1}
        ids2 = {p["id"] for p in self.team2}
        if ids1 & ids2:
            raise ValueError("Один или несколько игроков используются в обеих командах.")
        self._prepare_players(self.team1)
        self._prepare_players(self.team2)

    @staticmethod
    def _age(player: Dict) -> int:
        try:
            return CURRENT_YEAR - int(player.get("born", CURRENT_YEAR))
        except ValueError:
            return 30

    @staticmethod
    def _weight(player: Dict) -> int:
        w = str(player.get("weight", "0"))
        digits = "".join(c for c in w if c.isdigit())
        try:
            return int(digits)
        except ValueError:
            return 80

    def _prepare_players(self, team: List[Dict]):
        country_count = defaultdict(int)
        for p in team:
            country = p.get("country")
            if country:
                country_count[country] += 1
        for p in team:
            p["strength"] = self.effective_strength(p, country_count)
            p["tech"] = min(1.0, 0.5 + p["strength"] / 120)
            p["injured"] = False
            p["penalty"] = 0

    def effective_strength(self, player: Dict, country_count: Dict[str, int]) -> float:
        strength = float(player.get("points", 50))
        rarity = player.get("rarity", "common")
        strength *= RARITY_MULTIPLIER.get(rarity, 1.0)
        # fatigue by age and weight
        age = self._age(player)
        weight = self._weight(player)
        fatigue_mult = max(0.85, 1.0 - (age - 25) * 0.005 - (weight - 85) * 0.001)
        strength *= fatigue_mult
        strength *= random.uniform(0.95, 1.05)  # form
        if country_count.get(player.get("country"), 0) >= 3:
            strength *= 1.05
        return strength

    def _team_power(self, team: List[Dict], key: str) -> float:
        return sum(p["strength"] for p in team if not p["injured"] and p.get("pos", "").startswith(key))

    def _attackers(self, team: List[Dict]) -> List[Dict]:
        return [p for p in team if not p["injured"] and p.get("pos", "G") != "G"]

    def _goalie(self, team: List[Dict]) -> Dict:
        goalies = [p for p in team if p.get("pos") == "G" and not p["injured"]]
        return goalies[0] if goalies else random.choice(team)

    def _attempt_goal(self, attacker: Dict, goalie: Dict, attack_mod: float, defense_mod: float) -> bool:
        atk = attacker["strength"] * attack_mod
        df = goalie["strength"] * defense_mod
        chance = atk / (atk + df)
        return random.random() < chance

    def _apply_fatigue(self, team: List[Dict]):
        for p in team:
            p["strength"] *= random.uniform(0.97, 1.0)

    def _shootout(self, team1: List[Dict], team2: List[Dict]):
        shooters1 = [p for p in team1 if p.get("pos") != "G" and not p["injured"]]
        shooters2 = [p for p in team2 if p.get("pos") != "G" and not p["injured"]]
        random.shuffle(shooters1)
        random.shuffle(shooters2)
        shooters1 = shooters1[:3]
        shooters2 = shooters2[:3]
        g1 = self._goalie(team1)
        g2 = self._goalie(team2)
        for i in range(3):
            if i < len(shooters1):
                p = shooters1[i]
                success = random.random() < p["tech"] * 0.7
                if success:
                    self.score["team1"] += 1
                    self.contribution[p["name"]] += 1
                    self.log.append(f"Буллит: {p['name']} забивает")
                else:
                    self.log.append(f"Буллит: {p['name']} промахивается")
            if i < len(shooters2):
                p = shooters2[i]
                success = random.random() < p["tech"] * 0.7
                if success:
                    self.score["team2"] += 1
                    self.contribution[p["name"]] += 1
                    self.log.append(f"Буллит: {p['name']} забивает")
                else:
                    self.log.append(f"Буллит: {p['name']} промахивается")

    def simulate(self) -> Dict:
        attack_mod1 = TACTIC_MODIFIERS[self.tactic1]["attack"]
        defense_mod1 = TACTIC_MODIFIERS[self.tactic1]["defense"]
        attack_mod2 = TACTIC_MODIFIERS[self.tactic2]["attack"]
        defense_mod2 = TACTIC_MODIFIERS[self.tactic2]["defense"]
        penalty1 = TACTIC_MODIFIERS[self.tactic1]["penalty"]
        penalty2 = TACTIC_MODIFIERS[self.tactic2]["penalty"]

        for period in range(1, 4):
            self.log.append(f"--- Период {period} ---")
            for _ in range(5):
                # team1 attack
                attacker_team1 = random.choice(self._attackers(self.team1))
                goalie_team2 = self._goalie(self.team2)
                if random.random() < 0.02:
                    attacker_team1["injured"] = True
                    self.log.append(f"Травма: {attacker_team1['name']} покидает матч")
                elif attacker_team1["strength"] < 25 and random.random() < 0.1 * penalty1:
                    self.log.append(f"Удаление: {attacker_team1['name']} (team1)")
                else:
                    if self._attempt_goal(attacker_team1, goalie_team2, attack_mod1, defense_mod2):
                        self.score["team1"] += 1
                        self.contribution[attacker_team1["name"]] += 1
                        self.log.append(f"Гол: {attacker_team1['name']} (team1)")
                    else:
                        self.contribution[goalie_team2["name"]] += 1
                        self.log.append(f"Сейв: {goalie_team2['name']} (team2)")
                # team2 attack
                attacker_team2 = random.choice(self._attackers(self.team2))
                goalie_team1 = self._goalie(self.team1)
                if random.random() < 0.02:
                    attacker_team2["injured"] = True
                    self.log.append(f"Травма: {attacker_team2['name']} покидает матч")
                elif attacker_team2["strength"] < 25 and random.random() < 0.1 * penalty2:
                    self.log.append(f"Удаление: {attacker_team2['name']} (team2)")
                else:
                    if self._attempt_goal(attacker_team2, goalie_team1, attack_mod2, defense_mod1):
                        self.score["team2"] += 1
                        self.contribution[attacker_team2["name"]] += 1
                        self.log.append(f"Гол: {attacker_team2['name']} (team2)")
                    else:
                        self.contribution[goalie_team1["name"]] += 1
                        self.log.append(f"Сейв: {goalie_team1['name']} (team1)")
            self._apply_fatigue(self.team1)
            self._apply_fatigue(self.team2)

        if self.score["team1"] == self.score["team2"]:
            self.log.append("Ничья, серия буллитов")
            self._shootout(self.team1, self.team2)

        if self.score["team1"] > self.score["team2"]:
            winner = "team1"
        elif self.score["team2"] > self.score["team1"]:
            winner = "team2"
        else:
            winner = "draw"

        mvp = max(self.contribution.items(), key=lambda x: x[1])[0] if self.contribution else ""
        self.log.append(f"Финальный счёт: {self.score['team1']} - {self.score['team2']}")
        if winner == "team1":
            self.log.append(f"Победа {self.name1}")
        elif winner == "team2":
            self.log.append(f"Победа {self.name2}")
        else:
            self.log.append("Ничья")
        return {
            "winner": winner,
            "score": self.score,
            "log": self.log,
            "mvp": mvp,
        }
