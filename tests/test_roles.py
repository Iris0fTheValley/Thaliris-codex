from __future__ import annotations
from tests.host_maintenance_test_support import authorized_host_install, authorized_host_uninstall, legacy_file_hashes

from tests.support.history import historical_blob

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import types

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, lifecycle, roles


def _sentinel_definition() -> roles.RoleDefinition:
    return roles.RoleDefinition(
        id="sentinel",
        default_model="gpt-5.6-luna",
        reasoning_effort="high",
        native_profile="thaliris-sentinel",
        instructions="sentinel instructions",
        repo_write_allowed=True,
        allowed_delegation_targets=frozenset(),
        controller_control_state_modification_allowed=False,
        generated_profile=True,
        profile_filename="thaliris-sentinel.toml",
    )


def _formal_sentinel_registration() -> tuple[roles.RoleSpec, roles.CodexExecutionBinding]:
    return (
        roles.RoleSpec(
            id="formal-sentinel",
            purpose="A seventh role used to prove registry propagation.",
            instructions="formal sentinel instructions",
        ),
        roles.CodexExecutionBinding(
            model="gpt-5.6-luna",
            reasoning_effort="high",
            native_profile="thaliris-formal-sentinel",
            native_aliases=("formal-sentinel-alias",),
            generated_profile=True,
            profile_filename="thaliris-formal-sentinel.toml",
            repo_write_allowed=False,
            allowed_delegation_targets=frozenset(),
            controller_control_state_modification_allowed=False,
            telemetry_notice=True,
            write_denial_code="THALIRIS_FORMAL_SENTINEL_WRITE_BLOCKED",
            write_denial_reason="Formal sentinel must remain read-only.",
        ),
    )


def test_registry_is_authoritative_for_native_profiles_and_mechanical_facts() -> None:
    native = roles.native_role_definitions()
    assert [definition.id for definition in native] == [
        "investigator", "curator", "reasoning-specialist", "implementer", "focused-implementer", "verifier", "reviewer",
    ]
    for definition in native:
        assert definition.native_profile == f"thaliris-{definition.id}"
        assert definition.profile_filename == f"thaliris-{definition.id}.toml"
        assert definition.instructions
        assert definition.reasoning_effort
        assert definition.legacy_profile_hashes or definition.id == "focused-implementer"
    assert roles.native_agent_roles() == {
        profile: definition.id for definition in native
        for profile in (definition.native_profile, definition.astra_medium_native_profile, definition.exceptional_native_profile) if profile
    }
    expected_profiles = {
        definition.profile_filename: (
            definition.default_model, definition.reasoning_effort, definition.id
        )
        for definition in native
    }
    for definition in native:
        if definition.astra_medium_native_profile:
            expected_profiles[definition.astra_medium_native_profile + ".toml"] = ("gpt-6-astra", "medium", definition.id)
        if definition.exceptional_native_profile:
            expected_profiles[definition.exceptional_native_profile + ".toml"] = ("gpt-6-astra", "xhigh", definition.id)
    assert roles.agent_profiles() == expected_profiles
    assert roles.notice_roles() == {"curator", "reasoning-specialist", "verifier", "reviewer"}


def test_profile_defaults_and_static_astra_selection_are_fixed() -> None:
    assert codex_adapter._ROLE_MODEL_DEFAULTS == {
        "controller": (None, None),
        "investigator": ("gpt-6-luna", "xhigh"),
        "curator": ("gpt-6-luna", "xhigh"),
        "reasoning-specialist": ("gpt-6.1-sol", "high"),
        "implementer": ("gpt-6-luna", "xhigh"),
        "focused-implementer": ("gpt-6.1-sol", "high"),
        "verifier": ("gpt-6-luna", "xhigh"),
        "reviewer": ("gpt-6.1-sol", "high"),
    }
    assert len(roles.native_codex_role_map()) == len(set(roles.native_codex_role_map()))
    for name, (model, effort, role) in roles.agent_profiles().items():
        value = tomllib.loads(codex_adapter._agent_profile(name.removesuffix(".toml"), role, model, effort).decode())
        assert (value["name"], value["model"], value["model_reasoning_effort"]) == (name.removesuffix(".toml"), model, effort)
        assert roles.resolve_native_profile(value["name"]).id == role
        assert value["developer_instructions"] == roles.profile_instructions(role, name.removesuffix(".toml"))
        assert "Never select your own model or reasoning effort" not in value["developer_instructions"]
        assert "model choice follows the current semantic slice" not in value["developer_instructions"]
        assert "Facts unknown route to Investigator" not in value["developer_instructions"]
        if role in {"implementer", "focused-implementer"}:
            assert roles._EXECUTOR_INSTRUCTIONS in value["developer_instructions"]
            assert "decision-changing unknown" in value["developer_instructions"]
            assert "verification" in value["developer_instructions"].lower()
    for role in ("focused-implementer", "reasoning-specialist"):
        for effort, suffix in (("medium", "astra-medium"), ("xhigh", "xhigh")):
            name = f"thaliris-{role}-{suffix}.toml"
            assert roles.agent_profiles()[name] == ("gpt-6-astra", effort, role)
            assert codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(name, frozenset())


def test_ba84553_profiles_migrate_by_exact_filename_and_preserve_edits(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    # These bytes are rendered by the immutable ba84553 registry/adapter
    # revision; the host files were independently compared before pinning.
    expected = {
        "thaliris-curator.toml": "25b4addb9686086fe406076a122423b64017bff12bb8a49b7ef3940562a02791",
        "thaliris-focused-implementer-astra-medium.toml": "a47c1cdca975dd10c4a0260f0a4b470b08c24b09d78ce58f40b49ac0f2cf031c",
        "thaliris-focused-implementer-xhigh.toml": "9a508f3a20aa0ead6dfe5a497a28360bb80fcbae0b517449328ad72082459ed0",
        "thaliris-focused-implementer.toml": "78adaf70f2719f7d1eae4f77fd59510f26ae4390e9143e33bfd97e940dece36b",
        "thaliris-implementer.toml": "652bc0ec379f699307f52acdd8f3112f423aa885c19bff0244ac294ee4ae1d35",
        "thaliris-investigator.toml": "1dbe2cca46484bcd31e13ebf6f3e7422dd477d4522d72da00360b8fd558d28b4",
        "thaliris-reasoning-specialist-astra-medium.toml": "cf81e133c7382584a16852c22eedffe7a5c6a67388f64421b073ec721754fadd",
        "thaliris-reasoning-specialist-xhigh.toml": "b88730b4bd7d9a18d5e57c95db2316c895f44c74cea32f0eba5810bbdee38211",
        "thaliris-reasoning-specialist.toml": "ed9b227397dabf75552067d54663f6cac853d96f592e07b511e564493ee13d51",
        "thaliris-reviewer.toml": "39c4396ea903bc58477dc329f670a34cc8e2b553c7a9e604fb85c8bfdfba0624",
        "thaliris-verifier.toml": "67f965ebb7566330cdf771bfb78da20d4a0248c34c231b6ec336657bb529df0f",
    }
    assert codex_adapter._BA84553_GENERATED_AGENT_PROFILE_HASHES == expected
    assert {
        name: digest
        for name, digest in expected.items()
        if digest in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES[name]
    } == expected

    tracked = (
        "thaliris-focused-implementer.toml",
        "thaliris-focused-implementer-astra-medium.toml",
        "thaliris-focused-implementer-xhigh.toml",
        "thaliris-reasoning-specialist-astra-medium.toml",
        "thaliris-reasoning-specialist-xhigh.toml",
        "thaliris-verifier.toml",
    )
    historical: dict[str, bytes] = {}
    for name in tracked:
        value = _historical_profile("ba84553", name)
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other = "thaliris-verifier.toml" if name != "thaliris-verifier.toml" else "thaliris-reviewer.toml"
        assert codex_adapter._agent_profile_state(value, other) == "user"
        historical[name] = value

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    root = _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in historical.items():
        (agents / name).write_bytes(value)
    edited_name = "thaliris-focused-implementer-xhigh.toml"
    edited = historical[edited_name] + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in set(tracked) - {edited_name}]
        ),
    )

    assert (agents / edited_name).read_bytes() == edited
    assert any(str(agents / edited_name) in item for item in result["manual_action_required"])
    assert result["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before


def test_1f98dae_profiles_migrate_by_exact_filename_and_preserve_edits(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    # These bytes are rendered by the immutable 1f98dae revision immediately
    # before b218783 changed focused-role wording; the host files were
    # independently compared before pinning.
    expected = {
        "thaliris-curator.toml": "0ddddf8aae4cdbd2ccc49b455712ee9861c203e054333d418ff4f39fd9c898ae",
        "thaliris-focused-implementer-astra-medium.toml": "4ba712ecb415700ce05bedbd0860d9d180d87baff0919143977e2969092b58b7",
        "thaliris-focused-implementer-xhigh.toml": "62c946403f45b0cdc2e278fe4b37cdaf09a84ec6535a65e9885c2636967c6484",
        "thaliris-focused-implementer.toml": "42042dbc7564432c5864c4c6faf6f58c1821da3c47041402faa979b69904286a",
        "thaliris-implementer.toml": "c3e6fd2d10452a0d15e145decba7189d2a71db2d7e599b0de25c6875a6b44e59",
        "thaliris-investigator.toml": "a787e046a558eb25c5e0cefe8aa933727beacbc5460c131dde5347cb532f01ad",
        "thaliris-reasoning-specialist-astra-medium.toml": "723d032ec7f431acd899730cfae55af98756c5925712be863b08719dc932521a",
        "thaliris-reasoning-specialist-xhigh.toml": "8a00c1fd917f795892af67b10c1a9acdaf8cd24c0d6f57cf3d9d22947e4d25f6",
        "thaliris-reasoning-specialist.toml": "077c5037dade5a6a53a5247bc25bcddc6a895258d3dbce0e63c7c74e1fb399d3",
        "thaliris-reviewer.toml": "01f1b4163a98bdf752c1bda84f45c6d53c662f86350739ac720d8027e680eff2",
        "thaliris-verifier.toml": "44fb8af36bb7b668b71eccd73aa8a21f9870f252c17c07cc41753499136a35da",
    }
    assert codex_adapter._1F98DAE_GENERATED_AGENT_PROFILE_HASHES == expected
    assert {
        name: digest
        for name, digest in expected.items()
        if digest in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES[name]
    } == expected

    tracked = tuple(expected)
    changed = set(tracked)
    historical: dict[str, bytes] = {}
    for name in tracked:
        value = _historical_profile("1f98dae", name)
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == ("legacy" if name in changed else "current")
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other = "thaliris-verifier.toml" if name != "thaliris-verifier.toml" else "thaliris-reviewer.toml"
        assert codex_adapter._agent_profile_state(value, other) == "user"
        historical[name] = value

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    root = _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in historical.items():
        (agents / name).write_bytes(value)
    edited_name = "thaliris-focused-implementer.toml"
    edited = historical[edited_name] + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in set(tracked) - {edited_name}]
        ),
    )

    assert (agents / edited_name).read_bytes() == edited
    assert any(str(agents / edited_name) in item for item in result["manual_action_required"])
    assert result["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before


def test_40fd5f2_focused_profiles_upgrade_only_exact_historical_bytes(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    expected = {
        "thaliris-focused-implementer.toml": "48b73ecaea2cd7b3c2515c0dfea69e1a7291c8e08599c1ddc9011208fcf3b6a2",
        "thaliris-focused-implementer-astra-medium.toml": "3f7142b441521aca5b978b38a7c5de081eab7326c327524bdc9214b20c5b2971",
        "thaliris-focused-implementer-xhigh.toml": "774b28e8a99a5f7396013cb94b2e183e57a940c482919526cf814fc54e018287",
    }
    assert codex_adapter._40FD5F2_GENERATED_AGENT_PROFILE_HASHES == expected
    historical = {name: _historical_profile("40fd5f2", name) for name in expected}
    for name, value in historical.items():
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other = next(candidate for candidate in expected if candidate != name)
        assert codex_adapter._agent_profile_state(value, other) == "user"

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in historical.items():
        (agents / name).write_bytes(value)

    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in expected]
        ),
    )
    assert result["manual_action_required"] == []
    for name in expected:
        assert codex_adapter._agent_profile_state((agents / name).read_bytes(), name) == "current"
        assert f"agents/{name}" in result["files"]
    assert codex_adapter._host_profile_definition_present(host_home) == "YES"
    assert len(list(agents.glob("thaliris-*.toml"))) == 11

    edited_name = "thaliris-focused-implementer.toml"
    edited = historical[edited_name] + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)
    guarded = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert (agents / edited_name).read_bytes() == edited
    assert any(str(agents / edited_name) in item for item in guarded["manual_action_required"])


def test_fd4fba36_profiles_upgrade_exact_historical_set_and_preserve_unknown_bytes(
    tmp_path: Path, monkeypatch, pinned_test_thaliris,
) -> None:
    expected = {
        "thaliris-curator.toml": "74aebff8c07c2a3359461085d165d440e8c6b8e9ca2d5ac9bc6c57ca83e91653",
        "thaliris-implementer.toml": "bb0767422861b66e0becd3386d6f0d5faecf247bbda767c52118ee58184ed613",
        "thaliris-investigator.toml": "d14a5376c3644495746fedcf74f92dac62bdca2321419473fd0dc8407ce8bc1b",
        "thaliris-reasoning-specialist-astra-medium.toml": "f1d75968331cdcc6e3b3e447c79909b02070475cfc2d764b83c2f4515f290f6e",
        "thaliris-reasoning-specialist-xhigh.toml": "0d05efd7edcb17965a1c6f3dee7b1152dcdd9ced067e86d60b878b9f3f6b0705",
        "thaliris-reasoning-specialist.toml": "432517da403000383ecf9ee0793122c1fe03aae2a8ef3395d6b8449b6b6ab73a",
        "thaliris-reviewer.toml": "44e684ed9a49c1f4d5e50e12b483136e148c9969c1cbc9ae6495fcd1b5a90a62",
        "thaliris-verifier.toml": "571bdd8c11d06a2393f1554f48621892c652dd6c09660a5d9fffe97844e6d59f",
    }
    assert codex_adapter._FD4FBA36_GENERATED_AGENT_PROFILE_HASHES == expected
    assert all(
        digest in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES[name]
        for name, digest in expected.items()
    )

    historical = {name: _historical_profile("fd4fba36", name) for name in expected}
    for name, value in historical.items():
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other_name = next(candidate for candidate in expected if candidate != name)
        assert codex_adapter._agent_profile_state(value, other_name) == "user"

    # Combine this historical eight-profile set with the three exact focused
    # profiles from their independently pinned renderer revision. Installation
    # must then refresh all historical generated bytes to the current renderer.
    focused = {
        name: _historical_profile("40fd5f2", name)
        for name in (
            "thaliris-focused-implementer.toml",
            "thaliris-focused-implementer-astra-medium.toml",
            "thaliris-focused-implementer-xhigh.toml",
        )
    }
    for name, value in focused.items():
        assert codex_adapter._agent_profile_state(value, name) == "legacy"

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in (historical | focused).items():
        (agents / name).write_bytes(value)

    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in (set(expected) | set(focused))]
        ),
    )

    assert result["manual_action_required"] == []
    assert len(list(agents.glob("thaliris-*.toml"))) == 11
    assert codex_adapter._host_profile_definition_present(host_home) == "YES"
    for name in roles.agent_profiles():
        assert codex_adapter._agent_profile_state((agents / name).read_bytes(), name) == "current"
    for name in expected:
        assert f"agents/{name}" in result["files"]

    # Exact historical bytes are upgradeable; an appended edit remains owned
    # by the user and blocks only that profile's write.
    edited_name = "thaliris-reviewer.toml"
    edited = historical[edited_name] + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)
    guarded = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert (agents / edited_name).read_bytes() == edited
    assert codex_adapter._agent_profile_state(edited, edited_name) == "user"
    assert any(str(agents / edited_name) in item for item in guarded["manual_action_required"])


def test_8a3fe930_changed_profiles_upgrade_exact_bytes_and_preserve_edits(
    tmp_path: Path, monkeypatch, pinned_test_thaliris,
) -> None:
    expected = {
        "thaliris-focused-implementer.toml": "a929ec5bbbb748a880a95fea40aec4de05b225269e70473937c9deee3411608a",
        "thaliris-focused-implementer-astra-medium.toml": "e22136925d2bcaed111c687c47a8de1464014427a6c8bbed7e1021076bd20d8a",
        "thaliris-focused-implementer-xhigh.toml": "1f4311da03a5ee0185253156c3510ed3c2855f0a8091a4699a80b1ebe7b9ca9a",
        "thaliris-reviewer.toml": "4b1593d4269bccd7e86da5fabaa129f9da431302e072469e60f273abb36a05a0",
    }
    assert codex_adapter._8A3FE930_GENERATED_AGENT_PROFILE_HASHES == expected
    historical = {name: _historical_profile("8a3fe930", name) for name in expected}
    for name, value in historical.items():
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other_name = next(candidate for candidate in expected if candidate != name)
        assert codex_adapter._agent_profile_state(value, other_name) == "user"

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in historical.items():
        (agents / name).write_bytes(value)
    edited_name = "thaliris-focused-implementer-xhigh.toml"
    edited = historical[edited_name] + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in set(expected) - {edited_name}]
        ),
    )
    assert (agents / edited_name).read_bytes() == edited
    assert any(str(agents / edited_name) in item for item in result["manual_action_required"])
    assert result["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before


def test_210782b1_all_profiles_migrate_and_unknown_modifications_stay_manual(
    tmp_path: Path, monkeypatch, pinned_test_thaliris,
) -> None:
    expected = {
        "thaliris-curator.toml": "828ff942256ffe8c1507023db6940069e7d88ef740edcd8ba01ad72fc4a0b115",
        "thaliris-focused-implementer-astra-medium.toml": "2bbcd612c4697025a5ca3948e0b07215995c9e5e0886e78e168c7a483a81882e",
        "thaliris-focused-implementer-xhigh.toml": "957d4bee345c4ad4dc9f65deabfdc87a1a8b8d32cf8d33da90846504af6b8300",
        "thaliris-focused-implementer.toml": "0f408384609c2a2217d7268a8c29afa28560299130c8de072d3bdd2cadcc0b1a",
        "thaliris-implementer.toml": "74bd3a8a9cfdc7d69c19060c0666dcc398a220f36955214a02121786c705becc",
        "thaliris-investigator.toml": "cc6cde5de4260746b590b6d8c603f69f4c2b9479a77505bc0d3631ae51510ad4",
        "thaliris-reasoning-specialist-astra-medium.toml": "e747753a31408500bb7f4eddf44348b5096e0d1d946163395edf4012fa2dbcea",
        "thaliris-reasoning-specialist-xhigh.toml": "9bbf7a90b54d5d850e262682128aa787d0c974f12c397fcb8e2c8b03f4ad1eb3",
        "thaliris-reasoning-specialist.toml": "4533322a06ee4b3bba7fb9d07e8eb2252b6a686884333324ebef3af6bf651a3e",
        "thaliris-reviewer.toml": "f0998da30f8029536151fdb155a80548b6093e1866b387d0dd98b459c9f0b3b2",
        "thaliris-verifier.toml": "81a9e2a9526962c0facf064e40b22b9ec261b1af9d2a6545bb41da21b1033f90",
    }
    assert codex_adapter._210782B1_GENERATED_AGENT_PROFILE_HASHES == expected
    assert set(expected) == set(roles.agent_profiles())

    historical = {
        name: _historical_profile("210782b1", name)
        for name in expected
    }
    for name, value in historical.items():
        assert hashlib.sha256(value).hexdigest() == expected[name]
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"

    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    for name, value in historical.items():
        (agents / name).write_bytes(value)

    edited_name = "thaliris-reviewer.toml"
    edited = historical[edited_name] + b"\nunknown modification\n"
    (agents / edited_name).write_bytes(edited)

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/{name}" for name in set(expected) - {edited_name}]
        ),
    )

    assert (agents / edited_name).read_bytes() == edited
    assert codex_adapter._agent_profile_state(edited, edited_name) == "user"
    assert any(str(agents / edited_name) in item for item in result["manual_action_required"])
    assert f"agents/{edited_name}" not in result["files"]
    assert result["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before


def test_ec1ad7b_investigator_generated_outputs_remain_upgradeable() -> None:
    old_profile = _historical_profile("ec1ad7b", "thaliris-investigator.toml")
    profile_digest = hashlib.sha256(old_profile).hexdigest()
    assert profile_digest == "ee818487dd21dacd9040e710d0fa3b4ca32524407d70981e03d11a600dcb81a6"
    assert codex_adapter._agent_profile_state(old_profile, "thaliris-investigator.toml") == "legacy"

    old_role_packs = historical_blob("ec1ad7b:docs/thaliris-role-packs.md")
    role_pack_digest = hashlib.sha256(old_role_packs).hexdigest()
    assert role_pack_digest == "4e4a1af986df48f8c9e0e632506ef13636531dba163fa7ae7032a7d18ab2c36a"
    assert role_pack_digest in codex_adapter._KNOWN_GENERATED_ROLE_PACK_HASHES
    assert codex_adapter._role_pack_state(old_role_packs) == "legacy"


def test_pre_reuse_generated_outputs_remain_upgradeable_by_exact_identity() -> None:
    revision = "e4b6975"
    historical = historical_blob(f'{revision}:AGENTS.md')
    start = historical.index(codex_adapter.MANAGED_START.encode())
    end = historical.index(codex_adapter.MANAGED_END.encode(), start) + len(codex_adapter.MANAGED_END)
    assert codex_adapter._managed_agents_state(historical[start:end].decode()) == "legacy"
    role_pack = historical_blob(f'{revision}:docs/thaliris-role-packs.md')
    assert codex_adapter._role_pack_state(role_pack) == "legacy"
    for name in (
        "thaliris-focused-implementer.toml",
        "thaliris-focused-implementer-astra-medium.toml",
        "thaliris-focused-implementer-xhigh.toml",
    ):
        historical_profile = historical_blob(f'8eb1707:.codex/agents/{name}')
        assert codex_adapter._agent_profile_state(historical_profile, name) == "legacy"


def test_current_focused_profile_bytes_remain_upgradeable_by_exact_identity() -> None:
    expected = {
        "thaliris-focused-implementer.toml": "b4ff152b4a3978f31c7b80891a839bf1bd8408336fe19b2c8c27d42bf88d0311",
        "thaliris-focused-implementer-astra-medium.toml": "9b412596980063afae0a4678043e09ca6f3509735e55f373119c3da3655831ef",
        "thaliris-focused-implementer-xhigh.toml": "501fc4fc95c883f9249c649e6477a7d98babd97e41942b036da94e0086c3f662",
    }
    binding = roles.get_codex_binding("focused-implementer")
    assert {hashlib.sha256(_historical_profile("99a58fc", name)).hexdigest() for name in expected} == set(expected.values())
    assert set(expected.values()) <= binding.legacy_profile_hashes
    assert all(
        digest in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES[name]
        for name, digest in expected.items()
    )
    for name in expected:
        value = _historical_profile("99a58fc", name)
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"

    profiles = roles.agent_profiles()
    assert {name for name, (_, _, role) in profiles.items() if role == "focused-implementer"} == set(expected)
    for name in expected:
        model, effort, role = profiles[name]
        value = tomllib.loads(codex_adapter._agent_profile(name.removesuffix(".toml"), role, model, effort).decode())
        assert value["developer_instructions"] == roles.profile_instructions("focused-implementer", name.removesuffix(".toml"))
        assert "core semantic solution" in value["developer_instructions"].lower()


def test_ec1ad7b_project_focused_profiles_have_exact_historical_ownership() -> None:
    for name, digest in codex_adapter._EC1AD7B_FOCUSED_PROFILE_HASHES.items():
        historical = _historical_profile("ec1ad7b", name)
        assert hashlib.sha256(historical).hexdigest() == digest
        assert codex_adapter._agent_profile_state(historical, name) == "legacy"
        assert codex_adapter._agent_profile_state(historical + b"\nuser edit\n", name) == "user"
        other_name = next(other for other in codex_adapter._EC1AD7B_FOCUSED_PROFILE_HASHES if other != name)
        assert codex_adapter._agent_profile_state(historical, other_name) == "user"
        # Project-local .codex profiles are ignored user state. The generated
        # current template is verified below without relying on those files.


def test_pre_split_host_profiles_migrate_by_exact_historical_identity() -> None:
    for name, digest in codex_adapter._DDE3D0F_GENERATED_AGENT_PROFILE_HASHES.items():
        historical = _historical_profile("dde3d0f", name)
        assert hashlib.sha256(historical).hexdigest() == digest
        assert codex_adapter._agent_profile_state(historical, name) == "legacy"
        assert codex_adapter._agent_profile_state(historical + b"\nuser edit\n", name) == "user"
    old_agents = historical_blob('dde3d0f:AGENTS.md').decode("utf-8")
    start = old_agents.index("<!-- thaliris:begin -->")
    end = old_agents.index("<!-- thaliris:end -->") + len("<!-- thaliris:end -->")
    old_managed = old_agents[start:end]
    old_packs = historical_blob('dde3d0f:docs/thaliris-role-packs.md')
    assert codex_adapter._managed_agents_state(old_managed) == "legacy"
    assert codex_adapter._managed_agents_state(old_managed.replace("<!-- thaliris:end -->", "user edit\n<!-- thaliris:end -->")) == "user"
    assert codex_adapter._role_pack_state(old_packs) == "legacy"
    assert codex_adapter._role_pack_state(old_packs + b"\nuser edit") == "user"


def test_e4b6975_host_profiles_are_recognized_only_by_exact_identity() -> None:
    expected = {
        "thaliris-implementer.toml": "88ea13ad079412a4569a2360731d4bb377d9b20cb313cc9a882065cdd5861f29",
        "thaliris-focused-implementer.toml": "1eb28a0b74e72fcf4e03f63ec3ddba12d4972ab3f7cfb71bd02efc1b748cbd45",
        "thaliris-focused-implementer-astra-medium.toml": "37dacbc67a27f3551d6e60b26bc520113c274d233c01fd85c2d507806f62e625",
        "thaliris-focused-implementer-xhigh.toml": "c66aa6e934a6fdc354eda44d60145d6e92a4e7c4b65be796a18094ce03817a3e",
    }
    assert codex_adapter._E4B6975_GENERATED_AGENT_PROFILE_HASHES == expected

    for name, digest in expected.items():
        historical = _historical_profile("e4b6975889ef348e13e94521dc300f1e572b42a3", name)
        assert hashlib.sha256(historical).hexdigest() == digest
        assert digest in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES[name]
        assert codex_adapter._agent_profile_state(historical, name) == "legacy"
        assert codex_adapter._agent_profile_state(historical + b"\nuser edit\n", name) == "user"
        other_name = next(candidate for candidate in expected if candidate != name)
        assert codex_adapter._agent_profile_state(historical, other_name) == "user"


def test_pre_update_managed_and_role_pack_outputs_remain_upgradeable() -> None:
    managed = _historical_managed("99a58fc")
    role_packs = historical_blob("99a58fc:docs/thaliris-role-packs.md")
    assert hashlib.sha256(managed.encode("utf-8")).hexdigest() == "9b3ae3c7edbfc74255a3c743dc9a1c430c6c936ea3101b3f0777f2a78eb4c7b8"
    assert hashlib.sha256(role_packs).hexdigest() == "d2b3a1c5a776f6a1dbb3be52a907c1704903f64a92d2388f64dc2171096e92e8"
    assert codex_adapter._managed_agents_state(managed) == "legacy"
    assert codex_adapter._role_pack_state(role_packs) == "legacy"


def test_exact_phase_two_profile_bytes_are_recognized_only_for_own_role() -> None:
    fixture_dir = Path(__file__).parent / "fixtures"
    for role in ("investigator", "curator", "reasoning-specialist", "implementer", "verifier", "reviewer"):
        name = f"thaliris-{role}.toml"
        value = (fixture_dir / f"phase2-{role}.toml").read_bytes()
        assert hashlib.sha256(value).hexdigest() in roles.get_codex_binding(role).legacy_profile_hashes
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
        other_name = "thaliris-curator.toml" if role != "curator" else "thaliris-investigator.toml"
        assert codex_adapter._agent_profile_state(value, other_name) == "user"


def test_phase_two_profiles_migrate_while_edited_profile_is_preserved(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    root = _initialized_repo(tmp_path)
    agents = host_home / "agents"
    agents.mkdir(parents=True)
    fixture_dir = Path(__file__).parent / "fixtures"
    roles_to_migrate = ("investigator", "curator", "reasoning-specialist", "implementer", "verifier", "reviewer")
    for role in roles_to_migrate:
        (agents / f"thaliris-{role}.toml").write_bytes((fixture_dir / f"phase2-{role}.toml").read_bytes())
    edited_name = "thaliris-reviewer.toml"
    edited = (agents / edited_name).read_bytes() + b"\nuser edit\n"
    (agents / edited_name).write_bytes(edited)

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    result = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/thaliris-{role}.toml" for role in roles_to_migrate[:-1]]
        ),
    )

    assert (agents / edited_name).read_bytes() == edited
    assert any(str(agents / edited_name) in item for item in result["manual_action_required"])
    assert result["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before

    init_result = codex_adapter.init(root)
    assert init_result["agent_profile_changed"] is False
    assert not (root / ".codex" / "agents").exists()


def test_new_registry_role_flows_through_adapter_inventories_and_cli(monkeypatch) -> None:
    monkeypatch.setitem(roles.ROLE_REGISTRY, "sentinel", _sentinel_definition())

    assert "sentinel" in codex_adapter.role_choices()
    assert roles.agent_profiles()["thaliris-sentinel.toml"] == (
        "gpt-5.6-luna", "high", "sentinel"
    )
    assert lifecycle._native_agent_roles()["thaliris-sentinel"] == "sentinel"
    assert "thaliris-sentinel" in roles.native_profile_names()
    assert "| `sentinel` | `gpt-5.6-luna` | `high` | `thaliris-sentinel` |" in roles.render_registry_document().decode()

    parser = cli._parser()
    choices = parser._subparsers._group_actions[0].choices["task-update"]._actions
    role_action = next(action for action in choices if action.dest == "role")
    assert "sentinel" in role_action.choices


def test_new_registry_role_appears_in_active_spawn_isolation_diagnostic(tmp_path: Path, monkeypatch) -> None:
    # Synthetic Controller unit contract, not current Host Root proof.
    monkeypatch.setattr(lifecycle, "_controller_actor_assurance", lambda _payload: "CONTROLLER")
    monkeypatch.setitem(roles.ROLE_REGISTRY, "sentinel", _sentinel_definition())
    root = _initialized_repo(tmp_path)
    started = core.task_start(root, "registry diagnostic", None, None)
    session_id = "registry-controller-session"
    lifecycle.record_task_start_owner(root, started["task_id"], hashlib.sha256(session_id.encode()).hexdigest())

    denied = lifecycle._pre_tool_output(root=root, payload={
        "session_id": session_id,
        "tool_name": "spawn_agent",
        "tool_input": {"fork_turns": "all"},
    })

    reason = json.loads(denied)["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("THALIRIS_ISOLATION_REQUIRED:")
    assert reason.endswith('and Sentinel session explicitly with fork_turns="none".')


def _initialized_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex_adapter.init(tmp_path)
    return tmp_path


def _historical_profile(revision: str, name: str) -> bytes:
    """Render one profile from an immutable registry/adapter revision."""
    module_name = f"historical_roles_{revision}"
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module.__dict__["__name__"] = module_name
        sys.modules[module_name] = module
        source = historical_blob(f"{revision}:src/thaliris/roles.py")
        exec(compile(source, f"{module_name}.py", "exec"), module.__dict__)
    adapter_source = historical_blob(f"{revision}:src/thaliris/codex_adapter.py")
    function = next(
        node
        for node in ast.parse(adapter_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_agent_profile"
    )
    namespace: dict[str, object] = {
        "json": json,
        "roles": module,
    }
    exec(
        compile(ast.Module([function], type_ignores=[]), "historical_adapter.py", "exec"),
        namespace,
    )
    model, effort, role = module.agent_profiles()[name]
    return namespace["_agent_profile"](name.removesuffix(".toml"), role, model, effort)


@pytest.mark.parametrize("revision,hashes", [
    ("28e4297d2e489a8f893cb75aec7291cbb3518dcb", codex_adapter._HISTORICAL_28E4297_PROFILE_HASHES),
    ("69d9a33", codex_adapter._HISTORICAL_69D9A33_PROFILE_HASHES),
])
def test_retained_profile_ownership_is_witnessed_by_immutable_renderer(revision, hashes):
    for name, digest in hashes.items():
        raw = _historical_profile(revision, name)
        assert hashlib.sha256(raw).hexdigest() == digest
        assert codex_adapter._agent_profile_state(raw, name) in {"legacy", "current"}
        assert codex_adapter._agent_profile_state(raw + b"\nuser change\n", name) == "user"
    reviewer = Path(__file__).parent / "fixtures/thaliris-reviewer-28e4297.toml"
    assert reviewer.read_bytes() == _historical_profile("28e4297d2e489a8f893cb75aec7291cbb3518dcb", reviewer.name.replace("-28e4297", ""))


def _historical_managed(revision: str) -> str:
    """Render the managed instruction span from an immutable adapter revision."""
    module_name = f"historical_roles_{revision}"
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module.__dict__["__name__"] = module_name
        sys.modules[module_name] = module
        source = historical_blob(f"{revision}:src/thaliris/roles.py")
        exec(compile(source, f"{module_name}.py", "exec"), module.__dict__)
    adapter_source = historical_blob(f"{revision}:src/thaliris/codex_adapter.py")
    tree = ast.parse(adapter_source)
    required = {
        "_native_role_labels", "_native_profile_facts",
        "_native_role_names_text", "_render_managed",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in required
    ]
    constants = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"MANAGED_START", "MANAGED_END"}
    }
    namespace: dict[str, object] = {"roles": module, **constants}
    exec(
        compile(ast.Module(functions, type_ignores=[]), "historical_adapter.py", "exec"),
        namespace,
    )
    return namespace["_render_managed"]().removesuffix("\n")


def _historical_registry_document() -> bytes:
    # Fixed LF/UTF-8 bytes captured from immutable commit b1d517f (blob
    # 9c410a4d2af5d3780f4b415429227150d08626bd), not regenerated at test time.
    value = (Path(__file__).parent / "fixtures" / "thaliris-role-registry-v1.md").read_bytes()
    assert hashlib.sha256(value).hexdigest() in codex_adapter._KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES
    return value


def _simulate_registry_addition(monkeypatch) -> None:
    monkeypatch.setitem(roles.ROLE_REGISTRY, "sentinel", _sentinel_definition())
    # A new adapter process would capture the expanded current rendering at
    # import time; model that boundary so the historical six-role bytes cannot
    # be accepted merely because they match the old module constant.
    monkeypatch.setattr(codex_adapter, "ROLE_REGISTRY_DOC", roles.render_registry_document().decode())


def test_historical_registry_document_migrates_after_registry_addition(tmp_path: Path, monkeypatch) -> None:
    root = _initialized_repo(tmp_path)
    registry_document = root / "docs" / "thaliris-role-registry.md"
    registry_document.write_bytes(_historical_registry_document())
    _simulate_registry_addition(monkeypatch)

    assert codex_adapter._role_registry_state(registry_document.read_bytes()) == "legacy"
    result = codex_adapter.init(root)

    assert registry_document.read_bytes() == roles.render_registry_document()
    assert "docs/thaliris-role-registry.md" in result["files"]
    assert "docs/thaliris-role-registry.md" not in result["manual_action_required"]


def test_modified_registry_document_is_preserved_as_user_owned(tmp_path: Path, monkeypatch) -> None:
    root = _initialized_repo(tmp_path)
    registry_document = root / "docs" / "thaliris-role-registry.md"
    user_owned = _historical_registry_document() + b"\nuser edit\n"
    registry_document.write_bytes(user_owned)
    _simulate_registry_addition(monkeypatch)

    assert codex_adapter._role_registry_state(registry_document.read_bytes()) == "user"
    result = codex_adapter.init(root)

    assert registry_document.read_bytes() == user_owned
    assert "docs/thaliris-role-registry.md" not in result["files"]
    assert "docs/thaliris-role-registry.md" in result["preserved_manual_followup"]


def test_current_registry_document_generation_remains_stable(tmp_path: Path) -> None:
    root = _initialized_repo(tmp_path)
    registry_document = root / "docs" / "thaliris-role-registry.md"

    assert codex_adapter._role_registry_state(registry_document.read_bytes()) == "current"
    result = codex_adapter.init(root)

    assert result["changed"] is False
    assert registry_document.read_bytes() == roles.render_registry_document()
    assert "docs/thaliris-role-registry.md" not in result["files"]
    assert "docs/thaliris-role-registry.md" not in result["manual_action_required"]


def test_generated_registry_document_matches_tracked_artifact() -> None:
    from pathlib import Path

    assert Path("docs/thaliris-role-registry.md").read_bytes() == roles.render_registry_document()
    assert codex_adapter.ROLE_REGISTRY_DOC.encode("utf-8") == roles.render_registry_document()


def test_doctor_reports_missing_registry_document(tmp_path: Path) -> None:
    root = _initialized_repo(tmp_path)
    registry_document = root / "docs" / "thaliris-role-registry.md"
    registry_document.unlink()

    result = codex_adapter.doctor(root)

    assert result["role_registry"]["generated_role_document"] == "MISSING"


def test_formal_seventh_role_requires_only_spec_and_binding(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    monkeypatch.setitem(roles.ROLE_REGISTRY, "formal-sentinel", _formal_sentinel_registration())
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    root = _initialized_repo(tmp_path)
    install = authorized_host_install(tmp_path, pinned_test_thaliris)

    profile = host_home / "agents" / "thaliris-formal-sentinel.toml"
    assert profile.is_file()
    assert 'model_reasoning_effort = "high"' in profile.read_text(encoding="utf-8")
    assert "agents/thaliris-formal-sentinel.toml" in install["files"]
    assert not (root / ".codex" / "agents").exists()
    assert codex_adapter.bootstrap_check(root)["project_definition_present"] == "YES"
    assert lifecycle._native_agent_roles()["thaliris-formal-sentinel"] == "formal-sentinel"
    role_action = next(
        action
        for action in cli._parser()._subparsers._group_actions[0].choices["task-update"]._actions
        if action.dest == "role"
    )
    assert "formal-sentinel" in role_action.choices
    assert "formal-sentinel" in codex_adapter.doctor(root)["role_registry"]["roles"]
    assert "Formal Sentinel" in codex_adapter.render_managed()
    assert "Formal Sentinel" in codex_adapter.render_role_packs()
    assert "| `formal-sentinel` |" in roles.render_registry_document().decode()
    assert roles.get_codex_binding("formal-sentinel").legacy_profile_hashes == frozenset()

    delegation = lifecycle._child_pre_tool_output(root, {
        "agent_type": "thaliris-formal-sentinel",
        "tool_name": "spawn_agent",
        "tool_input": {},
    })
    write = lifecycle._child_pre_tool_output(root, {
        "agent_type": "thaliris-formal-sentinel",
        "tool_name": "Bash",
        "tool_input": {"command": "echo output > generated.txt"},
    })
    control = lifecycle._child_pre_tool_output(root, {
        "agent_type": "thaliris-formal-sentinel",
        "tool_name": "Bash",
        "tool_input": {"command": "thaliris task-update --role formal-sentinel"},
    })
    assert "THALIRIS_ROLE_SESSION_DELEGATION" in delegation
    assert "THALIRIS_FORMAL_SENTINEL_WRITE_BLOCKED" in write
    assert "THALIRIS_ROLE_SESSION_CONTROL_STATE_MUTATION" in control


def test_registry_rejects_key_that_differs_from_spec_identity(monkeypatch) -> None:
    monkeypatch.setitem(
        roles.ROLE_REGISTRY,
        "formal-key",
        (
            roles.RoleSpec(id="formal-spec", instructions="formal instructions"),
            roles.CodexExecutionBinding(native_profile="thaliris-formal-key"),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"ROLE_REGISTRY key 'formal-key' must match RoleSpec\.id 'formal-spec'",
    ):
        roles.role_choices()


def test_9b5bcf2_curator_profile_is_recognized_as_legacy() -> None:
    name = "thaliris-curator.toml"
    value = _historical_profile("9b5bcf2", name)
    digest = hashlib.sha256(value).hexdigest()

    assert digest == "7779da9180597f1235f2c3893088743b0baafa55b4edad1e9319774f88ae8e6a"
    assert digest in roles.get_codex_binding("curator").legacy_profile_hashes
    assert codex_adapter._agent_profile_state(value, name) == "legacy"
    assert codex_adapter._agent_profile_state(value + b"\nuser edit\n", name) == "user"
    binding = roles.get_codex_binding("curator")
    current = codex_adapter._agent_profile(name.removesuffix(".toml"), "curator", binding.model, binding.reasoning_effort)
    assert current != value
    assert codex_adapter._agent_profile_state(current, name) == "current"


def test_9b5bcf2_managed_and_role_pack_outputs_are_recognized_as_legacy() -> None:
    managed = _historical_managed("9b5bcf2")
    managed_digest = hashlib.sha256(managed.encode("utf-8")).hexdigest()
    role_packs = historical_blob("9b5bcf2:docs/thaliris-role-packs.md")
    role_pack_digest = hashlib.sha256(role_packs).hexdigest()

    assert managed_digest == "adebcedf67d1e3aa3e33d42da1174ea36d9e4199beb8453d8076a1de72cd638a"
    assert managed_digest in codex_adapter._KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES
    assert codex_adapter._managed_agents_state(managed) == "legacy"
    edited_managed = managed.replace(codex_adapter.MANAGED_END, "user edit\n" + codex_adapter.MANAGED_END)
    assert codex_adapter._managed_agents_state(edited_managed) == "user"
    assert role_pack_digest == "7009fc69d97ca403404c57d739e354cc3ebf7656fdca690c0fd60b2cfa9f6267"
    assert role_pack_digest in codex_adapter._KNOWN_GENERATED_ROLE_PACK_HASHES
    assert codex_adapter._role_pack_state(role_packs) == "legacy"
    assert codex_adapter._role_pack_state(role_packs + b"\nuser edit") == "user"


def test_managed_renderer_matches_working_artifact_and_derives_added_role(monkeypatch) -> None:
    current = Path("AGENTS.md").read_text(encoding="utf-8")
    start, end = codex_adapter._managed_span(current, "test")
    assert current[start:end] + "\n" == codex_adapter.render_managed()
    monkeypatch.setitem(roles.ROLE_REGISTRY, "formal-sentinel", _formal_sentinel_registration())
    assert "Formal Sentinel" in codex_adapter.render_managed()
    assert "formal sentinel instructions" in codex_adapter.render_role_packs()
    assert 'fork_turns="none"' in codex_adapter.render_managed()
