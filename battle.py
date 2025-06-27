"""Battle engine for hockey matches."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import List, Dict

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

# --- визуальные элементы для логов ---
RARITY_EMOJI = {
    "legendary": "⭐️",
    "mythic": "🟥",
    "epic": "💎",
    "rare": "🔵",
    "common": "🟢",
}

POSITION_EMOJI = {
    "G": "🧤",
    "F": "🏒",
    "D": "🛡️",
}

TEAM_EMOJI = {"team1": "🟦", "team2": "🟥"}

GOAL_ACTIONS = [
    "забивает!",
    "шайба в сетке!",
    "поражает ворота!",
    "прошивает вратаря!",
    "оформляет гол!",
    "мощный бросок в цель!",
]

SAVE_ACTIONS = [
    "отражает бросок!",
    "спасает свою команду!",
    "делает шикарный сейв!",
    "вратарь фиксирует шайбу!",
    "потрясающий сейв!",
    "молниеносная реакция!",
]

MISS_ACTIONS = [
    "❌ промахивается...",
    "не попадает по воротам...",
    "шайба проходит мимо ворот...",
    "мимо цели.",
    "не удалось точно бросить.",
]

PENALTY_ACTIONS = [
    "отправляется на штрафной бокс.",
    "нарушает правила и удаляется.",
    "удаляется за грубость.",
    "получает 2 минуты штрафа.",
    "отправляется отдыхать на скамейку штрафников.",
]

INJURY_ACTIONS = [
    "получает травму и покидает матч.",
    "не может продолжить игру.",
    "получает болезненный удар.",
    "травмирован и уходит со льда.",
    "врачи оказывают помощь.",
]

POST_ACTIONS = [
    "попадает в штангу!",
    "шайба звенит о перекладину!",
    "только штанга спасает!",
]

BLOCK_ACTIONS = [
    "блокирует бросок!",
    "отважно ставит клюшку под шайбу!",
    "перекрывает бросок соперника!",
]

FIGHT_ACTIONS = [
    "вступает в драку!",
    "устраивает потасовку на льду!",
    "бросает перчатки и дерётся!",
]


class BattleSession:
    def __init__(self, team1: List[Dict], team2: List[Dict], tactic1: str = "balanced", tactic2: str = "balanced", name1: str = "team1", name2: str = "team2"):
        self.team1 = [p.copy() for p in team1]
        self.team2 = [p.copy() for p in team2]
        self.tactic1 = tactic1 if tactic1 in TACTIC_MODIFIERS else "balanced"
        self.tactic2 = tactic2 if tactic2 in TACTIC_MODIFIERS else "balanced"
        self.name1 = name1
        self.name2 = name2
        self.log: List[str] = []
        self.events: List[Dict] = []  # store structured events for premium logs
        self.goals: List[Dict] = []  # track goal scorers for telecast-style logs
        self.score = {"team1": 0, "team2": 0}
        self.contribution = defaultdict(int)
        self._prepare_players(self.team1)
        self._prepare_players(self.team2)
        self.avg_power1 = sum(p["strength"] for p in self.team1) / len(self.team1)
        self.avg_power2 = sum(p["strength"] for p in self.team2) / len(self.team2)
        self.str_gap = (self.avg_power2 - self.avg_power1) / max(self.avg_power1, 1)
        self.current_period = 0

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
        lv_bonus = 1 + (player.get("owner_level", 1) // 5) * 0.02
        strength *= lv_bonus
        return strength

    def _team_power(self, team: List[Dict], key: str) -> float:
        return sum(p["strength"] for p in team if not p["injured"] and p.get("pos", "").startswith(key))

    def _attackers(self, team: List[Dict]) -> List[Dict]:
        return [p for p in team if not p["injured"] and p.get("pos", "G") != "G"]

    def _goalie(self, team: List[Dict]) -> Dict:
        goalies = [p for p in team if p.get("pos") == "G" and not p["injured"]]
        return goalies[0] if goalies else random.choice(team)

    def _defender(self, team: List[Dict]) -> Dict:
        defenders = [p for p in team if not p["injured"] and p.get("pos") != "G"]
        return random.choice(defenders) if defenders else self._goalie(team)

    def _pos_icon(self, player: Dict) -> str:
        pos = (player.get("pos") or "").upper()
        if pos.startswith("G"):
            return POSITION_EMOJI["G"]
        if pos.startswith("D"):
            return POSITION_EMOJI["D"]
        return POSITION_EMOJI["F"]

    def _format_player(self, player: Dict) -> str:
        rarity = RARITY_EMOJI.get(player.get("rarity", "common"), "")
        return f"{self._pos_icon(player)} {rarity} <b>{player['name']}</b>"

    def _team_prefix(self, idx: int) -> str:
        name = self.name1 if idx == 1 else self.name2
        emoji = TEAM_EMOJI["team1"] if idx == 1 else TEAM_EMOJI["team2"]
        return f"{emoji} {name}"

    def _log_action(self, idx: int, player: Dict, action: str, event_type: str = "action") -> None:
        """Append a formatted log line and record a structured event."""
        special = player.get("strength", 0) > 90
        prefix = self._team_prefix(idx)
        info = self._format_player(player)
        if special:
            line = f"{prefix} | 💥 ЗВЁЗДА МАТЧА! {info} {action}"
        else:
            line = f"{prefix} | {info} {action}"
        self.log.append(line)
        self.events.append({
            "team": self.name1 if idx == 1 else self.name2,
            "player": player.get("name"),
            "type": event_type,
            "text": line,
            "period": self.current_period,
        })

    def _attempt_goal(self, attacker: Dict, goalie: Dict, attack_mod: float, defense_mod: float) -> bool:
        atk = attacker["strength"] * attack_mod
        df = goalie["strength"] * defense_mod
        chance = atk / (atk + df)
        return random.random() < chance

    def _apply_fatigue(self, team: List[Dict]):
        for p in team:
            p["strength"] *= random.uniform(0.97, 1.0)

    def _simulate_period(self, attack_mod1: float, defense_mod1: float,
                         attack_mod2: float, defense_mod2: float,
                         penalty1: float, penalty2: float) -> None:
        """Run one period of the match."""
        for _ in range(5):
            attacker_team1 = random.choice(self._attackers(self.team1))
            goalie_team2 = self._goalie(self.team2)
            if random.random() < 0.02:
                attacker_team1["injured"] = True
                self._log_action(1, attacker_team1, random.choice(INJURY_ACTIONS), "injury")
            elif attacker_team1["strength"] < 25 and random.random() < 0.1 * penalty1:
                self._log_action(1, attacker_team1, random.choice(PENALTY_ACTIONS), "penalty")
            elif random.random() < 0.01:
                self._log_action(1, attacker_team1, random.choice(FIGHT_ACTIONS), "fight")
            else:
                if self._attempt_goal(attacker_team1, goalie_team2, attack_mod1, defense_mod2):
                    self.score["team1"] += 1
                    self.contribution[attacker_team1["name"]] += 1
                    self.goals.append({"player": attacker_team1["name"], "team": self.name1, "period": self.current_period})
                    self._log_action(1, attacker_team1, random.choice(GOAL_ACTIONS), "goal")
                else:
                    self.contribution[goalie_team2["name"]] += 1
                    r = random.random()
                    if r < 0.1:
                        self._log_action(1, attacker_team1, random.choice(POST_ACTIONS), "post")
                    elif r < 0.35:
                        defender = self._defender(self.team2)
                        self._log_action(2, defender, random.choice(BLOCK_ACTIONS), "block")
                    elif r < 0.55:
                        self._log_action(1, attacker_team1, random.choice(MISS_ACTIONS), "miss")
                    else:
                        self._log_action(2, goalie_team2, random.choice(SAVE_ACTIONS), "save")

            attacker_team2 = random.choice(self._attackers(self.team2))
            goalie_team1 = self._goalie(self.team1)
            if random.random() < 0.02:
                attacker_team2["injured"] = True
                self._log_action(2, attacker_team2, random.choice(INJURY_ACTIONS), "injury")
            elif attacker_team2["strength"] < 25 and random.random() < 0.1 * penalty2:
                self._log_action(2, attacker_team2, random.choice(PENALTY_ACTIONS), "penalty")
            elif random.random() < 0.01:
                self._log_action(2, attacker_team2, random.choice(FIGHT_ACTIONS), "fight")
            else:
                if self._attempt_goal(attacker_team2, goalie_team1, attack_mod2, defense_mod1):
                    self.score["team2"] += 1
                    self.contribution[attacker_team2["name"]] += 1
                    self.goals.append({"player": attacker_team2["name"], "team": self.name2, "period": self.current_period})
                    self._log_action(2, attacker_team2, random.choice(GOAL_ACTIONS), "goal")
                else:
                    self.contribution[goalie_team1["name"]] += 1
                    r = random.random()
                    if r < 0.1:
                        self._log_action(2, attacker_team2, random.choice(POST_ACTIONS), "post")
                    elif r < 0.35:
                        defender = self._defender(self.team1)
                        self._log_action(1, defender, random.choice(BLOCK_ACTIONS), "block")
                    elif r < 0.55:
                        self._log_action(2, attacker_team2, random.choice(MISS_ACTIONS), "miss")
                    else:
                        self._log_action(1, goalie_team1, random.choice(SAVE_ACTIONS), "save")

        self._apply_fatigue(self.team1)
        self._apply_fatigue(self.team2)

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
                    self.goals.append({"player": p["name"], "team": self.name1, "period": self.current_period})
                    self._log_action(1, p, "буллит реализует", "goal")
                else:
                    self._log_action(1, p, "буллит не забивает", "miss")
            if i < len(shooters2):
                p = shooters2[i]
                success = random.random() < p["tech"] * 0.7
                if success:
                    self.score["team2"] += 1
                    self.contribution[p["name"]] += 1
                    self.goals.append({"player": p["name"], "team": self.name2, "period": self.current_period})
                    self._log_action(2, p, "буллит реализует", "goal")
                else:
                    self._log_action(2, p, "буллит не забивает", "miss")

    def play_period(self, tactic1: str | None = None, tactic2: str | None = None) -> None:
        """Simulate a single period with optional tactic overrides."""
        if tactic1:
            self.tactic1 = tactic1 if tactic1 in TACTIC_MODIFIERS else self.tactic1
        if tactic2:
            self.tactic2 = tactic2 if tactic2 in TACTIC_MODIFIERS else self.tactic2

        self.current_period += 1
        self.log.append(f"📖 --- {self.current_period} Период ---")

        attack_mod1 = TACTIC_MODIFIERS[self.tactic1]["attack"]
        defense_mod1 = TACTIC_MODIFIERS[self.tactic1]["defense"]
        attack_mod2 = TACTIC_MODIFIERS[self.tactic2]["attack"]
        defense_mod2 = TACTIC_MODIFIERS[self.tactic2]["defense"]
        penalty1 = TACTIC_MODIFIERS[self.tactic1]["penalty"]
        penalty2 = TACTIC_MODIFIERS[self.tactic2]["penalty"]

        self._simulate_period(attack_mod1, defense_mod1, attack_mod2, defense_mod2, penalty1, penalty2)

    def play_overtime(self, tactic1: str, tactic2: str) -> bool:
        """Run overtime. Return True if a goal was scored."""
        if tactic1:
            self.tactic1 = tactic1 if tactic1 in TACTIC_MODIFIERS else self.tactic1
        if tactic2:
            self.tactic2 = tactic2 if tactic2 in TACTIC_MODIFIERS else self.tactic2

        self.log.append("⏱ Овертайм")
        # treat overtime as an additional period for event tracking
        self.current_period = 4

        attack_mod1 = TACTIC_MODIFIERS[self.tactic1]["attack"]
        defense_mod1 = TACTIC_MODIFIERS[self.tactic1]["defense"]
        attack_mod2 = TACTIC_MODIFIERS[self.tactic2]["attack"]
        defense_mod2 = TACTIC_MODIFIERS[self.tactic2]["defense"]
        penalty1 = TACTIC_MODIFIERS[self.tactic1]["penalty"]
        penalty2 = TACTIC_MODIFIERS[self.tactic2]["penalty"]

        before = self.score.copy()
        self._simulate_period(attack_mod1, defense_mod1, attack_mod2, defense_mod2, penalty1, penalty2)
        return self.score != before

    def shootout(self) -> None:
        self.log.append("Буллиты")
        # mark shootout as separate period for logs
        self.current_period = 5
        self._shootout(self.team1, self.team2)

    def finish(self) -> Dict:
        if self.score["team1"] > self.score["team2"]:
            winner = "team1"
        elif self.score["team2"] > self.score["team1"]:
            winner = "team2"
        else:
            winner = "draw"

        mvp = max(self.contribution.items(), key=lambda x: x[1])[0] if self.contribution else ""
        return {
            "winner": winner,
            "score": self.score,
            "log": self.log,
            "mvp": mvp,
            "str_gap": self.str_gap,
        }

    def simulate(self) -> Dict:
        """Run a full match using :class:`BattleController`."""
        controller = BattleController(self)
        return controller.auto_play()


class BattleController:
    """Controller that manages battle phases for step-by-step matches."""

    def __init__(self, session: BattleSession) -> None:
        self.session = session
        self.phase = "p1"

    def step(self, tactic1: str, tactic2: str) -> None:
        if self.phase == "p1":
            self.session.play_period(tactic1, tactic2)
            self.phase = "p2"
        elif self.phase == "p2":
            self.session.play_period(tactic1, tactic2)
            self.phase = "p3"
        elif self.phase == "p3":
            self.session.play_period(tactic1, tactic2)
            if self.session.score["team1"] == self.session.score["team2"]:
                self.phase = "ot"
            else:
                self.phase = "end"
        elif self.phase == "ot":
            goal = self.session.play_overtime(tactic1, tactic2)
            if not goal:
                self.session.log.append("⛔️ Никто не забил. Буллиты.")
                self.session.shootout()
            self.phase = "end"

    def auto_play(self) -> Dict:
        while self.phase != "end":
            self.step(self.session.tactic1, self.session.tactic2)
        return self.session.finish()
