from dataclasses import dataclass
from typing import Self, Iterable
from json import load

import base64
from pathlib import Path

from streamlit.delta_generator import DeltaGenerator
import streamlit as st

REWARD_IMAGES: dict[str, str] = {
    "cash": "images/cash.png",
    "ceram": "images/ceramic.png",
    "cf_frag": "images/TokenGreen.png",
    "epic_frag": "images/TokenBlue.png",
}
CHAPTER_IMAGES: list[str] = [
    "images/Bronze4.png",
    "images/Bronze3.png",
    "images/Bronze2.png",
    "images/Bronze1.png",
    "images/Silver4.png",
    "images/Silver3.png",
    "images/Silver2.png",
    "images/Silver1.png",
    "images/Gold4.png",
]

CHAPTER_ICON_HEIGHT_PX = 140
CHAPTER_ADDITIONAL_HEIGHT = 52
DISABLE_ICON_GREYSCALE = 0.2
DISABLE_ICON_OPACITY = 0.3

CHAPTER_NAMES = [
    medal + "_" + tier
    for medal in ["Bronze", "Silver"]
    for tier in ["IV", "III", "II", "I"]
] + ["Frontier"]
DEFAULT_CHAPTER_ON_STATES = [
    True,
    False,
    False,
    False,
    False,
    True,
    True,
    True,
    True,
]


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
    max_frontier: int
    min_chapter: int = 0

    def max_rnds(self, chapter: int) -> int:
        return len(self.cdata.costs[chapter])

    def step(self) -> list[State]:
        new_states: list[State] = []
        for chapter in range(self.min_chapter, len(self.progress)):
            if not self.access[chapter]:
                continue

            rnd = self.progress[chapter]
            if rnd == self.max_rnds(chapter):
                continue

            rnd_cost = self.cdata.costs[chapter][rnd]
            if self.nflags < rnd_cost:
                continue

            if is_frontier(chapter) and rnd >= self.max_frontier:
                continue

            new_progress = list(self.progress)
            new_progress[chapter] += 1
            new_access = list(self.access)
            if new_progress[chapter] == self.max_rnds(chapter) and not is_frontier(
                chapter
            ):
                new_access[chapter + 1] = True

            new_states.append(
                State(
                    nflags=self.nflags - rnd_cost,
                    progress=tuple(new_progress),
                    access=tuple(new_access),
                    reward=self.reward + self.cdata.rewards[chapter][rnd],
                    cdata=self.cdata,
                    max_frontier=self.max_frontier,
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


def is_frontier(chapter: int) -> bool:
    return chapter >= len(CHAPTER_NAMES) - 1


def outcomes(
    nflags: int,
    progress: Iterable[int],
    access: Iterable[bool],
    max_frontier: int,
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
            max_frontier=max_frontier,
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


@st.cache_data
def b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def previous_chapter_complete(chapter: int) -> bool:
    if chapter == 0:
        return True
    if chapter >= len(CHAPTER_NAMES):
        return False
    prev_chap_name = CHAPTER_NAMES[chapter - 1]
    prev_chap_progress = st.session_state.get(f"num_{prev_chap_name}", 0)
    return prev_chap_progress == 5


def chapter_card(container: DeltaGenerator, chapter: int) -> bool:
    chapter_name = CHAPTER_NAMES[chapter]
    on_key = f"on_{chapter_name}"
    st.session_state.setdefault(on_key, DEFAULT_CHAPTER_ON_STATES[chapter])

    if previous_chapter_complete(chapter):
        st.session_state[on_key] = True

    on = st.session_state[on_key]
    container.markdown(
        f"""
        <style>
        .st-key-btn_{chapter_name} button {{
            background-image: url(data:image/png;base64,{b64(CHAPTER_IMAGES[chapter])});
            background-size: contain; background-repeat: no-repeat;
            background-position: center; height: {CHAPTER_ICON_HEIGHT_PX}px;
            filter: {"none" if on else f"grayscale({DISABLE_ICON_GREYSCALE}) opacity({DISABLE_ICON_OPACITY})"};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    container.markdown(
        f"<div style='text-align:center; font-size:1.2rem'>{chapter_name.replace("_", " ")}</div>",
        unsafe_allow_html=True,
    )

    if container.button(" ", key=f"btn_{chapter_name}", use_container_width=True):
        # No need to check previous chapter since it is enforced above
        st.session_state[on_key] = not on
        st.rerun()

    container.number_input(
        label=chapter_name.replace("_", " "),
        min_value=0,
        max_value=25 if is_frontier(chapter) else 5,
        value=0 if chapter < 6 else 5,
        step=1,
        key=f"num_{chapter_name}",
        label_visibility="collapsed",
        disabled=not on,
    )
    return on


# TODO: Replace icons
def display_outcome(state: State, start_prog: list[int], idx: int) -> None:
    with st.container(border=True):
        # st.markdown(
        #     f"""
        #     <style>
        #     .st-key-metric_epic [data-testid="stMetricValue"] p::after {{
        #         content: "";
        #         display: inline-block;
        #         width: 1em; height: 1em;
        #         margin-left: 0.1em;
        #         vertical-align: middle;
        #         position: relative;
        #         top: -0.08em;
        #         background: url(data:image/png;base64,{b64(REWARD_IMAGES["epic_frag"])}) center / contain no-repeat;
        #     }}
        #     </style>
        #     """,
        #     unsafe_allow_html=True,
        # )

        cols = st.columns([6, 4, 4, 4, 6])
        cols[0].metric(
            ":material/local_atm: Cash Equivalent", state.reward.total_cash_equivalent()
        )
        with cols[1].container(key=f"metric_epic_frag_{idx}"):
            st.metric("Epic Tokens", state.reward.epic_frag)
        with cols[2].container(key=f"metric_cf_frag_{idx}"):
            st.metric("CF Tokens", state.reward.cf_frag)
        with cols[3].container(key=f"metric_ceram_{idx}"):
            st.metric("Ceramics", state.reward.ceram)
        with cols[4].container(key=f"metric_cash_{idx}"):
            st.metric("Cash", state.reward.cash)
        cols = st.columns(9)
        for chapter in range(9):
            delta = state.progress[chapter] - start_prog[chapter]
            cols[chapter].metric(
                CHAPTER_NAMES[chapter].replace("_", " "),
                state.progress[chapter],
                delta if delta else None,
            )


# TODO: Add a note that this is intended to maximize remaining flags and that maximizing
#       access for the next season should be the highest priority


@st.dialog("How To Use")
def how_to() -> None:
    st.text("""
            Enter your current Challenge League progress by selecting which challenges are unlocked and how many rounds you have already beaten.
            
            Then, enter how many flags you have remaining for this season and you will get the optimal way to use the rest of your flags!
            
            Note that this should only be used near the end of a season; unlocking the higher challenges for next season should be your first priority.
            """)


@st.dialog("Additional Settings")
def additional_settings() -> None:
    left, right = st.columns(2)
    left.number_input(
        "Epic fragment value",
        min_value=0,
        value=180000,
        step=50,
        key="epic_frag_value",
        help="The cash equivalent value of an Epic fragment (5 fragments can be exchanged for an epic)",
    )
    right.number_input(
        "CF fragment value",
        min_value=0,
        value=42250,
        step=50,
        key="cf_frag_value",
        help="The cash equivalent value of a Carbon Fiber fragment (5 fragments can be exchanged for a CF)",
    )
    st.number_input(
        "Number of results to display",
        min_value=1,
        max_value=10,
        value=1,
        step=1,
        key="num_displayed_results",
        help="Controls how many of the top results to display",
    )


left, right = st.columns(2)
if left.button(label="How To Use", icon=":material/info:", use_container_width=True):
    how_to()

if right.button(
    label="Additional Settings", icon=":material/settings:", use_container_width=True
):
    additional_settings()


with st.container(border=True):
    cols = st.columns([4, 3], vertical_alignment="bottom")
    cols[0].subheader("Challenge League Progress")
    # TODO: Add presets
    # cols[1].button(label="Preset: Blank")

    cols = st.columns(4)
    for i in range(8):
        chapter_card(cols[i % 4], chapter=i)

    cols = st.columns([1, 3], vertical_alignment="top")
    chapter_card(cols[0], chapter=8)
    cols[1].space(CHAPTER_ICON_HEIGHT_PX + CHAPTER_ADDITIONAL_HEIGHT)
    cols[1].toggle(
        label="Limit Frontier to 5 tickets?",
        value=False,
        key="tog_frontier",
        help="Limits solutions to 5 frontier rounds if there is only one day left in the season",
    )
    st.divider()

    _, center_col, _ = st.columns([1, 2, 1])

    center_col.number_input(
        "Flags Remaining", min_value=0, step=1, key="flags_remaining"
    )

    if center_col.button(
        "Calculate!", type="primary", use_container_width=True, key="btn_calc"
    ):
        progress = [
            st.session_state[f"num_{chapter_name}"] for chapter_name in CHAPTER_NAMES
        ]
        access = [
            st.session_state[f"on_{chapter_name}"] for chapter_name in CHAPTER_NAMES
        ]
        max_frontier = (
            progress[-1] + 5 if st.session_state.get("tog_frontier", False) else 25
        )
        results = outcomes(
            nflags=st.session_state.get("flags_remaining", 0),
            progress=progress,
            access=access,
            max_frontier=max_frontier,
        )
        for i in range(st.session_state.get("num_displayed_results", 1)):
            display_outcome(results[i], progress, i + 1)

st.markdown(
    """
    <style>
    .st-key-flags_remaining input {
        font-size: 1.3rem;
        font-weight: 600;
        text-align: center;
    }
    .st-key-flags_remaining [data-testid="stWidgetLabel"] {
        width: 100%;
        justify-content: center;
    }
    .st-key-flags_remaining label p {
        font-size: 1.5rem;
        font-weight: 600;
    }
    .st-key-flags_remaining button {
        display: none;
    }
    [data-testid="stMarkdownContainer"] hr {
        margin: 0.5rem 0;
    }
    .st-key-btn_calc button p {
        font-size: 1.3rem;
        font-weight: 600;
    }
    [data-testid="stMetricDelta"] {
        font-size: 1.1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

icon_rules = "".join(f"""
    [class*="st-key-metric_{name}"] [data-testid="stMetricValue"] p::after {{
        content: "";
        display: inline-block;
        width: 1em; height: 1em;
        margin-left: 0.1em;
        vertical-align: middle;
        position: relative; top: -0.08em;
        background: url(data:image/png;base64,{b64(REWARD_IMAGES[name])}) center / contain no-repeat;
    }}""" for name in REWARD_IMAGES)

st.markdown(f"<style>{icon_rules}</style>", unsafe_allow_html=True)

st.divider()
st.caption("Made with love by @CapSora")
st.caption("All game assets property of Hutch Games Ltd.")
st.caption("Special thanks to @TiagoXavi")
