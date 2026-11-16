# from collections import deque
from dataclasses import dataclass
from typing import Self, Iterable
from json import load

import streamlit as st


@dataclass(frozen=True, slots=True)
class Reward:
    cash: int = 0
    ceram: int = 0
    cf_frag: int = 0
    epic_frag: int = 0

    def cash_ceram_value(self) -> int:
        return 32500 * self.ceram + self.cash

    def total_cash_equivalent(self) -> int:
        # Assumes that the session states are numeric values as set by st.number_input
        cf_value: int = int(st.session_state.get("cf_frag_value", 42250))
        epic_value: int = int(st.session_state.get("epic_frag_value", 180000))
        return (
            epic_value * self.epic_frag
            + cf_value * self.cf_frag
            + self.cash_ceram_value()
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.epic_frag, self.cf_frag, self.ceram, self.cash)

    def __lt__(self, other: Reward) -> bool:
        return self.total_cash_equivalent() < other.total_cash_equivalent()

    def __add__(self, other: Reward) -> Reward:
        return Reward(
            self.cash + other.cash,
            self.ceram + other.ceram,
            self.cf_frag + other.cf_frag,
            self.epic_frag + other.epic_frag,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class State:
    nflags: int
    progress: tuple[int, ...]
    access: tuple[bool, ...]
    reward: Reward
    cdata: ChallengeData
    min_chapter: int = 0

    def max_rnds(self, chapter: int) -> int:
        return len(self.cdata.costs[chapter])

    def is_frontier(self, chapter: int) -> bool:
        return chapter >= len(self.cdata.costs) - 1

    def step(self) -> list[State]:
        new_states: list[State] = []
        for chapter in range(self.min_chapter, len(self.progress)):
            if not self.access[chapter]:
                continue

            rnd = self.progress[chapter]
            if rnd == self.max_rnds(chapter) and not self.is_frontier(chapter):
                continue

            rnd_cost = self.cdata.costs[chapter][rnd]
            if self.nflags < rnd_cost:
                continue

            new_progress = list(self.progress)
            new_progress[chapter] += 1
            new_access = list(self.access)
            if new_progress[chapter] == self.max_rnds(chapter):
                new_access[chapter + 1] = True

            new_states.append(
                State(
                    nflags=self.nflags - rnd_cost,
                    progress=tuple(new_progress),
                    access=tuple(new_access),
                    reward=self.reward + self.cdata.rewards[chapter][rnd],
                    cdata=self.cdata,
                    min_chapter=max(self.min_chapter, chapter),
                )
            )

        return new_states


@dataclass(frozen=True, slots=True)
class ChallengeData:
    costs: tuple[tuple[int, ...], ...]
    rewards: tuple[tuple[Reward, ...], ...]

    @classmethod
    def from_flags(cls, flags: list[list[list[int]]]) -> Self:
        costs: list[tuple[int, ...]] = []
        rewards: list[tuple[Reward, ...]] = []
        for challenge in flags:
            chal_costs: list[int] = []
            chal_rewards: list[Reward] = []
            for rnd in challenge:
                cost, *reward = rnd
                chal_costs.append(cost)
                chal_rewards.append(Reward(*reward))
            costs.append(tuple(chal_costs))
            rewards.append(tuple(chal_rewards))
        return cls(tuple(costs), tuple(rewards))


def load_challenge_data(season_name: str) -> ChallengeData:
    with open("flags.json") as f:
        all_flags = load(f)
        try:
            # flags[chapter][round] = [cost, cash, ceram, cf_frag, epic_frag]
            flags: list[list[list[int]]] = all_flags[season_name]
        except KeyError:
            raise ValueError(f"Cannot find season '{season_name}'.") from None

    return ChallengeData.from_flags(flags)


def outcomes(
    nflags: int,
    progress: Iterable[int],
    access: Iterable[bool],
    season_name: str = "default",
):
    cdata = load_challenge_data(season_name)

    pending: list[State] = [
        State(
            nflags=nflags,
            progress=tuple(progress),
            access=tuple(access),
            reward=Reward(),
            cdata=cdata,
        )
    ]
    terminal: list[State] = []

    while pending:
        state = pending.pop()
        new_states = state.step()
        if new_states:
            pending.extend(new_states)
        else:
            terminal.append(state)

    def dominates(a: Reward, b: Reward) -> bool:
        return all(x >= y for x, y in zip(a.as_tuple(), b.as_tuple()))

    pareto_dominant: list[State] = []
    for s in sorted(terminal, key=lambda s: s.reward.as_tuple(), reverse=True):
        if not any(dominates(d.reward, s.reward) for d in pareto_dominant):
            pareto_dominant.append(s)

    return sorted(pareto_dominant, key=lambda s: s.reward, reverse=True)


def display_outcome(
    state: State,
    start_prog: list[int],
    all_chals: list[str],
) -> None:
    cols = st.columns([6, 4, 4, 4, 5])
    cols[0].metric(
        ":material/local_atm: Cash Equivalent", state.reward.total_cash_equivalent()
    )
    cols[1].metric(":material/token: Epic Tokens", state.reward.epic_frag)
    cols[2].metric(":material/token: CF Tokens", state.reward.cf_frag)
    cols[3].metric(":material/capture: Ceramics", state.reward.ceram)
    cols[4].metric(":material/local_atm: Cash", state.reward.cash)
    cols = st.columns(9)
    for chapter in range(9):
        delta = state.progress[chapter] - start_prog[chapter]
        cols[chapter].metric(
            all_chals[chapter], state.progress[chapter], delta if delta else None
        )


with st.expander("Cash Values", icon=":material/local_atm:"):
    col1, col2 = st.columns(2)
    col1.number_input(
        "Epic fragment value",
        min_value=0,
        value=180000,
        step=50,
        required=True,
        key="epic_frag_value",
    )
    col2.number_input(
        "CF fragment value",
        min_value=0,
        value=42250,
        step=50,
        required=True,
        key="cf_frag_value",
    )

# TODO: Remove form
# TODO: Enforce access toggle behaviour from previous challenge round
with st.form("options"):
    st.subheader("Challenge League Progress")
    st.text("")
    challenges = [
        medal + " " + tier
        for medal in ["Bronze", "Silver"]
        for tier in ["IV", "III", "II", "I"]
    ]
    cols = st.columns(2)
    for i in range(len(challenges)):
        cols[i % 2].segmented_control(
            challenges[i],
            options=["Locked"] + list(range(0, 6)),
            default="Locked",
            key=challenges[i],
        )
        cols[i % 2].text("")
    st.segmented_control(
        "Frontier",
        options=["Locked"] + list(range(0, 26)),
        default="Locked",
        key="Frontier",
    )
    st.text("")
    _, num_col, _ = st.columns([3, 2, 3])
    num_col.number_input("Flags remaining", min_value=0, step=1, key="flags_remaining")
    _, submit_col, _ = st.columns([3, 4, 3])
    if submit_col.form_submit_button(
        "Calculate!", type="primary", use_container_width=True
    ):
        all_chals = challenges + ["Frontier"]
        progress: list[int] = [
            0 if st.session_state[chal] == "Locked" else st.session_state[chal]
            for chal in all_chals
        ]
        access: list[bool] = [st.session_state[chal] != "Locked" for chal in all_chals]
        results = outcomes(
            nflags=st.session_state["flags_remaining"],
            progress=progress,
            access=access,
        )
        for i in range(5):
            with st.container(border=True):
                st.header(f"Result {i+1}")
                display_outcome(results[i], progress, all_chals)
