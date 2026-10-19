"""Codex adapter for explicit handoff delivery and native lifecycle hooks."""
from __future__ import annotations

import json
import hashlib
import base64
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

from thaliris import core

from . import codex_app_server, lifecycle, roles, runtime_identity, host_preflight, task_authority, native_wait_capability
from .lifecycle import (
    MANAGED_HOOKS_DESCRIPTION,
    MANAGED_HOOK_ABI,
    HOST_HOOK_SCRIPT_NAME,
    HOST_RUN_SCRIPT_NAME,
    PROJECT_ACTIVATION_MARKER,
    handle_hook,
    host_hook_script_bytes,
    host_run_script_bytes,
    merge_host_hooks,
    remove_hooks,
    remove_host_hooks,
)

# This adapter-owned vocabulary is a CLI ingress contract. Core receives an
# opaque actor marker after this boundary has authorized the operation.
# This is the complete public CLI ingress vocabulary. Native identifiers are
# translated only at the native adapter boundary and never accepted as roles.
ROLE_CHOICES = roles.role_choices()
_PROJECT_ACTIVATION_BYTES = b'{"format":"thaliris-project-activation-v1"}\n'

def role_choices() -> tuple[str, ...]:
    return roles.role_choices()


def _role_choices() -> tuple[str, ...]:
    return role_choices()


def _native_codex_role_map() -> dict[str, str]:
    return roles.native_codex_role_map()


def _role_model_defaults() -> dict[str, tuple[str | None, str | None]]:
    return {
        role: (binding.model, binding.reasoning_effort)
        for role in roles.role_choices()
        for binding in (roles.get_codex_binding(role),)
        if binding is not None
    }


def _agent_profiles() -> dict[str, tuple[str | None, str | None, str]]:
    return roles.agent_profiles()


# Compatibility aliases retained for existing callers. Runtime paths below
# use the registry accessors so adding a role does not require another set.
_NATIVE_CODEX_ROLE_MAP = _native_codex_role_map()
_ROLE_MODEL_DEFAULTS = _role_model_defaults()
_AGENT_PROFILES = _agent_profiles()
_NATIVE_PROFILE_NAMES = roles.native_profile_names()
_KNOWN_GENERATED_AGENT_PROFILE_HASHES = {
    binding.profile_filename: binding.legacy_profile_hashes
    for binding in roles.iter_codex_bindings()
    if binding.profile_filename is not None
}
# Independently witnessed complete historical renders, not current HEAD's
# claim about its own output. 28e4297d2e489a8f893cb75aec7291cbb3518dcb:
# adapter blob443f92a103ba7bfb1e0ad1c14cd4eab7d8960bec; registry
# blobc3ded0e264771024f7cad71bccee0308a6f009a5. Filename binding is mandatory.
_HISTORICAL_28E4297_PROFILE_HASHES = {
    'thaliris-curator.toml': '55aed52f61396de5d75b430fa4a0d03d2487e084b9c54e0ced7c32493ea44cbe',
    'thaliris-implementer.toml': 'ebb2136a91990dfe855428b568a42b01a470494db14c3d3cc6c818c62fff23be',
    'thaliris-investigator.toml': '70238f39468e11ebedc5612056e4e11139f9c285cbc1b7c43c8d2da3f639d7ca',
    'thaliris-reasoning-specialist-astra-medium.toml': 'ef5e1521bedaeba7bb316042d28385700774d78f8d1c798eac308c175c5ba34b',
    'thaliris-reasoning-specialist-xhigh.toml': 'f42bc785a0c76c516fd0493b24c85d0e381cf6e5ac82808befa4a01e8baab3c0',
    'thaliris-reasoning-specialist.toml': 'd8a6f94789958424783f6de7154eb51d3fcb76cb4f00f6e7260bf06e3a93d011',
    'thaliris-reviewer.toml': 'e631e603f87405c5d21a31bfdb07eaf3c7a0553d937b3069e2d7ddea22decc12',
    'thaliris-verifier.toml': '3c598e8bb39c52682f6021505a8b37b71415ce9016e1b53a6741363e8a16a6e2',
}
# 69d9a33 historical renderer/registry witness for the previous current set.
_HISTORICAL_69D9A33_PROFILE_HASHES = {
    'thaliris-curator.toml': 'a3665bf571db75df3530fcea172bed154cfb7aac5f88b40bd847109e15459108',
    'thaliris-focused-implementer-astra-medium.toml': 'd4fef2b7b5e77d027b4d3e0807fdeb3a6bc6d81f3cf8aabf41affce7b912e573',
    'thaliris-focused-implementer-xhigh.toml': '8f6890bfa3ad76b2a0401a04f33a4e7494ea91b3cb266b749f1d72a7cbf8aba7',
    'thaliris-focused-implementer.toml': 'cca2ff3bf783baa3c8926efd42e2c5807c9db9ea1a6a64b7e34e30a791274b17',
    'thaliris-implementer.toml': '3d393a145c900749c33296550e740bf61af64b91d2b4cf3462cb2c44e1d65195',
    'thaliris-investigator.toml': 'd34b8571689c0ffc5e68cd5fb316ef1b26d41dfa8e2e363e34bf8b465ecca544',
    'thaliris-reasoning-specialist-astra-medium.toml': '31639f9b001b0b8ba88c6733e6c881f98b817513257c1921b67790c832f37b00',
    'thaliris-reasoning-specialist-xhigh.toml': '476a79f410a5f68bbae0a8c4257ac69873523f73cb8d4de6fb3de8725a638817',
    'thaliris-reasoning-specialist.toml': '3f2caaead9fbb239a3dd4d118762efb70a60b9954cfa287954033a4a9694d0fc',
    'thaliris-reviewer.toml': '58e4dce82be3a5fb2483f86ebc274c306eb8f1ede469a0794fc6b7eb545fa938',
    'thaliris-verifier.toml': 'fc1d73fec897f250125e3031d8c02ef0e035411467ed0126f62df193e8345188',
}
for _historical_profiles in (_HISTORICAL_28E4297_PROFILE_HASHES, _HISTORICAL_69D9A33_PROFILE_HASHES):
    for _profile_name, _profile_hash in _historical_profiles.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
            _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
        )

# Exact SHA-256 identities of the complete eleven-profile set rendered by the
# immutable ba84553 adapter/registry revision (source blobs
# e1262c3440bdb5f6007a0cab5d78b49141cecbd9 and
# 151f4ea6a403062fcc070acfd8b5fd1f830600f0). These hashes were independently
# compared with the effective CODEX_HOME files before being recorded here.
# They are historical generated ownership evidence, never a claim made by the
# current renderer, and remain keyed by the exact native profile filename.
_BA84553_GENERATED_AGENT_PROFILE_HASHES = {
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
for _profile_name, _profile_hash in _BA84553_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact SHA-256 identities of the complete eleven-profile set rendered by the
# immutable 1f98dae adapter/registry revision immediately before the focused
# role wording update (source blobs
# b7e26ce90a940ba874390ab4cfa72982c2d0f813 and
# c0ec3ad81b5461bff4d09aaf3e7a5357f2a3d407). These hashes were independently
# compared with the effective CODEX_HOME files before being recorded here.
# These hashes are historical generated ownership evidence, never a claim made
# by the current renderer, and remain keyed by the exact native profile filename.
_1F98DAE_GENERATED_AGENT_PROFILE_HASHES = {
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
for _profile_name, _profile_hash in _1F98DAE_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# The three exact focused-implementer profiles emitted by immutable revision
# 40fd5f2bcb928f8f9443b01389168f6a1b8e3054 (adapter blob
# d1badfc56feb2c65a72f80d158ce67d0ad88f30c, role registry blob
# 2e092e2e9293c6b51897a83e8b5de9d8326b2225). The effective Host files
# were independently SHA-256 checked against these historical renderer bytes.
# Preserve filename binding: a matching digest under another role is user-owned.
_40FD5F2_GENERATED_AGENT_PROFILE_HASHES = {
    "thaliris-focused-implementer.toml": "48b73ecaea2cd7b3c2515c0dfea69e1a7291c8e08599c1ddc9011208fcf3b6a2",
    "thaliris-focused-implementer-astra-medium.toml": "3f7142b441521aca5b978b38a7c5de081eab7326c327524bdc9214b20c5b2971",
    "thaliris-focused-implementer-xhigh.toml": "774b28e8a99a5f7396013cb94b2e183e57a940c482919526cf814fc54e018287",
}
for _profile_name, _profile_hash in _40FD5F2_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact SHA-256 identities of the eight non-focused profiles emitted by the
# immutable fd4fba36 adapter/registry revision (adapter blob
# 45b0e509dd491adfc2f55723036e4f1aab5a7cc2, roles blob
# 2e092e2e9293c6b51897a83e8b5de9d8326b2225). Each hash was independently
# matched to the historical renderer output. These remain exact-filename
# ownership evidence; edits and cross-role copies stay user-owned.
_FD4FBA36_GENERATED_AGENT_PROFILE_HASHES = {
    "thaliris-curator.toml": "74aebff8c07c2a3359461085d165d440e8c6b8e9ca2d5ac9bc6c57ca83e91653",
    "thaliris-implementer.toml": "bb0767422861b66e0becd3386d6f0d5faecf247bbda767c52118ee58184ed613",
    "thaliris-investigator.toml": "d14a5376c3644495746fedcf74f92dac62bdca2321419473fd0dc8407ce8bc1b",
    "thaliris-reasoning-specialist-astra-medium.toml": "f1d75968331cdcc6e3b3e447c79909b02070475cfc2d764b83c2f4515f290f6e",
    "thaliris-reasoning-specialist-xhigh.toml": "0d05efd7edcb17965a1c6f3dee7b1152dcdd9ced067e86d60b878b9f3f6b0705",
    "thaliris-reasoning-specialist.toml": "432517da403000383ecf9ee0793122c1fe03aae2a8ef3395d6b8449b6b6ab73a",
    "thaliris-reviewer.toml": "44e684ed9a49c1f4d5e50e12b483136e148c9969c1cbc9ae6495fcd1b5a90a62",
    "thaliris-verifier.toml": "571bdd8c11d06a2393f1554f48621892c652dd6c09660a5d9fffe97844e6d59f",
}
for _profile_name, _profile_hash in _FD4FBA36_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact generated profile bytes from immutable 8a3fe930 (roles blob
# 758a31568fb6b8755b68721028d9b4a912bb6ef0, adapter blob
# 7c7d7ea689461206502efe9fe4f521df5489dae4). Only these four profiles
# changed in the role-contract update; ownership remains filename-bound.
_8A3FE930_GENERATED_AGENT_PROFILE_HASHES = {
    "thaliris-focused-implementer.toml": "a929ec5bbbb748a880a95fea40aec4de05b225269e70473937c9deee3411608a",
    "thaliris-focused-implementer-astra-medium.toml": "e22136925d2bcaed111c687c47a8de1464014427a6c8bbed7e1021076bd20d8a",
    "thaliris-focused-implementer-xhigh.toml": "1f4311da03a5ee0185253156c3510ed3c2855f0a8091a4699a80b1ebe7b9ca9a",
    "thaliris-reviewer.toml": "4b1593d4269bccd7e86da5fabaa129f9da431302e072469e60f273abb36a05a0",
}
for _profile_name, _profile_hash in _8A3FE930_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact Focused Implementer profile bytes rendered by the immutable 99a58fc
# revision immediately before the focused-work guidance update. Keep each
# identity bound to its exact filename, including both exceptional profiles.
_99A58FC_FOCUSED_PROFILE_HASHES = {
    "thaliris-focused-implementer.toml": "b4ff152b4a3978f31c7b80891a839bf1bd8408336fe19b2c8c27d42bf88d0311",
    "thaliris-focused-implementer-astra-medium.toml": "9b412596980063afae0a4678043e09ca6f3509735e55f373119c3da3655831ef",
    "thaliris-focused-implementer-xhigh.toml": "501fc4fc95c883f9249c649e6477a7d98babd97e41942b036da94e0086c3f662",
}
for _profile_name, _profile_hash in _99A58FC_FOCUSED_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact SHA-256 identities of all eleven generated profiles rendered by the
# immutable 210782b1d652e8266859e2999e558be8e061d46f revision. Its packaged
# roles.py and codex_adapter.py were byte-identical to those source files; the
# renderer output was independently matched against the prior immutable
# installed runtime and all eleven effective Host profiles. The focused test
# re-renders these bytes from that source revision. These filename-bound hashes
# establish historical generated ownership only.
_210782B1_GENERATED_AGENT_PROFILE_HASHES = {
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
for _profile_name, _profile_hash in _210782B1_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact output from immutable dde3d0f872d7b1b9ecb97d2aa59049ae104f6363.
# Re-rendered from that revision's source and matched byte-for-byte against
# all eleven effective Host profiles before changing their instructions.
_DDE3D0F_GENERATED_AGENT_PROFILE_HASHES = {
    "thaliris-investigator.toml": "96a633af50c1ddf32c8be39e744536a7c0f7368dd536400aa5a87b3766f065cf",
    "thaliris-curator.toml": "3740fdbedb75b7196aa4d5ce64afd6a46626ef5cd6128c7c80d58030e2615f42",
    "thaliris-reasoning-specialist.toml": "f74fb5f14bcd0addab1aa3c854ff1a89d319152b2e274293aea94c0cb8d478ad",
    "thaliris-implementer.toml": "bc01341e1380d7677e6404a4329b06e2412daf300b50b11ba45a983e5ea33039",
    "thaliris-focused-implementer.toml": "07402540f774fb554843915c104383eedb6646d14c51b41dc32f1e9a87a40883",
    "thaliris-verifier.toml": "2e7d71453611cfcfd956dc82c9727bb4f055492b417fce608264386f2d11c99d",
    "thaliris-reviewer.toml": "f94e08afe5021d1284839465964a91b2b550d392029725b6d6d6ba7ee991b699",
    "thaliris-reasoning-specialist-astra-medium.toml": "1f66a702a5dd8c58f5ccbade5e3cabeb8790cf29e1463ae072f0af41dfaebacc",
    "thaliris-reasoning-specialist-xhigh.toml": "bc9c4c5eb8a8b39015a9664728f1f16eeef516269b0d856408ff8071b5107e88",
    "thaliris-focused-implementer-astra-medium.toml": "2472c64230f3315c55a084d504c57cd117e9d743314cd6bd61c8d1a06e9fb9a7",
    "thaliris-focused-implementer-xhigh.toml": "0fa1303f77009d11f8e4932081b5a99f25ca9e025b2954a14065b4436511d855",
}
for _profile_name, _profile_hash in _DDE3D0F_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact focused profiles committed in immutable 8eb1707; each was independently
# re-rendered from that revision's roles and adapter source and matched bytewise.
_8EB1707_FOCUSED_PROFILE_HASHES = {
    "thaliris-focused-implementer.toml": "3b19e5d8a0e72e794f76883ad3242c83bb4d542388c076ffacf9a28e377bf86a",
    "thaliris-focused-implementer-astra-medium.toml": "7ae1bef593fc06fa4d8e5ee40a009718b0ca31358ed1a9de362dc3cfb65055e3",
    "thaliris-focused-implementer-xhigh.toml": "fe996dfb59c467d173d7da754bbe73ee9659d88b7bb27ff09cc32c730a6fd2e9",
}
for _profile_name, _profile_hash in _8EB1707_FOCUSED_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# Exact generated bytes for the four affected profiles rendered by immutable
# revision e4b6975889ef348e13e94521dc300f1e572b42a3 (adapter blob
# 16ad86097d0635c25f1a3acf936963930c7f310c, roles blob
# ca8daae4f2182028d7927daabcca917ff4b17447). The installed runtime and
# effective Host files were independently matched to this revision. These
# historical ownership hashes remain bound to their exact profile filenames.
_E4B6975_GENERATED_AGENT_PROFILE_HASHES = {
    "thaliris-implementer.toml": "88ea13ad079412a4569a2360731d4bb377d9b20cb313cc9a882065cdd5861f29",
    "thaliris-focused-implementer.toml": "1eb28a0b74e72fcf4e03f63ec3ddba12d4972ab3f7cfb71bd02efc1b748cbd45",
    "thaliris-focused-implementer-astra-medium.toml": "37dacbc67a27f3551d6e60b26bc520113c274d233c01fd85c2d507806f62e625",
    "thaliris-focused-implementer-xhigh.toml": "c66aa6e934a6fdc354eda44d60145d6e92a4e7c4b65be796a18094ce03817a3e",
}
for _profile_name, _profile_hash in _E4B6975_GENERATED_AGENT_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
# The three project-local Focused Implementer files committed at ec1ad7b are
# exact output of that immutable revision's renderer.  The current files were
# independently compared byte-for-byte with that renderer.  This evidence is
# bound to each filename; it does not establish ownership of the other local
# profiles or of similarly named files in another directory.
_EC1AD7B_FOCUSED_PROFILE_HASHES = {
    "thaliris-focused-implementer.toml": "edeb1136eab3d7685552e7a8ec4da70a7cec22085dc236e203a7ef2c7d8f03a4",
    "thaliris-focused-implementer-astra-medium.toml": "6b255fa51ad04def5bbe248c30d5e247bb17af3913cffd815e283ec9178aae53",
    "thaliris-focused-implementer-xhigh.toml": "6484ff491175ebf56a63d65d7439c3c661f782e6401c09e43f6bfbf26a3f0ff1",
}
for _profile_name, _profile_hash in _EC1AD7B_FOCUSED_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )
_KNOWN_GENERATED_ROLE_PACK_HASHES = frozenset({
    "fd5542ef501e16bc3d409f1e463e465080e1e7e0063164ce113a917ef397a95d",  # immutable 4a754d2 renderer
    "4e4a1af986df48f8c9e0e632506ef13636531dba163fa7ae7032a7d18ab2c36a",  # ec1ad7b committed generated role pack
    "4f6f4a41baedc5bc0b01fa8a37b86d3bdee2384846e260bf8f896cff12b650f4",  # e4b6975 committed generated role pack
    "7009fc69d97ca403404c57d739e354cc3ebf7656fdca690c0fd60b2cfa9f6267",  # 9b5bcf2
    # 5e6554196d27c4d6bc87c2a8008bd3c37ef01b31, blob 7dfd7ab321c4ec1f1c32bd02b1d87f1b88d2aef7.
    "0a51833bf936b14053c08a6502a6a1d27ecd1518263e7eea5c4e43f53fa1c5f1",
    "b6dba8d5d5e855face02667993601f84c4a54e77d7c33012d542a6b91483ec6c",
    "c019c41505c8bc000a5d00151fe837d4d1e9000f242bdb9f98bb7add905104bc",
    "844a2278b311c253c2da3a06133b503edb822a2929eeb082b50ecd2925e4cd30",
    "e14a01cfb3444ed553e43472581b6bf59b5858d6bdc279f61fda17823b4670b0",
    "e3473113697a9343d0ca108468434b26a53b8d8175a4f344e86067e93bf2c853",
    "ea1f1c8386b41a0138bcdf3691cae95cc9c816db47bfa14dcdcbf36d2e87f0d9",
    "cc609291e31edb07d89784a1fe6f6d933dc8351229c1e66f5eb909da2db99e34",
    "2636a41ddd2f5cc3c9ee4efc522acc891b36068b67c1839593a1336c155497e8",
    "5d798d5a45e522db623a4d22b618e1e674905aa46da95acba6733a51f9d63a9d",
    "df6daef7e33c0032179c462f25afdc9af8883d2677c3d34c98b735039c0ad3e0",
    "4ee70a3c36b2c76d74c03179359181dfd34c96bbfae5bf1e5e7ee1c71b6f13d7",  # 8a3fe930, blob 3253fc8
    "d2b3a1c5a776f6a1dbb3be52a907c1704903f64a92d2388f64dc2171096e92e8",  # 99a58fc renderer output before focused-work guidance update
    "44fad20e3e751dcaaa4d055d567bf3875242b158e62c58f312c4ea0bfdcb025c",  # dde3d0f exact committed generated role pack
    # Exact generated document at immutable pre-update revision
    # 3094c0a69a620780558b535cf6aaf0f91ea66b62.
    "411188829d23a709901ae00137397a038d2168a990ec375e67425beffe63d181",
})
# Exact SHA-256 identity of the mechanical role-registry document emitted by
# the first registry generator.  This is historical install metadata captured
# from immutable commit b1d517f (blob 9c410a4d2af5d3780f4b415429227150d08626bd),
# not an ownership claim derived from the current registry.
_KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES = frozenset({
    "8a1393b2e175860242923d7387a6207b44fb13fc5b2900b10219458264ca3fad",  # immutable split 158690b document, independently compared with its renderer
    "b4ed3e53315009c79bb48f3b221e8599c36a47574b90e6ba56e0e7791a2fe982",  # immutable 4a754d2 document, blob f3ed5169eb5ed53e1c3bde4445ce0c275fb64e4a
    "b55b370ac265e4802f19d4034b234d8725437ade2e286eb52d1f0c4142a04e91",
})
# Exact managed spans from immutable repository revisions that carried the
# renderer equality test. A marker alone never establishes generated ownership.
# 3485ec4 is the predecessor release, not the candidate's generated output.
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES = frozenset({
    "90c383ae48e7a0c0bac9e6f9cff5191bef01ecd901a58d8cb475570b5b42984c",  # immutable 4a754d2 renderer; not its user-edited AGENTS block
    "df7c8832a47f59fac6ba2692bb54166a629cc4bdbc4b58661582a42bc04fb152",  # e4b6975 committed managed span
    "d249d418ccf38ca3f159065715c3930d492682e93402025d067e99e2225b91fd",  # 3485ec4
    "1b1cb7331dddc504a0908af91e32fba2b72cced74af1b56007099bb088b36c56",  # a33db5b
    "c0072af2e11ee5ed315712c301a33c39a993af13d6243816b319700b432ef2ed",  # 729809f
    "0238e56f242ca68c31d8b63c6d34ffcecc88ace6e245cad986ca3bd1c21e78d2",  # 3ae1b21
    "66c1ac81e010fba307cb579b519142124ddca128e028890f48c7e33f8fac6a11",  # 8eb1707
    "bc47c81d7004bc8a4095cc5d9079068af9ca3d2804a5a557d17a5abaf371f494",  # f316910
    "943c67bb7683785403429063bec0a0174119e8c2dbbe70f6684b8c46d1434c0b",  # e02b953
    "96102e74cd2812e2f06382173807939c79e856371180f94c1413ba8e26e8facb",  # 8a3fe930, blob 93d73da
    "3c1e3475797d0c9270d9adafa210492b8b305748f5e7bd7fc9411752f74d959d",  # 11e0cc9:AGENTS.md, exact published managed span
    "adebcedf67d1e3aa3e33d42da1174ea36d9e4199beb8453d8076a1de72cd638a",  # 9b5bcf2 renderer output
    "9b3ae3c7edbfc74255a3c743dc9a1c430c6c936ea3101b3f0777f2a78eb4c7b8",  # 99a58fc managed span before focused-work guidance update
    "3787a539d15224a357bc2703215dea7a474b43f8b3fe85f43f43b30cea854807",  # dde3d0f exact committed managed span
    # Exact generated span at immutable pre-update revision
    # 3094c0a69a620780558b535cf6aaf0f91ea66b62.
    "febde2dd8181652986a05d27ff9763a57e9cbc21b7916d84616802cdc9c40e9f",
})
# Immutable 6396e138 source witnesses and renders are retained under
# tests/fixtures/prompt-contract-before. Matching edits and cross-role copies
# remain user-owned; no current-HEAD historical ownership inference.
_PRE_NORMALIZATION_PROFILE_HASHES = {
    'thaliris-investigator.toml': 'd34b8571689c0ffc5e68cd5fb316ef1b26d41dfa8e2e363e34bf8b465ecca544',
    'thaliris-curator.toml': '591e347124439005370b416f094c4f1fccf5d6b9283111fa334cc35a00cfc96c',
    'thaliris-reasoning-specialist.toml': '196dd48254f6a70efc107a6e8102fe0c213f340f1c3121c81ced631eadfdd6ec',
    'thaliris-implementer.toml': '12d444bd5e6e4692b9273c4d27e0a455dbae51bc111df93698a36af20917089d',
    'thaliris-focused-implementer.toml': '7d782db39b9bc717d66829e601f2d98e37b04dc60cbb8f88ae1236e5fcf5614c',
    'thaliris-verifier.toml': 'fc1d73fec897f250125e3031d8c02ef0e035411467ed0126f62df193e8345188',
    'thaliris-reviewer.toml': 'a68a71a887329db70b7a0c4a1678265bf50bf8559d2e448a424c927e6d5e88da',
    'thaliris-reasoning-specialist-astra-medium.toml': '31639f9b001b0b8ba88c6733e6c881f98b817513257c1921b67790c832f37b00',
    'thaliris-reasoning-specialist-xhigh.toml': '476a79f410a5f68bbae0a8c4257ac69873523f73cb8d4de6fb3de8725a638817',
    'thaliris-focused-implementer-astra-medium.toml': 'b4e4f862e020beb7741a150df71ec34fda7b668d3f24b3833bb88c17a497316a',
    'thaliris-focused-implementer-xhigh.toml': 'bc47660b4eae25733cc6a7542e3757226d0f61a59b21510f5b165af11db2f719',
}
for _profile_name, _profile_hash in _PRE_NORMALIZATION_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
    )
# The immutable 6396e138 renderer also emitted this exact luna-only set.
# Filename binding remains mandatory; user edits and cross-role copies are not owned.
_PRE_NORMALIZATION_LUNA_ONLY_PROFILE_HASHES = {
    'thaliris-reasoning-specialist.toml': '2e676eb0320e3db6dc66d6b088e5bd576bc68a8a906dbade0dd45723cd9a501e',
    'thaliris-focused-implementer.toml': '2cf93560defdfab4d77c853b3c9e29371894c0279acee84f0cfb345d0a92f3e8',
    'thaliris-reviewer.toml': 'db03a68d46eb5057da6f72e04fea9dec3a1c48c0e2e32b0d2581272bb63343ae',
}
for _profile_name, _profile_hash in _PRE_NORMALIZATION_LUNA_ONLY_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
    )
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES = _KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES | frozenset({'5dcbf66972efa6bc2b7888eee060a87c448ea7ee6991eae93d98ce8298dc7cd9'})
_KNOWN_GENERATED_ROLE_PACK_HASHES = _KNOWN_GENERATED_ROLE_PACK_HASHES | frozenset({'0f8db6dc0f89c5ae6d82a84de8e38b7e63bca877cdf0e20fa1fe452ae5dd82c8'})

_KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES = _KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES | frozenset({'04d6b201ff2329e8e203808a041d7243335eecebedcdbcb9094aee2dd4067014'})

# Exact prior 7045c7de outputs, independently replayed from its role source;
# tracked native profiles were compared byte-for-byte. No current-render ownership.
_NATIVE_INTEGRATION_PREDECESSOR_PROFILE_HASHES = {
    'thaliris-investigator.toml': frozenset({
        '061fac29692264c5110c33f139c1bffdaf2f6e9475eb3e1db9ac8cba9d1f9533',
    }),
    'thaliris-curator.toml': frozenset({
        'a3cc082f0a3047fb88da9bd62b8a0c11c90754f203a9804c4541e7766ae63b14',
    }),
    'thaliris-reasoning-specialist.toml': frozenset({
        '613ae91b36c9a13d6982751f003bbce316b0cc88c41145af2e69d893bd761642',
        'd60806998f08871aeaa34556b936d7b300e7bd3cda98323ed7e8d0c7d0f8ba19',
    }),
    'thaliris-implementer.toml': frozenset({
        '2226e75df4098378f2af73d802d7b535af007506a827091f379a499fadd879a4',
    }),
    'thaliris-focused-implementer.toml': frozenset({
        'd7137acf77e439f628743893e27adc4e7c039e069a2980aa43100616d833b757',
        'db56acafac386dc26b7f4d23d862b95311dfdd719b5826254310453b709262c2',
    }),
    'thaliris-verifier.toml': frozenset({
        'bb93576ce6ee0649ffd51baed6af9acbf582e62a6a614a8c94890d763268acd7',
    }),
    'thaliris-reviewer.toml': frozenset({
        '2a15fc83200b7f00f0c29f57d5b0c906d1179cfce901fc38ca2f00bc5f0d039d',
        '2fce0899c36c42ad86b86caf349c291af04302739397ada4ba11b2ae471e43d1',
    }),
    'thaliris-reasoning-specialist-astra-medium.toml': frozenset({
        '21c570cd6243d02d9077485d92f6258d556a69edeb4e4b1c37caa9a072e06037',
    }),
    'thaliris-reasoning-specialist-xhigh.toml': frozenset({
        '3c5d45e320562eb604ad78d3ce170cebd88413ef235c34a758e23574857bbb75',
    }),
    'thaliris-focused-implementer-astra-medium.toml': frozenset({
        '2fc299fda4d7b82473a5aa367394be39fe4047c6c46f4d848622a53a115c02bd',
    }),
    'thaliris-focused-implementer-xhigh.toml': frozenset({
        '365e4c9362f176a94d1c60ba36cb0dd9baa072cd71c987b0cf8af7198a7b09d8',
    }),
}
for _profile_name, _profile_hashes in _NATIVE_INTEGRATION_PREDECESSOR_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | _profile_hashes
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES |= frozenset({'e59e6654cf81fb71bed838618a09dfc96a9709c5cc58a0077b09ea0ad76ae088'})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'3e96d0dfee9a246582269fb1951ce779c8970117ecddc2a6160162a6ad230c36'})

# Independently rendered immutable 3d2d302 predecessor; see orchestration-before provenance.
_ORCHESTRATION_PREDECESSOR_PROFILE_HASHES = {
    'thaliris-curator.toml': frozenset(['1bf0a0422df0966c5ada8d37dc7311060efc20f381f48c8f60604a180c85a5f2']),
    'thaliris-focused-implementer-astra-medium.toml': frozenset(['d3f739f0dcada7c9e473d1fa77250f2506b233866dae7e26e0ca14d580f81c1f']),
    'thaliris-focused-implementer-xhigh.toml': frozenset(['df484eb48bfdad86314f87192a6bcb18abb25ac3d6c65dbdada40baf732c335e']),
    'thaliris-focused-implementer.toml': frozenset(['411cda72bc89ea8f27d51acf6bdab17dc6a0bf24a1af99b67c9a0e8fccb04578', 'dfa358e95e92174ee2bf1fe462337aef6c8105aa070a94291f4ce4128d2ed5ab']),
    'thaliris-implementer.toml': frozenset(['816434c50701253107e72d571c62c223f68378edc2a939a70d8003c6c4e07eec']),
    'thaliris-investigator.toml': frozenset(['dd0075723ee9c5baba4c2b4fed35b94bfbc0173409209d8cd31719242df0d3e3']),
    'thaliris-reasoning-specialist-astra-medium.toml': frozenset(['4ba6322a1391b24aa6358cf8c89ba0eb2f12daa7ddd84025a39cc6f0b05e73a1']),
    'thaliris-reasoning-specialist-xhigh.toml': frozenset(['4a877a8e464c40fe82ee9e71bde3a6647799f8a9f5c8033bb7645d7d457a31d4']),
    'thaliris-reasoning-specialist.toml': frozenset(['4348fd39f46791f31f483d45deed37769fcc7eab1ddc219bcc227ea0879a9033', '63847f63f04b5bfa9a6ce57c620030c7c37ec50c41765bcc498e67a51d28acd6']),
    'thaliris-reviewer.toml': frozenset(['6dc05774bd2d443f4509758167da48c820c8db5d8718a8390dd68b728c72c826', 'cdb634485ed110e819c7c394377969705853c2ba9ee71351930a548f5f2fb951']),
    'thaliris-verifier.toml': frozenset(['5897a210bda97a99ec1c019303b2923d085b74370f1d86b15629a115612b7be1']),
}
for _profile_name, _profile_hashes in _ORCHESTRATION_PREDECESSOR_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | _profile_hashes
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES |= frozenset({'b65f45a9335c174d542368a0ec69c1d10ea8b898cbdeefbf31b31ca5eee10bd6'})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'3c54cb36dd73d82c180e8fe7b659d9a9a4c98f9c6ab1be148c8469b67c1eb526'})

# Exact filename-bound output of immutable 5f80214bb8d4ef219851405b017f660c5f8b554e.
# Independent source/blob and default/luna-only witnesses: role-model-before fixtures.
_ROLE_MODEL_PREDECESSOR_PROFILE_HASHES = {'default': {'thaliris-investigator.toml': '2097e14170126ac4a875a0871c341514ec04ccdaceb342d1c62b6c3049271aba',
             'thaliris-curator.toml': '29b5160bd0d7b14f98b2ff2a3d38eadc4531fba6626ce50f991aeccf94b2531e',
             'thaliris-reasoning-specialist.toml': '7fba12985f08117a4fad30e8c5f84cbcadcbe925ca5794be5ec1bf959b38316d',
             'thaliris-implementer.toml': 'caaea59835f5298ea40e579c5e48d32d20957f913d08c0b92aa8447b834f67a6',
             'thaliris-focused-implementer.toml': '0d77bc6f8b289816a49a82077f817564b295af3aa99864598be5641177d03fbc',
             'thaliris-verifier.toml': '1c4bc1c070ae85470649fb644cd722383ba8e963e4f213efd64de8973f47ac40',
             'thaliris-reviewer.toml': '936a380a53f7d48b8e9e9a14d298daf4bd703791420dda86b60b8b6ab80f7c40',
             'thaliris-reasoning-specialist-astra-medium.toml': '0cb2407978fa5ead51910f0be2bc1040d4c41d1c95edcc2b598cd149545944e7',
             'thaliris-reasoning-specialist-xhigh.toml': 'cef6f5ff5f83bff32886bd8330c1fe453a593aa9f5463b31ee68e59e24d19ce2',
             'thaliris-focused-implementer-astra-medium.toml': 'b92a19bb533c2de930ff735d0305ad36b19e68815849cb4859359f64ca6e07b9',
             'thaliris-focused-implementer-xhigh.toml': '43b9b56bbd5f51501069feb4a2badd74679d9801c2e903c4b20d860e8dc8b0cc'},
 'luna-only': {'thaliris-investigator.toml': '2097e14170126ac4a875a0871c341514ec04ccdaceb342d1c62b6c3049271aba',
               'thaliris-curator.toml': '29b5160bd0d7b14f98b2ff2a3d38eadc4531fba6626ce50f991aeccf94b2531e',
               'thaliris-reasoning-specialist.toml': '04b52b097d727a81fa79d79d337e8560560490cb419abee61f2c294b6e70e036',
               'thaliris-implementer.toml': 'caaea59835f5298ea40e579c5e48d32d20957f913d08c0b92aa8447b834f67a6',
               'thaliris-focused-implementer.toml': '9ca15bcd5ce8051e0a419a77c0029d04e8fa80185eb666e9f48fe504543e86ce',
               'thaliris-verifier.toml': '1c4bc1c070ae85470649fb644cd722383ba8e963e4f213efd64de8973f47ac40',
               'thaliris-reviewer.toml': '9ffcc6e5e8716d94be7a5c0c196bfca694a0dbe3ff4c724bd872e87f076f953d',
               'thaliris-reasoning-specialist-astra-medium.toml': '0cb2407978fa5ead51910f0be2bc1040d4c41d1c95edcc2b598cd149545944e7',
               'thaliris-reasoning-specialist-xhigh.toml': 'cef6f5ff5f83bff32886bd8330c1fe453a593aa9f5463b31ee68e59e24d19ce2',
               'thaliris-focused-implementer-astra-medium.toml': 'b92a19bb533c2de930ff735d0305ad36b19e68815849cb4859359f64ca6e07b9',
               'thaliris-focused-implementer-xhigh.toml': '43b9b56bbd5f51501069feb4a2badd74679d9801c2e903c4b20d860e8dc8b0cc'}}
for _profile_set in _ROLE_MODEL_PREDECESSOR_PROFILE_HASHES.values():
    for _profile_name, _profile_hash in _profile_set.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES |= frozenset({'0fc5f465d6543b0ab4a2087b4de41511991a20683902fe8e5fc48b971b8f0692'})
# Exact canonical managed span from immutable adapter 1551e29fb69af971ee51478184b2ced3bd1b76e9.
# Controller-only shared ownership guidance changed; native child profiles did not.
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES |= frozenset({'42c93d3705db662650025949921530d68caccbc071404f63be413d53217a5e70'})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'e6b28d06d39de22f9a7fc5d80e07eaf044caf45a328551834dbcb2336123360b'})
_KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES |= frozenset({'ffecc599a0e593d7634d837a9b32150c1782602f4bdd0ec3941673de3efe5dc6'})

# Exact filename-bound outputs from immutable 41157f59ca26657e4b8ef99a09d55cbf6229fded;
# tests/fixtures/all-layer-wait-predecessor retains renderer and Git-blob witnesses.
_ALL_LAYER_WAIT_PREDECESSOR_PROFILE_HASHES = {'default': {'thaliris-investigator.toml': '54f34cf19fc31e9fd7d71c8b72853c1e222125f23f66c9e5caa3f2b5bf73a325',
             'thaliris-curator.toml': '918d995f999c740c5df7878ac2d2f1dd7109f860834d567bdf3300eb7c29d769',
             'thaliris-reasoning-specialist.toml': '68b52f3cf672b2706854a29337c00ae6d37873add1931294b5f5cfd087e3a934',
             'thaliris-implementer.toml': 'b6f2dc5d679a4e40e09888fdafd658f59502c8bccd5c9b6bf71f78f0524b235b',
             'thaliris-focused-implementer.toml': '580470c3e98de8e0967d6492e90d52b671f174ec354bc9d4e61a28ca3c30d20f',
             'thaliris-verifier.toml': '838ddb9b867a108abc0f09773dec73ebcb796e7a40479a14d7debdd831f21acb',
             'thaliris-reviewer.toml': 'fede9888e91be61417dc9f03662cfeff70c0e156486300071314cf4aac11ce5e',
             'thaliris-reasoning-specialist-astra-medium.toml': '0cb2407978fa5ead51910f0be2bc1040d4c41d1c95edcc2b598cd149545944e7',
             'thaliris-reasoning-specialist-xhigh.toml': 'cef6f5ff5f83bff32886bd8330c1fe453a593aa9f5463b31ee68e59e24d19ce2',
             'thaliris-focused-implementer-astra-medium.toml': '2c9c9dbecdb69c590ddd48e574c6e06d65c93f581a379c04fd7f529edf1b7a5e',
             'thaliris-focused-implementer-xhigh.toml': 'd8ebab7c88e5dba8e4fe7ac893360ceb732aafadba40857028a13efc6bc34a6f'},
 'luna-only': {'thaliris-investigator.toml': '2097e14170126ac4a875a0871c341514ec04ccdaceb342d1c62b6c3049271aba',
               'thaliris-curator.toml': '29b5160bd0d7b14f98b2ff2a3d38eadc4531fba6626ce50f991aeccf94b2531e',
               'thaliris-reasoning-specialist.toml': '04b52b097d727a81fa79d79d337e8560560490cb419abee61f2c294b6e70e036',
               'thaliris-implementer.toml': '8d731714b1e9e4cbc40156f69716444131d6d509e6605970de5624d8d2acd713',
               'thaliris-focused-implementer.toml': '0289ee18a671da351634a309ca3ed6d32865b38d6fc65853c3e0c5ad1297ad59',
               'thaliris-verifier.toml': '02b61aea580a02b975b7836376153c8eb58f42d44fa71c2e04bb750e9a74f5f9',
               'thaliris-reviewer.toml': '3f7ec5db8bb22ba29f88b53bc0443e254f6c2e7446e6a8650d8be50de2c9eabe',
               'thaliris-reasoning-specialist-astra-medium.toml': '0cb2407978fa5ead51910f0be2bc1040d4c41d1c95edcc2b598cd149545944e7',
               'thaliris-reasoning-specialist-xhigh.toml': 'cef6f5ff5f83bff32886bd8330c1fe453a593aa9f5463b31ee68e59e24d19ce2',
               'thaliris-focused-implementer-astra-medium.toml': '2c9c9dbecdb69c590ddd48e574c6e06d65c93f581a379c04fd7f529edf1b7a5e',
               'thaliris-focused-implementer-xhigh.toml': 'd8ebab7c88e5dba8e4fe7ac893360ceb732aafadba40857028a13efc6bc34a6f'}}
for _profile_set in _ALL_LAYER_WAIT_PREDECESSOR_PROFILE_HASHES.values():
    for _profile_name, _profile_hash in _profile_set.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'77b0f582764de7a713f008e51194e21b85a49539d51151e432415f2596551657'})


# Immutable 5d65c128 predecessor; source and renderer are pinned in fixtures.
_ROLE_WAIT_SCOPE_PREDECESSOR_PROFILE_HASHES = {'default': {'thaliris-investigator.toml': 'c83ce88656ec2b81b1cd028e67fef5b4342346eadb6689841408638dc0d05a96', 'thaliris-curator.toml': '8f607364e0bdde6db5e969d00f0450b25060c7ace187c868d7b659d4dbd1d67c', 'thaliris-reasoning-specialist.toml': '34c27f7edf7d48a433e9d77153f4a68bbaec0e7a7b79b69eb61a1bfb5797cdca', 'thaliris-implementer.toml': '3304aa453e614949803e72257e6dff0632fbfed7f8cef23df7eb31bc1a2aacf9', 'thaliris-focused-implementer.toml': '43e3f17c3ded67848b991251079d3323183c23b12be75f6f036955a8ad7a395f', 'thaliris-verifier.toml': 'de4d50487e34772b763076fc996f2dade84c99f89dc9479753697edbc454fd6a', 'thaliris-reviewer.toml': '314ff6d2846d753212b7ead1c2d21f0f66c5d5fe23c03e41e147a0cd6a393c0c', 'thaliris-reasoning-specialist-astra-medium.toml': 'ff780e0f49a5b7b405cdb5f08f1351878e658ad7b032ca03000db33b7bc4f756', 'thaliris-reasoning-specialist-xhigh.toml': '7018d45917a41e50ebd692a8e9ac5282fa8f19772d08f627338d9a0470ce7b8c', 'thaliris-focused-implementer-astra-medium.toml': 'aaeb64e8aa62f551d2786e00a7e2a3c06c767bbaa4938c91902ba363f4cbd159', 'thaliris-focused-implementer-xhigh.toml': '1fa63dbf7105cbf3327e40a5b29f0efb8842046d5ecc978de0a491ba6107bd4a'}, 'luna-only': {'thaliris-investigator.toml': '0a0311de57b0931b3a96fe235868bc8ff3ee2a8421efd9915558a3e49e5e9e32', 'thaliris-curator.toml': 'e98208e47358706270fdbd5d671039a7caa43e4c39559efeed36bca434c4a03a', 'thaliris-reasoning-specialist.toml': 'a055e348e1ae49a2538829e2e41248fe95a9310743984ae8130faa19538c1635', 'thaliris-implementer.toml': '64ff2a185f2f90995aed66f566585df5e8364e7b053e3d85a211288e49645fce', 'thaliris-focused-implementer.toml': 'd86c068d9f8babbd9c0e7975774605ff353a663c21f0a8a880fe3f15cff43f67', 'thaliris-verifier.toml': '63f6aced59ac0f9e2399209dd09ab6d809261d16e2dbee1dadc6c0f464a6b38e', 'thaliris-reviewer.toml': '89e1d000fe3d7a5f8c8f62cc4ced49bf02bc9cd8c4ac364499f58b8bd6ad82da', 'thaliris-reasoning-specialist-astra-medium.toml': 'ff780e0f49a5b7b405cdb5f08f1351878e658ad7b032ca03000db33b7bc4f756', 'thaliris-reasoning-specialist-xhigh.toml': '7018d45917a41e50ebd692a8e9ac5282fa8f19772d08f627338d9a0470ce7b8c', 'thaliris-focused-implementer-astra-medium.toml': 'aaeb64e8aa62f551d2786e00a7e2a3c06c767bbaa4938c91902ba363f4cbd159', 'thaliris-focused-implementer-xhigh.toml': '1fa63dbf7105cbf3327e40a5b29f0efb8842046d5ecc978de0a491ba6107bd4a'}}
for _profile_set in _ROLE_WAIT_SCOPE_PREDECESSOR_PROFILE_HASHES.values():
    for _profile_name, _profile_hash in _profile_set.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'07b0565e3790ae2768c557a50ce6e48feb6a366ec8eae3e4b0768a44129d22a1'})

# Exact filename-bound profile outputs from immutable 257df596fd2047b4ca819992fe1a388ed23b4ef9,
# captured before the product-completion and durable-memory prompt update. The
# tracked profiles were matched byte-for-byte against that revision's renderer.
_PRE_ACCEPTANCE_UPDATE_PROFILE_HASHES = {
    "thaliris-curator.toml": "7696a236eb4eefd700b34e763c24c7f22d361c280474de67b0c5182538a2a15f",
    "thaliris-implementer.toml": "436b5cb82c8465da6618df5f9a2908e93c8df7fcab651dc0cc32ab55cb97444d",
    "thaliris-focused-implementer.toml": "93a6409f8984de5e2c93b0697755091d18c84045252d1a9f37319268997c4fa0",
    "thaliris-focused-implementer-astra-medium.toml": "56d02ad34cc72b59de81cd064f303118d8d7bc6853ae4386adc868228542316d",
    "thaliris-focused-implementer-xhigh.toml": "3579140a6eee9d75214d95b7249debaf3ae2ed7cf8b85fbefaf3411c02de4fa9",
    "thaliris-verifier.toml": "95afcaf92a19d3ac46584b14a75ca86f6de57a26baf37bc982feab11678b3c2d",
    "thaliris-reviewer.toml": "b59ed89b37aabb83c0cd395432978a8c1cc252224ed26c22dd0a8c4f9a4dc0b2",
}
for _profile_name, _profile_hash in _PRE_ACCEPTANCE_UPDATE_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )

# Exact filename-bound profile bytes from immutable commit 7e1c11d before the
# nested Scanner wording moved to role-only routing instructions.
_ROLE_MODEL_ROUTING_PROMPT_PREDECESSOR_PROFILE_HASHES = {
    "thaliris-implementer.toml": "065e20f35bd68e4de4b00e7658c62799faebe2745944e604155fc9ee7b7cc79e",
    "thaliris-focused-implementer.toml": "8dcaeaca7da475c0732aa1c3fe7d922850bbe085856611373a2d3c0f1b13ab12",
    "thaliris-focused-implementer-astra-medium.toml": "c5d64c787a5fe9c70ffabb066e82e99170bd213c532073db924de6f8c56c0125",
    "thaliris-focused-implementer-xhigh.toml": "e859971fcdf713e7afbe97a6c000444a79f263377fba81a54fc64d4fd5341c36",
    "thaliris-reviewer.toml": "0bf17c556edc9608612031c17886d72c9f786ea61a432ea31c236d643786620e",
}
for _profile_name, _profile_hash in _ROLE_MODEL_ROUTING_PROMPT_PREDECESSOR_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )


_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'28c21dbecccdac55b72219ba12ea234cf2d2c0bdcaf13688aeac349f1022af20'})

# Immutable renderer/profile ownership before selected-evidence semantics: 96b6f0a214e35a13fcb889482c5f5c0277d3f036.
_EVIDENCE_CONTINUITY_PREDECESSOR_PROFILE_HASHES = {'thaliris-investigator.toml': '4ca30ad65b15457e3daa75be7ce44d9ce076cafb410d9de8540036a144e1ff50', 'thaliris-curator.toml': '5329a73de60a85dda0c070352ca13314dad519d636764b15076d704254080618', 'thaliris-reasoning-specialist.toml': '8be2723eee2c1c318e98476b450d88845afe4b2fb42795498ff10bf801f1b285', 'thaliris-implementer.toml': 'e54f1b1432879ae564f0cbdc308c08dfdf2438d18c38d7cab675f691f400acff', 'thaliris-focused-implementer.toml': 'c0812215dd1f92e0215e13863f9d9aa8b43ca4b442a82a18425d87df014ce98d', 'thaliris-verifier.toml': '504451792183f0c6f3d98486764abcab7db11c303afc72770ed9b13c7e6d57dd', 'thaliris-reviewer.toml': 'efe04f24cbd59cd9cfdcaae413d10dbd1dc08463a83f8dd7bc29336ba32ab2c7', 'thaliris-reasoning-specialist-astra-medium.toml': 'ed0b89e0145444191179170628eb582015ff56acbc83e817f3fb8fa66795a341', 'thaliris-reasoning-specialist-xhigh.toml': '5ad7d68effca5fb34947e028e465701b2a271f3b1c708adfd84366622857fde0', 'thaliris-focused-implementer-astra-medium.toml': '557f12e7a964ca5d44bae36795d23da8771388196502bd0addda59890cabdb81', 'thaliris-focused-implementer-xhigh.toml': '3ab871ac05e4bd57bee7e629931b43a0e0e4aa53bcbc629bea35a6669969bfec'}
for _profile_name, _profile_hash in _EVIDENCE_CONTINUITY_PREDECESSOR_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )


_EVIDENCE_CONTINUITY_PREDECESSOR_LUNA_PROFILE_HASHES = {'thaliris-investigator.toml': 'f5f08a2c27f29e6895c2c7a642fc5fb7641c9b782b708bdc5e054c8d29d06bd2', 'thaliris-curator.toml': '2914bee9f8a9eab031c4249825379d3e63a811d7c80c89d290fbaf0d1c55e9c7', 'thaliris-reasoning-specialist.toml': '4f8bdfd57111d742728c2420b0585e9106ae6d01e55d123c3a62b9ec467206a7', 'thaliris-implementer.toml': '50093753205cfd3e7eecab8db26712075b6b27741f05aab7dc89f8716dd773f8', 'thaliris-focused-implementer.toml': '686a542e6a5791fe7d50406348509249c5822d8813cb9aa6fe4053231a96cf2f', 'thaliris-verifier.toml': 'e7bcd0f460e20faf61a5e339796b2bdf0cc5a010770022acf93043585353be36', 'thaliris-reviewer.toml': '743bdb2204d70c1d94977d255d6d33c0aa0bef9437c6cd6e0c0ee7b64a6091f4', 'thaliris-reasoning-specialist-astra-medium.toml': 'ed0b89e0145444191179170628eb582015ff56acbc83e817f3fb8fa66795a341', 'thaliris-reasoning-specialist-xhigh.toml': '5ad7d68effca5fb34947e028e465701b2a271f3b1c708adfd84366622857fde0', 'thaliris-focused-implementer-astra-medium.toml': '557f12e7a964ca5d44bae36795d23da8771388196502bd0addda59890cabdb81', 'thaliris-focused-implementer-xhigh.toml': '3ab871ac05e4bd57bee7e629931b43a0e0e4aa53bcbc629bea35a6669969bfec'}
for _profile_name, _profile_hash in _EVIDENCE_CONTINUITY_PREDECESSOR_LUNA_PROFILE_HASHES.items():
    _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset())
        | frozenset({_profile_hash})
    )



# Exact filename-bound output from immutable 936fac07f73d6405a3300aafcc6262d176aa6b61; source/renderer witnesses
# and managed/role-pack bytes live in tests/fixtures/role-ownership-before.
_ROLE_OWNERSHIP_PREDECESSOR_PROFILE_HASHES = {'default': {'thaliris-investigator.toml': 'b4cf613136660edf844a6615f2c89c734ffc4789b8a357ef0ae1fae88783980a',
             'thaliris-curator.toml': 'a77e870d0d877433410344ba3d5da09f20031c3e1db0dbd46b60123f68f581aa',
             'thaliris-reasoning-specialist.toml': '83e182e293543d3ac995930b8f424b2c056a56a5ee972d5e3fa0b8b7510fcff6',
             'thaliris-implementer.toml': '805743b439eeebbeedbf939e371f503f608f5f7c6c896c576fab789d99e37fc9',
             'thaliris-focused-implementer.toml': 'd3a686ec5de97f59aaf4b1d85630e5a8fee3650a6130467543692ab15bdd3d18',
             'thaliris-verifier.toml': 'b3d2faa7415ce5962e235f6273b54d5ce1e3c37b3a2f000e38dd6cbaa4e45b84',
             'thaliris-reviewer.toml': 'fbe884a5832edc2afbd780e2494ccb24659953a01f94a8b9f2d49e1f036eb26d',
             'thaliris-reasoning-specialist-astra-medium.toml': '2e6475256878d78d11800a4bf16ae31a0712ce6b4b4f7632870a5d7c19c1a125',
             'thaliris-reasoning-specialist-xhigh.toml': '54fbef255e9c68957913ae96b87182d2e53711efaa077b697ffd38d7db721e52',
             'thaliris-focused-implementer-astra-medium.toml': 'd92fc7b58e37865e29fceb4ece1e7765b0ad452cd23899e7d30d2d6d07fdf366',
             'thaliris-focused-implementer-xhigh.toml': '37117ee7eef732320d1b73702ab352fa9be63f23d43c03436b351692730f48f2'},
 'luna-only': {'thaliris-investigator.toml': '95624a3478ca150124871d2c48de93f9dfc0115aea8d420c5c0278a1911b1418',
               'thaliris-curator.toml': '65809097f6f150a631d31b2d86858fac52151409811f2e5080afc7b8d167756a',
               'thaliris-reasoning-specialist.toml': '285afa6b1c3f5745bc2a0317b84e8187dd9325f91734a3024962787d112f6044',
               'thaliris-implementer.toml': '8f6509ab79bd62f6800605669936dfde13903b2cc8b44237ad029e3250f77c62',
               'thaliris-focused-implementer.toml': '408f95bbc20d48efbe701d866779b0007a3595ca5c26a8176a783c3fc1719c2a',
               'thaliris-verifier.toml': '80a5d0474517b1655c092e89d3b0472db1e6f34fc365ab619723fea6439b1ded',
               'thaliris-reviewer.toml': 'ca2b4171ca1a80157801ca37db55be4b5ee595d84a7301ced94fb8cb04696590',
               'thaliris-reasoning-specialist-astra-medium.toml': '2e6475256878d78d11800a4bf16ae31a0712ce6b4b4f7632870a5d7c19c1a125',
               'thaliris-reasoning-specialist-xhigh.toml': '54fbef255e9c68957913ae96b87182d2e53711efaa077b697ffd38d7db721e52',
               'thaliris-focused-implementer-astra-medium.toml': 'd92fc7b58e37865e29fceb4ece1e7765b0ad452cd23899e7d30d2d6d07fdf366',
               'thaliris-focused-implementer-xhigh.toml': '37117ee7eef732320d1b73702ab352fa9be63f23d43c03436b351692730f48f2'}}
for _profile_set in _ROLE_OWNERSHIP_PREDECESSOR_PROFILE_HASHES.values():
    for _profile_name, _profile_hash in _profile_set.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
            _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash})
        )
_KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES |= frozenset({'da899c4afb9df4e24e1772606aa3d965e51607c8c3748b89ebc99e245991d5a9'})
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'71affa6b8abc26009254d3b67b6de65f3c31d2d75a75cd96dca9c70ac3ceeeed'})


# Exact released predecessor 96b4c72472d2529ea2f0ce277e7c23ebc3e22521; immutable source and
# renderer witnesses are in tests/fixtures/execution-observation-predecessor.
_EXECUTION_OBSERVATION_PREDECESSOR_PROFILE_HASHES = {'default': {'thaliris-investigator.toml': '1f00963434e3787f09facebe0c3c3212199e6014847c765d8b9950b97419a9d3',
             'thaliris-curator.toml': '883d8a2abdcbf320e93be3b91b58cb568a2502cf27d0302d5e968f3ff97b3d54',
             'thaliris-reasoning-specialist.toml': 'fe355d1ef7a41b90e1b84d8d67df231d38953196dd2b91f82ecfe4482a96e284',
             'thaliris-implementer.toml': '8439f13c9d21e00f47807fc666d7c57880524f6e4ccd00cbd59139ac14781b44',
             'thaliris-focused-implementer.toml': '68514dc332e3ba7c5b61cddc7e08fc47529437bd11513ce71caa01dd08925c08',
             'thaliris-verifier.toml': '74037ebbfb5766b616e835a0f9b599b2b66d7e417eff7e54d3f108b2e63acb7a',
             'thaliris-reviewer.toml': '68261876656f4075b2429484f0d807e79a73502fa639573f83d027cd9c703681',
             'thaliris-reasoning-specialist-astra-medium.toml': '05f43bec89f1a15a8532a67133f5b8e57298c1b2be8571aa0c67dd820193dfcc',
             'thaliris-reasoning-specialist-xhigh.toml': '83f51065acee41827ff25d4b2aec98af0032f80aadce004c743ad10e584b1db0',
             'thaliris-focused-implementer-astra-medium.toml': '8f3b6b53394c9d96f83f7afffd9805f39fda9b297bd484fa5910364c172e1206',
             'thaliris-focused-implementer-xhigh.toml': '058d03b35f47aff6614d1f51ff2acf0b0ae1ce5b590ee202ac82b2bba5456c58'},
 'luna-only': {'thaliris-investigator.toml': 'ac908c1b19a461e4c015f6bf4ecac66fc3950799235e18992d2578f957b50643',
               'thaliris-curator.toml': '8c21d00c3b0653cd09ddce0ea1b73b32a75e169df6410144e13d8f5c3f0effa7',
               'thaliris-reasoning-specialist.toml': '5bae6373aaf7691ba898eb124801568c4c387b76cdccde97caafd987501968c3',
               'thaliris-implementer.toml': 'a3d878d4dc0a0c6989c02006ecd48ff5158ad5e754faababe8ac5786221ea5f5',
               'thaliris-focused-implementer.toml': '9ed6641f3dc55c73294d5f4efd81403de198ef84094ed90be0527db499a08f8c',
               'thaliris-verifier.toml': 'fd4646ffcb3a9380ea6eaf9f5ab2fd6215178124e1403f82c8bba6505de13cd6',
               'thaliris-reviewer.toml': '38cdff22766910920ca04e0d13beea00a614b94951797f4ef71925684c06567a',
               'thaliris-reasoning-specialist-astra-medium.toml': '05f43bec89f1a15a8532a67133f5b8e57298c1b2be8571aa0c67dd820193dfcc',
               'thaliris-reasoning-specialist-xhigh.toml': '83f51065acee41827ff25d4b2aec98af0032f80aadce004c743ad10e584b1db0',
               'thaliris-focused-implementer-astra-medium.toml': '8f3b6b53394c9d96f83f7afffd9805f39fda9b297bd484fa5910364c172e1206',
               'thaliris-focused-implementer-xhigh.toml': '058d03b35f47aff6614d1f51ff2acf0b0ae1ce5b590ee202ac82b2bba5456c58'}}
for _profile_set in _EXECUTION_OBSERVATION_PREDECESSOR_PROFILE_HASHES.values():
    for _profile_name, _profile_hash in _profile_set.items():
        _KNOWN_GENERATED_AGENT_PROFILE_HASHES[_profile_name] = (
            _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(_profile_name, frozenset()) | frozenset({_profile_hash}))
_KNOWN_GENERATED_ROLE_PACK_HASHES |= frozenset({'8c317baf8cbd65c747223f8a1fa84084f7ad95b451dcb0625ad2dc4e2a6206e7'})


def _agent_profile(name: str, role: str, model: str | None, effort: str | None) -> bytes:
    # JSON string escaping is compatible with TOML basic strings; native
    # isolation instructions contain quotes that must not terminate the value.
    spec = roles.get_role(role)
    binding = roles.get_codex_binding(role)
    if spec is None or binding is None or not binding.generated_profile:
        raise ValueError(f"unknown generated role: {role}")
    instructions = roles.profile_instructions(role, name)
    return (
        f'name = "{name}"\n'
        f'description = "Thaliris {role} execution role"\n'
        + (f'model = "{model}"\n' if model is not None else "")
        + (f'model_reasoning_effort = "{effort}"\n' if effort is not None else "")
        + f'developer_instructions = {json.dumps(instructions, ensure_ascii=False)}\n'
    ).encode("utf-8")


def _agent_profile_state(value: bytes, name: str, execution_constraint: str | None = None) -> str:
    profile = roles.agent_profiles(execution_constraint).get(name)
    if profile is None:
        return "user"
    expected = _agent_profile(name.removesuffix(".toml"), profile[2], profile[0], profile[1])
    if value == expected:
        return "current"
    hashes = _KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(name, frozenset())
    binding = roles.get_codex_binding(profile[2])
    if binding is not None and binding.profile_filename == name:
        hashes |= binding.legacy_profile_hashes
    return "legacy" if hashlib.sha256(value).hexdigest() in hashes else "user"


def _host_profile_definition_present(codex_home: Path | None = None) -> str:
    """Report exact generated role definitions in the effective Host directory."""
    home = _codex_home(codex_home)
    agents = home / "agents"
    if home.is_symlink() or agents.is_symlink() or not agents.is_dir():
        return "NO"
    try:
        return "YES" if any(all(
            not (agents / name).is_symlink()
            and (agents / name).is_file()
            and _agent_profile_state((agents / name).read_bytes(), name, constraint) == "current"
            for name in roles.agent_profiles(constraint)
        ) for constraint in (None, *roles.EXECUTION_CONSTRAINTS)) else "NO"
    except OSError:
        return "UNKNOWN"


def execution_profile_snapshot(root: Path, constraint: str | None) -> dict:
    """Validate the installed binding, without claiming a loaded Host catalog.

    The external task anchor retains these exact public configuration bytes.
    A child cannot switch policy through mutable installation/project files.
    Actual native execution still requires Host rollout evidence.
    """
    from . import task_authority
    home = _codex_home()
    agents = home / "agents"
    if any(runtime_identity._is_link(path) for path in (home, *home.parents, agents)):
        raise ValueError("EXECUTION_PROFILE_UNSAFE_PATH")
    project_agents = root / ".codex" / "agents"
    if project_agents.exists() and (project_agents.is_symlink() or any(project_agents.glob("*.toml"))):
        raise ValueError("EXECUTION_PROFILE_PROJECT_SHADOW")
    snapshot = {"home": str(home), "files": {}}
    for config in (home / "config.toml", root / ".codex" / "config.toml"):
        if config.exists():
            runtime_identity._safe_file(config)
            value = tomllib.loads(config.read_text(encoding="utf-8"))
            # An explicitly configured native role can override file discovery.
            if any(isinstance(entry, dict) for entry in value.get("agents", {}).values()):
                raise ValueError("EXECUTION_PROFILE_CONFIG_SHADOW")
        snapshot["files"][str(config)] = task_authority.digest(config)
    for name, (model, effort, role) in roles.agent_profiles(constraint).items():
        target = agents / name
        runtime_identity._safe_file(target)
        if target.read_bytes() != _agent_profile(name.removesuffix(".toml"), role, model, effort):
            raise ValueError("EXECUTION_PROFILE_CONSTRAINT_MISMATCH")
        snapshot["files"][str(target)] = task_authority.digest(target)
    return snapshot


def _installed_execution_constraint() -> str | None:
    agents = _codex_home() / "agents"
    profiles = roles.agent_profiles("luna-only")
    defaults = roles.agent_profiles()
    # Historical fixed defaults can share exact Luna bytes with a constrained
    # installation. Model names alone cannot prove that installation's policy.
    # Use filename-bound immutable default witnesses to avoid inventing a
    # partial frozen constraint after ordinary profiles begin inheriting.
    historical_defaults = _ROLE_MODEL_PREDECESSOR_PROFILE_HASHES["default"]
    historical_luna = _ROLE_MODEL_PREDECESSOR_PROFILE_HASHES["luna-only"]
    observed_luna_profiles = 0
    complete_luna_install = True
    for name in profiles:
        try:
            raw = (agents / name).read_bytes()
            current = _agent_profile_state(raw, name, "luna-only") == "current"
            digest = hashlib.sha256(raw).hexdigest()
            known_luna = current or digest == historical_luna.get(name)
            proven_default = (
                raw == _agent_profile(name[:-5], defaults[name][2], *defaults[name][:2])
                or digest == historical_defaults.get(name)
            )
        except OSError:
            current = False
            known_luna = False
            proven_default = False
        observed_luna_profiles += known_luna and not proven_default
        complete_luna_install = complete_luna_install and known_luna
    if complete_luna_install:
        return "luna-only"
    if observed_luna_profiles:
        # Do not treat a partially reverted constrained installation as an
        # unconstrained legacy Host.  Every role must agree on one mapping.
        raise ValueError("EXECUTION_PROFILE_CONSTRAINT_MISMATCH")
    return None


def _project_local_profile_files_present(root: Path) -> str:
    """Report only whether known Thaliris profile filenames exist in this project."""
    agents = root / ".codex" / "agents"
    if agents.is_symlink() or not agents.is_dir():
        return "NO"
    return "YES" if any(
        not (agents / name).is_symlink() and (agents / name).is_file()
        for name in _agent_profiles()
    ) else "NO"


def _project_activation_marker_present(root: Path) -> str:
    marker = core._safe(root, PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
    if marker.is_symlink() or not marker.is_file():
        return "NO"
    try:
        return "YES" if marker.read_bytes() == _PROJECT_ACTIVATION_BYTES else "NO"
    except OSError:
        return "UNKNOWN"


def role_profile_inventory(root: Path) -> dict[str, str]:
    """Report generated profile states keyed by registry-owned filenames."""
    root = core._repo_root(root)
    agents = root / ".codex" / "agents"
    if agents.is_symlink() or not agents.is_dir():
        return {name: "missing" for name in _agent_profiles()}
    return {
        name: (
            _agent_profile_state((agents / name).read_bytes(), name)
            if (agents / name).is_file() and not (agents / name).is_symlink()
            else "missing"
        )
        for name in _agent_profiles()
    }


def _activation_fields(
    root: Path,
    profile_native_active: str = "UNKNOWN",
    project_layer_activation: str = "UNKNOWN",
    compatible_profile_observed: str = "UNKNOWN",
    host_hook_runtime_observed: str = "UNKNOWN",
) -> dict[str, str]:
    return {
        "host_profile_definition_present": _host_profile_definition_present(),
        "project_local_profile_files_present": _project_local_profile_files_present(root),
        "project_activation_marker_present": _project_activation_marker_present(root),
        "profile_native_active": profile_native_active,
        "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN,
        "project_layer_activation": project_layer_activation,
        "compatible_profile_observed": compatible_profile_observed,
        "host_hook_runtime_observed": host_hook_runtime_observed,
    }


def _project_definition_facts(root: Path, codex_home: Path | None = None) -> dict[str, str]:
    """Return explicit adapter-owned facts used by the startup contract."""
    root = core._repo_root(root)
    instruction = _effective_root_instruction_path(root)
    instruction_present = "NO"
    instruction_state = "MISSING"
    instruction_sha256 = "UNKNOWN"
    if instruction.is_file():
        try:
            current = _read_text(instruction)
            span = _managed_span(current, instruction.name)
            if span is not None:
                owned = _normalize_line_endings(current[span[0]:span[1]])
                instruction_sha256 = hashlib.sha256(owned.encode("utf-8")).hexdigest()
                instruction_state = _managed_agents_state(current).upper()
                start, end = span
                # Only the adapter-owned span participates in definition
                # validity. User-owned text may use different line endings;
                # normalize the owned block before comparing it to the
                # canonical LF-rendered definition.
                expected = _normalize_line_endings(render_managed()).removesuffix("\n")
                instruction_present = "YES" if _normalize_line_endings(current[start:end]) == expected else "NO"
                if instruction_present == "YES":
                    instruction_state = "CURRENT"
        except (OSError, UnicodeError, ValueError):
            instruction_present = "NO"
            instruction_state = "UNKNOWN"
    activation = _project_activation_marker_present(root)
    host_hooks = lifecycle.host_hooks_health(_codex_home(codex_home))
    # Host integration is installed once in CODEX_HOME before a session.
    # Project init adds only the marker that lets its stable trampoline enter
    # the current executable on subsequent tool events in that same session.
    initialized = "YES" if instruction_present == "YES" and activation == "YES" else "NO"
    return {
        "project_definition_present": initialized,
        "instruction_definition_present": instruction_present,
        "managed_instruction_state": instruction_state,
        "managed_instruction_sha256": instruction_sha256,
        "expected_managed_instruction_sha256": hashlib.sha256(
            _normalize_line_endings(render_managed()).removesuffix("\n").encode("utf-8")
        ).hexdigest(),
        "managed_instruction_recovery_action": (
            f"thaliris init --accept-managed-instruction-sha256 {instruction_sha256}"
            if instruction_state == "USER"
            else "thaliris init" if instruction_state == "LEGACY" else "NONE"
        ),
        "project_activation_marker_present": activation,
        "project_local_profile_files_present": _project_local_profile_files_present(root),
        "host_profile_definition_present": _host_profile_definition_present(codex_home),
        "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN,
        "host_hook_registration_present": host_hooks["hooks_configured"],
        "legacy_project_hook_registration_present": lifecycle.legacy_project_hook_registration_present(root),
    }


def semantic_role(runtime_role: str) -> str:
    if runtime_role in _role_choices():
        return runtime_role
    raise ValueError(f"unknown Thaliris role: {runtime_role}")


def controller_actor(runtime_role: str) -> str:
    """Authorize a Controller-only adapter operation and return its marker."""
    actor = semantic_role(runtime_role)
    if actor != "controller":
        raise ValueError("only Controller may perform this operation")
    return actor


@lru_cache(maxsize=8)
def _host_wait_mode_cached(runner: str) -> dict[str, object]:
    """Observe CLI provenance only; a version cannot certify native waiting."""
    try:
        completed = subprocess.run([runner, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"version": "UNKNOWN", "reason": "Codex executable is unavailable"}
    match = re.fullmatch(
        r"(?:codex(?:-cli)?\s+)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)",
        ((completed.stdout or "") + (completed.stderr or "")).strip(),
        flags=re.IGNORECASE,
    )
    if completed.returncode != 0 or match is None:
        return {"version": "UNKNOWN", "reason": "Codex version could not be determined"}
    version = match.group(1)
    return {"version": version}


def host_wait_mode(executable: str | None = None, *, wait_schema: object = None,
                   runtime_observations: object = None) -> dict[str, object]:
    provenance = _host_wait_mode_cached(executable or os.environ.get("THALIRIS_CODEX_EXECUTABLE") or "codex")
    return {**provenance, **native_wait_capability.classify(wait_schema, runtime_observations)}


def host_explicit_blocking_wait(executable: str | None = None, *, wait_schema: object = None,
                                runtime_observations: object = None) -> dict[str, object]:
    """Report selected schema support separately from unproven runtime facts."""
    host = (host_wait_mode(executable) if wait_schema is None and runtime_observations is None
            else host_wait_mode(executable, wait_schema=wait_schema, runtime_observations=runtime_observations))
    if host.get("status") != "PASS":
        return {"status": "UNKNOWN", "host": host}
    if host.get("explicit_timeout_supported") is not True:
        return {"status": "UNSUPPORTED", "host": host}
    return {
        "status": "PASS",
        "version": host["version"],
        "min_wait_timeout_ms": host["min"],
        "default_wait_timeout_ms": host["default"],
        "schema_max_wait_timeout_ms": host["max"],
        "release_hard_max_wait_timeout_ms": "UNAVAILABLE",
        "effective_max_wait_timeout_ms": "UNAVAILABLE",
        "explicit_timeout_supported": True,
        "runtime": host.get("runtime", {}),
    }


def native_child_completion_reenters_root(executable: str | None = None, *,
                                        runtime_observations: object = None) -> str:
    """Return only PASS, UNSUPPORTED, or UNKNOWN for native re-entry."""
    capability = (host_wait_mode(executable) if runtime_observations is None
                  else host_wait_mode(executable, runtime_observations=runtime_observations))
    result = capability.get("native_completion_reenters_root")
    return result if result in {"PASS", "UNSUPPORTED", "UNKNOWN"} else "UNKNOWN"


def selected_continuation_mode(root: Path, executable: str | None = None, *,
                               wait_schema: object = None, runtime_observations: object = None) -> str:
    continuation = (native_child_completion_reenters_root(executable) if runtime_observations is None
                    else native_child_completion_reenters_root(executable, runtime_observations=runtime_observations))
    if continuation == "PASS":
        return "EVENT_DRIVEN"
    blocking = (host_explicit_blocking_wait(executable) if wait_schema is None and runtime_observations is None
                else host_explicit_blocking_wait(executable, wait_schema=wait_schema,
                                                runtime_observations=runtime_observations))
    if blocking.get("status") == "PASS":
        return "BLOCKING_WAIT"
    # Unknown optimizations cannot revoke task intent or native dispatch.
    # The caller uses the native tool's documented ordinary staged wait and
    # observes actual wake reasons; this claims no long-wait or reentry bound.
    return "STAGED_WAIT"


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _normalize_line_endings(value: str) -> str:
    """Normalize all newline spellings for owned-block comparisons."""
    return value.replace("\r\n", "\n").replace("\r", "\n")

MANAGED_START = "<!-- thaliris:begin -->"
MANAGED_END = "<!-- thaliris:end -->"
GLOBAL_MANAGED_START = b"<!-- thaliris:global:begin -->"
GLOBAL_MANAGED_END = b"<!-- thaliris:global:end -->"
AUDIT_IGNORE_START = "# thaliris-codex:begin"
AUDIT_IGNORE_END = "# thaliris-codex:end"
AUDIT_IGNORE_RULE = ".context/audit/"


def _native_role_labels() -> list[str]:
    """Return display labels from the canonical role query boundary."""
    labels: list[str] = []
    for role in roles.role_choices():
        spec = roles.get_role(role)
        binding = roles.get_codex_binding(role)
        if spec is not None and binding is not None and binding.native_profile is not None:
            labels.append(spec.id.replace("-", " ").title())
    return labels


def _native_role_names_text(*, final_conjunction: str = "and", with_article: bool = False) -> str:
    # Compatibility prose: Fresh Investigator, Curator, Reasoning Specialist, Implementer, Verifier, and Reviewer sessions use values from this query boundary.
    labels = _native_role_labels()
    if not labels:
        return "no named roles"
    if len(labels) == 1:
        text = labels[0]
    elif len(labels) == 2:
        text = f"{labels[0]} {final_conjunction} {labels[1]}"
    else:
        text = ", ".join(labels[:-1]) + f", {final_conjunction} " + labels[-1]
    if with_article:
        article = "an" if labels[0][0].lower() in "aeiou" else "a"
        return f"{article} {text}"
    return text


def _controller_model() -> str:
    binding = roles.get_codex_binding("controller")
    return binding.model if binding is not None and binding.model is not None else "(host/task)"


def _native_profile_facts() -> str:
    """Render native model/reasoning facts without a second role list."""
    entries: list[tuple[str, str, str]] = []
    for role in roles.role_choices():
        spec = roles.get_role(role)
        binding = roles.get_codex_binding(role)
        if spec is None or binding is None or binding.native_profile is None:
            continue
        entries.append((spec.id.replace("-", " ").title(), binding.model or "(host/task)", binding.reasoning_effort or "(host/task)"))
    rendered = [f"{label} (`{model}`, `{effort}`)" for label, model, effort in entries]
    if not rendered:
        return "The native child profiles are not configured."
    if len(rendered) == 1:
        return f"The native child profiles are {rendered[0]}."
    if len(rendered) == 2:
        return f"The native child profiles are {rendered[0]} and {rendered[1]}."
    return f"The native child profiles are {', '.join(rendered[:-1])}, and {rendered[-1]}."


def render_managed() -> str:
    """Render marker-owned instructions from the current role registry."""
    return _render_managed()


def _controller_bridge() -> dict[str, str]:
    """Give Controller the exact managed text to acknowledge in this session.

    A CLI result cannot promote text to Host developer instruction authority.
    The digest is an explicit Controller receipt bound to a one-shot hook
    attestation; Host instruction activation remains unproved.
    """
    content = render_managed()
    return {
        "controller_bridge_content": content,
        "controller_bridge_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "host_instruction_activation": "UNKNOWN",
    }

def _render_managed() -> str:
    return f"""{MANAGED_START}
## Thaliris shared boundaries

The owning Controller is the Thaliris task owner; native execution
observations never decide semantic acceptance. Authority is persistent Controller-asserted
intent, not universal Host owner authentication. Children cannot establish, expand,
rewrite or reactivate it, alter frozen constraints or mutate Controller/security state.
Isolation and readonly boundaries hold in every mode; damaged management grants no
additional authority. Effective live Host maintenance needs separate human authority.
Changed disk files do not prove native activation. Preserve unknown user-owned bytes.

Controller owns the full goal, global facts and invariants, acceptance and routing.
The child owns its selected local assignment and investigation, implementation and
verification working set. Legal tool capability does not transfer cognitive ownership.
The adapter/lifecycle binds mechanical identity, provenance, task, role, handoff and
workchain; children do not reconstruct global state or choose what follows their result.

Assigned children use current-role native instructions and their authorized parent's
selected spawn handoff without parent conversation history; unselected material stays
outside the Workstream. Parent means the immediate delegator, not necessarily the
owning Controller. Methods and ordinary local repair belong to the assigned executor.
Return decision-changing unknowns to Controller. Rules are retrievable on demand
within authority; contextual selection is not secrecy.

The owning Controller uses resident guidance delivered by normal bootstrap for
startup/admission, routing, handoff, waiting, endpoints and product acceptance.
[Controller instructions](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/docs/thaliris-controller.md)
are the canonical full reference; the installed pinned runner's `controller-instructions`
lists retrieval paths. Rules remain retrievable within existing authority.
Role responsibilities are in native profiles and
[role docs](docs/thaliris-role-packs.md); mechanical details are in
[Codex protocol](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/adapter/codex/README.md).
{MANAGED_END}
"""


MANAGED = _render_managed()

def render_role_packs() -> str:
    """Render the role-pack document with current registry facts."""
    return _render_role_packs()


def _render_role_packs() -> str:
    role_sections = "\n\n".join(f"## {label}\n\n{roles.get_role(role).instructions}" for role, label in zip((r for r in roles.role_choices() if r != "controller"), _native_role_labels()))
    return f"""<!-- thaliris-role-packs:v5 -->
# Thaliris Role Profiles

Generated from `thaliris_codex.roles`; edit canonical role instructions and render
this document and native TOMLs through the adapter. These prompts supply role-owned
responsibility, working style, delegation, endpoint and output. Project routing
selects roles; resident Controller instructions own normal orchestration, with exceptional
recovery/Host maintenance retrieved on demand. Full mechanical
design belongs to [Codex protocol](../adapter/codex/README.md), not repeated prompts.

Role meaning is separate from model/profile bindings. The Controller selects the
role, model and context under the task's authorization; model defaults and routing
belong to its [resident guidance](thaliris-controller.md). The adapter applies
mechanical bindings and preserves readonly and task constraints. Source rendering
does not prove that a running Host loaded these profiles. Host-specific routing,
version observations and compatibility details live in the Codex protocol reference.

{role_sections}
"""


ROLE_PACKS = _render_role_packs()
ROLE_REGISTRY_DOC = roles.render_registry_document().decode("utf-8")


def _role_registry_document() -> bytes:
    return roles.render_registry_document()


def _role_registry_state(value: bytes) -> str:
    if value == _role_registry_document():
        return "current"
    # Historical generated bytes are recognized by exact independent evidence.
    # This lets registry additions regenerate the mechanical document while
    # still treating arbitrary edits as user-owned.
    return "legacy" if hashlib.sha256(value).hexdigest() in _KNOWN_GENERATED_ROLE_REGISTRY_DOC_HASHES else "user"


def _codex_config() -> dict[str, object]:
    base = Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else Path.home() / ".codex"
    path = base / "config.toml"
    if not path.is_file():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _fallback_instruction_names(codex_config: dict[str, object] | None = None) -> tuple[str, ...]:
    value = (codex_config or _codex_config()).get("project_doc_fallback_filenames")
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or Path(item).name != item or item in names:
            continue
        names.append(item)
    return tuple(names)


def _root_instruction_candidates(root: Path, codex_config: dict[str, object] | None = None) -> tuple[Path, ...]:
    names = ("AGENTS.override.md", "AGENTS.md", *_fallback_instruction_names(codex_config))
    return tuple(core._safe(root, name) for name in names)


def _effective_root_instruction_path(root: Path, codex_config: dict[str, object] | None = None) -> Path:
    """Match Codex root discovery: first non-empty candidate wins.

    The adapter intentionally manages only the repository-root layer, not the
    full root-to-cwd instruction hierarchy.
    """
    candidates = _root_instruction_candidates(root, codex_config)
    for path in candidates:
        if path.is_file() and _read_text(path).strip():
            return path
    return core._safe(root, "AGENTS.md")


def _strip_managed_agents(current: str) -> str:
    span = _managed_span(current, "AGENTS.md")
    if span is None:
        return current
    start, end = span
    suffix = current[end:]
    if suffix.startswith("\r\n"):
        suffix = suffix[2:]
    elif suffix.startswith("\n"):
        suffix = suffix[1:]
    return current[:start] + suffix


def _managed_span(current: str, label: str) -> tuple[int, int] | None:
    counts = current.count(MANAGED_START), current.count(MANAGED_END)
    if counts == (0, 0):
        return None
    if counts == (1, 1):
        start, end_start = current.index(MANAGED_START), current.index(MANAGED_END)
        end = end_start + len(MANAGED_END)
    else:
        raise ValueError(f"{label} has duplicate or damaged managed markers")
    if start >= end_start:
        raise ValueError(f"{label} has duplicate or damaged managed markers")
    return start, end


def _managed_agents(current: str, accept_managed_instruction_sha256: str | None = None) -> str:
    span = _managed_span(current, "AGENTS.md")
    if span is not None:
        start, end = span
        expected = _normalize_line_endings(render_managed()).removesuffix("\n")
        if _normalize_line_endings(current[start:end]) == expected:
            # Preserve the complete document when only user-owned content
            # differs (including its line-ending convention).
            return current
        if _managed_agents_state(current) == "user":
            actual = hashlib.sha256(_normalize_line_endings(current[start:end]).encode("utf-8")).hexdigest()
            if accept_managed_instruction_sha256 != actual:
                return current
    newline = "\r\n" if "\r\n" in current else "\n"
    block = render_managed().replace("\n", newline)
    if span is None:
        return block + current
    start, end = span
    canonical_span = block.removesuffix(newline)
    prefix, suffix = current[:start], current[end:]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += newline
    if not suffix:
        suffix = newline
    elif not suffix.startswith(("\n", "\r")):
        suffix = newline + suffix
    return prefix + canonical_span + suffix


def _managed_agents_state(current: str) -> str:
    span = _managed_span(current, "AGENTS.md")
    if span is None:
        return "absent"
    owned = _normalize_line_endings(current[span[0]:span[1]])
    if owned == _normalize_line_endings(render_managed()).removesuffix("\n"):
        return "current"
    return "legacy" if hashlib.sha256(owned.encode("utf-8")).hexdigest() in _KNOWN_GENERATED_MANAGED_INSTRUCTION_HASHES else "user"


def _role_pack_state(value: bytes) -> str:
    if value == render_role_packs().encode("utf-8"):
        return "current"
    return "legacy" if hashlib.sha256(value).hexdigest() in _KNOWN_GENERATED_ROLE_PACK_HASHES else "user"


def _audit_ignore(current: str, *, remove: bool = False) -> str:
    counts = tuple(current.count(marker) for marker in (AUDIT_IGNORE_START, AUDIT_IGNORE_END))
    if counts not in {(0, 0), (1, 1)}:
        raise ValueError(".gitignore has duplicate or damaged Codex managed markers")
    if counts == (0, 0):
        if remove:
            return current
        newline = "\r\n" if "\r\n" in current else "\n"
        block = newline.join((AUDIT_IGNORE_START, AUDIT_IGNORE_RULE, AUDIT_IGNORE_END)) + newline
        return current + ("" if not current or current.endswith(("\n", "\r")) else newline) + block
    start, end_start = current.index(AUDIT_IGNORE_START), current.index(AUDIT_IGNORE_END)
    if start >= end_start:
        raise ValueError(".gitignore has duplicate or damaged Codex managed markers")
    if not remove:
        return current
    end = end_start + len(AUDIT_IGNORE_END)
    suffix = current[end:]
    if suffix.startswith("\r\n"):
        suffix = suffix[2:]
    elif suffix.startswith("\n"):
        suffix = suffix[1:]
    return current[:start] + suffix


def _install_plan(
    root: Path,
    *,
    accept_managed_instruction_sha256: str | None = None,
) -> tuple[dict[str, bytes], list[str]]:
    """Plan Codex-owned files without taking a second lock or backup."""
    root = core._repo_root(root)
    codex_config = _codex_config()
    target_agents = _effective_root_instruction_path(root, codex_config)
    all_agents = _root_instruction_candidates(root, codex_config)
    for instruction in all_agents:
        if instruction.is_file():
            _managed_span(_read_text(instruction), instruction.name)
    ignore = core._safe(root, ".gitignore")
    _audit_ignore(_read_text(ignore) if ignore.is_file() else "")
    writes: dict[str, bytes] = {}
    manual: list[str] = []
    current_agents = _read_text(target_agents) if target_agents.is_file() else ""
    current_agents_state = _managed_agents_state(current_agents)
    current_span = _managed_span(current_agents, target_agents.name)
    current_span_sha256 = (
        hashlib.sha256(_normalize_line_endings(current_agents[current_span[0]:current_span[1]]).encode("utf-8")).hexdigest()
        if current_span is not None else None
    )
    accepted_current_block = (
        current_agents_state == "user"
        and isinstance(accept_managed_instruction_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", accept_managed_instruction_sha256)
        and accept_managed_instruction_sha256 == current_span_sha256
    )
    if current_agents_state == "user" and not accepted_current_block:
        manual.append(target_agents.relative_to(root).as_posix())
    rendered_agents = _managed_agents(
        current_agents,
        accept_managed_instruction_sha256=(current_span_sha256 if accepted_current_block else None),
    )
    if current_agents != rendered_agents:
        writes[target_agents.relative_to(root).as_posix()] = rendered_agents.encode("utf-8")
    # If an override became active after an earlier install, remove only our
    # now-shadowed block from the inactive root file.
    for instruction in all_agents:
        if instruction == target_agents or not instruction.is_file():
            continue
        current = _read_text(instruction)
        if _managed_agents_state(current) == "user":
            manual.append(instruction.relative_to(root).as_posix())
            continue
        stripped = _strip_managed_agents(current)
        if stripped != current:
            writes[instruction.relative_to(root).as_posix()] = stripped.encode("utf-8")
    from . import controller_instructions
    controller_doc = core._safe(root, "docs/thaliris-controller.md")
    controller_bytes = controller_instructions.render().encode("utf-8")
    if not controller_doc.exists():
        writes["docs/thaliris-controller.md"] = controller_bytes
    elif controller_doc.read_bytes() != controller_bytes:
        manual.append("docs/thaliris-controller.md")
    role_packs = core._safe(root, "docs/thaliris-role-packs.md")
    if not role_packs.exists():
        writes["docs/thaliris-role-packs.md"] = render_role_packs().encode("utf-8")
    elif _role_pack_state(role_packs.read_bytes()) == "legacy":
        writes["docs/thaliris-role-packs.md"] = render_role_packs().encode("utf-8")
    elif _role_pack_state(role_packs.read_bytes()) == "user":
        manual.append("docs/thaliris-role-packs.md")
    role_registry = core._safe(root, "docs/thaliris-role-registry.md")
    if not role_registry.exists():
        writes["docs/thaliris-role-registry.md"] = _role_registry_document()
    else:
        state = _role_registry_state(role_registry.read_bytes())
        if state == "legacy":
            writes["docs/thaliris-role-registry.md"] = _role_registry_document()
        elif state == "user":
            manual.append("docs/thaliris-role-registry.md")
    # Native role identities belong to the Host's user role catalog.  Project
    # init intentionally leaves any existing project-local profiles alone and
    # never creates new identities in this workspace.
    current_ignore = _read_text(ignore) if ignore.is_file() else ""
    rendered_ignore = _audit_ignore(current_ignore)
    if current_ignore != rendered_ignore:
        writes[".gitignore"] = rendered_ignore.encode("utf-8")
    marker = core._safe(root, PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
    marker_name = marker.relative_to(root).as_posix()
    if marker.is_symlink():
        manual.append(marker_name)
    elif not marker.exists():
        writes[marker_name] = _PROJECT_ACTIVATION_BYTES
    else:
        try:
            if not marker.is_file() or marker.read_bytes() != _PROJECT_ACTIVATION_BYTES:
                manual.append(marker_name)
        except OSError:
            manual.append(marker_name)
    # Project hooks were the old lifecycle registration surface. Remove only
    # exact generated handlers; project init no longer installs or refreshes
    # Host hooks, and user handlers remain byte-for-byte JSON values.
    hooks = core._safe(root, ".codex/hooks.json")
    if hooks.exists():
        if hooks.is_symlink():
            manual.append(".codex/hooks.json")
        else:
            try:
                value = json.loads(_read_text(hooks))
                if not isinstance(value, dict):
                    raise ValueError("hooks root must be an object")
                if lifecycle.legacy_managed_handler_cleanup_required(value):
                    manual.append("legacy_project_hook_manual_cleanup_required")
                    manual.append(".codex/hooks.json")
                    return writes, manual
                merged, changed = remove_hooks(value)
                if changed:
                    writes[".codex/hooks.json"] = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            except (OSError, ValueError, json.JSONDecodeError):
                manual.append(".codex/hooks.json")
    # The current Host hook does not expose the active turn's effective cap.
    # Preserve native wait arguments unless a future trusted Host contract
    # supplies that session-bound value.
    return writes, manual


def init(
    root: Path,
    *,
    accept_managed_instruction_sha256: str | None = None,
) -> dict[str, object]:
    resolved = core._repo_root(root)
    for instruction in _root_instruction_candidates(resolved):
        if instruction.is_file():
            _managed_span(_read_text(instruction), instruction.name)
    ignore = core._safe(resolved, ".gitignore")
    if ignore.is_file():
        _audit_ignore(_read_text(ignore))
    root = core._repo_root(root)
    generic_files, generic_manual = core._init_plan(root)
    adapter_files, adapter_manual = _install_plan(
        root,
        accept_managed_instruction_sha256=accept_managed_instruction_sha256,
    )
    # Both layers contribute ignored private paths. Compose the adapter's
    # addition over the Core-rendered .gitignore before the single mutation.
    if ".gitignore" in generic_files:
        adapter_files[".gitignore"] = _audit_ignore(generic_files[".gitignore"].decode("utf-8")).encode("utf-8")
    files = generic_files | adapter_files
    manual = sorted(set(generic_manual) | set(adapter_manual))
    instruction_changed = any(path in {"AGENTS.md", "AGENTS.override.md"} for path in files)
    profile_changed = any(path.startswith(".codex/agents/") for path in files)
    new_profile_names: list[str] = []
    backup = None
    # Apply the generated files under one lock so the mutation is atomic.
    with task_authority._lock(root):
        backup = core._apply_with_backup(root, files, [], "init") if files else None
        hooks = lifecycle.hooks_health(root)
    facts = _project_definition_facts(root)
    definition_recovery_status = (
        "READY" if facts["project_definition_present"] == "YES"
        else "EXPLICIT_CONFIRMATION_REQUIRED" if any(item in manual for item in ("AGENTS.md", "AGENTS.override.md"))
        else "INIT_REQUIRED"
    )
    return {"ok": True, "changed": bool(files), "backup": backup, "files": sorted(files), "manual_action_required": [p for p in manual if not p.startswith("docs/")], "preserved_manual_followup": [p for p in manual if p.startswith("docs/")], "definition_recovery_status": definition_recovery_status, "instruction_definition_changed": instruction_changed, "hook_definition_changed": False, "project_activation_marker_changed": ".codex/thaliris.json" in files, "agent_profile_changed": profile_changed, "new_role_profile_files": new_profile_names, "role_catalog_changed": bool(new_profile_names), "hook_re_attestation_required": False, "managed_hook_abi": lifecycle.MANAGED_HOOK_ABI, "executable_adapter_protocol_version": lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION, "canonical_executable_available": hooks["canonical_executable_available"], "canonical_executable_identity": hooks["canonical_executable_identity"], "session_restart_required": False, "hook_trust_required": False, "host_wait_mode": host_wait_mode(), **facts, **_activation_fields(root), **_controller_bridge()}


def _codex_home(codex_home: Path | None = None) -> Path:
    """Resolve the user's Codex home without consulting project state."""
    if codex_home is not None:
        return Path(codex_home).expanduser().absolute()
    configured = os.environ.get("CODEX_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".codex").absolute()


def _host_install_executable(
    codex_home: Path,
    executable: str | Path | None,
    executable_sha256: str | None,
) -> tuple[Path | None, str | None, str | None]:
    """Resolve and exercise the direct executable route before installing hooks."""
    if (executable is None) != (executable_sha256 is None):
        return None, None, "host_executable_path_and_sha256_must_be_paired"
    configured = Path(executable).expanduser() if executable is not None else lifecycle._trusted_thaliris_executable()
    if configured is None and executable is None:
        found = shutil.which("thaliris")
        configured = Path(found) if found else None
    if configured is None or not configured.is_absolute() or configured.is_symlink() or not configured.is_file():
        return None, None, "host_executable_unavailable_or_not_absolute"
    try:
        resolved = configured.resolve(strict=True)
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except (OSError, RuntimeError):
        return None, None, "host_executable_unavailable_or_not_absolute"
    expected = executable_sha256.lower() if isinstance(executable_sha256, str) else digest
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest != expected:
        return None, None, "host_executable_sha256_mismatch"
    try:
        package_dir = Path(json.loads(runtime_identity.manifest_bytes(resolved))["package_dir"])
    except (OSError, RuntimeError, ValueError):
        return None, None, "host_installed_runtime_unavailable_or_unsafe"
    interpreter = resolved.parent / ("python.exe" if os.name == "nt" else "python")
    if not interpreter.is_file() or interpreter.is_symlink():
        return None, None, "host_runtime_interpreter_unavailable_or_unsafe"
    probe_env = os.environ.copy()
    probe_env.pop("PYTHONPATH", None)
    probe_env.pop("PYTHONHOME", None)
    probe_env["PYTHONNOUSERSITE"] = "1"
    probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        origin = subprocess.run(
            [str(interpreter), "-I", "-B", "-c", "import thaliris_codex; print(thaliris_codex.__file__)"],
            capture_output=True, timeout=15, check=False, env=probe_env,
        )
        if origin.returncode != 0 or origin.stderr or Path(origin.stdout.decode("utf-8").strip()).resolve(strict=True) != (package_dir / "__init__.py").resolve(strict=True):
            return None, None, "host_runtime_import_origin_mismatch"
    except (OSError, UnicodeError, subprocess.SubprocessError, RuntimeError):
        return None, None, "host_runtime_import_origin_mismatch"
    # A process exit check prevents a stale installed launcher from being
    # embedded in the stable Host trampoline. This exact direct invocation
    # accepts no shell wrapper and runs from a disposable non-Thaliris repo.
    try:
        with tempfile.TemporaryDirectory(prefix="thaliris-host-abi-probe-") as probe_root:
            initialized = subprocess.run(
                ["git", "init", "-q", probe_root],
                capture_output=True,
                timeout=15,
                check=False,
            )
            if initialized.returncode != 0:
                return None, None, "host_executable_current_hook_abi_probe_failed"
            probe = subprocess.run(
                [str(resolved), "audit-hook", "PreToolUse", "--managed-hook-abi", MANAGED_HOOK_ABI],
                input=b"{}",
                cwd=probe_root,
                capture_output=True,
                timeout=15,
                check=False,
                env=probe_env,
            )
    except (OSError, subprocess.SubprocessError):
        return None, None, "host_executable_current_hook_abi_probe_failed"
    if probe.returncode != 0 or probe.stderr:
        return None, None, "host_executable_current_hook_abi_probe_failed"
    if any(character in str(resolved) for character in ('"', "%", "!", "`", "\r", "\n")):
        return None, None, "host_executable_path_not_safe_for_cmd_trampoline"
    return resolved, digest, None


def _atomic_host_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".thaliris-install-tmp",
            dir=path.parent, delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def _write_runtime_audit(home: Path, previous: bytes, old_executable: Path) -> Path:
    """Keep exact prior pin and best-effort observed runtime identity off the active path."""
    try:
        observed = runtime_identity.manifest_identity(runtime_identity.manifest_bytes(old_executable))
    except (OSError, RuntimeError, ValueError):
        observed = "UNAVAILABLE"
    record = {
        "format": "thaliris-installed-runtime-audit-v1",
        "prior_manifest_base64": base64.b64encode(previous).decode("ascii"),
        "prior_manifest_sha256": runtime_identity.manifest_identity(previous),
        "observed_runtime_sha256": observed,
    }
    with tempfile.NamedTemporaryFile(mode="wb", prefix="thaliris-install-audit-", suffix=".json",
                                     dir=home, delete=False) as output:
        output.write((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
        return Path(output.name)


def _global_agents_block(executable: Path | None = None, executable_sha256: str | None = None,
                         codex_home: Path | None = None) -> bytes:
    """Cross-role boundaries, shared working principles and one-shot startup entry."""
    from . import controller_instructions
    if (executable is None) != (executable_sha256 is None):
        raise ValueError("global instruction executable and SHA-256 must be paired")
    script = _codex_home(codex_home) / HOST_RUN_SCRIPT_NAME
    route = controller_instructions.runner_command(script)
    return f"""<!-- thaliris:global:begin -->
## Thaliris shared entry

Use the installed pinned runner for managed commands; do not substitute unknown
runtime code. Authority comes from persistent Controller-asserted human intent,
not session/PID/environment, missing actor fields or universal Host authentication.
Known child, readonly, abandoned and fenced actors cannot establish, expand, rewrite
or reactivate it. Goal, scope, acceptance, mode, unfencing and security-baseline
changes require an actual superior human decision. Isolation and readonly boundaries
hold in every mode. Live Host maintenance requires separate explicit authority;
changed disk files do not prove native activation. Preserve unknown user-owned bytes.

For substantive file-changing project work, including README-only changes,
configuration changes and new project creation, unless the human opts out, the
owning Controller initiates the normal Thaliris bootstrap once by running
`{route} --root <repo> codex-bootstrap` directly. Its normal response delivers
resident Controller guidance for admission, routing, handoffs, waiting, endpoints,
acceptance and causal diagnosis without another procedure get. Its complete END marker
contains an exact digest; a same-context bootstrap for another workspace can pass that
digest as `--controller-guidance-sha256 <digest>` to suppress duplicate text. The fact
that the CLI wrote stdout is not delivery evidence; require the complete returned tool
result and END marker. Bootstrap places compact status diagnostics before the guidance
body so truncation leaves the state readable; a missing END marker still forbids
acknowledgement. Omit the digest in a new session, a fresh child or after truncation. Use
`controller-instructions --resident` to restore a complete truncated response. Follow that guidance
and the project entry. Use `{route} --root <repo> controller-instructions`
only for a missing-context index or exceptional recovery/Host maintenance;
`controller-instructions --section <name>` retrieves the exact procedure.
Chatting and read-only work need no project bootstrap.

An explicit existing project directory without Git metadata supports bootstrap and
managed task admission. Bootstrap never runs git init. Create Git metadata only
when repository creation is within the user's requested scope, independently of
bootstrap. Native cwd, managed project root and Git worktree root are distinct;
missing Git capabilities do not revoke task authority or lifecycle.

Managed children follow their selected handoff and role instructions; they do not
initiate project bootstrap or task admission, and they do not bootstrap, task-start
or task-abandon the owning Controller's ACTIVE task. Rules remain retrievable on demand within
authority. Source synchronization never changes a live task's security anchor or
installs into Host.

### Thaliris shared working principles

Role-specific instructions and selected handoffs remain authoritative. These shared
principles grant no role, task-admission, security-maintenance or Host authority.

- Continue necessary independent work before waiting. Prefer meaningful native
  notifications over repeated status polling. Use available completion evidence
  without repeated confirmation; messages, timeouts and exceptions do not prove
  completion. Preserve UNKNOWN when evidence is unavailable.
- Assign one observation owner to each operation: observe your own tests, builds,
  processes and CI using their tools. Avoid unchanged-state wakeups and routine
  agent heartbeats; communicate substantive findings, blockers and final results.
  User-requested progress reporting remains allowed.
- Keep working sets private and transfer selected facts, source pointers, unknowns,
  contradictions and verification. Reuse established discovery; reopen originals
  when a decision requires them. Do not repeat already covered inventories.
- Preserve the objective, scope, constraints and acceptance. Resolve in-scope
  defects; report unrelated anomalies without expanding the modification boundary.
  Start with the smallest meaningful checks and broaden for concrete risks. A
  passing check alone does not establish product acceptance. Do not use fixed
  time, token, call, retry or file thresholds as substitutes for semantic completion.
- Coordinate overlapping writes or isolate them. ACTIVE alone is not a write
  conflict. Preserve unknown/user-owned bytes; render derived outputs through
  canonical sources. Historical ownership needs independent historical evidence.
- Use a stable primary language and retain precision-bearing original terms.
  Durable knowledge and INDEX changes belong to the explicitly assigned role;
  do not add routine memory-management workflows. Synchronize affected repository
  instruction surfaces within their ownership boundaries; source edits do not
  authorize installed Host or protected global instruction changes.

<!-- thaliris:global:end -->
""".encode("utf-8")


def _global_agents_span(current: bytes) -> tuple[int, int] | None:
    """Find one well-formed owned block, including its trailing line break."""
    start_count = current.count(GLOBAL_MANAGED_START)
    end_count = current.count(GLOBAL_MANAGED_END)
    if (start_count, end_count) == (0, 0):
        if b"<!-- thaliris:global:" in current:
            raise ValueError("AGENTS.md has damaged global Thaliris markers")
        return None
    if (start_count, end_count) != (1, 1) or current.count(b"<!-- thaliris:global:") != 2:
        raise ValueError("AGENTS.md has duplicate or damaged global Thaliris markers")
    start = current.index(GLOBAL_MANAGED_START)
    end_marker = current.index(GLOBAL_MANAGED_END)
    end = end_marker + len(GLOBAL_MANAGED_END)
    if start >= end_marker or (start and current[start - 1:start] != b"\n"):
        raise ValueError("AGENTS.md has misplaced global Thaliris markers")
    if current[end:end + 2] == b"\r\n":
        end += 2
    elif current[end:end + 1] == b"\n":
        end += 1
    elif end != len(current):
        raise ValueError("AGENTS.md has misplaced global Thaliris markers")
    return start, end


def _global_agents_update(
    current: bytes, *, remove: bool = False,
    executable: Path | None = None, executable_sha256: str | None = None,
    codex_home: Path | None = None,
) -> bytes:
    span = _global_agents_span(current)
    # Project-owned markers in the user layer indicate a different ownership
    # claim. Never silently replace or combine it with the global block.
    outside = current if span is None else current[:span[0]] + current[span[1]:]
    if MANAGED_START.encode() in outside or MANAGED_END.encode() in outside:
        raise ValueError("AGENTS.md has conflicting project Thaliris markers")
    if span is None:
        return current if remove else _global_agents_block(executable, executable_sha256, codex_home) + current
    start, end = span
    return current[:start] + (b"" if remove else _global_agents_block(executable, executable_sha256, codex_home)) + current[end:]


def _install_host_hook_trust(home: Path, executable: Path, executable_sha256: str, runtime_sha256: str) -> dict[str, Any]:
    return codex_app_server.trust_installed_host_hooks(home, executable, executable_sha256, runtime_sha256)


def _owned_host_hook_commands(data: dict[str, Any], home: Path) -> dict[str, set[str]]:
    commands: dict[str, set[str]] = {event: set() for event in lifecycle.HOOK_EVENTS}
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return commands
    for event in lifecycle.HOOK_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            handlers = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if lifecycle._host_hook_command_is_managed(handler, event, home):
                    command = handler.get("command")
                    if isinstance(command, str):
                        commands[event].add(command)
    return commands


def codex_install(
    codex_home: Path | None = None,
    executable: str | Path | None = None,
    executable_sha256: str | None = None,
    execution_constraint: str | None = None,
    maintenance_contract: str | Path | None = None,
) -> dict[str, object]:
    """Host-scoped maintenance with separately selected intent and ownership."""
    from . import host_maintenance
    return host_maintenance.install(_codex_home(codex_home), executable,
        executable_sha256, execution_constraint, maintenance_contract)


def codex_uninstall(codex_home: Path | None = None,
                    maintenance_contract: str | Path | None = None) -> dict[str, object]:
    """Remove only bytes owned by an authorized installation or exact approval."""
    from . import host_maintenance
    return host_maintenance.uninstall(_codex_home(codex_home), maintenance_contract)


def _adapter_uninstall_plan(root: Path) -> tuple[dict[str, bytes], list[str], list[str], list[str]]:
    agent_paths = _root_instruction_candidates(root)
    ignore = core._safe(root, ".gitignore")
    for agents in agent_paths:
        if agents.is_file():
            _managed_span(_read_text(agents), agents.name)
    if ignore.is_file():
        _audit_ignore(_read_text(ignore))
    writes: dict[str, bytes] = {}
    deletes: list[str] = []
    kept: list[str] = []
    manual: list[str] = []
    for agents in agent_paths:
        if not agents.is_file():
            continue
        current = _read_text(agents)
        span = _managed_span(current, agents.name)
        if span is not None:
            if _managed_agents_state(current) == "user":
                kept.append(agents.relative_to(root).as_posix())
                continue
            stripped = _strip_managed_agents(current)
            name = agents.relative_to(root).as_posix()
            if stripped:
                writes[name] = stripped.encode("utf-8")
            else:
                deletes.append(name)
    audit_present = (root / ".context" / "audit").exists()
    if ignore.is_file() and not audit_present:
        current = _read_text(ignore)
        rendered = _audit_ignore(current, remove=True)
        if rendered != current:
            writes[".gitignore"] = rendered.encode("utf-8")
    marker = core._safe(root, PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
    if marker.is_symlink():
        manual.append(PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
    elif marker.exists():
        try:
            if marker.is_file() and marker.read_bytes() == _PROJECT_ACTIVATION_BYTES:
                deletes.append(PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
            else:
                kept.append(PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
        except OSError:
            manual.append(PROJECT_ACTIVATION_MARKER.replace("\\", "/"))
    from . import controller_instructions
    controller_doc = core._safe(root, "docs/thaliris-controller.md")
    if controller_doc.is_file():
        if controller_doc.read_bytes() == controller_instructions.render().encode("utf-8"):
            deletes.append("docs/thaliris-controller.md")
        else:
            kept.append("docs/thaliris-controller.md")
    packs = core._safe(root, "docs/thaliris-role-packs.md")
    if packs.is_file():
        if _role_pack_state(packs.read_bytes()) == "current":
            deletes.append("docs/thaliris-role-packs.md")
        else:
            kept.append("docs/thaliris-role-packs.md")
    role_registry = core._safe(root, "docs/thaliris-role-registry.md")
    if role_registry.is_file():
        if _role_registry_state(role_registry.read_bytes()) in {"current", "legacy"}:
            deletes.append("docs/thaliris-role-registry.md")
        else:
            kept.append("docs/thaliris-role-registry.md")
    hooks = core._safe(root, ".codex/hooks.json")
    if hooks.is_file():
        try:
            value = json.loads(_read_text(hooks))
            if not isinstance(value, dict):
                raise ValueError("hooks root must be an object")
            if lifecycle.legacy_managed_handler_cleanup_required(value):
                manual.append(".codex/hooks.json")
            else:
                cleaned, changed = remove_hooks(value)
                if changed:
                    owned_empty = value.get("description") == MANAGED_HOOKS_DESCRIPTION and set(cleaned) <= {"description", "hooks"} and cleaned.get("description") == MANAGED_HOOKS_DESCRIPTION and cleaned.get("hooks", {}) == {}
                    if owned_empty:
                        deletes.append(".codex/hooks.json")
                    else:
                        writes[".codex/hooks.json"] = (json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        except (OSError, ValueError, json.JSONDecodeError):
            manual.append(".codex/hooks.json")
    return writes, deletes, kept, manual


def uninstall(root: Path) -> dict[str, object]:
    root = core._repo_root(root)
    adapter = _adapter_uninstall_plan(root)
    generic_writes, generic_deletes, generic_kept, generic_manual = core._uninstall_plan(root)
    writes = generic_writes | adapter[0]
    deletes = sorted(set(generic_deletes) | set(adapter[1]))
    with task_authority._lock(root):
        backup = core._apply_with_backup(root, writes, deletes, "uninstall") if writes or deletes else None
    return {"ok": True, "changed": bool(writes or deletes), "backup": backup, "kept": sorted(set(generic_kept) | set(adapter[2])), "manual_action_required": sorted(set(generic_manual) | set(adapter[3]))}


def task_start(
    root: Path,
    goal: str,
    milestone: str | None,
    input_file: str | None,
    hook_attestation: str | None = None,
    controller_bridge_sha256: str | None = None,
    authority_contract: str | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    root = core._repo_root(root)
    from . import task_authority
    intent = task_authority.contract(authority_contract) if authority_contract else None
    definition = _project_definition_facts(root)
    if definition["project_definition_present"] != "YES":
        bootstrap = {
            **definition,
            "init_required": True,
            "session_restart_required": "UNKNOWN",
            "same_session_task_start": "UNKNOWN",
            "managed_runtime_after_restart": "UNVERIFIED",
        }
        if definition.get("legacy_managed_handler_cleanup") == "MANUAL_CLEANUP_REQUIRED":
            bootstrap["manual_action_required"] = "legacy_managed_handler_manual_cleanup_required"
        return {
            "ok": False,
            "status": "BOOTSTRAP_REQUIRED",
            "bootstrap": bootstrap,
        }
    # A new task does not depend on an old task ledger or authority.
    executable = lifecycle.managed_executable_health()
    # A missing trusted executable is an independent fail-closed bootstrap
    # fact. It is not represented by durable restart state.
    if hook_attestation is not None and executable["canonical_executable_available"] != "YES":
        return {
            "ok": False,
            "status": "BOOTSTRAP_REQUIRED",
            "bootstrap": {
                **definition,
                **executable,
                "init_required": False,
                "session_restart_required": False,
                "same_session_task_start": "UNKNOWN",
                "managed_runtime_after_restart": "UNVERIFIED",
                "manual_action_required": "canonical_executable_unavailable",
            },
        }
    # Direct Python callers retain the historical local API; the native hook
    # attestation path is the startup boundary whose trusted executable must
    # be explicit.
    bridge = _controller_bridge()
    if (hook_attestation is not None or controller_bridge_sha256 is not None) and controller_bridge_sha256 != bridge["controller_bridge_sha256"]:
        return {"ok": False, "status": "CONTROLLER_BRIDGE_REQUIRED", "expected_controller_bridge_sha256": bridge["controller_bridge_sha256"], "host_instruction_activation": "UNKNOWN"}
    # The explicit human contract, not a single-use Hook/session receipt,
    # admits current tasks. Preserve strict legacy proof validation whenever
    # a caller actually supplies one; missing observation stays unknown.
    session_hash = (None if intent is not None and hook_attestation is None else
        lifecycle.consume_task_start_attestation(root, hook_attestation, controller_bridge_sha256,
            task_authority.digest(Path(authority_contract)) if authority_contract else None))
    if session_hash is None and session_id is not None:
        session_hash = lifecycle._identity_hash(session_id)
    installed_constraint = _installed_execution_constraint()
    if (intent is not None and intent.get("execution_constraint") is not None) or installed_constraint is not None:
        profiles = execution_profile_snapshot(root, intent.get("execution_constraint") if intent else None)
        if hook_attestation is not None:
            observed = lifecycle._load_runtime(root / ".context" / "audit" / session_hash[:24] / "runtime.json")
            host = observed.get(lifecycle._PROFILE_FILES_PRESENT_AT_SESSION_START, {}).get("user_host", {})
            if host.get("directory") != str(_codex_home() / "agents") or any(
                host.get("sha256", {}).get(name) != profiles["files"][str(_codex_home() / "agents" / name)]
                for name in roles.agent_profiles(intent.get("execution_constraint") if intent else None)
            ):
                raise ValueError("EXECUTION_PROFILES_REQUIRE_FRESH_HOST_SESSION")
            config_snapshot = observed.get(lifecycle._PROFILE_FILES_PRESENT_AT_SESSION_START, {}).get("configuration_sha256")
            config_paths = (str(_codex_home() / "config.toml"), str(root / ".codex" / "config.toml"))
            if not isinstance(config_snapshot, dict) or any(
                config_snapshot.get(path) != profiles["files"].get(path)
                for path in config_paths
            ):
                raise ValueError("EXECUTION_CONFIGS_REQUIRE_FRESH_HOST_SESSION")
    if hook_attestation is not None:
        catalog_status = lifecycle.role_catalog_session_status(root, session_hash)
        if catalog_status == "NEW_ROLE_CATALOG_IDENTITY_NOT_ACTIVE":
            return {"ok": False, "status": catalog_status, "new_role_profile_files": lifecycle.new_role_profile_files(root, session_hash), "host_instruction_activation": "UNKNOWN"}
    mode = selected_continuation_mode(root)
    readiness = {
        "status": "PASS" if mode in {"EVENT_DRIVEN", "BLOCKING_WAIT"} else "UNKNOWN" if mode == "STAGED_WAIT" else "MANAGED_CONTINUATION_UNAVAILABLE",
        "NATIVE_CHILD_COMPLETION_REENTERS_ROOT": native_child_completion_reenters_root(),
        "HOST_EXPLICIT_BLOCKING_WAIT": host_explicit_blocking_wait().get("status"),
        "selected_continuation_mode": mode,
    }
    if mode == "UNAVAILABLE" and intent is None:
        return {"ok": False, "status": "MANAGED_CONTINUATION_UNAVAILABLE", "managed_readiness": readiness}
    if mode == "UNAVAILABLE" and intent is not None:
        # Unknown Host scheduling capability is not revocation of selected
        # human task intent. Keep the observation unknown; never invent a
        # wait cap or an automatic reentry capability from this grant.
        readiness["status"] = "UNKNOWN"
    result = core.task_start(root, goal, milestone, input_file, actor="controller")
    if intent is not None:
        task_authority.establish(root, core._load_state(root), intent, session_hash)
    if session_hash is not None:
        lifecycle.record_task_start_owner(root, str(result["task_id"]), session_hash)
    result["managed_readiness"] = {**readiness, **_activation_fields(root), "CONTROLLER_ACTIVATION_BRIDGE_ACTIVE": "YES" if hook_attestation is not None else "NOT_APPLICABLE", "HOST_INSTRUCTION_ACTIVE": "UNKNOWN", "controller_activation_bridge": "ACTIVE" if hook_attestation is not None else "NOT_APPLICABLE", "host_instruction_activation": "UNKNOWN", "role_catalog_session_status": catalog_status if hook_attestation is not None else "NOT_APPLICABLE"}
    if intent is not None:
        result["task_authority"] = {"provenance": "CONTROLLER_ASSERTED_HUMAN_INSTRUCTION", "host_actor_assurance": "UNKNOWN", "execution_mode": intent["execution_mode"]}
    return result


def task_abandon(
    root: Path, task_id: str, revision: int, state_sha256: str,
    lifecycle_sha256: str, reason: str, hook_attestation: str | None,
) -> dict[str, object]:
    """Use a current Hook PreToolUse proof for explicit ACTIVE takeover."""
    root = core._repo_root(root)
    session_hash, proof_hash = lifecycle.consume_task_abandon_attestation(root, hook_attestation)
    return lifecycle.task_abandon(
        root, task_id, revision, state_sha256, lifecycle_sha256,
        reason, session_hash, proof_hash,
    )


def task_state_schema_error(root: Path, error: core.TaskStateSchemaIncompatible) -> dict[str, object]:
    """Add lifecycle recoverability without exposing the archived task ID."""
    result = dict(error.diagnostic)
    if result.get("recoverable") is True:
        action = str(result.get("recovery_action", ""))
        if action.startswith("thaliris "):
            action = "thaliris --task-id <task-id> " + action[len("thaliris "):]
            if result.get("abandon_active_confirmation_required") is True:
                action += " --abandon-active"
        if action:
            result["recovery_action"] = f"{action} --controller-bridge-sha256 <current-bridge-sha256>"
    if result.get("recoverable") is True and error.task_id is not None:
        blocker = lifecycle.task_state_recovery_blocker(core._repo_root(root), error.task_id)
        if blocker is not None:
            result["recoverable"] = False
            result["recovery_action"] = "NONE"
            result["recovery_blocker"] = blocker
    return result


def task_recover_state(
    root: Path,
    expected_sha256: str,
    abandon_active: bool,
    hook_attestation: str | None,
    controller_bridge_sha256: str | None,
) -> dict[str, object]:
    """Archive one exact incompatible ledger before a separately attested task-start."""
    root = core._repo_root(root)
    definition = _project_definition_facts(root)
    if definition["project_definition_present"] != "YES":
        return {
            "ok": False,
            "status": "BOOTSTRAP_REQUIRED",
            "bootstrap": {
                **definition,
                "init_required": True,
                "session_restart_required": "UNKNOWN",
                "same_session_task_start": "UNKNOWN",
                "managed_runtime_after_restart": "UNVERIFIED",
            },
        }
    executable = lifecycle.managed_executable_health()
    if executable["canonical_executable_available"] != "YES":
        return {
            "ok": False,
            "status": "BOOTSTRAP_REQUIRED",
            "bootstrap": {
                **definition,
                **executable,
                "init_required": False,
                "session_restart_required": False,
                "manual_action_required": "canonical_executable_unavailable",
            },
        }
    bridge = _controller_bridge()
    if controller_bridge_sha256 != bridge["controller_bridge_sha256"]:
        return {
            "ok": False,
            "status": "CONTROLLER_BRIDGE_REQUIRED",
            "expected_controller_bridge_sha256": bridge["controller_bridge_sha256"],
            "host_instruction_activation": "UNKNOWN",
        }
    session_hash = lifecycle.consume_task_start_attestation(
        root,
        hook_attestation,
        controller_bridge_sha256,
    )
    catalog_status = lifecycle.role_catalog_session_status(root, session_hash)
    if catalog_status == lifecycle.NEW_ROLE_CATALOG_IDENTITY_NOT_ACTIVE:
        return {
            "ok": False,
            "status": catalog_status,
            "new_role_profile_files": lifecycle.new_role_profile_files(root, session_hash),
            "host_instruction_activation": "UNKNOWN",
        }
    if selected_continuation_mode(root) == "UNAVAILABLE":
        return {"ok": False, "status": "MANAGED_CONTINUATION_UNAVAILABLE"}

    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected task state SHA-256 must be 64 lowercase hexadecimal characters")
    state_name = core._state_path(root).relative_to(root).as_posix()
    core._safe_without_final_symlink(root, state_name)

    with task_authority._lock(root):
        state_path = core._state_path(root)
        if not state_path.is_file():
            return {"ok": False, "status": "NO_INCOMPATIBLE_TASK_STATE", "recoverable": False}
        if state_path.stat().st_size > 512 * 1024:
            return {
                "ok": False,
                "status": "STATE_SCHEMA_INCOMPATIBLE",
                "from_version": "UNKNOWN",
                "to_version": core._STATE_SCHEMA_VERSION,
                "recoverable": False,
                "recovery_action": "NONE",
                "error": "task state exceeds 512 KiB",
            }
        raw_bytes = state_path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if digest != expected_sha256:
            return {
                "ok": False,
                "status": "TASK_STATE_CHANGED",
                "expected_sha256": expected_sha256,
                "observed_sha256": digest,
                "recovered": False,
            }
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {
                "ok": False,
                "status": "STATE_SCHEMA_INCOMPATIBLE",
                "from_version": "UNKNOWN",
                "to_version": core._STATE_SCHEMA_VERSION,
                "state_sha256": digest,
                "recoverable": False,
                "recovery_action": "NONE",
                "error": "task state is not valid UTF-8 JSON",
            }
        diagnostic = core._task_state_schema_diagnostic(raw, raw_bytes)
        if diagnostic is None:
            return {
                "ok": False,
                "status": "STATE_SCHEMA_NOT_RECOVERABLE",
                "to_version": core._STATE_SCHEMA_VERSION,
                "state_sha256": digest,
                "recoverable": False,
                "recovery_action": "NONE",
            }
        if diagnostic["recoverable"] is not True:
            return diagnostic
        if raw.get("status") == "ACTIVE" and not abandon_active:
            return {
                **diagnostic,
                "ok": False,
                "status": "STATE_ABANDON_CONFIRMATION_REQUIRED",
                "recovery_action": f"thaliris --task-id <task-id> task-recover-state --expected-sha256 {digest} --abandon-active --controller-bridge-sha256 <current-bridge-sha256>",
            }
        task_id = raw.get("task_id")
        blocker = lifecycle.task_state_recovery_blocker(root, task_id)
        if blocker is not None:
            return {
                **diagnostic,
                "ok": False,
                "status": "STATE_RECOVERY_BLOCKED",
                "recoverable": False,
                "recovery_action": "NONE",
                "recovery_blocker": blocker,
            }
        version = diagnostic["from_version"]
        archive_relative = f".context/recovery/task-state-v{version}-{digest}.json"
        archive_path = core._safe_without_final_symlink(root, archive_relative)
        if archive_path.exists():
            if not archive_path.is_file() or archive_path.read_bytes() != raw_bytes:
                return {
                    "ok": False,
                    "status": "STATE_ARCHIVE_COLLISION",
                    "state_sha256": digest,
                    "recoverable": False,
                    "recovery_action": "NONE",
                }
            writes: dict[str, bytes] = {}
        else:
            writes = {archive_relative: raw_bytes}
        backup = core._apply_with_backup(root, writes, [state_name], "task-state-recovery")
    return {
        "ok": True,
        "status": "STATE_ARCHIVED_FOR_RECOVERY",
        "from_version": version,
        "to_version": core._STATE_SCHEMA_VERSION,
        "state_sha256": digest,
        "preserved_state_location": archive_relative,
        "backup": backup,
        "recovered": True,
        "next_action": "bootstrap-check, then a fresh attested task-start",
    }
def bootstrap_check(root: Path, *, codex_home: Path | None = None) -> dict[str, object]:
    """Return the read-only facts needed by the external Codex bootstrap.

    This deliberately performs no initialization and creates no durable state;
    the host entrypoint uses it to decide whether one direct ``init`` call is
    necessary before handing control back to the Controller.
    """
    root = core._repo_root(root)
    facts = _project_definition_facts(root, codex_home)
    definition_recovery_status = (
        "READY" if facts["project_definition_present"] == "YES"
        else "EXPLICIT_CONFIRMATION_REQUIRED" if facts.get("managed_instruction_state") == "USER"
        else "INIT_REQUIRED"
    )
    return {"ok": True, **facts, "definition_recovery_status": definition_recovery_status, **_controller_bridge(), "managed_hook_abi": lifecycle.MANAGED_HOOK_ABI, "executable_adapter_protocol_version": lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION, "session_restart_required": False}


def task_evidence_register(root: Path, role: str, base_revision: int, input_file: str,
                           controller_session_id_hash: str | None = None) -> dict:
    """Extend ordinary registration with one Controller-selected next dispatch."""
    from . import task_authority
    actor = controller_actor(role)
    payload = core._read_input(input_file)
    if set(payload) - {"requirements", "handoffs", "next_dispatch"}:
        raise ValueError("invalid evidence registration")
    selection = payload.get("next_dispatch")
    if "next_dispatch" in payload and (not isinstance(selection, dict)
            or set(selection) - {"role", "expected_agent_type", "candidate", "requirement_refs", "durable_paths"}
            or not {"role", "expected_agent_type", "candidate", "requirement_refs"} <= set(selection)
            or not isinstance(selection["expected_agent_type"], str)
            or not isinstance(selection["role"], str)
            or lifecycle._native_agent_roles().get(selection["expected_agent_type"]) != selection["role"]
            or not roles.delegation_allowed("controller", selection["role"])):
        raise ValueError("invalid next dispatch evidence selection")
    with task_authority._lock(root):
        if task_authority.check(root) is None and selection is not None:
            raise ValueError("dispatch selection requires current task authority")
        state = core._load_state(root, active=True)
        if state["revision"] != base_revision:
            raise ValueError("task revision conflict")
        task_id = state["task_id"]
        path = lifecycle._lifecycle_path(root, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        if selection is None:
            core._append_continuity_state(state, actor, payload, "register")
            lifecycle._write_evidence_reservation(root, state, path, None)
            return core._task_ack(state, ["evidence_continuity"])
        owner = lifecycle.active_controller_owner(root, task_id)
        if owner is None or owner != controller_session_id_hash or lifecycle._session_fenced(root, owner):
            raise ValueError("dispatch selection requires an unfenced owning Controller")
        if ledger.get("next_evidence_dispatch") is not None or ledger["pending_authorized_spawn"] is not None:
            raise ValueError("dispatch selection or reservation already pending")
        data = core._continuity(state)
        for field in ("requirements", "handoffs"):
            if field in payload:
                values = payload[field]
                if not isinstance(values, list) or not values:
                    raise ValueError("registration requires append-only additions")
                data[field].extend(values)
        core._validate_continuity(state)
        # Validate using the same Core handoff contract without persisting a
        # provisional handoff. The real ID is assigned at reservation.
        identifier = "selection-validation"
        known = {item["id"] for values in data.values() for item in values}
        known.update(item["id"] for field in ("records", "evidence_refs", "artifact_refs", "verification_results")
                     for item in state[field])
        while identifier in known:
            identifier += "-next"
        prototype = {"id": identifier, "parent_handoff_id": None,
            "producer": "handoff:" + identifier, "candidate": selection["candidate"],
            "requirement_refs": selection["requirement_refs"]}
        if "durable_paths" in selection:
            if selection["role"] != "curator":
                raise ValueError("durable paths require Curator")
            prototype["durable_paths"] = selection["durable_paths"]
        core._register_evidence_handoff(state, prototype)
        data["handoffs"].pop()
        state["revision"] += 1
        ledger["next_evidence_dispatch"] = {**selection, "owner_session_id_hash": owner}
        lifecycle._write_evidence_reservation(root, state, path, ledger)
        return {**core._task_ack(state, ["evidence_continuity"]), "next_dispatch": selection}


def _selected_handoff(root: Path, handoff_id: str) -> dict:
    state = core._load_state(root, active=True)
    matches = [item for item in state.get("evidence_continuity", {}).get("handoffs", []) if item["id"] == handoff_id]
    if len(matches) != 1:
        raise ValueError("selected handoff has no evidence association; return the observation and sources to Controller to register its exact opaque requirement/candidate association")
    return matches[0]


def task_observe(root: Path, role: str, handoff_id: str | None, agent_id_hash: str | None,
                 input_file: str | None = None, observation_json: str | None = None) -> dict:
    """Persist one selected observation without rewriting caller-owned input."""
    from . import task_authority
    with task_authority._lock(root):
        task_authority.check(root)
        return _task_observe_locked(root, role, handoff_id, agent_id_hash, input_file, observation_json)


def _task_observe_locked(root: Path, role: str, handoff_id: str | None, agent_id_hash: str | None,
                          input_file: str | None, observation_json: str | None) -> dict:
    actor = semantic_role(role)
    if (input_file is None) == (observation_json is None):
        raise ValueError("task-observe requires exactly one of --input or --observation-json")
    if observation_json is not None:
        from . import observation_transport
        body = observation_transport.decode(observation_json)
        if not isinstance(body, dict):
            raise ValueError("observation JSON must be an object")
    else:
        body = core._read_input(input_file)
    if not isinstance(body, dict):
        raise ValueError("observation must be an object")
    body = dict(body)
    if {"native_status", "native_status_conflict"} & set(body):
        raise ValueError("observation native execution status is assigned by the adapter")
    task = core._load_state(root, active=True)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task["task_id"]), task["task_id"])
    matches = [child for child in ledger["children"] if isinstance(child, dict)
               and child.get("handoff_id") == handoff_id and child.get("managed") is True
               and child.get("handoff_bound") is True]
    if actor == "controller":
        if agent_id_hash is not None or handoff_id is None or len(matches) != 1:
            raise ValueError("Controller import requires one exact historical native handoff")
        child = matches[0]
        if (not isinstance(child.get("agent_id_hash"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", child["agent_id_hash"])):
            raise ValueError("Controller import requires the exact native handoff identity")
        agent_id_hash = child["agent_id_hash"]
        submitted_by = "controller"
        native_status = child.get("native_terminal_status")
        body["native_status"] = native_status if isinstance(native_status, str) and native_status else "UNKNOWN"
        body["native_status_conflict"] = child.get("native_status_conflict") is True
    else:
        matches = [child for child in matches if child.get("agent_id_hash") == agent_id_hash and child.get("role") == actor
                   and child.get("management_disposition") != "ABANDONED_DEPENDENCY"
                   and not child.get("native_status_conflict")
                   and not lifecycle._native_execution_terminal(child)]
        if len(matches) != 1 or not isinstance(agent_id_hash, str):
            raise ValueError("observation requires exact live native handoff producer")
        child = matches[0]
        submitted_by = None
    handoff = _selected_handoff(root, handoff_id)
    if handoff.get("producer") != "handoff:" + handoff_id:
        raise ValueError("registered handoff producer must preserve the exact native handoff")
    for key, selected in (("handoff_id", handoff_id), ("candidate", handoff["candidate"]), ("requirement_refs", handoff["requirement_refs"])):
        if key in body and body[key] != selected:
            raise ValueError("observation differs from selected native handoff: " + key)
        body[key] = selected
    if "native_actor" in body and body["native_actor"] != agent_id_hash:
        raise ValueError("observation native actor conflict")
    if "submitted_by" in body:
        raise ValueError("observation submitter is assigned by the adapter")
    body["native_actor"] = agent_id_hash
    if submitted_by is not None:
        body["submitted_by"] = submitted_by
    core._append_continuity_state(task, handoff["producer"], body, "observations")
    lifecycle._write_evidence_reservation(root, task,
        lifecycle._lifecycle_path(root, task["task_id"]), None)
    return core._task_ack(task, ["evidence_continuity"])


def document_maintain(root: Path, role: str, base_revision: int, input_file: str, handoff_id: str | None = None) -> dict:
    actor = semantic_role(role)
    if actor == "controller":
        return core.document_maintain(root, actor, base_revision, input_file)
    if actor != "curator" or handoff_id is None:
        raise ValueError("durable maintenance requires Controller or exactly selected Curator handoff")
    handoff = _selected_handoff(root, handoff_id)
    body = core._read_input(input_file)
    paths = []
    for key in ("writes", "deletes"):
        entries = body.get(key, [])
        if not isinstance(entries, list):
            raise ValueError("Curator maintenance entries must be lists")
        for item in entries:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Curator maintenance requires explicit selected document paths")
            paths.append(item["path"])
    index_update = body.get("index_update")
    if index_update is not None:
        if not isinstance(index_update, dict) or not isinstance(index_update.get("path"), str):
            raise ValueError("Curator INDEX replacement requires an explicit selected path")
        paths.append(index_update["path"])
    if not paths or not set(paths) <= set(handoff.get("durable_paths", [])):
        raise ValueError("Curator maintenance exceeds Controller-selected durable paths")
    with tempfile.TemporaryDirectory(prefix="thaliris-maintenance-") as directory:
        snapshot = Path(directory) / "maintenance.json"
        snapshot.write_text(json.dumps(body), encoding="utf-8")
        return core.document_maintain(root, actor, base_revision, str(snapshot))


def task_close(root: Path, base_revision: int) -> dict[str, object]:
    from . import task_authority
    task_authority.check(core._repo_root(root))
    state = core.task_show(root)["state"]
    task_id = str(state["task_id"])
    if not lifecycle.native_execution_closed(core._repo_root(root)):
        raise ValueError("task-close requires resolved native execution risk: no pending, active, unknown or conflicting child identities/statuses; observe exact native terminal status with list_agents (V2) or wait_agent status map (V1). Historical handoff/Start/Stop completeness does not decide closure; the Controller decides product acceptance from the original objective, criteria and available evidence")
    result = core.task_close(root, base_revision, expected_task_id=task_id)
    task_authority.checkpoint(core._repo_root(root))
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(core._repo_root(root), task_id), task_id)
    if ledger.get("dependency_dispositions"):
        result = {**result, "task_disposition": "CLOSED_BY_CONTROLLER",
            "native_execution": "UNKNOWN", "death_proof": "UNKNOWN", "writing_risk": "UNKNOWN",
            "closure_basis": "DEPENDENCY_DISPOSITION_WITHOUT_NATIVE_TERMINATION"}
    return result


def audit_hook(root: Path, event: str, payload: object, managed_hook_abi: str | None = None) -> str:
    # Tool capacity cannot choose event/dependency waiting policy or override
    # higher-level duration limits. Preserve the caller's native wait arguments;
    # lifecycle admission, isolation and completion checks remain authoritative.
    return handle_hook(root, event, payload, managed_hook_abi)


def doctor(root: Path) -> dict[str, object]:
    from .doctor import report
    root = core._repo_root(root)
    result = report(root)
    home = _codex_home()
    manifest = home / runtime_identity.MANIFEST_NAME
    runtime_drift = (runtime_identity.diagnose_manifest(manifest.read_bytes())
                     if manifest.is_file() and not manifest.is_symlink()
                     else {"status": "UNKNOWN", "execution_assurance": "UNKNOWN", "error": "installed manifest unavailable"})
    definitions = []
    for name, expected in ((HOST_HOOK_SCRIPT_NAME, host_hook_script_bytes()),
                           (host_preflight.NAME, host_preflight.script_bytes())):
        path = home / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else "UNKNOWN"
        wanted = hashlib.sha256(expected).hexdigest()
        definitions.append({"surface": "hook", "path": name, "expected": wanted, "actual": actual,
                            "status": "MATCH" if actual == wanted else "UNKNOWN" if actual == "UNKNOWN" else "CHANGED"})
    profiles = []
    try:
        execution_constraint = _installed_execution_constraint()
    except ValueError as exc:
        if str(exc) != "EXECUTION_PROFILE_CONSTRAINT_MISMATCH":
            raise
        execution_constraint = "incoherent"
    expected_constraint = execution_constraint if execution_constraint in roles.EXECUTION_CONSTRAINTS else None
    for name, (model, effort, role) in roles.agent_profiles(expected_constraint).items():
        path = home / "agents" / name
        actual = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        expected = _agent_profile(name.removesuffix(".toml"), role, model, effort)
        profiles.append({"surface": "profile", "path": name,
                         "ownership": _agent_profile_state(actual, name, expected_constraint) if actual is not None else "missing",
                         "expected": hashlib.sha256(expected).hexdigest(),
                         "actual": hashlib.sha256(actual).hexdigest() if actual is not None else "UNKNOWN"})
    result["drift_evidence"] = {"installed_runtime": runtime_drift, "hook_definitions": definitions,
                                "profile_definitions": profiles, "ordinary_workspace_work_allowed": True,
                                "user_configuration": "PRESERVE_UNLESS_EXPLICITLY_AUTHORIZED",
                                "cli_version": host_wait_mode().get("version", "UNKNOWN"),
                                "daemon_version": "UNKNOWN", "daemon_control_authority": "UNKNOWN",
                                "controller_actor_assurance": lifecycle._controller_actor_assurance({}),
                                "host_topology": "UNKNOWN",
                                "decision": "CONTROLLER_REPAIR_RESTORE_OR_ACCEPT_WITHIN_USER_AUTHORIZATION"}
    registry_path = root / "docs" / "thaliris-role-registry.md"
    registry_state = (
        _role_registry_state(registry_path.read_bytes())
        if registry_path.is_file()
        else "missing"
    )
    result["role_registry"] = {
        "roles": list(_role_choices()),
        "installed_execution_constraint": execution_constraint,
        "native_profiles": sorted(roles.native_profile_names()),
        "host_profile_definition_present": _host_profile_definition_present(),
        "project_local_profile_files_present": _project_local_profile_files_present(root),
        "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN,
        "profile_inventory": role_profile_inventory(root),
        "generated_role_document": "CURRENT" if registry_state == "current" else "MISSING_OR_USER"
        if registry_state != "missing" else "MISSING",
    }
    result["durable_index_integrity"] = core.durable_index_check(root)
    result["managed_task_state"] = lifecycle.managed_task_state(root)[0]
    observations: list[tuple[int, int, dict[str, object]]] = []
    events: set[str] = set()
    pretool_tools: set[str] = set()
    compatible_profile_observed = False
    orchestration = {
        "wait_calls": 0,
        "wait_timeouts": 0,
        "list_agents_calls": 0,
        **{
            binding.orchestration_metric: 0
            for binding in roles.iter_codex_bindings()
            if binding.orchestration_metric is not None
        },
    }
    expected = lifecycle.managed_hook_spec_hash()
    for path in (root / ".context" / "audit").glob("*/runtime.json"):
        try:
            runtime = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        current = isinstance(runtime, dict) and runtime.get("managed_hook_spec_hash") == expected and runtime.get("adapter_protocol_version") == lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION
        samples = runtime.get("execution_observations") if current else None
        if current and isinstance(runtime.get("events_observed"), dict):
            events.update(name for name, observed in runtime["events_observed"].items() if observed is True)
        if current and isinstance(runtime.get("pretool_tools_observed"), list):
            pretool_tools.update(tool for tool in runtime["pretool_tools_observed"] if isinstance(tool, str))
        if current and isinstance(runtime.get("subagent_start_agent_types"), list):
            compatible_profile_observed = compatible_profile_observed or any(
                isinstance(value, str) and value in roles.native_profile_names()
                for value in runtime["subagent_start_agent_types"]
            )
        if isinstance(samples, list):
            observations.extend((int(item.get("observed_at_ns", runtime.get("observed_at_ns", 0))), int(runtime.get("observation_sequence", 0)), item) for item in samples if isinstance(item, dict))
        metrics = runtime.get("orchestration_metrics") if current else None
        if isinstance(metrics, dict):
            orchestration["wait_calls"] += int(metrics.get("wait_agent_calls", 0))
            orchestration["wait_timeouts"] += int(metrics.get("wait_timeouts", 0))
            orchestration["list_agents_calls"] += int(metrics.get("list_agents_calls", 0))
    latest = max(observations, default=None, key=lambda item: (item[0], item[1]))
    latest_item = latest[2] if latest is not None else None
    tool_schemas: dict[str, dict[str, object]] = {}
    for _, _, item in sorted(observations, key=lambda entry: (entry[0], entry[1])):
        if isinstance(item.get("tool"), str):
            tool_schemas[item["tool"]] = item
    health = lifecycle.hooks_health(root)
    lifecycle_start = lifecycle_stop = lifecycle_reconciled = lifecycle_bound = False
    identity_sources: set[str] = set()
    routing_counts = {field: {status: 0 for status in ("MATCH", "MISMATCH", "INVALID", "UNKNOWN")}
                      for field in ("model", "reasoningEffort")}
    for path in (root / ".context" / "audit" / "lifecycle").glob("*.json"):
        try:
            lifecycle_state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(lifecycle_state, dict) or lifecycle_state.get("version") != lifecycle.LIFECYCLE_STATE_VERSION or lifecycle_state.get("managed_hook_spec_hash") != expected or lifecycle_state.get("adapter_protocol_version") != lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION:
            continue
        for observation in lifecycle_state.get("native_routing_observations", []):
            routing = observation.get("routing") if isinstance(observation, dict) else None
            if isinstance(routing, dict):
                for field, counts in routing_counts.items():
                    fact = routing.get(field)
                    status = fact.get("status") if isinstance(fact, dict) else None
                    if isinstance(status, str) and status in counts:
                        counts[status] += 1
        for child in lifecycle_state.get("children", []):
            if isinstance(child, dict):
                bound = (child.get("managed") is True and child.get("handoff_bound") is True
                    and isinstance(child.get("handoff_id"), str))
                lifecycle_bound = lifecycle_bound or bound
                if bound and isinstance(child.get("native_identity_source"), str):
                    identity_sources.add(child["native_identity_source"])
                lifecycle_stop = lifecycle_stop or isinstance(child.get("stop_observed"), int)
                lifecycle_reconciled = lifecycle_reconciled or (
                    lifecycle._native_execution_terminal(child) and not child.get("native_status_conflict")
                    and child.get("native_terminal_source") in {"list_agents", "wait_agent", "interrupt_agent", "close_agent"})
            if isinstance(child, dict) and isinstance(child.get("started"), int):
                lifecycle_start = True
                binding = roles.get_codex_binding(child.get("role")) if isinstance(child.get("role"), str) else None
                metric = binding.orchestration_metric if binding is not None else None
                if metric is not None:
                    orchestration[metric] += 1
    result["verification_attestation"] = {
        "host_hook_registration_present": health["hooks_configured"],
        # Stored observations are intentionally useful diagnostics, but they
        # cannot prove that the session asking for this doctor report loaded
        # the current Host hook registration.
        "current_session_observed": "UNKNOWN",
        "task_start_attestation": "CURRENT_SESSION_REQUIRED",
        "adapter_protocol_current": "YES" if events or latest is not None else "UNKNOWN",
        "verification_shell_surface": "Bash",
        "verification_terminal_status": "UNAVAILABLE",
        "observed_outcome": latest_item.get("outcome") if latest_item is not None else "UNKNOWN",
        "hook_trust": "UNKNOWN",
        "detail": "No version-pinned terminal-status attestation is recorded; no automatic PASSED attestation is emitted.",
    }
    result["managed_readiness"] = {
        "CORE_READY": "YES",
        "HOST_HOOK_REGISTRATION_PRESENT": health["hooks_configured"],
        "CODEX_RUNTIME_OBSERVED": health["runtime_observed"],
        "CURRENT_SESSION_OBSERVED": "UNKNOWN",
        "TASK_START_ATTESTATION": "CURRENT_SESSION_REQUIRED",
        "CODEX_MANAGED_READY": "UNKNOWN",
        "spawn_pretool_observed": "YES" if "spawn_agent" in pretool_tools else "UNKNOWN",
        "subagent_start_observed": "YES" if lifecycle_start else "UNKNOWN",
        "subagent_stop_observed": "YES" if lifecycle_stop else "UNKNOWN",
        "explicit_handoff_binding_observed": "YES" if lifecycle_bound else "UNKNOWN",
        "native_dispatch_identity_sources": sorted(identity_sources),
        "CONTROLLER_ACTIVATION_BRIDGE_ACTIVE": "UNKNOWN",
        "HOST_INSTRUCTION_ACTIVE": "UNKNOWN",
        "controller_activation_bridge": "UNKNOWN",
        "NATIVE_CHILD_COMPLETION_REENTERS_ROOT": native_child_completion_reenters_root(),
        "HOST_EXPLICIT_BLOCKING_WAIT": host_explicit_blocking_wait().get("status"),
        "EFFECTIVE_WAIT_MAXIMUM": host_explicit_blocking_wait().get("effective_max_wait_timeout_ms", "UNAVAILABLE"),
        "BLOCKING_WAIT_MODE": "PASS" if selected_continuation_mode(root) == "BLOCKING_WAIT" else "FAIL",
        "selected_continuation_mode": selected_continuation_mode(root),
        **_activation_fields(
            root,
            profile_native_active="UNKNOWN",
            project_layer_activation="UNKNOWN",
            compatible_profile_observed="YES" if compatible_profile_observed else "UNKNOWN",
            host_hook_runtime_observed="YES" if events else "UNKNOWN",
        ),
    }
    # Keep Host registration and project marker disk facts separate from live
    # session observations; neither can stand in for a native hook run, a deny,
    # or a Reviewer sandbox observation.
    host = result.get("host_capability") if isinstance(result.get("host_capability"), dict) else {}
    host.update({
        "hook_runtime_observed": "YES" if events else "UNKNOWN",
        "controller_pretool_observed": "YES" if "PreToolUse" in events else "UNKNOWN",
        "subagent_lifecycle_observed": "YES" if lifecycle_start and lifecycle_stop else "UNKNOWN",
        "hook_hash_match": "YES" if events else host.get("hook_hash_match", "UNKNOWN"),
        "hook_trust_status": "UNKNOWN",
        "controller_deny_observed": "UNKNOWN",
        "controller_side_effect_prevented": "UNKNOWN",
        "reviewer_native_readonly_observed": "UNKNOWN",
        "trusted_runtime_isolation_observed": "UNKNOWN",
        "effective_wait_maximum": host_explicit_blocking_wait().get("effective_max_wait_timeout_ms", "UNAVAILABLE"),
    })
    result["host_capability"] = host
    posttool_schema = "PASS" if any(item.get("native_response_contract") in {"CURRENT_V2", "LEGACY_V1"}
        for tool, item in tool_schemas.items() if tool in lifecycle._COLLABORATION_TOOL_NAMES) else "UNKNOWN"
    result["lifecycle_reconciliation"] = {
        "subagent_stop_path": "PASS" if lifecycle_stop else "UNKNOWN",
        "managed_child_turn_notification_ingress": "UNKNOWN",
        "native_status_identity_scope": "legacy_thread_snapshot",
        # The pinned source supplies these shapes, but a
        # Host hook must observe a real payload before this is a live PASS.
        "native_terminal_reconciliation": "PASS" if lifecycle_reconciled else ("LIVE_NOT_OBSERVED" if posttool_schema == "PASS" else "UNKNOWN"),
        "PostToolUse_source_schema_support": posttool_schema,
        "PostToolUse_live_host_hook": "PASS" if "PostToolUse" in events else "LIVE_NOT_OBSERVED",
        "tool_response_schemas": tool_schemas,
        "recorded_routing_status_counts": routing_counts,
    }
    result["cost_regression"] = {
        # This Hook surface has no model-turn/token/context counter.  Leaving
        # these unavailable is safer than deriving model cost from wait calls.
        "root_model_activations": "UNAVAILABLE",
        "child_model_activations": "UNAVAILABLE",
        "root_input_tokens": "UNAVAILABLE",
        "child_input_tokens": "UNAVAILABLE",
        "root_context_size_per_activation": "UNAVAILABLE",
        "ROOT_ACTIVATIONS_WITHOUT_NEW_INFORMATION": "UNAVAILABLE",
        "ROOT_MODEL_ACTIVATIONS_PER_CHILD": "UNAVAILABLE",
        **orchestration,
    }
    return result
