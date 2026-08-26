"""Tests for saved energy definitions (energy presets) and the multi-region scan path.

Covers the format helpers, preset discovery/resolution, and the conversion that carries a
multi-region definition — with its per-region dwells — through to the server's scan dict.
"""

import json

import pytest

from pystxmcontrol.controller import energy_presets as ep
from pystxmcontrol.controller import scan_conversion as sc
from pystxmcontrol.controller.scan_model import ScanModel


# ── fixtures ────────────────────────────────────────────────────────────────

TWO_REGIONS = {
    "EnergyRegion1": {"start": 280.0, "stop": 282.0, "step": 0.5,
                      "n_energies": 5, "dwell": 1.0},
    "EnergyRegion2": {"start": 284.0, "stop": 290.0, "step": 0.5,
                      "n_energies": 13, "dwell": 3.0},
}


@pytest.fixture
def preset_dirs(tmp_path, monkeypatch):
    """Point both preset sources at a temp directory.

    ``_CONFIG_DIRS`` is what ``favorites_file_path``/``presets_dir`` resolve against, so
    patching it redirects discovery without touching the real runtime config.  The
    environment overrides are cleared so a var set in the developer's shell (or by a
    container profile) cannot reach into these tests.
    """
    for var in (ep.CFG_DIR_ENV, ep.PRESETS_DIR_ENV, ep.FAVORITES_ENV):
        monkeypatch.delenv(var, raising=False)
    cfg = tmp_path / "pystxmcontrol_cfg"
    (cfg / ep.PRESETS_DIRNAME).mkdir(parents=True)
    monkeypatch.setattr(ep, "_CONFIG_DIRS", (str(cfg),))
    return cfg


def write_favorites(cfg, favorites):
    (cfg / ep.FAVORITES_BASENAME).write_text(json.dumps({"favorites": favorites}))


def write_preset_file(cfg, name, regions, wrapped=True):
    payload = {"energy_regions": regions} if wrapped else regions
    (cfg / ep.PRESETS_DIRNAME / f"{name}.json").write_text(json.dumps(payload))


# ── format ──────────────────────────────────────────────────────────────────

class TestReadAndNormalize:

    def test_reads_wrapped_and_bare(self, tmp_path):
        wrapped = tmp_path / "w.json"
        wrapped.write_text(json.dumps({"energy_regions": TWO_REGIONS}))
        bare = tmp_path / "b.json"
        bare.write_text(json.dumps(TWO_REGIONS))
        assert ep.read_energy_regions_json(str(wrapped)) == TWO_REGIONS
        assert ep.read_energy_regions_json(str(bare)) == TWO_REGIONS

    @pytest.mark.parametrize("content", ["not json at all", "[]", "{}",
                                         '{"energy_regions": {}}'])
    def test_unusable_files_return_none(self, tmp_path, content):
        p = tmp_path / "bad.json"
        p.write_text(content)
        assert ep.read_energy_regions_json(str(p)) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert ep.read_energy_regions_json(str(tmp_path / "nope.json")) is None

    def test_orders_regions_by_index_not_dict_order(self):
        out_of_order = {"EnergyRegion2": TWO_REGIONS["EnergyRegion2"],
                        "EnergyRegion1": TWO_REGIONS["EnergyRegion1"]}
        regions = ep.normalize_regions(out_of_order)
        assert [r["start"] for r in regions] == [280.0, 284.0]

    def test_derives_missing_step(self):
        regions = ep.normalize_regions(
            {"EnergyRegion1": {"start": 280.0, "stop": 282.0,
                               "n_energies": 5, "dwell": 1.0}})
        assert regions[0]["step"] == pytest.approx(0.5)

    def test_single_energy_region_has_zero_step(self):
        regions = ep.normalize_regions(
            {"EnergyRegion1": {"start": 700.0, "stop": 700.0,
                               "n_energies": 1, "dwell": 0.2}})
        assert regions[0]["step"] == 0.0

    @pytest.mark.parametrize("regions", [
        {},
        {"EnergyRegion1": "not a dict"},
        {"EnergyRegion1": {"stop": 282.0}},              # no start
        {"EnergyRegion1": {"start": "abc", "stop": 282.0}},
    ])
    def test_malformed_returns_none(self, regions):
        assert ep.normalize_regions(regions) is None

    def test_round_trips_through_regions_to_dict(self):
        regions = ep.normalize_regions(TWO_REGIONS)
        assert ep.normalize_regions(ep.regions_to_dict(regions)) == regions

    def test_total_energies_sums_regions(self):
        assert ep.total_energies(ep.normalize_regions(TWO_REGIONS)) == 18

    def test_summary_mentions_each_region_dwell(self):
        summary = ep.summarize_regions(ep.normalize_regions(TWO_REGIONS))
        assert "1 ms" in summary and "3 ms" in summary


# ── discovery ───────────────────────────────────────────────────────────────

class TestDiscovery:

    def test_finds_both_sources(self, preset_dirs):
        write_favorites(preset_dirs, [{"alias": "C 1s stack",
                                       "energy_regions": TWO_REGIONS}])
        write_preset_file(preset_dirs, "Fe L3", TWO_REGIONS)
        names = {p["name"] for p in ep.list_presets()}
        assert names == {"C 1s stack", "Fe L3"}

    def test_directory_preset_named_after_file_stem(self, preset_dirs):
        write_preset_file(preset_dirs, "N K-edge", TWO_REGIONS, wrapped=False)
        assert [p["name"] for p in ep.list_presets()] == ["N K-edge"]

    def test_favorite_wins_name_collision(self, preset_dirs):
        one_region = {"EnergyRegion1": {"start": 700.0, "stop": 700.0,
                                        "n_energies": 1, "dwell": 0.2}}
        write_favorites(preset_dirs, [{"alias": "dup", "energy_regions": TWO_REGIONS}])
        write_preset_file(preset_dirs, "dup", one_region)
        presets = ep.list_presets()
        assert len(presets) == 1
        assert presets[0]["source"] == "favorites"
        assert len(presets[0]["regions"]) == 2

    def test_malformed_entries_are_skipped_not_fatal(self, preset_dirs):
        write_favorites(preset_dirs, [{"alias": "bad", "energy_regions": {}},
                                      "not a dict",
                                      {"alias": "good", "energy_regions": TWO_REGIONS}])
        (preset_dirs / ep.PRESETS_DIRNAME / "junk.json").write_text("{{{")
        assert [p["name"] for p in ep.list_presets()] == ["good"]

    def test_no_sources_is_empty_not_an_error(self, preset_dirs):
        assert ep.list_presets() == []

    def test_describe_presets_reports_counts(self, preset_dirs):
        write_favorites(preset_dirs, [{"alias": "C 1s", "energy_regions": TWO_REGIONS}])
        described = ep.describe_presets()[0]
        assert described["n_regions"] == 2
        assert described["n_energies"] == 18
        assert described["source"] == "favorites"


class TestEnvironmentOverrides:
    """Deployments that don't share the GUI's sys.prefix — chiefly the MCP container —
    point at the presets with environment variables."""

    def test_cfg_dir_override_finds_both_sources(self, tmp_path, monkeypatch):
        cfg = tmp_path / "mounted_cfg"
        (cfg / ep.PRESETS_DIRNAME).mkdir(parents=True)
        write_favorites(cfg, [{"alias": "pinned", "energy_regions": TWO_REGIONS}])
        write_preset_file(cfg, "on disk", TWO_REGIONS)
        # No _CONFIG_DIRS patching: the override alone must be enough, which is the
        # container's situation (its sys.prefix holds no pystxmcontrol_cfg).
        monkeypatch.setenv(ep.CFG_DIR_ENV, str(cfg))
        monkeypatch.delenv(ep.PRESETS_DIR_ENV, raising=False)
        monkeypatch.delenv(ep.FAVORITES_ENV, raising=False)
        assert ep._config_dir() == str(cfg)
        assert {p["name"] for p in ep.list_presets()} == {"pinned", "on disk"}

    def test_presets_dir_override_alone(self, tmp_path, monkeypatch):
        """Sharing only the presets avoids mounting main.json and its secrets."""
        presets = tmp_path / "just_presets"
        presets.mkdir()
        (presets / "N K-edge.json").write_text(json.dumps({"energy_regions": TWO_REGIONS}))
        monkeypatch.delenv(ep.CFG_DIR_ENV, raising=False)
        monkeypatch.setenv(ep.PRESETS_DIR_ENV, str(presets))
        monkeypatch.setenv(ep.FAVORITES_ENV, str(tmp_path / "no-favorites.json"))
        assert ep.presets_dir() == str(presets)
        assert [p["name"] for p in ep.list_presets()] == ["N K-edge"]

    def test_favorites_file_override(self, tmp_path, monkeypatch):
        favs = tmp_path / "elsewhere.json"
        favs.write_text(json.dumps({"favorites": [{"alias": "pinned",
                                                   "energy_regions": TWO_REGIONS}]}))
        monkeypatch.delenv(ep.CFG_DIR_ENV, raising=False)
        monkeypatch.setenv(ep.FAVORITES_ENV, str(favs))
        monkeypatch.setenv(ep.PRESETS_DIR_ENV, str(tmp_path / "none"))
        assert ep.favorites_file_path() == str(favs)
        assert [p["name"] for p in ep.list_presets()] == ["pinned"]

    def test_granular_override_beats_cfg_dir(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cfg"
        (cfg / ep.PRESETS_DIRNAME).mkdir(parents=True)
        other = tmp_path / "other_presets"
        other.mkdir()
        monkeypatch.setenv(ep.CFG_DIR_ENV, str(cfg))
        monkeypatch.setenv(ep.PRESETS_DIR_ENV, str(other))
        assert ep.presets_dir() == str(other)

    def test_wrong_path_is_reported_not_silently_ignored(self, tmp_path, monkeypatch):
        """A typo'd mount must surface as the path we looked in, so the operator can
        see it in list_energy_presets' 'they come from ...' note."""
        missing = str(tmp_path / "not_mounted")
        monkeypatch.setenv(ep.CFG_DIR_ENV, missing)
        monkeypatch.delenv(ep.PRESETS_DIR_ENV, raising=False)
        monkeypatch.delenv(ep.FAVORITES_ENV, raising=False)
        assert ep.presets_dir().startswith(missing)
        assert ep.favorites_file_path().startswith(missing)
        assert ep.list_presets() == []

    def test_empty_override_is_ignored(self, preset_dirs, monkeypatch):
        """An unset-but-present env var (e.g. `-e PYSTXM_CFG_DIR=`) must not blank out
        the normal search path."""
        write_preset_file(preset_dirs, "still found", TWO_REGIONS)
        monkeypatch.setenv(ep.CFG_DIR_ENV, "   ")
        assert ep._config_dir() == str(preset_dirs)
        assert [p["name"] for p in ep.list_presets()] == ["still found"]


class TestResolve:

    @pytest.fixture(autouse=True)
    def _presets(self, preset_dirs):
        write_favorites(preset_dirs, [
            {"alias": "C 1s stack", "energy_regions": TWO_REGIONS},
            {"alias": "C 1s quick", "energy_regions": TWO_REGIONS},
            {"alias": "Fe L3", "energy_regions": TWO_REGIONS},
        ])
        self.cfg = preset_dirs

    def test_exact_name(self):
        name, regions = ep.resolve_preset("C 1s stack")
        assert name == "C 1s stack"
        assert len(regions) == 2

    def test_exact_name_is_case_insensitive(self):
        assert ep.resolve_preset("fe l3")[0] == "Fe L3"

    def test_unique_substring(self):
        assert ep.resolve_preset("Fe")[0] == "Fe L3"

    def test_ambiguous_substring_names_the_candidates(self):
        with pytest.raises(ep.PresetNotFound) as exc:
            ep.resolve_preset("C 1s")
        assert "ambiguous" in str(exc.value)
        assert "C 1s stack" in str(exc.value) and "C 1s quick" in str(exc.value)

    def test_unknown_name_lists_what_is_available(self):
        with pytest.raises(ep.PresetNotFound) as exc:
            ep.resolve_preset("Ti L2")
        assert "Fe L3" in str(exc.value)

    def test_empty_name_rejected(self):
        with pytest.raises(ep.PresetNotFound):
            ep.resolve_preset("   ")

    def test_explicit_path(self, tmp_path):
        p = tmp_path / "custom edge.json"
        p.write_text(json.dumps({"energy_regions": TWO_REGIONS}))
        name, regions = ep.resolve_preset(str(p))
        assert name == "custom edge"
        assert len(regions) == 2

    def test_missing_path_reports_the_path(self, tmp_path):
        missing = str(tmp_path / "gone.json")
        with pytest.raises(ep.PresetNotFound) as exc:
            ep.resolve_preset(missing)
        assert missing in str(exc.value)

    def test_path_with_no_regions_rejected(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("{}")
        with pytest.raises(ep.PresetNotFound):
            ep.resolve_preset(str(p))


# ── the scan path ───────────────────────────────────────────────────────────

class TestMultiRegionScanPath:
    """A preset is worth nothing if the regions collapse on the way to the server."""

    def test_scan_model_accepts_regions_and_syncs_flat_fields(self):
        m = ScanModel(energy_regions=ep.normalize_regions(TWO_REGIONS))
        assert m.energy_start == 280.0 and m.energy_stop == 290.0
        assert m.energy_points == 18
        assert m.total_energies() == 18
        assert m.dwell == 1.0            # first region's

    def test_build_emits_every_region_with_its_own_dwell(self):
        scan = ScanModel(energy_regions=ep.normalize_regions(TWO_REGIONS)).model_dump()
        built = sc.build_energy_regions(scan)
        assert list(built) == ["EnergyRegion1", "EnergyRegion2"]
        assert [r["dwell"] for r in built.values()] == [1.0, 3.0]
        assert [r["n_energies"] for r in built.values()] == [5, 13]

    def test_energy_list_withheld_for_multi_region(self):
        """A non-None energy_list makes the server ignore energy_regions entirely
        (writeNX._extractEnergies), flattening every region onto one dwell."""
        scan = ScanModel(energy_regions=ep.normalize_regions(TWO_REGIONS),
                         energy_list=[280.0, 281.0]).model_dump()
        assert sc.energy_list_for_scan(scan) is None

    def test_energy_list_passed_through_without_regions(self):
        scan = ScanModel(energy_list=[280.0, 281.0]).model_dump()
        assert sc.energy_list_for_scan(scan) == [280.0, 281.0]
        assert list(sc.build_energy_regions(scan)) == ["EnergyRegion1"]

    def test_flat_fields_build_one_region(self):
        scan = ScanModel(energy_start=700.0, energy_stop=710.0,
                         energy_points=11, dwell=0.5).model_dump()
        built = sc.build_energy_regions(scan)
        assert list(built) == ["EnergyRegion1"]
        assert built["EnergyRegion1"]["dwell"] == 0.5

    def test_round_trip_preserves_regions(self):
        scan = ScanModel(energy_regions=ep.normalize_regions(TWO_REGIONS)).model_dump()
        server_dict = _server_scan(sc.build_energy_regions(scan))
        flat = sc.convert_scan(server_dict)
        assert [(r["start"], r["stop"], r["dwell"]) for r in flat["energy_regions"]] == [
            (280.0, 282.0, 1.0), (284.0, 290.0, 3.0)]
        assert ScanModel(**flat).total_energies() == 18

    def test_single_region_leaves_energy_regions_unset(self):
        """The common case stays simple: flat fields fully describe one region."""
        server_dict = _server_scan({"EnergyRegion1": {
            "start": 700.0, "stop": 700.0, "step": 0.0,
            "n_energies": 1, "dwell": 0.2}})
        assert sc.convert_scan(server_dict)["energy_regions"] is None

    def test_single_energy_stop_collapse(self):
        """A stale descending stop on a single-energy scan must not trip validation —
        that failure silently reverted the scan to ScanModel defaults."""
        server_dict = _server_scan({"EnergyRegion1": {
            "start": 708.0, "stop": 500.0, "step": 0.0,
            "n_energies": 1, "dwell": 0.2}})
        flat = sc.convert_scan(server_dict)
        assert flat["energy_stop"] == 708.0
        assert ScanModel(**flat).energy_start == 708.0


def _server_scan(energy_regions):
    """Minimal server-shaped scan dict wrapping the given energy regions."""
    return {
        "scan_type": "Image", "proposal": "p", "experimenters": "e", "sample": "s",
        "x_motor": "SampleX", "y_motor": "SampleY",
        "energy_regions": energy_regions,
        "scan_regions": {"Region1": {
            "xCenter": 0.0, "yCenter": 0.0, "zCenter": 0.0,
            "xRange": 5.0, "yRange": 5.0, "zRange": 0.0,
            "xPoints": 50, "yPoints": 50, "zPoints": 1}},
    }
