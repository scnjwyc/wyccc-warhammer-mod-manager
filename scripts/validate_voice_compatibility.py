"""Offline real-Pack validation; never stages files in Data or launches a game.

Run from the project root with ``python -m scripts.validate_voice_compatibility``.
Inputs are read-only. Output consists of a generated Pack, cache and JSON proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.models import ModAsset
from backend.start_options import read_pack_entries
from backend.voice_compatibility import bank_scope, build_voice_compatibility_entries, event_paths, parse_soundbank
from backend.voice_patch_state import _snapshot, _voice_language, ensure_voice_compatibility_patch


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(data_path: Path, packs: list[Path], reference: Path, output_dir: Path):
    originals = [*packs, reference]
    hashes = {str(path): digest(path) for path in originals}
    assets = {str(i): ModAsset(str(i), path.name, path.stem, str(path), str(path.parent), "workshop")
              for i, path in enumerate(packs)}
    settings = {"voice_compatibility_patch_enabled": True}
    result = ensure_voice_compatibility_patch(output_dir, data_path, assets, list(assets), "validation", settings,
                                              subscribed=True)
    assert result["status"] in {"generated", "reused"}, result
    cached = ensure_voice_compatibility_patch(output_dir, data_path, assets, list(assets), "validation", settings,
                                              subscribed=True)
    assert cached["status"] == "reused", cached
    output = Path(result["path"])
    entries = read_pack_entries(output)
    language_scope = _voice_language(data_path)
    sources, _ = _snapshot(data_path, assets, list(assets), language_scope)
    current_entries, current_stats = build_voice_compatibility_entries(sources, language_scope=language_scope)
    assert current_stats == result["stats"]
    assert {e.name: e.payload for e in current_entries} == {
        e.name: e.payload for e in entries if e.name.casefold().endswith(".bnk")
    }, "Cached Pack differs from the current builder"
    reference_events = {}
    for entry in read_pack_entries(reference, "audio\\wwise\\"):
        if entry.name.casefold().endswith(".bnk"):
            for event_id, event in parse_soundbank(entry.payload).dialogues().items():
                reference_events[(bank_scope(entry.name), event_id)] = event
    merged = {}
    consistent_copies = 0
    for entry in entries:
        if not entry.name.casefold().endswith(".bnk"):
            continue
        for event_id, event in parse_soundbank(entry.payload).dialogues().items():
            key = (bank_scope(entry.name), event_id)
            if key not in reference_events:
                continue
            if key in merged:
                assert merged[key] == event, (entry.name, event_id, "inconsistent event copies")
                consistent_copies += 1
            merged[key] = event
    path_count, differences, additional = 0, [], 0
    mode_differences, tree_metadata_differences = [], []
    for key, expected_event in reference_events.items():
        actual_event = merged[key]
        expected, actual = event_paths(expected_event), event_paths(actual_event)
        for path, value in expected.items():
            path_count += 1
            if actual.get(path) != value:
                differences.append({"scope": key[0], "event_id": key[1], "path": path,
                                    "expected": value, "actual": actual.get(path)})
        additional += len(set(actual) - set(expected))
        if expected_event.root != actual_event.root:
            tree_metadata_differences.append({"scope": key[0], "event_id": key[1]})
        if expected_event.mode != actual_event.mode:
            mode_differences.append({"scope": key[0], "event_id": key[1],
                                     "reference": expected_event.mode, "generated": actual_event.mode})
    assert not differences, differences[:10]
    assert hashes == {str(path): digest(path) for path in originals}, "Original Packs changed"
    report = {
        "kind": "offline_real_pack_validation", "result": result, "cache_status": cached["status"],
        "source_sha256_before_and_after": hashes,
        "original_packs_unchanged": True, "game_launched": False,
        "current_builder_output_matches_cached_pack": True,
        "generated_pack_size": output.stat().st_size, "generated_pack_sha256": digest(output),
        "reference_event_count": len(reference_events), "reference_path_count": path_count,
        "different_paths": differences, "additional_paths": additional,
        "consistent_event_copies": consistent_copies,
        "tree_metadata_differences": tree_metadata_differences, "mode_differences": mode_differences,
        "entries": [{"name": entry.name, "size": len(entry.payload),
                     "sha256": hashlib.sha256(entry.payload).hexdigest()} for entry in entries],
    }
    report_path = output_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "stats": result["stats"],
                      "reference_paths": path_count, "different_paths": len(differences),
                      "tree_metadata_differences": len(tree_metadata_differences),
                      "mode_differences": len(mode_differences), "bytes": output.stat().st_size},
                     ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--pack", required=True, action="append", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    validate(args.data.resolve(), [path.resolve() for path in args.pack],
             args.reference.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
