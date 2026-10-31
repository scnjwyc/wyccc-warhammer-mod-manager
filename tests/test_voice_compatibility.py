from __future__ import annotations

import os
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from backend.constants import VOICE_COMPATIBILITY_PATCH_NAME
from backend.game_data import DbSource, GameDataEntry
from backend.start_options import read_pack_entries
from backend.voice_compatibility import (
    DecisionNode, DialogueEvent, VOICE_RUNTIME_MARKER, WH3_BANK_VERSION,
    build_voice_compatibility_entries, encode_dialogue_event, event_paths,
    parse_dialogue_event, parse_soundbank,
)
from backend.voice_patch_state import ensure_voice_compatibility_patch
from tests.helpers import make_asset, write_pack

PREFIX = "audio\\wwise\\"
BASE_NAME = PREFIX + "english(uk)\\campaign_vo__core.bnk"


@pytest.fixture(autouse=True)
def isolated_audio_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


def event(values, *, event_id=100, arguments=(123,), mode=0):
    def node(key, value):
        if isinstance(value, dict):
            return DecisionNode(key, 50, 100, children=tuple(node(k, v) for k, v in sorted(value.items())))
        return DecisionNode(key, 50, 100, audio_id=value)

    return DialogueEvent(event_id, 100, arguments, bytes([1] * len(arguments)), mode,
                         node(0, values), b"\0\0")


def bank(events, *, bank_id=1000, extras=(), version=WH3_BANK_VERSION):
    objects = [*(struct.pack("<BI", 15, len(raw)) + raw for raw in map(encode_dialogue_event, events)),
               *(struct.pack("<BI", kind, len(payload)) + payload for kind, payload in extras)]
    header = struct.pack("<6I", version, bank_id, 550298558, 16, 2361, 0)
    hirc = struct.pack("<I", len(objects)) + b"".join(objects)
    return b"BKHD" + struct.pack("<I", len(header)) + header + b"HIRC" + struct.pack("<I", len(hirc)) + hirc


def source(name, values, *, role="mod", filename=None, **kwargs):
    filename = filename or PREFIX + name + ".bnk"
    return DbSource(name, (GameDataEntry(filename, bank([event(values, **kwargs)])),), role)


def merged_events(entries):
    return {parse_soundbank(entry.payload).dialogues()[100] for entry in entries}


def test_binary_tree_layout_with_nested_and_early_terminal_paths():
    # Independent byte fixture, including an early terminal and explicit silence.
    nodes = b"".join([
        struct.pack("<IHHHH", 0, 1, 2, 50, 100),
        struct.pack("<IHHHH", 10, 3, 2, 17, 99),
        struct.pack("<IIHH", 20, 0xABCDEF01, 18, 97),
        struct.pack("<IIHH", 0, 0xABCDEF02, 19, 96),
        struct.pack("<IIHH", 7, 0, 20, 95),
    ])
    payload = struct.pack("<IBI2I2BIB", 100, 90, 2, 123, 456, 1, 0, len(nodes), 1) + nodes + b"\0\0"
    parsed = parse_dialogue_event(payload)
    assert event_paths(parsed) == {(10, 0): (0xABCDEF02, 19, 96), (10, 7): (0, 20, 95),
                                  (20,): (0xABCDEF01, 18, 97)}
    assert encode_dialogue_event(parsed) == payload


def test_full_banks_keep_both_mod_deltas_and_current_vanilla_paths():
    entries, stats = build_voice_compatibility_entries([
        source("high", {1: 111, 2: 20, 3: 300}),
        source("low", {1: 10, 2: 222, 4: 400}),
        source("vanilla", {1: 10, 2: 20, 5: 50}, role="vanilla"),
    ])
    merged, = merged_events(entries)
    assert {path: value[0] for path, value in event_paths(merged).items()} == {
        (1,): 111, (2,): 222, (3,): 300, (4,): 400, (5,): 50,
    }
    assert stats["merged_event_count"] == 1 and stats["conflicting_path_count"] == 0


def test_three_mods_same_branch_uses_first_mod_and_reversing_order_changes_winner():
    high, low = source("high", {1: 111}), source("low", {1: 222})
    third, base = source("third", {2: 333}), source("base", {1: 10}, role="vanilla")
    for sources, winner in [([high, low, third, base], 111), ([low, high, third, base], 222)]:
        entries, stats = build_voice_compatibility_entries(sources)
        merged, = merged_events(entries)
        assert event_paths(merged) == {(1,): (winner, 50, 100), (2,): (333, 50, 100)}
        assert stats["conflicting_path_count"] == 1


def test_authoring_tree_wins_over_testing_copy_inside_the_same_mod():
    full = source("high", {1: 999}, filename=PREFIX + "a_for_testing.bnk")
    explicit = source("high", {1: 10}, filename=PREFIX + "z_for_merging.bnk")
    combined = DbSource("high", (*full.entries, *explicit.entries))
    entries, _ = build_voice_compatibility_entries([
        combined, source("low", {1: 222}), source("base", {1: 10}, role="vanilla"),
    ])
    merged, = merged_events(entries)
    assert event_paths(merged)[(1,)][0] == 10


def test_shared_file_path_merges_dialogues_and_retains_lower_unique_events():
    name = PREFIX + "shared.bnk"
    high = DbSource("high", (GameDataEntry(name, bank([event({1: 111})])),))
    low = DbSource("low", (GameDataEntry(name, bank([event({2: 222}), event({3: 333}, event_id=200)])),))
    entries, _ = build_voice_compatibility_entries([high, low])
    assert len(entries) == 1
    events = parse_soundbank(entries[0].payload).dialogues()
    assert event_paths(events[100]) == {(1,): (111, 50, 100), (2,): (222, 50, 100)}
    assert event_paths(events[200]) == {(3,): (333, 50, 100)}


def test_shared_file_does_not_silently_lose_playback_objects():
    name = PREFIX + "shared.bnk"
    high = DbSource("high", (GameDataEntry(name, bank([event({1: 111})], extras=[(2, b"abcdhigh")])),))
    low = DbSource("low", (GameDataEntry(name, bank([event({2: 222})], extras=[(2, b"abcdlow")])),))
    with pytest.raises(ValueError, match="播放对象"):
        build_voice_compatibility_entries([high, low])


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_file_unions_disjoint_playback_objects_regardless_of_priority(reverse):
    name = PREFIX + "shared.bnk"
    high = DbSource("high", (GameDataEntry(name, bank([event({1: 111})], extras=[(2, b"abcdhigh")])),))
    low = DbSource("low", (GameDataEntry(name, bank([event({2: 222})], extras=[(5, b"efghlow")])),))
    entries, _ = build_voice_compatibility_entries([
        *( [low, high] if reverse else [high, low] ),
        source("base", {1: 10, 2: 20}, role="vanilla"),
    ])
    actual = parse_soundbank(entries[0].payload)
    assert (2, b"abcdhigh") in actual.objects
    assert (5, b"efghlow") in actual.objects
    assert event_paths(actual.dialogues()[100]) == {
        (1,): (111, 50, 100), (2,): (222, 50, 100),
    }


def test_shared_file_keeps_higher_priority_playback_bank_when_adding_missing_dialogues():
    name = PREFIX + "shared.bnk"
    original = bank([], bank_id=999, extras=[(2, b"abcdsound")])
    high = DbSource("high", (GameDataEntry(name, original),))
    low = source("low", {1: 111}, filename=name)
    entries, _ = build_voice_compatibility_entries([high, low])
    assert len(entries) == 1
    actual = parse_soundbank(entries[0].payload)
    assert actual.chunks[0] == parse_soundbank(original).chunks[0]
    assert (2, b"abcdsound") in actual.objects
    assert event_paths(actual.dialogues()[100]) == {(1,): (111, 50, 100)}


def test_bank_header_and_non_dialogue_objects_are_unchanged():
    original = bank([event({1: 111})], bank_id=123456, extras=[(2, b"abcdsound"), (5, b"efghcontainer")])
    high = DbSource("high", (GameDataEntry(PREFIX + "high.bnk", original),))
    entries, _ = build_voice_compatibility_entries([high, source("low", {2: 222})])
    actual, parsed = parse_soundbank(entries[0].payload), parse_soundbank(original)
    assert actual.chunks[0] == parsed.chunks[0]
    assert [(k, p) for k, p in actual.objects if k != 15] == [(k, p) for k, p in parsed.objects if k != 15]


def test_language_scopes_are_isolated():
    entries, stats = build_voice_compatibility_entries([
        source("cn1", {1: 111}, filename=PREFIX + "chinese\\one.bnk"),
        source("cn2", {2: 222}, filename=PREFIX + "chinese\\two.bnk"),
        source("en", {1: 999}, filename=PREFIX + "english(uk)\\one.bnk"),
    ])
    assert len(entries) == 2 and stats["merged_event_count"] == 1
    assert all("\\chinese\\" in entry.name for entry in entries)


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_global_and_localized_events_share_one_merged_tree_with_vanilla_fallback(reverse):
    global_source = source("global", {1: 111, 2: 20}, event_id=610793228)
    localized = source("local", {1: 222, 2: 200}, event_id=610793228,
                       filename=PREFIX + "english(uk)\\local.bnk")
    sources = [global_source, localized] if not reverse else [localized, global_source]
    entries, stats = build_voice_compatibility_entries([
        *sources, source("base", {1: 10, 2: 20, 3: 30}, role="vanilla", event_id=610793228,
                         filename=BASE_NAME),
    ])
    copies = {parse_soundbank(entry.payload).dialogues()[610793228] for entry in entries}
    assert len(entries) == 2 and len(copies) == 1
    assert event_paths(copies.pop()) == {(1,): (222 if reverse else 111, 50, 100),
                                        (2,): (200, 50, 100), (3,): (30, 50, 100)}
    assert stats["merged_event_count"] == 1
    assert stats["conflicting_path_count"] == 1


def test_mixed_layout_prefers_authoring_tree_across_directories_in_the_same_mod():
    high = DbSource("high", (
        *source("high", {1: 10}, filename=PREFIX + "high_for_merging.bnk").entries,
        *source("high", {1: 999}, filename=PREFIX + "english(uk)\\high_for_testing.bnk").entries,
    ))
    entries, _ = build_voice_compatibility_entries([
        high, source("low", {1: 222, 2: 200}, filename=PREFIX + "english(uk)\\low.bnk"),
        source("base", {1: 10, 3: 30}, role="vanilla", filename=BASE_NAME),
    ])
    merged, = merged_events(entries)
    assert event_paths(merged) == {(1,): (10, 50, 100), (2,): (200, 50, 100), (3,): (30, 50, 100)}
    assert len(entries) == 3


def test_mixed_layout_can_share_identical_localized_trees_without_counting_copies_as_mods():
    localized = DbSource("local", (
        *source("local", {2: 222}, filename=PREFIX + "english(uk)\\local.bnk").entries,
        *source("local", {2: 222}, filename=PREFIX + "chinese\\local.bnk").entries,
    ))
    entries, stats = build_voice_compatibility_entries([source("global", {1: 111}), localized])
    merged, = merged_events(entries)
    assert len(entries) == 3 and stats["voice_pack_count"] == 2
    assert stats["merged_event_count"] == 1
    assert event_paths(merged) == {(1,): (111, 50, 100), (2,): (222, 50, 100)}
    entries, stats = build_voice_compatibility_entries([
        DbSource("single", (*source("global", {1: 111}).entries, *localized.entries)),
    ])
    assert not entries and stats["merged_event_count"] == 0


def test_mixed_layout_does_not_merge_distinct_languages_into_the_global_bank():
    with pytest.raises(ValueError, match="混合布局"):
        build_voice_compatibility_entries([
            source("global", {1: 111}),
            source("cn", {2: 222}, filename=PREFIX + "chinese\\local.bnk"),
            source("en", {2: 999}, filename=PREFIX + "english(uk)\\local.bnk"),
        ])


def test_mixed_layout_does_not_copy_a_different_language_vanilla_fallback_into_the_global_bank():
    localized = DbSource("local", (
        *source("local", {2: 222}, filename=PREFIX + "english(uk)\\local.bnk").entries,
        *source("local", {2: 222}, filename=PREFIX + "chinese\\local.bnk").entries,
    ))
    with pytest.raises(ValueError, match="混合布局"):
        build_voice_compatibility_entries([
            source("global", {1: 111}), localized,
            source("en_base", {3: 300}, role="vanilla", filename=BASE_NAME),
            source("cn_base", {3: 333}, role="vanilla", filename=PREFIX + "chinese\\campaign_vo__core.bnk"),
        ])


@pytest.mark.parametrize("scope", ["chinese", "english(uk)"])
@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_layout_selects_current_language_bank_then_applies_mod_priority(scope, reverse):
    mods = [
        source("english", {1: 111, 2: 20}, event_id=165328208,
               filename=PREFIX + "english(uk)\\voice.bnk"),
        source("translation", {1: 222, 2: 333}, event_id=165328208,
               filename=PREFIX + "chinese\\voice.bnk"),
        source("mixer", {1: 10, 2: 0, 3: 300, 9: 999}, event_id=165328208,
               filename=PREFIX + "english(uk)\\mixer.bnk"),
        source("global", {4: 444}, event_id=165328208, filename=PREFIX + "global_for_merging.bnk"),
    ]
    entries, stats = build_voice_compatibility_entries([
        *(reversed(mods) if reverse else mods),
        source("en_base", {1: 10, 2: 20, 9: 999}, role="vanilla", event_id=165328208,
               filename=BASE_NAME),
        source("cn_base", {1: 10, 2: 20, 9: 900}, role="vanilla", event_id=165328208,
               filename=PREFIX + "chinese\\campaign_vo__core.bnk"),
    ], language_scope=scope)
    copies = {parse_soundbank(entry.payload).dialogues()[165328208] for entry in entries}
    assert len(entries) == 4 and len(copies) == 1
    assert event_paths(copies.pop()) == {
        (1,): (222 if scope == "chinese" else 111, 50, 100),
        (2,): (333 if scope == "chinese" and not reverse else 0, 50, 100),
        (3,): (300, 50, 100), (4,): (444, 50, 100),
        (9,): (900 if scope == "chinese" else 999, 50, 100),
    }
    assert stats["merged_event_count"] == 1


def test_current_language_bank_without_event_prevents_falling_back_to_the_english_copy():
    translation = DbSource("translation", (
        GameDataEntry(PREFIX + "chinese\\voice.bnk", bank([event({7: 777}, event_id=200)])),
    ))
    entries, _ = build_voice_compatibility_entries([
        source("english", {1: 111}, filename=PREFIX + "english(uk)\\voice.bnk"),
        translation,
        source("global", {4: 444}, filename=PREFIX + "global_for_merging.bnk"),
        source("en_base", {1: 10}, role="vanilla", filename=BASE_NAME),
        source("cn_base", {1: 20}, role="vanilla", filename=PREFIX + "chinese\\campaign_vo__core.bnk"),
    ], language_scope="chinese")
    copies = {parse_soundbank(entry.payload).dialogues()[100]
              for entry in entries if 100 in parse_soundbank(entry.payload).dialogues()}
    assert len(copies) == 1
    assert event_paths(copies.pop()) == {(1,): (20, 50, 100), (4,): (444, 50, 100)}


@pytest.mark.parametrize("nested", [False, True])
def test_english_fallback_never_imports_vanilla_branches_missing_from_the_current_language(nested):
    arguments = (123, 456) if nested else (123,)
    english_base = {1: {2: 20}} if nested else {1: 10}
    chinese_base = {3: {4: 40}} if nested else {3: 30}
    english_mod = {1: {2: 20, 5: 55}} if nested else {1: 10, 5: 55}
    global_mod = {6: {7: 77}} if nested else {6: 66}
    entries, _ = build_voice_compatibility_entries([
        source("english", english_mod, arguments=arguments, filename=PREFIX + "english(uk)\\voice.bnk"),
        source("global", global_mod, arguments=arguments, filename=PREFIX + "global_for_merging.bnk"),
        source("en_base", english_base, arguments=arguments, role="vanilla", filename=BASE_NAME),
        source("cn_base", chinese_base, arguments=arguments, role="vanilla",
               filename=PREFIX + "chinese\\campaign_vo__core.bnk"),
    ], language_scope="chinese")
    merged, = merged_events(entries)
    assert event_paths(merged) == ({(3, 4): (40, 50, 100), (1, 5): (55, 50, 100), (6, 7): (77, 50, 100)}
                                   if nested else {(3,): (30, 50, 100), (5,): (55, 50, 100), (6,): (66, 50, 100)})


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_layout_accepts_single_language_baseline_extensions(reverse):
    # Player report 3643531796: Audio Mixer exists only under english(uk),
    # whereas the other MOD has identical copies in several language folders.
    localized = DbSource("local", tuple(
        entry for scope in ("english(uk)", "chinese")
        for entry in source("local", {1: 111, 2: 20}, event_id=3643531796,
                            filename=PREFIX + scope + "\\local.bnk").entries
    ))
    mods = [source("global", {4: 444}, event_id=3643531796), localized,
            source("mixer", {1: 10, 2: 20, 3: 300}, event_id=3643531796,
                   filename=PREFIX + "english(uk)\\mixer.bnk")]
    entries, stats = build_voice_compatibility_entries([
        *(reversed(mods) if reverse else mods),
        *(source("base_" + scope, {1: 10, 2: 20}, role="vanilla", event_id=3643531796,
                 filename=PREFIX + scope + "\\frontend_vo__core.bnk")
          for scope in ("english(uk)", "chinese")),
    ])
    copies = {parse_soundbank(entry.payload).dialogues()[3643531796] for entry in entries}
    assert len(entries) == 4 and len(copies) == 1
    assert event_paths(copies.pop()) == {
        (1,): (111, 50, 100), (2,): (20, 50, 100),
        (3,): (300, 50, 100), (4,): (444, 50, 100),
    }
    assert stats["merged_event_count"] == 1 and stats["conflicting_path_count"] == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_layout_accepts_equivalent_localized_deltas_from_separate_mods(reverse):
    # Report 3563368242: the English bank has an older vanilla fallback;
    # its separately packaged Chinese copy has the same authored addition.
    event_id = 3563368242
    baseline = {1: 10, 2: 20, 3: 30}
    mods = [
        source("english", {1: 10, 5: 500}, event_id=event_id,
               filename=PREFIX + "english(uk)\\voice.bnk"),
        source("translation", {**baseline, 5: 500}, event_id=event_id,
               filename=PREFIX + "chinese\\voice.bnk"),
        source("global", {4: 444}, event_id=event_id, filename=PREFIX + "global_for_merging.bnk"),
        source("mixer", {**baseline, 6: 600}, event_id=event_id,
               filename=PREFIX + "english(uk)\\mixer.bnk"),
    ]
    entries, stats = build_voice_compatibility_entries([
        *(reversed(mods) if reverse else mods),
        *(source("base_" + scope, baseline, role="vanilla", event_id=event_id,
                 filename=PREFIX + scope + "\\battle_vo_conversational__core.bnk")
          for scope in ("english(uk)", "chinese")),
    ])
    copies = {parse_soundbank(entry.payload).dialogues()[event_id] for entry in entries}
    assert len(entries) == 4 and len(copies) == 1
    assert event_paths(copies.pop()) == {
        (1,): (10, 50, 100), (2,): (20, 50, 100), (3,): (30, 50, 100),
        (4,): (444, 50, 100), (5,): (500, 50, 100), (6,): (600, 50, 100),
    }
    assert stats["merged_event_count"] == 1 and stats["conflicting_path_count"] == 0


@pytest.mark.parametrize("difference", ["audio", "weight", "probability", "mode", "suffix"])
def test_mixed_layout_rejects_different_localized_results_from_separate_mods(difference):
    english = event({1: 10, 5: 500})
    translated = event({1: 10, 2: 20, 5: 500})
    if difference == "audio":
        translated = event({1: 10, 2: 20, 5: 555})
    elif difference == "weight":
        translated = replace(translated, root=replace(translated.root, children=(
            *translated.root.children[:-1], replace(translated.root.children[-1], weight=99),
        )))
    else:
        translated = replace(translated, **{difference: {"probability": 90, "mode": 1, "suffix": b"\1\0"}[difference]})
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            DbSource("english", (GameDataEntry(PREFIX + "english(uk)\\voice.bnk", bank([english])),)),
            DbSource("translation", (GameDataEntry(PREFIX + "chinese\\voice.bnk", bank([translated])),)),
            source("global", {4: 444}, filename=PREFIX + "global_for_merging.bnk"),
            *(source("base_" + scope, {1: 10, 2: 20}, role="vanilla",
                     filename=PREFIX + scope + "\\campaign_vo__core.bnk")
              for scope in ("english(uk)", "chinese")),
        ])
    assert caught.value.details["reason"] == "mixedLayout"


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_layout_rejects_equivalent_contributions_with_different_priority_results(reverse):
    bilingual = DbSource("bilingual", tuple(
        entry for scope in ("english(uk)", "chinese")
        for entry in source("bilingual", {1: 222}, filename=PREFIX + scope + "\\bilingual.bnk").entries
    ))
    mods = [
        source("english", {1: 111}, filename=PREFIX + "english(uk)\\voice.bnk"),
        bilingual,
        source("translation", {1: 111}, filename=PREFIX + "chinese\\voice.bnk"),
        source("global", {4: 444}, filename=PREFIX + "global_for_merging.bnk"),
    ]
    # Both languages have the same contributions, but their relative priorities
    # select different audio for the existing vanilla path.
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            *(reversed(mods) if reverse else mods),
            *(source("base_" + scope, {1: 10}, role="vanilla",
                     filename=PREFIX + scope + "\\campaign_vo__core.bnk")
              for scope in ("english(uk)", "chinese")),
        ])
    assert caught.value.details["reason"] == "mixedLayout"


def test_mixed_layout_does_not_share_disjoint_language_additions_when_global_hides_the_difference():
    # A global replacement can make the final trees equal while still masking
    # unrelated voices that were never packaged together in either language.
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            source("global", {2: 222, 3: 333}, filename=PREFIX + "global_for_merging.bnk"),
            source("english", {1: 10, 2: 200}, filename=PREFIX + "english(uk)\\voice.bnk"),
            source("translation", {1: 10, 3: 300}, filename=PREFIX + "chinese\\voice.bnk"),
            source("base", {1: 10}, role="vanilla", filename=BASE_NAME),
        ])
    assert caught.value.details["reason"] == "mixedLayout"


@pytest.mark.parametrize("difference", ["audio", "missing", "weight", "probability", "mode",
                                        "suffix", "branch_metadata", "explicit", "no_baseline"])
def test_mixed_layout_rejects_unproven_cross_language_extensions(difference):
    baseline = event({1: {2: 20}}, arguments=(123, 456))
    extension = event({1: {2: 20}, 3: {4: 40}}, arguments=(123, 456))
    if difference == "audio":
        extension = event({1: {2: 999}, 3: {4: 40}}, arguments=(123, 456))
    elif difference == "missing":
        extension = event({3: {4: 40}}, arguments=(123, 456))
    elif difference == "weight":
        branch = extension.root.children[0]
        branch = replace(branch, children=(replace(branch.children[0], weight=99),))
        extension = replace(extension, root=replace(extension.root, children=(branch, extension.root.children[1])))
    elif difference == "branch_metadata":
        branch = replace(extension.root.children[0], probability=99)
        extension = replace(extension, root=replace(extension.root, children=(branch, extension.root.children[1])))
    elif difference in {"probability", "mode", "suffix"}:
        extension = replace(extension, **{difference: {"probability": 90, "mode": 1, "suffix": b"\1\0"}[difference]})
    name = "extra_for_merging.bnk" if difference == "explicit" else "extra.bnk"
    sources = [
        source("global", {5: {6: 60}}, arguments=(123, 456)),
        DbSource("local", tuple(GameDataEntry(PREFIX + scope + "\\local.bnk", bank([baseline]))
                                for scope in ("english(uk)", "chinese"))),
        DbSource("extra", (GameDataEntry(PREFIX + "english(uk)\\" + name, bank([extension])),)),
    ]
    if difference != "no_baseline":
        sources.append(DbSource("base", tuple(
            GameDataEntry(PREFIX + scope + "\\campaign_vo__core.bnk", bank([baseline]))
            for scope in ("english(uk)", "chinese")
        ), role="vanilla"))
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries(sources)
    assert caught.value.details["reason"] == "mixedLayout"


def test_mixed_layout_does_not_combine_separate_language_additions():
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            source("global", {4: 444}),
            source("cn", {1: 10, 2: 222}, filename=PREFIX + "chinese\\local.bnk"),
            source("en", {1: 10, 2: 999}, filename=PREFIX + "english(uk)\\local.bnk"),
            source("base", {1: 10}, role="vanilla", filename=BASE_NAME),
        ])
    assert caught.value.details["reason"] == "mixedLayout"


@pytest.mark.parametrize("broken", [b"", b"BKHD\x18\0\0\0short", bank([event({1: 111})])[:-1]])
def test_rejects_truncated_banks(broken):
    with pytest.raises(ValueError):
        parse_soundbank(broken)


def test_rejects_incompatible_versions_and_argument_structures():
    with pytest.raises(ValueError, match="0x80000088"):
        parse_soundbank(bank([event({1: 111})], version=135))
    with pytest.raises(ValueError, match="参数结构"):
        build_voice_compatibility_entries([source("one", {1: 111}), source("two", {2: 222}, arguments=(456,))])


@pytest.mark.parametrize("event_id,arguments", [
    (165328208, (3113488887, 112324978, 702015320)),
    (855899397, (3113488887, 112324978, 702015320)),
    (2302243677, (112324978, 495479955, 2956310662)),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_legacy_trailing_argument_uses_any_without_losing_vanilla_or_author_paths(event_id, arguments, reverse):
    author = event({5: {6: 56}}, event_id=event_id, arguments=arguments[:-1])
    leaf = replace(author.root.children[0].children[0], weight=17, probability=91)
    author = replace(author, root=replace(author.root, children=(
        replace(author.root.children[0], children=(leaf,)),
    )))
    legacy = DbSource("trojan_archer.pack", (
        GameDataEntry(PREFIX + "legacy_for_merging.bnk", bank([author])),
        GameDataEntry(PREFIX + "legacy_for_testing.bnk", bank([
            event({1: {2: 999}, 5: {6: 56}}, event_id=event_id, arguments=arguments[:-1]),
        ])),
    ))
    current = source("current", {8: {9: {0: 89}}}, event_id=event_id, arguments=arguments)
    baseline = source("vanilla", {1: {2: {0: 20, 7: 27}}}, role="vanilla",
                      event_id=event_id, arguments=arguments)
    entries, _ = build_voice_compatibility_entries([
        *([current, legacy] if reverse else [legacy, current]), baseline,
    ])
    copies = [parse_soundbank(entry.payload).dialogues()[event_id] for entry in entries]
    assert len(copies) == 3 and len(set(copies)) == 1
    merged = copies[0]
    assert merged.arguments == arguments and merged.argument_types == b"\1\1\1"
    assert event_paths(merged) == {
        (1, 2, 0): (20, 50, 100), (1, 2, 7): (27, 50, 100),
        (5, 6, 0): (56, 17, 91), (8, 9, 0): (89, 50, 100),
    }
    assert parse_dialogue_event(encode_dialogue_event(merged)) == merged
    assert event_paths(author) == {(5, 6): (56, 17, 91)}


def test_legacy_arguments_are_updated_with_only_one_mod_and_multiple_new_conditions():
    entries, stats = build_voice_compatibility_entries([
        source("legacy", {5: 56}, arguments=(123,), filename=PREFIX + "legacy_for_merging.bnk"),
        source("vanilla", {1: {2: {3: 20}}}, arguments=(123, 456, 789), role="vanilla"),
    ])
    merged, = merged_events(entries)
    assert merged.arguments == (123, 456, 789)
    assert event_paths(merged) == {(1, 2, 3): (20, 50, 100), (5, 0, 0): (56, 50, 100)}
    assert stats["voice_pack_count"] == 1


@pytest.mark.parametrize("difference", ["missing_middle", "type", "new_type", "no_vanilla"])
def test_legacy_argument_extension_requires_a_matching_current_vanilla_prefix(difference):
    legacy = event({1: {2: 12}}, arguments=(123, 789) if difference == "missing_middle" else (123, 456))
    current = event({3: {4: {0: 34}}}, arguments=(123, 456, 789))
    if difference == "type":
        legacy = replace(legacy, argument_types=b"\1\0")
    if difference == "new_type":
        current = replace(current, argument_types=b"\1\1\0")
    sources = [DbSource("legacy", (GameDataEntry(PREFIX + "legacy.bnk", bank([legacy])),)),
               DbSource("current", (GameDataEntry(PREFIX + "current.bnk", bank([current])),))]
    if difference != "no_vanilla":
        sources.append(DbSource("vanilla", (GameDataEntry(BASE_NAME, bank([current])),), "vanilla"))
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries(sources)
    assert caught.value.details["reason"] == "argumentMismatch"


@pytest.mark.parametrize("difference", ["order", "count", "type"])
def test_argument_conflict_identifies_both_packs_banks_and_exact_definitions(difference):
    first = event({1: {2: 111}}, event_id=165328208, arguments=(123, 456))
    other = replace(first, arguments=(456, 123)) if difference == "order" else (
        event({2: 222}, event_id=165328208) if difference == "count"
        else replace(first, argument_types=b"\1\0")
    )
    sources = [DbSource(name, (GameDataEntry(PREFIX + name + ".bnk", bank([definition])),))
               for name, definition in [("one.pack", first), ("two.pack", other)]]
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries(sources)
    assert "165328208" in str(caught.value)
    for name in ["one.pack", "two.pack"]:
        assert name in str(caught.value)
        assert PREFIX + name + ".bnk" in str(caught.value)
    details = caught.value.details
    assert details["reason"] == "argumentMismatch"
    assert {tuple(item["arguments"]) for item in details["sources"]} == {first.arguments, other.arguments}
    assert {tuple(item["argument_types"]) for item in details["sources"]} == {
        tuple(first.argument_types), tuple(other.argument_types),
    }


def test_argument_conflict_marks_the_actual_vanilla_baseline():
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            source("one.pack", {1: 111}), source("two.pack", {2: 222}),
            source("audio_en_bnk.pack", {1: 10}, arguments=(456,), role="vanilla", filename=BASE_NAME),
        ])
    assert "audio_en_bnk.pack" in str(caught.value)
    baseline, = [item for item in caught.value.details["sources"] if item["role"] == "vanilla"]
    assert baseline["bank"] == BASE_NAME


def test_argument_conflict_in_an_unselected_testing_copy_is_not_overwritten():
    high = DbSource("broken.pack", (
        *source("high", {1: 111}, filename=PREFIX + "author_for_merging.bnk").entries,
        *source("high", {2: 222}, arguments=(456,), filename=PREFIX + "copy_for_testing.bnk").entries,
    ))
    with pytest.raises(ValueError, match="broken.pack") as caught:
        build_voice_compatibility_entries([high, source("other.pack", {3: 333})])
    assert "copy_for_testing.bnk" in str(caught.value)
    assert "author_for_merging.bnk" in str(caught.value)


def test_different_authoring_banks_in_one_mod_do_not_silently_lose_branches():
    high = DbSource("split.pack", (
        *source("high", {1: 111}, filename=PREFIX + "a_for_merging.bnk").entries,
        *source("high", {2: 222}, filename=PREFIX + "b_for_merging.bnk").entries,
    ))
    with pytest.raises(ValueError, match="split.pack") as caught:
        build_voice_compatibility_entries([high, source("other.pack", {3: 333})])
    assert caught.value.details["reason"] == "ambiguousCopies"


def test_tree_shape_conflict_names_the_sources():
    with pytest.raises(ValueError) as caught:
        build_voice_compatibility_entries([
            source("branch.pack", {1: {2: 111}}, arguments=(123, 456)),
            source("leaf.pack", {1: 222}, arguments=(123, 456)),
        ])
    assert "branch.pack" in str(caught.value) and "leaf.pack" in str(caught.value)
    assert caught.value.details["reason"] == "treeMismatch"


def test_rejects_invalid_tree_ranges_duplicate_keys_and_overflow():
    valid = encode_dialogue_event(event({1: 111, 2: 222}))
    for index, value in [(14, 99999), (23, 0), (43, 1)]:
        broken = bytearray(valid)
        struct.pack_into("<I", broken, index, value)
        with pytest.raises(ValueError):
            parse_dialogue_event(bytes(broken))
    oversized = replace(event({1: 111}), root=DecisionNode(0, 50, 100, children=tuple(
        DecisionNode(i, 50, 100, audio_id=111) for i in range(65536)
    )))
    with pytest.raises(ValueError, match="容量"):
        encode_dialogue_event(oversized)


def prepare(root):
    data = root / "data"
    write_pack(data / "audio_en_bnk.pack", entries=[(BASE_NAME, bank([event({1: 10, 2: 20})]))])
    assets = {}
    for name, values in [("high", {1: 111, 2: 20}), ("low", {1: 10, 2: 222})]:
        path = write_pack(root / "mods" / f"{name}.pack", byte_mask=3,
                          entries=[(PREFIX + name + ".bnk", bank([event(values)])),
                                   (PREFIX + name + ".wem", b"unmodified audio")])
        assets[name] = make_asset(path, name, "workshop")
    return data, assets


def ensure(root, data, assets, ids=None, enabled=True, playset="playset", subscribed=True):
    return ensure_voice_compatibility_patch(root / "runtime", data, assets,
                                           list(assets) if ids is None else ids, playset,
                                           {"voice_compatibility_patch_enabled": enabled}, subscribed=subscribed)


def test_cache_tampering_source_content_order_playset_and_stale_cleanup(tmp_path):
    data, assets = prepare(tmp_path)
    generated = ensure(tmp_path, data, assets)
    assert generated["status"] == "generated"
    output = Path(generated["path"])
    assert all(entry.name.endswith(".bnk") or entry.name == VOICE_RUNTIME_MARKER
               for entry in read_pack_entries(output))
    assert ensure(tmp_path, data, assets)["status"] == "reused"
    output.write_bytes(b"bad cache")
    assert ensure(tmp_path, data, assets)["status"] == "generated"
    source_path = Path(assets["high"].path)
    before = source_path.stat()
    source_path.write_bytes(source_path.read_bytes().replace(struct.pack("<I", 111), struct.pack("<I", 333)))
    os.utime(source_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = ensure(tmp_path, data, assets)
    assert changed["status"] == "generated" and changed["fingerprint"] != generated["fingerprint"]
    reordered = ensure(tmp_path, data, assets, ids=["low", "high"])
    assert reordered["fingerprint"] != changed["fingerprint"]
    assert ensure(tmp_path, data, assets, playset="other")["status"] == "generated"
    assert ensure(tmp_path, data, assets, ids=["high"])["status"] == "zero_modification"
    assert not output.exists()
    assert ensure(tmp_path, data, assets)["path"]
    assert ensure(tmp_path, data, assets, enabled="false")["reason"] == "disabled"
    assert not output.exists()


def test_conflict_uses_the_visible_mod_name_pack_and_workshop_id(tmp_path):
    data, assets = prepare(tmp_path)
    assets["low"].display_name = "Example Voice"
    assets["low"].workshop_id = "123456789"
    write_pack(Path(assets["low"].path), byte_mask=3,
               entries=[(PREFIX + "low.bnk", bank([event({2: 222}, arguments=(456,))]))])
    with pytest.raises(ValueError) as caught:
        ensure(tmp_path, data, assets)
    assert "Example Voice [low.pack] (Workshop 123456789)" in str(caught.value)
    assert not (tmp_path / "runtime" / VOICE_COMPATIBILITY_PATCH_NAME).exists()


def test_auto_movie_participates_but_disabled_normal_mod_and_old_runtime_do_not(tmp_path):
    data, assets = prepare(tmp_path)
    movie = write_pack(data / "movie.pack", byte_mask=4,
                       entries=[(PREFIX + "english(uk)\\movie.bnk", bank([event({3: 333})]))])
    generated = ensure(tmp_path, data, assets, ids=["high"])
    assert generated["stats"]["voice_pack_count"] == 2
    merged, = merged_events([entry for entry in read_pack_entries(Path(generated["path"]))
                             if entry.name.endswith(".bnk")])
    assert event_paths(merged) == {(1,): (111, 50, 100), (2,): (20, 50, 100), (3,): (333, 50, 100)}
    stale = write_pack(data / "renamed_old_runtime.pack", byte_mask=4,
                       entries=[(VOICE_RUNTIME_MARKER, b"{}"), (PREFIX + "stale.bnk", bank([event({4: 444})]))])
    assert ensure(tmp_path, data, assets, ids=["high"])["fingerprint"] == generated["fingerprint"]
    movie.unlink()
    assert ensure(tmp_path, data, assets, ids=["high"])["status"] == "zero_modification"
    assert stale.is_file()


def test_builder_upgrade_rebuilds_the_cached_voice_patch(tmp_path, monkeypatch):
    from backend import voice_patch_state

    data, assets = prepare(tmp_path)
    current_version = voice_patch_state.BUILDER_VERSION
    monkeypatch.setattr(voice_patch_state, "BUILDER_VERSION", current_version - 1)
    previous = ensure(tmp_path, data, assets)
    monkeypatch.setattr(voice_patch_state, "BUILDER_VERSION", current_version)
    current = ensure(tmp_path, data, assets)
    assert current["status"] == "generated" and current["fingerprint"] != previous["fingerprint"]
    assert ensure(tmp_path, data, assets)["status"] == "reused"


@pytest.mark.parametrize("audio,steam,expected", [
    ("", "schinese", "chinese"), ("en", "schinese", "english(uk)"),
    ("cn", "english", "chinese"), ("de", "schinese", "german"),
    ("", "french", "french(france)"), ("", "russian", "russian"),
    ("unknown", "schinese", ""), ("", "unknown", ""),
])
def test_voice_language_uses_audio_override_before_steam_and_never_interface_language(tmp_path, audio, steam, expected):
    from backend.voice_patch_state import _voice_language

    data = tmp_path / "steamapps" / "common" / "WH3" / "data"
    data.mkdir(parents=True)
    manifest = tmp_path / "steamapps" / "appmanifest_1142710.acf"
    manifest.write_text('"AppState" { "UserConfig" { "language" "' + steam + '" } }', encoding="utf-8")
    preferences = Path(os.environ["APPDATA"]) / "The Creative Assembly" / "Warhammer3" / "scripts" / "preferences.script.txt"
    preferences.parent.mkdir(parents=True)
    preferences.write_text('language_audio "' + audio + '"; # audio override\nlanguage_text "en";\n', encoding="utf-8")
    assert _voice_language(data) == expected


def test_voice_language_change_rebuilds_cache_and_selects_the_matching_translation(tmp_path):
    data = tmp_path / "steamapps" / "common" / "WH3" / "data"
    manifest = tmp_path / "steamapps" / "appmanifest_1142710.acf"
    mods = [source("english", {1: 111}, filename=PREFIX + "english(uk)\\voice.bnk"),
            source("translation", {1: 222}, filename=PREFIX + "chinese\\voice.bnk"),
            source("global", {4: 444}, filename=PREFIX + "global_for_merging.bnk")]
    assets = {}
    for mod in mods:
        path = write_pack(tmp_path / "mods" / (mod.name + ".pack"), byte_mask=3,
                          entries=[(entry.name, entry.payload) for entry in mod.entries])
        assets[mod.name] = make_asset(path, mod.name, "workshop")
    for scope, filename, value in [("english(uk)", "audio_en_bnk.pack", 10), ("chinese", "audio_cn_bnk.pack", 20)]:
        write_pack(data / filename, entries=[(PREFIX + scope + "\\campaign_vo__core.bnk", bank([event({1: value})]))])
    manifest.write_text('"AppState" { "UserConfig" { "language" "schinese" } }', encoding="utf-8")
    chinese = ensure(tmp_path, data, assets)
    assert chinese["status"] == "generated"
    assert chinese["source_diagnostics"]["voice_language"] == "chinese"
    assert ensure(tmp_path, data, assets)["status"] == "reused"
    entries = [entry for entry in read_pack_entries(Path(chinese["path"])) if entry.name.endswith(".bnk")]
    merged, = merged_events(entries)
    assert event_paths(merged) == {(1,): (222, 50, 100), (4,): (444, 50, 100)}
    manifest.write_text('"AppState" { "UserConfig" { "language" "english" } }', encoding="utf-8")
    english = ensure(tmp_path, data, assets)
    assert english["status"] == "generated" and english["fingerprint"] != chinese["fingerprint"]
    entries = [entry for entry in read_pack_entries(Path(english["path"])) if entry.name.endswith(".bnk")]
    merged, = merged_events(entries)
    assert event_paths(merged) == {(1,): (111, 50, 100), (4,): (444, 50, 100)}
    assert ensure(tmp_path, data, assets)["status"] == "reused"


def test_unused_language_banks_need_not_be_installed(tmp_path):
    data, assets = prepare(tmp_path)
    for name, asset in assets.items():
        values = {1: 111, 2: 20} if name == "high" else {1: 10, 2: 222}
        write_pack(Path(asset.path), byte_mask=3, entries=[
            (PREFIX + "chinese\\" + name + ".bnk", bank([event(values)])),
        ])
    assert not (data / "audio_cn_bnk.pack").exists()
    generated = ensure(tmp_path, data, assets)
    assert generated["status"] == "generated"
    assert generated["stats"]["merged_path_count"] == 2


def test_missing_vanilla_and_continuously_changing_sources_fail_before_writing(tmp_path, monkeypatch):
    from backend import voice_patch_state

    data, assets = prepare(tmp_path)
    original_snapshot = voice_patch_state._snapshot
    calls = 0

    def changing(*args):
        nonlocal calls
        sources, records = original_snapshot(*args)
        calls += 1
        records.append({"changed": calls})
        return sources, records

    monkeypatch.setattr(voice_patch_state, "_snapshot", changing)
    with pytest.raises(ValueError, match="连续变化"):
        ensure(tmp_path, data, assets)
    assert not (tmp_path / "runtime" / VOICE_COMPATIBILITY_PATCH_NAME).exists()
    monkeypatch.setattr(voice_patch_state, "_snapshot", original_snapshot)
    (data / "audio_en_bnk.pack").unlink()
    with pytest.raises(ValueError, match="原版对话事件库"):
        ensure(tmp_path, data, assets)


def test_mock_launch_stages_hidden_patch_before_mods_then_removes_it(tmp_path, monkeypatch):
    from backend import api as api_module
    from tests.test_storage_and_api import ApiContractTests

    api, _ = ApiContractTests._prepare_launch_api(tmp_path)
    try:
        monkeypatch.setattr(api_module, "get_subscribed_workshop_items", lambda **kwargs: [api_module.VOICE_FEATURE_WORKSHOP_ID])
        data = tmp_path / "Total War WARHAMMER III/data"
        fixture_data, assets = prepare(tmp_path / "fixtures")
        (data / "audio_en_bnk.pack").write_bytes((fixture_data / "audio_en_bnk.pack").read_bytes())
        for asset in assets.values():
            (data / asset.pack_name).write_bytes(Path(asset.path).read_bytes())
        scan = api.call("scan_mods", [False])
        assert scan["ok"], scan
        ids = [mod["id"] for mod in scan["data"]["mods"] if mod["pack_name"] in {"high.pack", "low.pack"}]
        preference = api.call("save_compatibility_patch_settings", [{"voice_compatibility_patch_enabled": "true"}])
        assert preference["ok"] and preference["data"]["settings"]["voice_compatibility_patch_enabled"]
        monkeypatch.setattr(api_module, "launch_game", lambda *args, **kwargs: {"pid": 123})
        monkeypatch.setattr(api_module, "is_game_running", lambda *args, **kwargs: False)
        monkeypatch.setattr(api_module, "query_workshop_subscription_status", lambda *args, **kwargs: [])
        monkeypatch.setattr(api, "set_game_running", lambda *args, **kwargs: None)
        launch = api.call("launch_game", [ids, scan["data"]["order_token"]])
        assert launch["ok"], launch
        assert launch["data"]["voice_compatibility_patch"]["status"] == "generated"
        assert launch["data"]["launch_plan"]["ordered_mod_ids"] == ["runtime:voice-compatibility", *ids]
        assert (data / VOICE_COMPATIBILITY_PATCH_NAME).is_file()
        scan = api.call("scan_mods", [False])
        patch = next(mod for mod in scan["data"]["mods"] if mod["pack_name"] == VOICE_COMPATIBILITY_PATCH_NAME)
        assert patch["hidden"]
        assert api.call("save_compatibility_patch_settings", [{"voice_compatibility_patch_enabled": False}])["ok"]
        launch = api.call("launch_game", [ids, scan["data"]["order_token"]])
        assert launch["ok"], launch
        assert launch["data"]["launch_plan"]["ordered_mod_ids"] == ids
        assert not (data / VOICE_COMPATIBILITY_PATCH_NAME).exists()
        assert not (api.data_dir / "runtime" / VOICE_COMPATIBILITY_PATCH_NAME).exists()
    finally:
        api.close()


def test_mock_launch_returns_voice_conflict_details_and_never_starts_the_game(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from backend import api as api_module
    from tests.test_storage_and_api import ApiContractTests

    api, _ = ApiContractTests._prepare_launch_api(tmp_path)
    try:
        monkeypatch.setattr(api_module, "get_subscribed_workshop_items",
                            lambda **kwargs: [api_module.VOICE_FEATURE_WORKSHOP_ID])
        monkeypatch.setattr(api_module, "is_game_running", lambda *args, **kwargs: False)
        launch_game = Mock()
        monkeypatch.setattr(api_module, "launch_game", launch_game)
        data = tmp_path / "Total War WARHAMMER III/data"
        fixture_data, assets = prepare(tmp_path / "fixtures")
        (data / "audio_en_bnk.pack").write_bytes((fixture_data / "audio_en_bnk.pack").read_bytes())
        for asset in assets.values():
            (data / asset.pack_name).write_bytes(Path(asset.path).read_bytes())
        write_pack(data / "low.pack", byte_mask=3,
                   entries=[(PREFIX + "low.bnk", bank([event({2: 222}, arguments=(456,))]))])
        scan = api.call("scan_mods", [False])
        assert scan["ok"], scan
        ids = [mod["id"] for mod in scan["data"]["mods"] if mod["pack_name"] in {"high.pack", "low.pack"}]
        assert api.call("save_compatibility_patch_settings", [{"voice_compatibility_patch_enabled": True}])["ok"]
        result = api.call("launch_game", [ids, scan["data"]["order_token"]])
        assert not result["ok"]
        assert result["error"]["voice_compatibility"]["reason"] == "argumentMismatch"
        assert "audio_en_bnk.pack" in result["error"]["message"] and "low.pack" in result["error"]["message"]
        assert "high.pack" not in result["error"]["message"]
        launch_game.assert_not_called()
        assert not (data / VOICE_COMPATIBILITY_PATCH_NAME).exists()
    finally:
        api.close()


def test_subscription_gate_removes_stale_patch_even_with_saved_setting_enabled(tmp_path):
    data, assets = prepare(tmp_path)
    built = ensure(tmp_path, data, assets)
    assert Path(built["path"]).is_file()
    unavailable = ensure(tmp_path, data, assets, subscribed=False)
    assert unavailable["reason"] == "patch_not_subscribed" and not unavailable["path"]
    assert not Path(built["path"]).exists()
    assert ensure(tmp_path, data, assets)["status"] == "generated"


def test_api_requires_current_account_subscription_not_local_marker_files(tmp_path, monkeypatch):
    from backend import api as api_module
    from backend.api import API
    from backend.constants import VOICE_FEATURE_PACK_NAME
    from backend.models import GamePaths
    from backend.scanner import is_internal_feature_mod
    from backend.steamworks_bridge import SteamworksBridgeError

    api = API(tmp_path / "state")
    try:
        # Both a local shell and another account's downloaded copy are insufficient.
        write_pack(tmp_path / "data" / VOICE_FEATURE_PACK_NAME)
        write_pack(tmp_path / "workshop" / "111" / VOICE_FEATURE_PACK_NAME)
        monkeypatch.setattr(api_module, "get_subscribed_workshop_items", lambda **kwargs: [])
        result = api.call("save_compatibility_patch_settings", [{"voice_compatibility_patch_enabled": True}])
        assert result["ok"] and not result["data"]["settings"]["voice_compatibility_patch_enabled"]
        monkeypatch.setattr(api_module, "get_subscribed_workshop_items", lambda **kwargs: [api_module.VOICE_FEATURE_WORKSHOP_ID])
        assert api.call("get_voice_feature_status")["data"]["subscribed"]
        result = api.call("save_compatibility_patch_settings", [{"voice_compatibility_patch_enabled": True}])
        assert result["data"]["settings"]["voice_compatibility_patch_enabled"]

        def unavailable(**kwargs):
            raise SteamworksBridgeError("offline fixture")

        monkeypatch.setattr(api_module, "get_subscribed_workshop_items", unavailable)
        assert not api.call("get_voice_feature_status")["data"]["subscribed"]
        assert not api._voice_feature_status(GamePaths(game_id="three_kingdoms"))["subscribed"]
        asset = make_asset(tmp_path / "data" / VOICE_FEATURE_PACK_NAME, "marker", "data")
        assert is_internal_feature_mod(asset, "warhammer3")
        assert not is_internal_feature_mod(asset, "three_kingdoms")
    finally:
        api.close()
