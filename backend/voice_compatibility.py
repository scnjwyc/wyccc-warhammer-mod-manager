"""Merge WH3 Wwise dialogue state paths without copying or re-encoding audio.

The binary layout is checked against WH3's 0x80000088 banks. Each conflicting
MOD bank keeps its name, BKHD and non-dialogue objects; all copies of a shared
event receive the same merged tree, regardless of which bank loads first.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Sequence

from .game_data import DbSource, GameDataEntry
from .constants import VOICE_COMPATIBILITY_MARKER_ENTRY

VOICE_RUNTIME_MARKER = VOICE_COMPATIBILITY_MARKER_ENTRY
VOICE_SETTING_KEY = "voice_compatibility_patch_enabled"
WH3_BANK_VERSION = 0x80000088


def normalized_name(name: str) -> str:
    return name.replace("/", "\\").casefold()


def bank_scope(name: str) -> str:
    return normalized_name(name).removeprefix("audio\\wwise\\").rpartition("\\")[0]


@dataclass(frozen=True)
class DecisionNode:
    key: int
    weight: int
    probability: int
    audio_id: int | None = None
    children: tuple[DecisionNode, ...] = ()


@dataclass(frozen=True)
class DialogueEvent:
    event_id: int
    probability: int
    arguments: tuple[int, ...]
    argument_types: bytes
    mode: int
    root: DecisionNode
    suffix: bytes


@dataclass(frozen=True)
class EventDefinition:
    priority: int
    source: str
    role: str
    bank: str
    event: DialogueEvent

    def diagnostic(self):
        return {"source": self.source, "role": self.role, "bank": self.bank,
                "arguments": list(self.event.arguments), "argument_types": list(self.event.argument_types)}


class VoiceCompatibilityError(ValueError):
    """Keep provenance across the desktop bridge as well as in the launch log."""

    def __init__(self, reason: str, sources: list[dict], event_id: int | None = None, detail: str = ""):
        self.details = {"reason": reason, "event_id": event_id, "sources": sources, "detail": detail}
        descriptions = {
            "argumentMismatch": "参数结构不一致，无法合并",
            "ambiguousCopies": "同一 MOD 的多份同优先级语音定义不同，无法确定合并来源",
            "treeMismatch": "决策树层级不一致，无法合并",
            "mixedLayout": "通用目录与多个语言目录的语音不同，暂不支持这种混合布局",
            "bankConflict": "同名语音库包含冲突的播放对象或音频资源，无法仅合并对话事件",
            "invalidBank": "语音库损坏或格式不受支持",
            "encodeFailed": "合并后的语音决策树无法写入或回读",
        }
        label = f"语音事件 {event_id}" if event_id is not None else "语音兼容"
        lines = [f"{label}：{descriptions[reason]}"]
        for item in sources:
            role = "原版" if item["role"] == "vanilla" else "MOD"
            line = f"{role}：{item['source']} / {item['bank']}"
            if reason == "argumentMismatch":
                line += f"；参数={item['arguments']}；类型={item['argument_types']}"
            lines.append(line)
        if detail:
            lines.append(detail)
        super().__init__("\n".join(lines))


def parse_dialogue_event(payload: bytes) -> DialogueEvent:
    def invalid():
        raise ValueError("语音对话事件的决策树损坏或格式不受支持")

    if len(payload) < 14:
        invalid()
    event_id, probability, depth = struct.unpack_from("<IBI", payload)
    if not 1 <= depth <= 32:
        invalid()
    size_offset = 9 + depth * 5
    tree_offset = size_offset + 5
    if tree_offset > len(payload):
        invalid()
    tree_size = struct.unpack_from("<I", payload, size_offset)[0]
    if not tree_size or tree_size % 12 or tree_offset + tree_size > len(payload):
        invalid()
    count = tree_size // 12
    visited: set[int] = set()

    def node(index: int, level: int) -> DecisionNode:
        if not 0 <= index < count or index in visited:
            invalid()
        visited.add(index)
        key, value, weight, chance = struct.unpack_from("<IIHH", payload, tree_offset + index * 12)
        first, length = value & 0xFFFF, value >> 16
        # WH3 also uses terminal audio IDs before the declared maximum depth.
        terminal = not length or first <= index or first + length > count
        if level == depth or (level > 0 and terminal):
            return DecisionNode(key, weight, chance, value)
        if terminal:
            invalid()
        children = tuple(node(i, level + 1) for i in range(first, first + length))
        keys = [child.key for child in children]
        if keys != sorted(set(keys)):
            invalid()
        return DecisionNode(key, weight, chance, children=children)

    root = node(0, 0)
    if len(visited) != count:
        invalid()
    return DialogueEvent(
        event_id, probability,
        struct.unpack_from(f"<{depth}I", payload, 9),
        payload[9 + depth * 4:size_offset], payload[size_offset + 4], root,
        payload[tree_offset + tree_size:],
    )


def encode_dialogue_event(event: DialogueEvent) -> bytes:
    records: list[bytes] = [b""]

    def write(node: DecisionNode, index: int):
        if node.audio_id is not None:
            value = node.audio_id
        else:
            first, length = len(records), len(node.children)
            if first > 0xFFFF or not 0 < length <= 0xFFFF:
                raise ValueError("合并后的语音决策树超过 Wwise 索引容量")
            records.extend([b""] * length)
            value = first | (length << 16)
            for i, child in enumerate(node.children, first):
                write(child, i)
        records[index] = struct.pack("<IIHH", node.key, value, node.weight, node.probability)

    write(event.root, 0)
    tree = b"".join(records)
    return b"".join((
        struct.pack("<IBI", event.event_id, event.probability, len(event.arguments)),
        struct.pack(f"<{len(event.arguments)}I", *event.arguments),
        event.argument_types, struct.pack("<IB", len(tree), event.mode), tree, event.suffix,
    ))


@dataclass(frozen=True)
class SoundBank:
    chunks: tuple[tuple[bytes, bytes], ...]
    objects: tuple[tuple[int, bytes], ...]

    def dialogues(self) -> dict[int, DialogueEvent]:
        events = [parse_dialogue_event(payload) for kind, payload in self.objects if kind == 15]
        if len({event.event_id for event in events}) != len(events):
            raise ValueError("语音库包含重复的对话事件 ID")
        return {event.event_id: event for event in events}

    def replace_dialogues(self, replacements: dict[int, bytes]) -> bytes:
        objects = [
            (kind, replacements.get(struct.unpack_from("<I", payload)[0], payload) if kind == 15 else payload)
            for kind, payload in self.objects
        ]
        existing = {struct.unpack_from("<I", payload)[0] for kind, payload in objects if kind == 15}
        objects.extend((15, replacements[event_id]) for event_id in sorted(replacements) if event_id not in existing)
        hirc = struct.pack("<I", len(objects)) + b"".join(
            struct.pack("<BI", kind, len(payload)) + payload for kind, payload in objects
        )
        return b"".join(
            tag + struct.pack("<I", len(hirc if tag == b"HIRC" else data))
            + (hirc if tag == b"HIRC" else data)
            for tag, data in self.chunks
        )


def parse_soundbank(payload: bytes) -> SoundBank:
    chunks, objects = [], []
    offset = 0
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise ValueError("Wwise 语音库分块不完整")
        tag, size = struct.unpack_from("<4sI", payload, offset)
        offset += 8
        if offset + size > len(payload):
            raise ValueError("Wwise 语音库分块长度无效")
        data = payload[offset:offset + size]
        if tag in {b"BKHD", b"HIRC"} and any(existing == tag for existing, _ in chunks):
            raise ValueError("Wwise 语音库包含重复分块")
        chunks.append((tag, data))
        offset += size
        if tag != b"HIRC":
            continue
        if len(data) < 4:
            raise ValueError("Wwise 语音库对象清单不完整")
        count = struct.unpack_from("<I", data)[0]
        pos = 4
        for _ in range(count):
            if pos + 5 > len(data):
                raise ValueError("Wwise 语音库对象头不完整")
            kind, length = struct.unpack_from("<BI", data, pos)
            pos += 5
            if length < 4 or pos + length > len(data):
                raise ValueError("Wwise 语音库对象长度无效")
            objects.append((kind, data[pos:pos + length]))
            pos += length
        if pos != len(data):
            raise ValueError("Wwise 语音库对象清单长度无效")
    if not chunks or chunks[0][0] != b"BKHD" or len(chunks[0][1]) < 16:
        raise ValueError("Wwise 语音库缺少 BKHD")
    if any(kind == 15 for kind, _ in objects):
        if struct.unpack_from("<I", chunks[0][1])[0] != WH3_BANK_VERSION:
            raise ValueError("仅支持战锤 3 的 Wwise 0x80000088 语音库")
    return SoundBank(tuple(chunks), tuple(objects))


def event_paths(event: DialogueEvent) -> dict[tuple[int, ...], tuple[int, int, int]]:
    result = {}

    def walk(node: DecisionNode, path: tuple[int, ...]):
        if node.audio_id is not None:
            result[path] = (node.audio_id, node.weight, node.probability)
        for child in node.children:
            walk(child, (*path, child.key))

    walk(event.root, ())
    return result


def _overlay(current: DecisionNode, incoming: DecisionNode, baseline: DecisionNode | None) -> DecisionNode:
    # A pre-merged vanilla branch is fallback data, not an explicit MOD edit.
    if incoming == baseline:
        return current
    if incoming.audio_id is not None:
        return incoming
    if current.audio_id is not None:
        raise ValueError("同一语音事件的决策树层级不一致")
    children = {node.key: node for node in current.children}
    base_children = {node.key: node for node in baseline.children} if baseline else {}
    for child in incoming.children:
        original = base_children.get(child.key)
        if child == original:
            continue
        if child.key in children:
            children[child.key] = _overlay(children[child.key], child, original)
        elif original is not None and child.audio_id is None:
            # A fallback language can have vanilla branches absent from the
            # current language. Only carry its authored descendants across.
            added = _overlay(replace(child, children=()), child, original)
            if added.children:
                children[child.key] = added
        else:
            children[child.key] = child
    metadata = current if baseline and (
        incoming.weight, incoming.probability
    ) == (baseline.weight, baseline.probability) else incoming
    return replace(metadata, children=tuple(children[key] for key in sorted(children)))


def _source_events(items):
    # Prefer explicit authoring trees over their pre-merged testing copies.
    selected = {}
    for item in sorted(items, key=lambda item: (
        item.priority, "_for_merging" not in item.bank, item.bank,
    )):
        previous = selected.setdefault(item.priority, item)
        if ("_for_merging" in previous.bank) == ("_for_merging" in item.bank) and previous.event != item.event:
            raise VoiceCompatibilityError("ambiguousCopies", [previous.diagnostic(), item.diagnostic()],
                                          item.event.event_id)
    return selected


def _baseline_event(base, key):
    event_id = key[1]
    return (base.get(key) or base.get(("english(uk)", event_id)) or base.get(("chinese", event_id))
            or next((event for (_, base_id), event in base.items() if base_id == event_id), None))


def _extend_trailing_arguments(event: DialogueEvent, baseline: DialogueEvent) -> DialogueEvent:
    depth = len(event.arguments)
    missing = len(baseline.arguments) - depth
    if (missing <= 0 or event.arguments != baseline.arguments[:depth]
            or event.argument_types != baseline.argument_types[:depth]
            or any(kind != 1 for kind in baseline.argument_types[depth:])):
        return event

    def extend(node: DecisionNode, level: int) -> DecisionNode:
        if node.audio_id is not None:
            # Existing early terminals already ignore all remaining conditions.
            if level < depth:
                return node
            # State key 0 is Wwise Any. Keep the terminal's playback ID,
            # weight and probability; only add unconstrained trailing states.
            child = replace(node, key=0)
            for _ in range(missing - 1):
                child = DecisionNode(0, 50, 100, children=(child,))
            return replace(node, audio_id=None, children=(child,))
        return replace(node, children=tuple(extend(child, level + 1) for child in node.children))

    return replace(event, arguments=baseline.arguments, argument_types=baseline.argument_types,
                   root=extend(event.root, 0))


def _only_adds_branches(event: DialogueEvent, baseline: DialogueEvent) -> bool:
    if replace(event, root=baseline.root) != baseline:
        return False

    def preserves(node, original):
        if replace(node, children=original.children) != original:
            return False
        children = {child.key: child for child in node.children}
        return all(child.key in children and preserves(children[child.key], child)
                   for child in original.children)

    return preserves(event.root, baseline.root)


def _localized_copies_agree(localized, candidates, base) -> bool:
    baselines = [_baseline_event(base, key) for key in localized]
    baseline = baselines[0].event if baselines[0] else None
    if any((item.event if item else None) != baseline for item in baselines[1:]):
        return False
    selected = [_source_events(candidates[key]) for key in localized]
    priorities = {priority for group in selected for priority in group}
    shared = list(candidates.get(("", localized[0][1]), ()))
    for priority in priorities:
        copies = [group[priority] for group in selected if priority in group]
        if any(item.event != copies[0].event for item in copies[1:]):
            return False
        # Complete, unchanged vanilla fallbacks with only new branches can be
        # shared across languages, as with English-only Audio Mixer scaffolding.
        if len(copies) != len(selected) and (
            baseline is not None and not any("_for_merging" in item.bank for item in copies)
            and _only_adds_branches(copies[0].event, baseline)
        ):
            shared.append(copies[0])

    def merged(items):
        by_source = _source_events(items)
        ordered = [by_source[priority] for priority in sorted(by_source, reverse=True)]
        root = baseline.root if baseline else ordered[0].event.root
        for item in ordered:
            root = _overlay(root, item.event.root,
                            None if "_for_merging" in item.bank else (baseline.root if baseline else None))
        return replace(ordered[-1].event, root=root)

    # Separately packaged translations can carry the same authored changes
    # with newer vanilla fallbacks. Compare the actual priority-ordered result
    # in every language against the combined result before sharing a global tree.
    try:
        contributions = [
            {("_for_merging" in item.bank, merged([item])) for item in group.values()}
            for group in selected
        ]
        # One language must already contain every authored contribution, allowing
        # equivalent translations from different sources to stand for each other.
        # Never assemble unrelated additions from separate language-only packs.
        if not any(group == set().union(*contributions) for group in contributions):
            return False
        combined = merged([*shared, *(item for key in localized for item in candidates[key])])
        return all(merged([*shared, *candidates[key]]) == combined for key in localized)
    except VoiceCompatibilityError:
        raise
    except ValueError:
        return False


def build_voice_compatibility_entries(
    sources: Sequence[DbSource], *, language_scope: str = "",
) -> tuple[list[GameDataEntry], dict]:
    """Sources are ordered from highest to lowest Pack priority; vanilla is fallback."""
    banks = []
    base: dict[tuple[str, int], EventDefinition] = {}
    effective_banks: dict[str, SoundBank] = {}
    effective_events: dict[str, dict[int, DialogueEvent]] = {}
    bank_origins = {}
    localized_bank_names = set()
    candidates = defaultdict(list)
    for priority, source in enumerate(sources):
        for entry in sorted(source.entries, key=lambda item: normalized_name(item.name)):
            name = normalized_name(entry.name)
            if not name.startswith("audio\\wwise\\") or not name.endswith(".bnk"):
                continue
            try:
                bank = parse_soundbank(entry.payload)
                events = bank.dialogues()
            except ValueError as exc:
                raise VoiceCompatibilityError("invalidBank", [
                    {"source": source.name, "role": source.role, "bank": entry.name},
                ], detail=str(exc)) from exc
            scope = bank_scope(name)
            if language_scope and scope == language_scope:
                localized_bank_names.add(name.rpartition("\\")[2])
            if source.role == "vanilla":
                for event_id, event in events.items():
                    base.setdefault((scope, event_id),
                                    EventDefinition(priority, source.name, source.role, name, event))
                continue
            winner = effective_banks.get(name)
            if winner is None:
                effective_banks[name] = bank
                bank_origins[name] = {"source": source.name, "role": source.role, "bank": entry.name}
                effective_events[name] = dict(events)
                banks.append((entry, bank, effective_events[name], scope))
            elif events:
                # Same-path banks can be safely combined when their playback
                # object IDs do not disagree. Keep the higher-priority copy
                # for duplicate IDs and append disjoint objects from the
                # lower-priority copy so its dialogue events remain reachable.
                winner_objects = {payload[:4]: (kind, payload) for kind, payload in winner.objects if kind != 15}
                incoming_objects = {payload[:4]: (kind, payload) for kind, payload in bank.objects if kind != 15}
                if any(winner_objects.get(object_id) != value
                       for object_id, value in incoming_objects.items()
                       if object_id in winner_objects) or any(
                    tag in {b"DATA", b"DIDX"} and (tag, data) not in winner.chunks for tag, data in bank.chunks
                ):
                    raise VoiceCompatibilityError("bankConflict", [bank_origins[name],
                        {"source": source.name, "role": source.role, "bank": entry.name}])
                merged_objects = list(winner.objects)
                for kind, payload in bank.objects:
                    if kind != 15 and payload[:4] not in winner_objects:
                        merged_objects.append((kind, payload))
                        winner_objects[payload[:4]] = (kind, payload)
                effective_banks[name] = replace(winner, objects=tuple(merged_objects))
                for event_id, event in events.items():
                    effective_events[name].setdefault(event_id, event)
            for event_id, event in events.items():
                candidates[(scope, event_id)].append(EventDefinition(priority, source.name, source.role, name, event))

    extended_keys = set()
    for key, items in candidates.items():
        baseline = _baseline_event(base, key)
        if baseline is None:
            continue
        extended = [replace(item, event=_extend_trailing_arguments(item.event, baseline.event)) for item in items]
        if extended != items:
            extended_keys.add(key)
            candidates[key] = extended

    replacements = {}
    stats = {"voice_pack_count": 0, "merged_event_count": 0, "merged_path_count": 0,
             "conflicting_path_count": 0, "patched_bank_count": 0}
    voice_sources = {item.priority for items in candidates.values() for item in items}
    stats["voice_pack_count"] = len(voice_sources)
    event_keys = defaultdict(list)
    for key in candidates:
        event_keys[key[1]].append(key)
    merge_groups = []
    for event_id, keys in event_keys.items():
        if ("", event_id) in candidates:
            # A shared event in a global bank must receive the same tree as its
            # localized copies; separate language-only events remain isolated.
            key = next((key for key in keys if key[0]), keys[0])
            merge_groups.append((key, keys, [item for target in keys for item in candidates[target]]))
        else:
            merge_groups.extend((key, [key], candidates[key]) for key in keys)
    for key, target_keys, items in merge_groups:
        if len({item.priority for item in items}) < 2 and not extended_keys.intersection(target_keys):
            continue
        event_id = key[1]
        language_selected = bool(language_scope and ("", event_id) in candidates)
        if language_selected:
            key = (language_scope, event_id)
        # Validate every copy that will be replaced, including discarded testing
        # copies. Replacing an incompatible copy used to conceal broken inputs.
        baseline_definition = _baseline_event(base, key)
        definitions = [*items, *([baseline_definition] if baseline_definition else [])]
        expected = baseline_definition or items[0]
        for item in definitions:
            if (item.event.arguments, item.event.argument_types) != (
                expected.event.arguments, expected.event.argument_types
            ):
                raise VoiceCompatibilityError("argumentMismatch", [expected.diagnostic(), item.diagnostic()], event_id)
        localized = [key for key in target_keys if key[0]]
        if len(localized) > 1 and not language_selected:
            if not _localized_copies_agree(localized, candidates, base):
                involved = [*items, *(baseline for target in localized
                                      if (baseline := _baseline_event(base, target)))]
                raise VoiceCompatibilityError("mixedLayout", [item.diagnostic() for item in involved], event_id)
        if language_selected:
            # Select the game's localized file before merging MOD priorities.
            # An English-only bank is fallback; a same-name localized bank,
            # even from another Pack, takes its place for the current language.
            items = [item for item in items if bank_scope(item.bank) in {"", language_scope}
                     or (bank_scope(item.bank) == "english(uk)"
                         and item.bank.rpartition("\\")[2] not in localized_bank_names)]
        baseline = baseline_definition.event if baseline_definition else None
        by_source = _source_events(items)
        selected = [by_source[priority] for priority in sorted(by_source, reverse=True)]
        prototype = baseline if language_selected and baseline else selected[-1].event
        root = baseline.root if baseline else selected[0].event.root
        edited_paths = {}
        baseline_paths = event_paths(baseline) if baseline else {}
        applied = [baseline_definition] if baseline_definition else [selected[0]]
        for item in selected:
            event = item.event
            explicit = "_for_merging" in item.bank
            incoming_base = baseline
            if language_selected:
                definition = _baseline_event(base, (bank_scope(item.bank), event_id))
                incoming_base = definition.event if definition else None
                # Unchanged English fallback metadata must not replace the
                # current language's vanilla metadata.
                prototype = replace(event, **{
                    field: (getattr(prototype, field) if not explicit and incoming_base
                            and getattr(event, field) == getattr(incoming_base, field) else getattr(event, field))
                    for field in ("probability", "mode", "suffix")
                })
            incoming_base_paths = event_paths(incoming_base) if incoming_base else baseline_paths
            for path, value in event_paths(event).items():
                if explicit or incoming_base_paths.get(path) != value:
                    if path in edited_paths and edited_paths[path] != value:
                        stats["conflicting_path_count"] += 1
                    edited_paths[path] = value
            try:
                root = _overlay(root, event.root, None if explicit else (incoming_base.root if incoming_base else None))
            except ValueError as exc:
                raise VoiceCompatibilityError("treeMismatch", [origin.diagnostic() for origin in [*applied, item]],
                                              event_id) from exc
            if item not in applied:
                applied.append(item)
        merged = replace(prototype, root=root)
        try:
            payload = encode_dialogue_event(merged)
            if parse_dialogue_event(payload) != merged:
                raise ValueError(f"语音事件 {event_id} 合并回读失败")
        except ValueError as exc:
            raise VoiceCompatibilityError("encodeFailed", [item.diagnostic() for item in selected],
                                          event_id, str(exc)) from exc
        replacements.update(dict.fromkeys(target_keys, payload))
        stats["merged_event_count"] += 1
        stats["merged_path_count"] += len(event_paths(merged))

    entries = []
    for entry, original_bank, events, scope in banks:
        bank = effective_banks[normalized_name(entry.name)]
        original_ids = {struct.unpack_from("<I", payload)[0] for kind, payload in bank.objects if kind == 15}
        changed = {event_id: replacements[(scope, event_id)] for event_id in events
                   if (scope, event_id) in replacements}
        changed.update({event_id: encode_dialogue_event(event) for event_id, event in events.items()
                        if event_id not in original_ids and event_id not in changed})
        if changed or bank != original_bank:
            payload = bank.replace_dialogues(changed)
            if payload != entry.payload:
                entries.append(GameDataEntry(entry.name, payload))
    stats["patched_bank_count"] = len(entries)
    return entries, stats
