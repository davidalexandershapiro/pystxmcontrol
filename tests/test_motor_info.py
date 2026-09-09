"""Tests for the dashboard's motor.json queries.

No Qt: these are the rules that decide which motors the user can see, group and
drive, checked against the config dictionary directly.

The visibility rules are the reason this file exists.  ``display`` gates the
scan-axis dropdowns in both modes, while the move/jog rail shows everything in
Staff mode — so a ``display: false`` motor can be jogged by staff but can never
be chosen as a scan axis.  Those two are easy to conflate when reading the
window code.
"""

import pytest

from pystxmcontrol.gui.dashboard import motor_info as mi


def motor(index=0, group="sample", display=True, driver="mclMotor",
          last=0.0, lo=-100.0, hi=100.0, unit="um", **extra):
    d = {"index": index, "group": group, "display": display, "driver": driver,
         "last value": last, "minValue": lo, "maxValue": hi, "unit": unit}
    d.update(extra)
    return d


# ── grouping ────────────────────────────────────────────────────────────────

def test_group_comes_from_the_group_field():
    assert mi.group_of({"group": "sample"}) == "sample"


def test_legacy_panel_field_still_groups():
    """Configs predating the rename still carry `panel`."""
    assert mi.group_of({"panel": "optics"}) == "optics"


def test_group_wins_over_the_legacy_field():
    assert mi.group_of({"group": "sample", "panel": "optics"}) == "sample"


def test_a_motor_with_no_group_lands_in_beamline():
    assert mi.group_of({}) == "beamline"
    assert mi.group_of({"group": "   "}) == "beamline"


def test_groups_are_ordered_by_their_lowest_index_motor():
    info = {
        "C": motor(index=2, group="optics"),
        "A": motor(index=0, group="sample"),
        "B": motor(index=1, group="optics"),
        "D": motor(index=3, group="sample"),
    }
    assert mi.motor_groups(info) == ["sample", "optics"]


def test_groups_are_listed_once_each():
    info = {"A": motor(index=0, group="s"), "B": motor(index=1, group="s")}
    assert mi.motor_groups(info) == ["s"]


# ── ordering ────────────────────────────────────────────────────────────────

def test_motors_are_index_ordered():
    info = {"C": motor(index=5), "A": motor(index=1), "B": motor(index=3)}
    assert [n for n, _ in mi.motors_sorted(info)] == ["A", "B", "C"]


def test_a_motor_without_an_index_sorts_last():
    info = {"noidx": {"driver": "x"}, "first": motor(index=1)}
    assert [n for n, _ in mi.motors_sorted(info)] == ["first", "noidx"]


# ── the two visibility rules ────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False),
    ("true", True), ("True", True), ("1", True), ("yes", True),
    ("false", False), ("no", False), ("", False),
])
def test_display_flag_accepts_the_string_forms_configs_use(value, expected):
    assert mi.is_visible({"display": value}) is expected


def test_a_motor_must_opt_in_to_be_visible():
    """Absent `display` means hidden, matching the classic GUI."""
    assert mi.is_visible({}) is False


def test_scan_axis_dropdowns_only_offer_display_motors():
    info = {"shown": motor(index=0, display=True),
            "hidden": motor(index=1, display=False)}
    assert [n for n, _ in mi.visible_motors(info)] == ["shown"]


def test_staff_mode_lists_every_motor_in_the_rail():
    info = {"shown": motor(index=0, group="s", display=True),
            "hidden": motor(index=1, group="s", display=False)}
    rows = mi.motor_rows(info, "s", expert=True)
    assert [r[0] for r in rows] == ["shown", "hidden"]


def test_user_mode_hides_undisplayed_motors_from_the_rail():
    info = {"shown": motor(index=0, group="s", display=True),
            "hidden": motor(index=1, group="s", display=False)}
    rows = mi.motor_rows(info, "s", expert=False)
    assert [r[0] for r in rows] == ["shown"]


def test_a_staff_only_motor_is_joggable_but_never_a_scan_axis():
    """The distinction the two rules exist for."""
    info = {"staff_only": motor(index=0, group="s", display=False)}
    assert [r[0] for r in mi.motor_rows(info, "s", expert=True)] == ["staff_only"]
    assert mi.visible_motors(info) == []


def test_rows_only_include_the_requested_group():
    info = {"a": motor(index=0, group="sample"),
            "b": motor(index=1, group="optics")}
    assert [r[0] for r in mi.motor_rows(info, "sample")] == ["a"]


def test_row_carries_the_driver_badge_and_unit():
    info = {"m": motor(driver="xpsMotor", unit="mm", last=12.5)}
    (name, kind, pos, unit, _frac, moving) = mi.motor_rows(info, "sample")[0]
    assert (name, kind, pos, unit, moving) == ("m", "XPS", "12.50", "mm", False)


def test_an_unknown_driver_falls_back_to_its_upper_cased_name():
    info = {"m": motor(driver="someNewDriver")}
    assert mi.motor_rows(info, "sample")[0][1] == "SOMENEWDRIVER"


# ── travel fraction ─────────────────────────────────────────────────────────

def test_travel_fraction_maps_the_range_to_zero_one():
    assert mi.frac(0.0, -100.0, 100.0) == pytest.approx(0.5)
    assert mi.frac(-100.0, -100.0, 100.0) == pytest.approx(0.0)
    assert mi.frac(100.0, -100.0, 100.0) == pytest.approx(1.0)


def test_travel_fraction_clamps_outside_the_limits():
    assert mi.frac(500.0, -100.0, 100.0) == pytest.approx(1.0)
    assert mi.frac(-500.0, -100.0, 100.0) == pytest.approx(0.0)


@pytest.mark.parametrize("lo,hi", [(0.0, 0.0), (None, 100.0), (0.0, None)])
def test_an_unusable_range_reads_as_mid_travel(lo, hi):
    """A zero-width or missing limit must not raise while painting a row."""
    assert mi.frac(5.0, lo, hi) == pytest.approx(0.5)


# ── jog step ────────────────────────────────────────────────────────────────

def test_jog_step_prefers_the_configured_scan_step():
    assert mi.jog_step({"last step:": 0.25}) == pytest.approx(0.25)


def test_jog_step_falls_back_to_one_percent_of_travel():
    assert mi.jog_step({"minValue": 0.0, "maxValue": 200.0}) == pytest.approx(2.0)


def test_jog_step_ignores_a_non_positive_configured_step():
    assert mi.jog_step({"last step:": 0.0, "minValue": 0.0,
                        "maxValue": 200.0}) == pytest.approx(2.0)


def test_jog_step_has_a_last_resort():
    assert mi.jog_step({}) == pytest.approx(1.0)
    assert mi.jog_step({"minValue": 5.0, "maxValue": 5.0}) == pytest.approx(1.0)


# ── enumerated values ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (1, "1"), (1.0, "1"), (3, "3"), (5.0, "5"),      # harmonics read as integers
    (0.5, "0.5"), (1.25, "1.25"),
    ("auto", "auto"), (None, "None"),
])
def test_enumerated_values_render_compactly(value, expected):
    assert mi.format_enum(value) == expected
