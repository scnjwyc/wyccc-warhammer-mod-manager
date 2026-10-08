"""Offline readback and reference checks; never starts the game or edits source Packs."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.game_data import DbSource, GameDataEntry, _collect_effective_rows, parse_db_table  # noqa: E402
from backend.settlement_schema import SETTLEMENT_SCHEMAS  # noqa: E402
from backend.start_options import PackEntry, read_pack_entries, write_pfh5_pack  # noqa: E402
from backend.tier5_compatibility import (  # noqa: E402
    TIER5_SOURCE_PREFIXES, _whole_file_sources, build_tier5_compatibility_entries,
)


def validate(sources, output):
    built = build_tier5_compatibility_entries(sources)
    write_pfh5_pack(output, [PackEntry(e.name, e.payload) for e in built.entries])
    readback = read_pack_entries(output)
    assert [(e.name, e.payload) for e in readback] == [(e.name, e.payload) for e in built.entries]
    effective = _collect_effective_rows(_whole_file_sources([
        DbSource("generated", [GameDataEntry(e.name, e.payload) for e in readback]), *sources,
    ]), set(SETTLEMENT_SCHEMAS))
    levels = {k: c.row.values for k, c in effective['building_levels_tables'].items()}
    models = {c.row.values['model_id'] for c in effective['campaign_settlement_display_buildings_tables'].values()}
    registry = set(effective['campaign_settlement_display_building_model_ids_tables'])
    chains = set(effective['building_chains_tables'])
    changed_levels = []
    rows = 0
    for entry in readback:
        table = entry.name.replace('/', '\\').split('\\')[1]
        parsed = parse_db_table(table, entry.payload)
        rows += len(parsed.rows)
        for record in parsed.rows:
            row = record.values
            if table == 'building_levels_tables':
                assert row['chain'] in chains, row
                changed_levels.append(row['level_name'])
            elif table == 'campaign_settlement_display_building_ids_tables':
                assert row['building_level_key'] in levels, row
                assert row['building_model_id'] in registry and row['building_model_id'] in models, row
            elif table == 'building_culture_variants_tables':
                assert row['building'] in levels, row
            elif table == 'building_upgrades_junction_tables':
                assert row['from'] in levels and row['to'] in levels, row
            elif table == 'campaign_settlement_display_buildings_tables':
                assert row['model_id'] in registry, row
    modified_chains = {levels[k]['chain'] for k in changed_levels}
    variants = effective['building_culture_variants_tables']
    variant_buildings = {c.row.values['building'] for c in variants.values()}
    missing_ui = sorted(k for k, r in levels.items() if r['chain'] in modified_chains and k not in variant_buildings)
    assert not missing_ui, ('display buildings without UI', missing_ui[:8])
    assert len(variants) >= len(levels), ('building UI initializer bound', len(variants), len(levels))
    upgrades = {(c.row.values['from'], c.row.values['to']) for c in effective['building_upgrades_junction_tables'].values()}
    display_levels = {c.row.values['building_level_key'] for c in effective['campaign_settlement_display_building_ids_tables'].values()}
    for chain in modified_chains:
        group = {int(r['level']): k for k, r in levels.items() if r['chain'] == chain}
        assert set(group) == set(range(6)), (chain, group)
        assert all(building in display_levels for building in group.values()), chain
        assert all((group[t], group[t + 1]) in upgrades for t in range(5)), chain
    return {"stats": built.stats, "pack": str(output), "entry_count": len(readback),
            "readback_rows": rows, "complete_modified_chains": len(modified_chains),
            "effective_building_levels": len(levels), "effective_culture_variants": len(variants),
            "all_building_indices_fit": True, "missing_display_ui": 0,
            "reference_failures": 0, "byte_readback_matches": True, "game_test": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vanilla', required=True)
    parser.add_argument('--pack', action='append', default=[])
    parser.add_argument('--overlay')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    sources = []
    for path in [*args.pack, args.vanilla]:
        entries = [GameDataEntry(e.name, e.payload) for e in read_pack_entries(Path(path), TIER5_SOURCE_PREFIXES)]
        sources.append(DbSource(Path(path).name, entries, role='vanilla' if path == args.vanilla else 'mod'))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results = [validate(sources, output / 'sample_overlay_false.pack')]
    if args.overlay:
        entries = [GameDataEntry(e.name, e.payload) for e in read_pack_entries(Path(args.overlay), TIER5_SOURCE_PREFIXES)]
        results.append(validate([DbSource(Path(args.overlay).name, entries), *sources], output / 'sample_overlay_true.pack'))
    (output / 'sample_verification.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
