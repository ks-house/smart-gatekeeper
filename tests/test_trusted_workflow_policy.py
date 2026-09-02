import copy
import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_trusted_workflow_policy as trusted  # noqa: E402


MERGED_MAIN_COMMIT = "ca2977638c535aa8ba7bc4ddbeb07342051d1f50"
EXPECTED_BUNDLE_ID = "crash-durable-access-ca29776-persistent-baseline"
MERGED_MAIN_DIGEST_LINES = """\
.github/workflows/deploy.yml 4350339bac833ed6ac744940dc35f31fb8a41b45b8a094cb5065cd181678a98e
.github/workflows/build_app.yml 64551776dd81ecc9018de045793e289bbcb3d52e690d0dfc5eb3f6e5253f3487
.github/workflows/ota_contract.yml ea1e3180ab1865b43df368cdb09b7eda162cc7e027752aaf2a87e4ee4f76e92d
.github/workflows/personal_installation_firmware.yml d29439b9754c8baec015bcb19989ced81fa950da5dd800a5c6c8ee7515c97704
.github/workflows/protocol.yml b60ce78c630c30f6ab5b5b3d23a042f08d125c6507ebd347e3fc4d0dc66b5740
.github/workflows/trusted_workflow_policy.yml 79aaf7a773592ecf9156191f589a9ae3e3649b4de06a1b08034507c83184a658
scripts/verify_trusted_workflow_policy.py 78a96058cd12cfadde01ac0c7aa733bfa96a43789a0a5173d02ffaea582e2641
scripts/ota_contract_gate.py 4dd7914e2cb3e388bb1cb9d456dca93e1a00ded6584beb448d6a7aec39211065
ota/requirements.txt 21f985255f11f89d00cd6061a3817c860b6da951424121040e82358053cf90c7
ota/requirements.lock 5b8c5859426a7febd6bd9d9b0482bf78f8f4854c2d83d0ce53ba49c14c5cea12
src/OtaManager.cpp 36f1db079f0ea65feb175c7fcf5d079b1e9952ad40e98607036874f252f3cea7
.github/workflows/backend_security.yml 07289ce868ed24464d95fd3735e20511756a78588d37eaae321d29c557df98f2
.orca/scripts/setup_worktree.ps1 07662269a4ee145547a6d0365764f4ab2d42d4234b64fe452b8a9bac4a6440ab
scripts/ops_commercial_gate.py 06391a17506af7c0e44fd0efb7e2ef56b911a04a3425877440d2ad32af7f46e4
ops/backend_trusted_bundle_paths.json 9f110ed03158aadd3c77db3cd9c4851e18a36dd0ddfab2a86012ca7ffec19849
ops/evidence_sources.json 49d23f9125f65db4ba0e4398e742bcf7f41b34174b2df3d47aef1efa4fbb951b
ops/fixtures/evidence_adversarial_v1.json c2bbc316b4730a28e873abc3017f533afab2e6d7d45f95e29e228b661f72c04f
ops/fixtures/load_nominal.jsonl c7ae231d1d7321255ce0d5539b3fd18b1aa077c94ae5060fc293624913b8015e
ops/prometheus_rules.yml 8bfea1ed8d82d4bf4ce7c75ee52e5909c4b7af2c0f405d1b942ddf1119012fe9
ops/slo_policy.json e7c734c431d232e6caffa32d0796990e3dc71ff88c557498bd4433479c825e4a
backend/.env.example d7203e116734677c8ace54ccf90bbac02529856cb185a99c88cae5a17894f3b0
backend/app/Dockerfile ec66fbe0de7f4fe47edf36e594810a0bb1192cf94fa5fc81cc7fced224479573
backend/app/acl_refresh.py 4f040eb22f2d1e7277f6eb65c47e0db8cd122de17296cd707217cb7aafafd537
backend/app/acl_api.py ab95deb6aea6f625451e26aa6c7e6caf8a55c43ff1642b4c28d37b24f76b7c40
backend/app/acl_management.py 190b7c7891b46a7b313ca3876d0bfa552eeba62bc122d39cfbac3bb53b17d6c9
backend/app/access_actor_ref.py 5e02534777365be7fc9c9997d96dc22458c4292bd3c2f1998cacebc44034cd3d
backend/app/admin_security.py f3f769eebea014f94b36cdba1bec4627b657094f2d5fa737f29f54a57db0d4c9
backend/app/command_security.py 9b5c058fd8fe4d58c6c20a23548e803ddeb06b493a344f18e29453f599271e1c
backend/app/home_assistant_bridge.py 8c89a034937534524ee319065bcc6eae5502892f46435e02e20a683847ef92e9
backend/app/main.py afd0b0fc78fbcd77ecee6fcbb1f43f14f63176dbef9d9ff2d4f594ebd42d2451
backend/app/ops_runtime.py 9aad988a7bd1c59d90d445ff3577e265289424c17e98c0b1f8311c1e14a58b26
backend/app/requirements.lock 4a1f393a82340ed062e7e2efdc7b57edd8df6d6d59d62a561643c93685a19a71
backend/app/requirements.txt 75bca144713e5c0ac8c09f2963cccb45e077e22b2f5a166a0db1fa28617595f7
backend/app/static/admin.html b787c235355e459133f18cbf796cc0b04bd728578a331a2453d7b4739932d120
backend/app/static/admin_login.html 87000b8f02d22b84bc24a41b0360caf9ce1c8a58741a95d090bf5e8acaabff3f
backend/app/static/index.html 1ae6e77c85f965b09334ebf6222d3a8a66b8ad35b409aba65a0a9543bcf2bc12
backend/app/target_boot_registry.py 7650ad165594d3a35ee59fafa36ce1f6cbc0ffa4fd8b3dfb98873339a83859dd
backend/app/target_acl_delivery.py 3888c4fb5d5814471e6d1827d6227015a730683eee089733b65b8703fdb1093d
backend/compose.production.yml 0f0d1bd3ff45635bf6cb17b79af7df1043d6814f70ebb728d8a41009570114e6
backend/compose.synology.yml f90bc1675e97b6e0710deb415de32a6ce1dd22f21cb3cdf3b98fd7be5c50fcbd
backend/db/Dockerfile 8b14bf8091ae110d5c2a6aac1bcaf41b66f490a742c7bdc1a7291c9a9f670613
backend/db/migrations/002_acl_management_expand_down.sql 19c26782df1ef78755681805839e704f3adaf83cce1dec4b29c4ecdf1c0cf687
backend/db/migrations/002_acl_management_expand_up.sql aa3b07f195c0502434f8ad5ba633b0d46d6b04f7e21fa0ff22215fb136746543
backend/db/migrations/003_admin_security_down.sql 1fb6804703a9fdd4d9ffdb74adb1113cd7f420b914fa572978dcb2e6212f9d71
backend/db/migrations/003_admin_security_up.sql 488f52723e9e4d089c25f46d80bfcd641cf573a0d68d950bfbbf6b6c7c5923e1
backend/db/migrations/004_admin_control_v2_down.sql 5ac8153a9247176f0631f8e621d99913cb010b870cd42e635ae7c6d7f5cc0b78
backend/db/migrations/004_admin_control_v2_up.sql 58cefa03fb7c70a96b819510b80ccd8bd0cc085b0cb981d76bd0c86b78801d49
backend/db/migrations/005_force_open_reconciliation_down.sql c9f0e1c5f85fbc6c462f9fefc8417548f86ae0a3f3d39c4d9b9ab7c6eab2de13
backend/db/migrations/005_force_open_reconciliation_up.sql 36d08998dd633cce71d67ad6124b668e81804911eddf7e9322f9e40c9c14e5e7
backend/db/migrations/006_target_boot_state_down.sql d746fd9fca137863f19f54d461edde52c09d2c4fd64bfc0d2b8610361e3e03ff
backend/db/migrations/006_target_boot_state_up.sql b7beae706b694d3fde5b63bf2d1587ba5ded887aedec060e148b15109f5fcabd
backend/db/migrations/007_ops_privacy_down.sql 2f0c2094f6c5748ad3a067a71c3d31effed310ccc68ebb14c714ec09fe901922
backend/db/migrations/007_ops_privacy_up.sql edde5662c42e65dda82b2e0a9145d64dc4ebfc9fe7a5e5bd44b0b3aae0fe1d79
backend/db/migrations/008_mobile_credential_control_down.sql 362cb1abbddfd2603263cdaa9ca2b6b75b8ac67c876424bb91ad4c2d11d37391
backend/db/migrations/008_mobile_credential_control_up.sql f95e752d96ea34ce7373d8573738936c5ec08ac296ee600a96c45d087e7219a8
backend/db/migrations/009_admin_account_management_down.sql ad2fff10af88b6c382ebfcdc30cc3a56b907ad0da6553a401f03235301367b88
backend/db/migrations/009_admin_account_management_up.sql 5ffe2f22c145faa1441af76b873606af7015310402b7e3f08e7e97fdce9a507d
backend/db/migrations/010_mobile_account_roles_down.sql 7af41ea77538e3ec3b8eb2c8a1d281bb03ed65c78113fa73e46160bda56865d6
backend/db/migrations/010_mobile_account_roles_up.sql 76260eac7406904ec5f039c68ec34440c829611a9a85d23208372dee4b02cfd7
backend/db/migrations/011_access_event_history_down.sql 436cfa498ac7074c07f84f71c945606284f6b9a5d09df09828a852c6bd2fdee3
backend/db/migrations/011_access_event_history_up.sql d29f683a1ad8aad86ba5e11b48d35aab1e39acadaca1f34b2c26c748fd364572
backend/db/migrations/012_access_event_actor_ref_down.sql f59b0b99a939c673b098357840228011cbb4477bea13f0e4ee3d2a15b7e68ef2
backend/db/migrations/012_access_event_actor_ref_up.sql f550f7857eb09a2f119454fe2698bdefc07365cf1105ca6447e9cafdc0586f4d
backend/db/migrations/013_ha_access_event_outbox_down.sql 5a034ee4da583fbfbb0dbfa6fb0aad19cdcc9307e66bff0232ded9d417a7fc6d
backend/db/migrations/013_ha_access_event_outbox_up.sql 81b72652f467b45e0a95dc2d7a363905accd76b17d170bcb78f8d82148d04732
backend/db/production_schema.sql b9e6910bff05272c1b05f1e23805abf250c6a9e3df9e4a7db966ae6517b555e3
backend/db/run_migrations.sh 2452092130ac42a69c6335e396203ce5d48d66039b95a39863f4178cdfc19917
backend/db/schema.env f77e61c0cb98460d91b4f1e04acd2034b2af9a45d5ec8ad79f45d9c5be8ede83
backend/db/schema.sql ce22d4e2675490f2e238cd98e9f9168e572cd45d0de8030811b01384226f4d43
backend/deploy/README.md 531530e27838029902d4830768644916538de31bf251d2b0a94f8d10b49effe8
backend/deploy/bootstrap_legacy_synology.sh 30ae4087a8c974fb7dd0e66f0cb768b9f5247522439192eac35cc33c707bc3c0
backend/deploy/capture_legacy_inventory.py 71bb7d9721934a00f44a8913ce3d5c514d18d3aeac0031679afe146d8a06181d
backend/deploy/create_legacy_backup.sh 7a6323dd90dab2494bad2c2afdc9eb348def38a0c4b98852f4d7f2f575631a54
backend/deploy/create_release_bundle.py 2d82ba4421de9d3d487661b0e09a840b2b4d7e0527b03c4d8e7582d429747195
backend/deploy/prepare_backup_in_wsl.py d502283be7b594f8d0d6c7fa0f2e65d6e61c0c9c548252215d3cf3ac3c484e79
backend/deploy/restore_backup_in_wsl.py 7e317efe496cc5f339a4bb90776a304268c20c2501066575488baa2677bd393b
backend/deploy/runtime.env.example f4ab9aed000713cf18e8fc0339bc698eefc8868aae9bb1dede267232b4ea31be
backend/deploy/sgk_backend_deploy.sh ec7e7eaafa0db301440dcfe4643efde4ebb67cfda914f48d9a5d2b99e11a9806
backend/deploy/sgk_backend_ssh_dispatch.sh 6e80dedc8a546062fe038d7a537383aa65eb1176bd54c99c44704e0e3ff2ff98
backend/deploy/verify_legacy_synology.sh 85bebd22ffdcb6ea0256a245af166901f9f58d155e1cd210265c0c8aaf3f78b6
backend/docker-compose.yml 84974c3f7104bc7b0b6c8e9c6f0465a140ea6c9ec935d6e3d0a973378075f770
backend/sbom.cdx.json 67b78d1a2cb4d5e48dc8b79f9630a58da0cee207d126c469cb0b0bfbd1945fd7
backend/supply_chain_policy.json fef90253f3ec0b065f14dd1e83a2b6702b4dd2ad8dbeefc59b12dc78f3cb15e4
backend/tests/test_acl_api.py 2442e46942db79c19a1058a5e53939404682744d90c7a896d58633ae6dfb5c82
backend/tests/test_acl_refresh.py 10fa6c79fd910e36c710d0b1fc1b96a16fb507a560dad70e8f02b13f1e54bb70
backend/tests/test_acl_management.py c1d476aad60f06aac4335a3b052135bf838739dbcc204996d33b1404eeb7ccc3
backend/tests/test_access_actor_ref.py 3c983d400b6d140166611fbe182efbbfb8fcc141668e431d8407278ba02810fc
backend/tests/test_admin_security.py f905d98bc2b073d04bf791e5c254a6cf0fd220c24dffd75cd2d3f07fe9b76a19
backend/tests/test_home_assistant_bridge.py 6d74feb0521246be2855fceca23af3846cff578d224090814301c8b4048ef3d7
backend/tests/test_legacy_ota_independence.py 3aa3ab2a36926bb409949d18caaa9fd65234f3af45d687726660d249fe458a72
backend/tests/test_migrations.py dd946cad0c5be1ea80d77e36b1ee3fe597ddd55239ff84e3e3ad03d79d9440ab
backend/tests/test_mobile_remote_control.py 0d847814ec779b236f2bfd7b162bc555c00c7a352d66042ea9d9a575a820edaa
backend/tests/test_nas_backend_deploy.py d71038e447fdb42283015323797f9ede6b5bcd0c440440698901909fce631ab9
backend/tests/test_ops_api.py 43b81c0be0f6e1545306a48a8d9bfc7ac6c903a1c69b8d1a55a7170971fadc5b
backend/tests/test_ops_commercial_gate.py a56ca1d6becf3361097b4e3bc0c7939494c1841860456447e070afe690e29d18
backend/tests/test_ops_runtime.py 322d72efa0c1ebf8154992bea6c153ac6904eaf3fe61b2dee7dc779d5c131519
backend/tests/test_target_boot_registry.py 8c4a2f2bb5cc11fa20415c7a53161d7a3808b42479a5a90e483a333f307fb861
backend/tests/test_target_acl_delivery.py f1b12c33a8adf1544a7f98acbbc6d468ef279ea3d7f11964a3265fd410acbf7b
protocol/test_vectors/v1.json a60dfef0d23b8b3bd016e8f30e690609a82ff009ca90ff2c6aa5525d7539048f
security/mosquitto.conf 67037e4d68decfaab224781f2618cfd864686cfa90dd6ccc801b51df532f4587
security/target-acl 4677a99651767157abe826744018e052d31c754890ecd32cce5f24712b3c21eb
tests/test_target_security_ota.py 34a98b9ae139d96e8a13611dc5c6f05c8d2b96cbd0538d7d09fe6ef3d627e8e3
"""
FEATURE_CHANGED_PROTECTED_PATHS = {
    ".github/workflows/deploy.yml",
    "scripts/ops_commercial_gate.py",
    "ops/backend_trusted_bundle_paths.json",
    "backend/.env.example",
    "backend/app/home_assistant_bridge.py",
    "backend/app/main.py",
    "backend/app/static/admin.html",
    "backend/db/Dockerfile",
    "backend/db/migrations/013_ha_access_event_outbox_down.sql",
    "backend/db/migrations/013_ha_access_event_outbox_up.sql",
    "backend/db/schema.env",
    "backend/docker-compose.yml",
    "backend/tests/test_home_assistant_bridge.py",
    "backend/tests/test_migrations.py",
    "backend/tests/test_nas_backend_deploy.py",
    "backend/tests/test_target_boot_registry.py",
}
MERGED_MAIN_DIGESTS = dict(
    line.split() for line in MERGED_MAIN_DIGEST_LINES.splitlines()
)
CURRENT_WORKFLOW_PATHS = sorted(
    path for path in MERGED_MAIN_DIGESTS if path.startswith(".github/workflows/")
)
OLD_FIVE_PATHS = [
    ".github/workflows/deploy.yml",
    ".github/workflows/build_app.yml",
    ".github/workflows/ota_contract.yml",
    "scripts/ota_contract_gate.py",
    "ota/requirements.txt",
]
RETIRED_MAIN_SAMPLE_DIGESTS = {
    ".github/workflows/backend_security.yml": (
        "5ea77cd7444c7a284485acf65a24e265746bcde4fbb18fa30b1f6220b45053b0"
    ),
    "backend/app/main.py": (
        "af96a303439e77fceb8cb781196f7558e768119ba0c5c03ed6331636fe721e80"
    ),
}
RETIRED_SOURCE_COMMITS = {
    "d3d15d1f540950b1232b3ebf3ee5eb4614c19fac",
    "8e0c02c415ac2f2214cca5393a2682fd4b6c3a85",
    "9291758c99fd21231ddb30fe029b3f6f11fb1de2",
    "15005944591a43a5437ccf33f9a945ab7b47809f",
    "7be876804c23d91caf252b92e2b859f81aee168a",
    "1feb4b9d14ee2742e228f298557e3335a2060d09",
    "dbafe9d4f803938d7570ef18769ef0925c6b0230",
    "8e2ec16daad6ead3d981ba476ada67936179a72a",
    "aebad8ef398e7d5a69e192547543424931ed38af",
    "40ccecc2bd5d0b35e648f7a5c2d0ed4923fc3b61",
    "146fd7f85f14c4da0a5ce17518f876bdb9c1b21b",
    "2339f6c9319f973b2b2a3b3062d87b5fb29137dc",
    "7236c550c05e8972c7517544d105adea7c957671",
    "b2e7d6000fc5096cf3fb8a1ed00761030b1c073a",
    "3fdc615833da68af22623eefafc876d4c84b86d7",
    "ecc189e8d1ab21ad0c797b3a6009f3f12ac48829",
    "5e0aec37282ec0af9846bb6681aee87d89dabfa3",
    "2b32fc5fe14b5c90db022ed14deca5f572a68040",
    "5a32570a8ec08a2433601dd29ff6ff9c4b31d44d",
    "6b1f1da3359dcca95c8434b73970ba992ef9d41d",
    "e787786f2514c641e02dd5608d0fe21c4476eca4",
    "42b754d75863072e4ad0af32f2667ff54ceb050c",
    "7b549978239455f12620429ffc06a553a1a0dd41",
    "21a0124f6e4b5dfc300b205073e1b464066355e8",
    "750a5456fae988c2595098dcec01f410c8941d4b",
    "43c775969b082397ceb063e7ef929307a72d4b74",
    "618220e106b0bc2eee5faba6485a54dd66a8b7c6",
    "828820da348afc509bc21ebd0b13f1c023563415",
    "a2f7ae2fc4bd1f4fa19839e1021d18cce85ad4fc",
    "2d3221ee54b9277bc3783811f17e12658fb93901",
    "89e047c2416de6924ee4b7aff4daf4250d55f907",
    "25562d1e1ae57bb52a8a0317de8d07a9a1365bef",
    "2cda04bc0ec7aff3192fc65292eb946fb5b57929",
    "aaeeb92b105d3864454b19921eb12de45d9458c0",
    "72fa8610e509de4bff3b20d60d9da19ab312bd3b",
    "44b43411d5156d9a3a08ec0f94b8336c90f6bcb5",
    "0a34796213d5677d9dc77a8b73564004e8e3a2cf",
    "0ec8221e275e36a5917c08a55cde10c36dd0e972",
    "2c676a2f71f33aebcf8b15beec40d868f6e6efd5",
    "f0f8666ab9aa2b68d042207ddb89d47f97ea7146",
    "24b8e4122b6aad37175fc4be3449372abb1eed0d",
    "bbe842a13541386c9e101284cf49ab4df6bca042",
    "2e540d13f1ea31d800a9a6f2f3bca668a23c4013",
    "5f68de9523e6c2ee263452a7c593ad50069a657b",
    "03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b",
    "4db7a975d7af45b96d6f6aaf6beb6f2ca6aa2a34",
    "5389f6a3ab2f28698d423567481ecdc29a260ace",
    "22ddc7237f15758a0c77c72902b51ff25d31e483",
    "e42d1f417a555b17d7476522aa48f7e4d72306b7",
    "4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22",
    "9d33d10ce3b500dfcad818f08de11b324da4bdbb",
    "f5c90bef2c2d4500ff68c014d1385ac37b440f0c",
    "2bb223629c848f298177fc16ec3cac1fa40b8e0f",
    "1ce7f16a52380a6ff1dcd84a4cdca70569cbff75",
    "ed19f3256ac8857367f1f490eb1f5f717e20ca03",
    "e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad",
    "4e628baf043721d0e0ae86290915886cee7e3d5c",
    "cc977e42770e6d88822459436a770295632c6e45",
    "3bf205aeeb87efccddcd7d0db0ffd421d225f8da",
    "a643a7ec42a07de78103872c17cf15be2d5f75cd",
    "d4a3da40b4b6772bb1edcd4583eeb59951d6e7f6",
    "02090c31b6813d6d1691262809dfc86330283a9d",
    "e6b1b323955d81b1b2741cf021247729574ce6af",
    "b3ebcc8329c327731286f70f54ef05fb432120cf",
    "40929cda90c40afbb70d49760a7ec06ab657dc25",
    "78bc231a4b2b429483332ed0bf124289de5276b1",
    "23a3f3ed8fac513f1b7f88962e561cfd376f7ea2",
    "539844ecead1576afd54518bb8db63eb3ec72422",
    "7021150d57aa6ceffec6a69e12cdf12cc88c548f",
    "6ca977f71f19a9b2017bc51922b5fc808a8e5d2c",
    "47f7e111ed3c8f625dad09597af3426f8204930d",
    "374043426b560108b30cb954fc15d658a56631a2",
    "4538fcb184d77f92991063f93dc4d875ba1e870f",
    "900f22179db54b50aba03fba519ac80266519c2d",
    "df2ac4869f4ee15c567f4a5ce1e0a99fab08e269",
    "91858585f8db6fb1b8b50ca0182526fdb653f0bf",
    "e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0",
    "23e28e14cf79e618070d0ea3543bf92910ca9558",
}


def _digest(content: bytes) -> str:
  return trusted.normalized_sha256(content)


def _tree_for_policy(policy: dict[str, Any]) -> dict[str, dict[str, str]]:
  tree: dict[str, dict[str, str]] = {}
  for prefix, paths in policy["protected_inventories"].items():
    if paths:
      tree[prefix[:-1]] = {"mode": "040000", "type": "tree"}
    for path in paths:
      tree[path] = {"mode": "100644", "type": "blob"}
  return tree


def validate_trusted_workflow_structure(
    workflow_data: Any, raw_text: str | None = None
) -> None:
  if raw_text is not None:
    for index, char in enumerate(raw_text):
      code = ord(char)
      if (code < 32 and code not in (10, 13)) or code == 127:
        raise ValueError(
            f"Raw workflow text contains invalid C0 control character 0x{code:02x} at offset {index}"
        )

  if not isinstance(workflow_data, dict):
    raise ValueError("Workflow data must be a dictionary")

  # 1. Strict key type checking (reject boolean keys / YAML key collisions)
  def _check_keys_strict_strings(obj: Any, path: str = "root") -> None:
    if isinstance(obj, dict):
      for key, val in obj.items():
        if not isinstance(key, str):
          raise ValueError(
              f"YAML key collision / non-string key detected at {path}: key {key!r} (type {type(key).__name__}) is not a string"
          )
        _check_keys_strict_strings(val, f"{path}.{key}")
    elif isinstance(obj, list):
      for idx, item in enumerate(obj):
        _check_keys_strict_strings(item, f"{path}[{idx}]")

  _check_keys_strict_strings(workflow_data)

  expected_top_keys = {"name", "on", "permissions", "jobs"}
  actual_top_keys = set(workflow_data.keys())
  if actual_top_keys != expected_top_keys:
    raise ValueError(
        f"Top-level keys must be exactly {sorted(expected_top_keys)}; got {sorted(actual_top_keys)}"
    )

  if workflow_data.get("name") != "Trusted Workflow Policy":
    raise ValueError("Workflow name mismatch")

  # 2. Permissions check
  if workflow_data.get("permissions") != {"contents": "read"}:
    raise ValueError("Permissions must be exactly {'contents': 'read'}")

  # 3. Trigger ('on') block check
  on_block = workflow_data.get("on")
  if not isinstance(on_block, dict):
    raise ValueError("'on' block must be a dictionary")
  if set(on_block.keys()) != {"pull_request_target"}:
    raise ValueError("'on' block keys must be exactly {'pull_request_target'}")

  pr_target = on_block.get("pull_request_target")
  if not isinstance(pr_target, dict):
    raise ValueError("'pull_request_target' must be a dictionary")
  if set(pr_target.keys()) != {"branches", "types"}:
    raise ValueError(
        "'pull_request_target' keys must be exactly {'branches', 'types'} (no paths or paths-ignore)"
    )

  if pr_target.get("branches") != ["main"]:
    raise ValueError("pull_request_target branches must be ['main']")
  if pr_target.get("types") != ["opened", "synchronize", "reopened"]:
    raise ValueError("pull_request_target types mismatch")

  if (
      "paths" in pr_target
      or "paths-ignore" in pr_target
      or "paths" in on_block
      or "paths-ignore" in on_block
  ):
    raise ValueError(
        "pull_request_target must not contain paths or paths-ignore filters"
    )

  # 4. Jobs check
  jobs = workflow_data.get("jobs")
  if not isinstance(jobs, dict) or set(jobs.keys()) != {"verify"}:
    raise ValueError("jobs block must contain exactly one job named 'verify'")

  verify_job = jobs.get("verify")
  if not isinstance(verify_job, dict):
    raise ValueError("'verify' job must be a dictionary")

  expected_verify_keys = {"name", "if", "runs-on", "steps"}
  if set(verify_job.keys()) != expected_verify_keys:
    raise ValueError(
        f"'verify' job keys must be exactly {sorted(expected_verify_keys)}; got {sorted(verify_job.keys())}"
    )

  if (
      verify_job.get("name")
      != "Verify protected files against trusted base policy"
  ):
    raise ValueError("Job name mismatch")

  expected_if = (
      "github.event.pull_request.base.repo.full_name == github.repository && "
      "github.event.pull_request.base.ref =="
      " github.event.repository.default_branch"
  )
  if verify_job.get("if") != expected_if:
    raise ValueError("Job 'if' condition mismatch")

  if verify_job.get("runs-on") != "ubuntu-latest":
    raise ValueError("Job 'runs-on' must be 'ubuntu-latest'")

  steps = verify_job.get("steps")
  if not isinstance(steps, list) or len(steps) != 2:
    raise ValueError(
        f"Job steps must be exactly 2 ordered steps; got {len(steps) if isinstance(steps, list) else type(steps)}"
    )

  step1, step2 = steps[0], steps[1]
  if not isinstance(step1, dict) or not isinstance(step2, dict):
    raise ValueError("Steps must be dictionaries")

  # Step 1 (Checkout) check
  if set(step1.keys()) != {"name", "uses", "with"}:
    raise ValueError(
        f"Step 1 keys must be exactly {{'name', 'uses', 'with'}}; got {set(step1.keys())}"
    )
  if step1.get("name") != "Checkout trusted policy from the PR base SHA":
    raise ValueError("Step 1 name mismatch")

  expected_uses = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
  if step1.get("uses") != expected_uses:
    raise ValueError(f"Step 1 uses must be pinned action SHA {expected_uses!r}")

  with1 = step1.get("with")
  if not isinstance(with1, dict):
    raise ValueError("Step 1 'with' block must be a dictionary")

  expected_with1_keys = {
      "ref",
      "persist-credentials",
      "sparse-checkout",
      "sparse-checkout-cone-mode",
  }
  if set(with1.keys()) != expected_with1_keys:
    raise ValueError(
        f"Step 1 'with' keys must be exactly {sorted(expected_with1_keys)}; got {sorted(with1.keys())}"
    )

  if with1.get("ref") != "${{ github.event.pull_request.base.sha }}":
    raise ValueError(
        "Step 1 ref must be exact base SHA"
        " '${{ github.event.pull_request.base.sha }}'"
    )
  if with1.get("persist-credentials") is not False:
    raise ValueError("Step 1 persist-credentials must be False")
  if with1.get("sparse-checkout-cone-mode") is not False:
    raise ValueError("Step 1 sparse-checkout-cone-mode must be False")

  sparse_raw = str(with1.get("sparse-checkout", ""))
  sparse_lines = [
      line.strip() for line in sparse_raw.strip().splitlines() if line.strip()
  ]
  expected_sparse = [
      ".github/workflow-policy/trusted_workflow_policy.json",
      "scripts/verify_trusted_workflow_policy.py",
  ]
  if sparse_lines != expected_sparse:
    raise ValueError(
        f"Step 1 sparse-checkout paths must be exactly {expected_sparse}; got {sparse_lines}"
    )

  # Step 2 (Verifier) check
  if set(step2.keys()) != {"name", "env", "run"}:
    raise ValueError(
        f"Step 2 keys must be exactly {{'name', 'env', 'run'}}; got {set(step2.keys())}"
    )
  if step2.get("name") != "Verify candidate files as inert GitHub API bytes":
    raise ValueError("Step 2 name mismatch")

  env2 = step2.get("env")
  if not isinstance(env2, dict):
    raise ValueError("Step 2 'env' block must be a dictionary")

  expected_env_keys = {
      "GITHUB_TOKEN",
      "GITHUB_API_URL",
      "CANDIDATE_REPOSITORY",
      "CANDIDATE_SHA",
  }
  if set(env2.keys()) != expected_env_keys:
    raise ValueError(
        f"Step 2 env keys must be exactly {sorted(expected_env_keys)}; got {sorted(env2.keys())}"
    )

  if env2.get("GITHUB_TOKEN") != "${{ github.token }}":
    raise ValueError("Step 2 GITHUB_TOKEN mismatch")
  if env2.get("GITHUB_API_URL") != "${{ github.api_url }}":
    raise ValueError("Step 2 GITHUB_API_URL mismatch")
  if (
      env2.get("CANDIDATE_REPOSITORY")
      != "${{ github.event.pull_request.head.repo.full_name }}"
  ):
    raise ValueError("Step 2 CANDIDATE_REPOSITORY mismatch")
  if env2.get("CANDIDATE_SHA") != "${{ github.event.pull_request.head.sha }}":
    raise ValueError("Step 2 CANDIDATE_SHA mismatch")

  # --- EXACT NON-LOSSY PARSED RUN VALIDATION WITH CR/LF/TAB/SPACE REJECTION ---
  run_cmd = step2.get("run")
  if not isinstance(run_cmd, str):
    raise ValueError("Step 2 run must be a string")

  if "\r" in run_cmd:
    raise ValueError("Step 2 run command contains bare CR or CRLF newline")
  if "\n" in run_cmd:
    raise ValueError("Step 2 run command contains LF newline")
  if "\t" in run_cmd:
    raise ValueError("Step 2 run command contains tab character")
  if "  " in run_cmd:
    raise ValueError("Step 2 run command contains multiple consecutive spaces")
  if "${{" in run_cmd or "github.event.pull_request" in run_cmd:
    raise ValueError(
        "Step 2 run command contains unquoted expression or PR-title execution"
    )

  expected_run_cmd = (
      "python scripts/verify_trusted_workflow_policy.py "
      "--policy .github/workflow-policy/trusted_workflow_policy.json "
      '--candidate-repository "$CANDIDATE_REPOSITORY" '
      '--candidate-ref "$CANDIDATE_SHA" '
      '--api-url "$GITHUB_API_URL"'
  )
  if run_cmd != expected_run_cmd:
    raise ValueError(
        f"Step 2 run command mismatch: expected {expected_run_cmd!r}, got {run_cmd!r}"
    )


class TrustedWorkflowPolicyTest(unittest.TestCase):
  def assert_current_main_baseline_is_exact(self, policy):
    self.assertEqual(policy["format_version"], 3)
    self.assertEqual(policy["protected_paths"], list(MERGED_MAIN_DIGESTS))
    self.assertEqual(len(policy["protected_paths"]), 102)
    self.assertEqual(
        policy["protected_inventories"],
        {
            ".github/actions/": [],
            ".github/workflows/": CURRENT_WORKFLOW_PATHS,
        },
    )
    self.assertEqual(len(policy["approved_bundles"]), 1)
    persistent = policy["approved_bundles"][0]
    self.assertEqual(persistent["id"], EXPECTED_BUNDLE_ID)
    self.assertEqual(persistent["mode"], "persistent-baseline")
    expected_source = {
        "repository": "ks-house/smart-gatekeeper",
        "commit": MERGED_MAIN_COMMIT,
    }
    self.assertEqual(persistent["source"], expected_source)
    self.assertEqual(persistent["files"], MERGED_MAIN_DIGESTS)
    self.assertEqual(list(persistent["files"]), policy["protected_paths"])

  def setUp(self):
    self.main_files = {
        "workflow.yml": b"name: main\r\n",
        "gate.py": b"print('main')\n",
    }
    self.alternate_files = {
        "workflow.yml": b"name: alternate\n",
        "gate.py": b"print('alternate')\n",
    }
    self.policy = {
        "format_version": 3,
        "normalization": trusted.NORMALIZATION,
        "protected_paths": list(self.main_files),
        "protected_inventories": {
            ".github/actions/": [],
            ".github/workflows/": [],
        },
        "approved_bundles": [
            {
                "id": "main",
                "mode": "persistent-baseline",
                "source": {
                    "repository": "owner/repository",
                    "commit": "1" * 40,
                },
                "files": {
                    path: _digest(content)
                    for path, content in self.main_files.items()
                },
            },
            {
                "id": "alternate",
                "mode": "temporary-exact",
                "source": {
                    "repository": "owner/repository",
                    "commit": "2" * 40,
                },
                "files": {
                    path: _digest(content)
                    for path, content in self.alternate_files.items()
                },
            },
        ],
    }

  def verify(
      self,
      files,
      repository="owner/repository",
      ref="3" * 40,
  ):
    return trusted.verify_candidate(
        self.policy,
        repository,
        ref,
        files.__getitem__,
        lambda: {},
        lambda ancestor, descendant: (
            ancestor == descendant or descendant in {"3" * 40, "f" * 40}
        ),
    )

  def test_exact_main_bundle_is_approved(self):
    bundle = self.verify(self.main_files)
    self.assertEqual(bundle["id"], "main")

  def test_exact_alternate_bundle_is_approved(self):
    bundle = self.verify(self.alternate_files, ref="2" * 40)
    self.assertEqual(bundle["id"], "alternate")

  def test_exact_temporary_precedes_same_byte_persistent_baseline(self):
    policy = copy.deepcopy(self.policy)
    policy["approved_bundles"][1]["files"] = copy.deepcopy(
        policy["approved_bundles"][0]["files"]
    )
    ancestry = mock.Mock(return_value=True)
    bundle = trusted.verify_candidate(
        policy,
        "owner/repository",
        "2" * 40,
        self.main_files.__getitem__,
        lambda: {},
        ancestry,
    )
    self.assertEqual(bundle["id"], "alternate")
    ancestry.assert_not_called()

  def test_persistent_baseline_accepts_later_same_repository_commit_only(self):
    for ref in ("1" * 40, "3" * 40, "f" * 40):
      with self.subTest(ref=ref):
        self.assertEqual(self.verify(self.main_files, ref=ref)["id"], "main")
    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify(self.main_files, repository="attacker/fork")

  def test_persistent_baseline_requires_proven_descendant(self):
    with self.assertRaisesRegex(trusted.PolicyError, "ancestry verification"):
      trusted.verify_candidate(
          self.policy,
          "owner/repository",
          "3" * 40,
          self.main_files.__getitem__,
          lambda: {},
      )
    ancestry = mock.Mock(return_value=False)
    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      trusted.verify_candidate(
          self.policy,
          "owner/repository",
          "3" * 40,
          self.main_files.__getitem__,
          lambda: {},
          ancestry,
      )
    ancestry.assert_called_once_with("1" * 40, "3" * 40)

  def test_github_compare_requires_ahead_status_and_exact_merge_base(self):
    ancestor = "1" * 40
    descendant = "3" * 40
    fetcher = trusted.GitHubContentsFetcher(
        "https://api.github.com", "owner/repository", descendant, "token"
    )
    valid = {
        "status": "ahead",
        "merge_base_commit": {"sha": ancestor},
        "base_commit": {"sha": ancestor},
    }
    cases = (
        (valid, True),
        ({**valid, "status": "behind"}, False),
        ({**valid, "status": "diverged"}, False),
        ({**valid, "merge_base_commit": {"sha": "2" * 40}}, False),
        ({**valid, "base_commit": {"sha": "2" * 40}}, False),
        ({"status": "ahead"}, False),
    )
    for payload, expected in cases:
      response = mock.MagicMock()
      response.__enter__.return_value.read.return_value = json.dumps(
          payload
      ).encode("utf-8")
      with self.subTest(payload=payload), mock.patch.object(
          trusted.urllib.request, "urlopen", return_value=response
      ) as urlopen:
        self.assertEqual(fetcher.is_descendant(ancestor, descendant), expected)
        request = urlopen.call_args.args[0]
        self.assertIn(f"/compare/{ancestor}...{descendant}", request.full_url)

    with mock.patch.object(trusted.urllib.request, "urlopen") as urlopen:
      self.assertTrue(fetcher.is_descendant(ancestor, ancestor))
      urlopen.assert_not_called()

  def test_github_recursive_tree_is_bound_to_candidate_sha_and_fail_closed(self):
    candidate_ref = "3" * 40
    fetcher = trusted.GitHubContentsFetcher(
        "https://api.github.com", "owner/repository", candidate_ref, "token"
    )
    payload = {
        "sha": "4" * 40,
        "truncated": False,
        "tree": [
            {
                "path": ".github/workflows",
                "mode": "040000",
                "type": "tree",
                "sha": "5" * 40,
            },
            {
                "path": ".github/workflows/current.yml",
                "mode": "100644",
                "type": "blob",
                "sha": "6" * 40,
            },
        ],
    }
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode(
        "utf-8"
    )
    with mock.patch.object(
        trusted.urllib.request, "urlopen", return_value=response
    ) as urlopen:
      self.assertEqual(
          fetcher.fetch_tree(),
          {
              ".github/workflows": {"mode": "040000", "type": "tree"},
              ".github/workflows/current.yml": {
                  "mode": "100644",
                  "type": "blob",
              },
          },
      )
      request = urlopen.call_args.args[0]
      self.assertIn(
          f"/repos/owner/repository/git/trees/{candidate_ref}?recursive=1",
          request.full_url,
      )

    for mutation in (
        {**payload, "truncated": True},
        {**payload, "truncated": None},
        {**payload, "tree": "not-a-list"},
        {
            **payload,
            "tree": [
                {
                    "path": ".github/workflows/current.yml",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "BAD",
                }
            ],
        },
    ):
      bad_response = mock.MagicMock()
      bad_response.__enter__.return_value.read.return_value = json.dumps(
          mutation
      ).encode("utf-8")
      with self.subTest(mutation=mutation), mock.patch.object(
          trusted.urllib.request, "urlopen", return_value=bad_response
      ):
        with self.assertRaises(trusted.PolicyError):
          fetcher.fetch_tree()

  def test_inventory_rejects_added_removed_renamed_and_non_regular_files(self):
    workflow_path = ".github/workflows/current.yml"
    workflow_content = b"name: current\n"
    policy = copy.deepcopy(self.policy)
    policy["protected_paths"].append(workflow_path)
    policy["protected_inventories"][".github/workflows/"] = [workflow_path]
    for bundle in policy["approved_bundles"]:
      bundle["files"][workflow_path] = _digest(workflow_content)
    trusted.validate_policy(policy)
    files = {**self.main_files, workflow_path: workflow_content}
    valid_tree = {
        ".github/workflows": {"mode": "040000", "type": "tree"},
        workflow_path: {"mode": "100644", "type": "blob"},
    }

    def verify_tree(tree):
      return trusted.verify_candidate(
          policy,
          "owner/repository",
          "3" * 40,
          files.__getitem__,
          lambda: tree,
          lambda _ancestor, _descendant: True,
      )

    self.assertEqual(verify_tree(valid_tree)["id"], "main")
    mutations = {
        "added": {
            **valid_tree,
            ".github/workflows/evil.yml": {
                "mode": "100644",
                "type": "blob",
            },
        },
        "removed": {
            ".github/workflows": {"mode": "040000", "type": "tree"},
        },
        "renamed": {
            ".github/workflows": {"mode": "040000", "type": "tree"},
            ".github/workflows/renamed.yml": {
                "mode": "100644",
                "type": "blob",
            },
        },
        "executable": {
            **valid_tree,
            workflow_path: {"mode": "100755", "type": "blob"},
        },
        "symlink": {
            **valid_tree,
            workflow_path: {"mode": "120000", "type": "blob"},
        },
        "submodule": {
            **valid_tree,
            workflow_path: {"mode": "160000", "type": "commit"},
        },
        "namespace-root-blob": {
            ".github/workflows": {"mode": "100644", "type": "blob"},
            workflow_path: {"mode": "100644", "type": "blob"},
        },
        "case-escape": {
            ".github/workflows": {"mode": "040000", "type": "tree"},
            ".github/Workflows/current.yml": {
                "mode": "100644",
                "type": "blob",
            },
        },
        "dot-segment": {
            **valid_tree,
            ".github/workflows/../evil.yml": {
                "mode": "100644",
                "type": "blob",
            },
        },
        "new-action": {
            **valid_tree,
            ".github/actions/evil/action.yml": {
                "mode": "100644",
                "type": "blob",
            },
        },
    }
    for label, tree in mutations.items():
      with self.subTest(label=label), self.assertRaises(trusted.PolicyError):
        verify_tree(tree)

  def test_policy_requires_exact_inventory_namespaces_and_protection(self):
    mutations = []
    old_format = copy.deepcopy(self.policy)
    old_format["format_version"] = 2
    mutations.append(old_format)

    missing_namespace = copy.deepcopy(self.policy)
    del missing_namespace["protected_inventories"][".github/actions/"]
    mutations.append(missing_namespace)

    extra_namespace = copy.deepcopy(self.policy)
    extra_namespace["protected_inventories"][".github/dependabot/"] = []
    mutations.append(extra_namespace)

    unprotected_inventory_file = copy.deepcopy(self.policy)
    unprotected_inventory_file["protected_inventories"][
        ".github/workflows/"
    ] = [".github/workflows/unprotected.yml"]
    mutations.append(unprotected_inventory_file)

    for index, mutation in enumerate(mutations):
      with self.subTest(index=index), self.assertRaises(trusted.PolicyError):
        trusted.validate_policy(mutation)

  def test_line_endings_are_normalized_but_other_bytes_are_exact(self):
    self.assertEqual(_digest(b"a\r\nb\r"), _digest(b"a\nb\n"))
    self.assertNotEqual(_digest(b"a\nb\n"), _digest(b"a\nb\n "))

  def test_arbitrary_byte_change_is_rejected(self):
    changed = dict(self.main_files)
    changed["gate.py"] += b"# attacker\n"
    with self.assertRaisesRegex(trusted.PolicyError, "gate.py"):
      self.verify(changed)

  def test_mixed_approved_bundles_are_rejected(self):
    mixed = {
        "workflow.yml": self.main_files["workflow.yml"],
        "gate.py": self.alternate_files["gate.py"],
    }
    with self.assertRaisesRegex(trusted.PolicyError, "not an approved bundle"):
      self.verify(mixed)

  def test_missing_protected_file_is_rejected(self):
    with self.assertRaises(KeyError):
      self.verify({"workflow.yml": b"x"})

  def test_pr_side_policy_change_cannot_change_current_decision(self):
    candidate_tree = dict(self.main_files)
    policy_path = ".github/workflow-policy/trusted_workflow_policy.json"
    candidate_tree[policy_path] = json.dumps(
        {"approved_bundles": [{"files": {"gate.py": "0" * 64}}]}
    ).encode()
    requested_paths = []

    def fetch(path):
      requested_paths.append(path)
      return candidate_tree[path]

    bundle = trusted.verify_candidate(
        copy.deepcopy(self.policy),
        "owner/repository",
        "3" * 40,
        fetch,
        lambda: {},
        lambda _ancestor, _descendant: True,
    )
    self.assertEqual(bundle["id"], "main")
    self.assertEqual(requested_paths, self.policy["protected_paths"])
    self.assertNotIn(policy_path, requested_paths)

  def test_pr_side_policy_cannot_bless_a_modified_protected_file(self):
    candidate_tree = dict(self.main_files)
    candidate_tree["gate.py"] += b"# attacker\n"
    candidate_tree[".github/workflow-policy/trusted_workflow_policy.json"] = (
        json.dumps(
            {
                "approved_bundles": [
                    {"files": {"gate.py": _digest(candidate_tree["gate.py"])}}
                ]
            }
        ).encode()
    )
    with self.assertRaisesRegex(trusted.PolicyError, "gate.py"):
      trusted.verify_candidate(
          copy.deepcopy(self.policy),
          "owner/repository",
          "3" * 40,
          candidate_tree.__getitem__,
          lambda: {},
          lambda _ancestor, _descendant: True,
      )

  def test_policy_requires_exact_file_set_for_every_bundle(self):
    policy = copy.deepcopy(self.policy)
    del policy["approved_bundles"][0]["files"]["gate.py"]
    with self.assertRaisesRegex(trusted.PolicyError, "protected_paths exactly"):
      trusted.validate_policy(policy)

  def test_policy_rejects_unknown_fields(self):
    policy = copy.deepcopy(self.policy)
    policy["allow_candidate_policy_override"] = True
    with self.assertRaisesRegex(trusted.PolicyError, "keys must be exactly"):
      trusted.validate_policy(policy)

  def test_policy_rejects_mode_identity_and_path_schema_mutations(self):
    mutations = []

    missing_mode = copy.deepcopy(self.policy)
    del missing_mode["approved_bundles"][0]["mode"]
    mutations.append(missing_mode)

    invalid_mode = copy.deepcopy(self.policy)
    invalid_mode["approved_bundles"][0]["mode"] = "branch-or-wildcard"
    mutations.append(invalid_mode)

    duplicate_identity = copy.deepcopy(self.policy)
    duplicate_identity["approved_bundles"][1]["mode"] = "persistent-baseline"
    duplicate_identity["approved_bundles"][1]["source"] = copy.deepcopy(
        duplicate_identity["approved_bundles"][0]["source"]
    )
    mutations.append(duplicate_identity)

    duplicate_persistent_repository = copy.deepcopy(self.policy)
    duplicate_persistent_repository["approved_bundles"].append(
        copy.deepcopy(duplicate_persistent_repository["approved_bundles"][0])
    )
    duplicate_persistent_repository["approved_bundles"][2]["id"] = "later-main"
    duplicate_persistent_repository["approved_bundles"][2]["source"][
        "commit"
    ] = "4" * 40
    mutations.append(duplicate_persistent_repository)

    for path_variant in (
        "Workflow.yml",
        "workflow.yml/../gate.py",
        "workflow.yml\\gate.py",
        "workflow.yml//gate.py",
        "/workflow.yml",
    ):
      mutated = copy.deepcopy(self.policy)
      if path_variant == "Workflow.yml":
        mutated["protected_paths"].append(path_variant)
        mutated["approved_bundles"][0]["files"][path_variant] = "0" * 64
        mutated["approved_bundles"][1]["files"][path_variant] = "0" * 64
      else:
        old_path = mutated["protected_paths"][0]
        mutated["protected_paths"][0] = path_variant
        for bundle in mutated["approved_bundles"]:
          bundle["files"][path_variant] = bundle["files"].pop(old_path)
      mutations.append(mutated)

    for index, mutated in enumerate(mutations):
      with self.subTest(index=index):
        with self.assertRaises(trusted.PolicyError):
          trusted.validate_policy(mutated)

  def test_runtime_rejects_missing_malformed_case_and_wrong_identity(self):
    fetch = mock.Mock(side_effect=self.main_files.__getitem__)
    invalid = (
        (None, "3" * 40),
        ("owner/repository", None),
        ("Owner/repository", "3" * 40),
        ("owner/repository/extra", "3" * 40),
        ("owner//repository", "3" * 40),
        ("../repository", "3" * 40),
        ("owner/..", "3" * 40),
        ("owner/repository", "3" * 39),
        ("owner/repository", "A" * 40),
        ("owner/repository", "refs/heads/main"),
    )
    for repository, ref in invalid:
      with self.subTest(repository=repository, ref=ref):
        fetch.reset_mock()
        with self.assertRaises(trusted.PolicyError):
          trusted.verify_candidate(self.policy, repository, ref, fetch, lambda: {})
        fetch.assert_not_called()

  def test_cli_rejects_missing_and_duplicate_candidate_identity(self):
    common = ["verify", "--policy", "policy.json"]
    cases = (
        common + ["--candidate-ref", "1" * 40],
        common + ["--candidate-repository", "owner/repository"],
        common + [
            "--candidate-repository", "owner/repository",
            "--candidate-repository", "attacker/fork",
            "--candidate-ref", "1" * 40,
        ],
        common + [
            "--candidate-repository", "owner/repository",
            "--candidate-ref", "1" * 40,
            "--candidate-ref", "2" * 40,
        ],
    )
    for argv in cases:
      with self.subTest(argv=argv), mock.patch.object(sys, "argv", argv):
        with contextlib.redirect_stderr(io.StringIO()):
          with self.assertRaises(SystemExit):
            trusted.parse_args()

  def verify_merged_main_digest_map(
      self,
      policy,
      digests,
      repository="ks-house/smart-gatekeeper",
      ref=MERGED_MAIN_COMMIT,
      is_descendant=None,
  ):
    if is_descendant is None:
      is_descendant = lambda ancestor, descendant: (
          ancestor == descendant and descendant == MERGED_MAIN_COMMIT
      )
    with mock.patch.object(
        trusted,
        "normalized_sha256",
        side_effect=lambda content: content.decode("ascii"),
    ):
      return trusted.verify_candidate(
          policy,
          repository,
          ref,
          lambda path: digests[path].encode("ascii"),
          lambda: _tree_for_policy(policy),
          is_descendant,
      )

  def test_final_rotation_has_one_current_main_baseline(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assert_current_main_baseline_is_exact(policy)
    ancestry = mock.Mock(return_value=True)
    bundle = self.verify_merged_main_digest_map(
        policy, MERGED_MAIN_DIGESTS, is_descendant=ancestry
    )
    self.assertEqual(bundle["id"], EXPECTED_BUNDLE_ID)
    ancestry.assert_called_once_with(MERGED_MAIN_COMMIT, MERGED_MAIN_COMMIT)
    self.assertEqual(
        {"persistent-baseline"},
        {approved["mode"] for approved in policy["approved_bundles"]},
    )

  def test_current_workflow_inventory_and_candidate_digests_are_coherent(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    actual_workflows = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / ".github/workflows").rglob("*")
        if path.is_file()
    )
    self.assertEqual(actual_workflows, CURRENT_WORKFLOW_PATHS)
    actions_root = ROOT / ".github/actions"
    actual_actions = (
        sorted(
            path.relative_to(ROOT).as_posix()
            for path in actions_root.rglob("*")
            if path.is_file()
        )
        if actions_root.exists()
        else []
    )
    self.assertEqual(
        policy["protected_inventories"][".github/actions/"],
        actual_actions,
    )
    self.assertEqual(
        policy["protected_paths"][10:],
        list(MERGED_MAIN_DIGESTS)[10:],
    )
    protected = policy["approved_bundles"][0]["files"]
    locally_unchanged_protected = [
        path
        for path in policy["protected_paths"]
        if path not in FEATURE_CHANGED_PROTECTED_PATHS
    ]
    self.assertEqual(len(FEATURE_CHANGED_PROTECTED_PATHS), 16)
    self.assertEqual(len(locally_unchanged_protected), 86)
    for path in locally_unchanged_protected:
      with self.subTest(path=path):
        self.assertIn(path, policy["protected_paths"])
        self.assertEqual(
          protected[path],
          trusted.normalized_sha256((ROOT / path).read_bytes()),
        )
    candidate_matches = []
    for path in FEATURE_CHANGED_PROTECTED_PATHS:
      local_path = ROOT / path
      candidate_matches.append(
          local_path.exists()
          and protected[path] == trusted.normalized_sha256(local_path.read_bytes())
      )
    self.assertTrue(
        all(candidate_matches) or not any(candidate_matches),
        "candidate protected bytes must be wholly policy-only or wholly merge-connected",
    )

  def test_publisher_requirements_lock_cannot_be_removed_or_modified(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    lock_path = "ota/requirements.lock"

    removed = copy.deepcopy(policy)
    removed["protected_paths"].remove(lock_path)
    for bundle in removed["approved_bundles"]:
      del bundle["files"][lock_path]
    trusted.validate_policy(removed)
    with self.assertRaises(AssertionError):
      self.assert_current_main_baseline_is_exact(removed)

    modified = dict(MERGED_MAIN_DIGESTS)
    modified[lock_path] = "0" * 64
    with self.assertRaisesRegex(trusted.PolicyError, lock_path):
      self.verify_merged_main_digest_map(policy, modified)

  def test_current_main_baseline_accepts_only_proven_descendant(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    future_ref = "a" * 40
    ancestry = mock.Mock(
        side_effect=lambda ancestor, descendant: (
            ancestor == MERGED_MAIN_COMMIT and descendant == future_ref
        )
    )
    bundle = self.verify_merged_main_digest_map(
        policy,
        MERGED_MAIN_DIGESTS,
        ref=future_ref,
        is_descendant=ancestry,
    )
    self.assertEqual(bundle["id"], EXPECTED_BUNDLE_ID)
    ancestry.assert_called_once_with(MERGED_MAIN_COMMIT, future_ref)

    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify_merged_main_digest_map(
          policy,
          MERGED_MAIN_DIGESTS,
          ref="bbe842a13541386c9e101284cf49ab4df6bca042",
          is_descendant=lambda _ancestor, _descendant: False,
      )

  def test_merged_main_source_forks_divergence_and_old_commits_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assert_current_main_baseline_is_exact(policy)
    mutations = [("repository", "attacker/fork"), ("commit", "f" * 40)]
    mutations.extend(("commit", commit) for commit in RETIRED_SOURCE_COMMITS)
    for field, value in mutations:
      with self.subTest(field=field, value=value):
        mutated = copy.deepcopy(policy)
        mutated["approved_bundles"][0]["source"][field] = value
        trusted.validate_policy(mutated)
        with self.assertRaises(AssertionError):
          self.assert_current_main_baseline_is_exact(mutated)

    runtime_identities = [
        ("attacker/fork", MERGED_MAIN_COMMIT),
        ("KS-HOUSE/smart-gatekeeper", MERGED_MAIN_COMMIT),
        ("ks-house/SMART-GATEKEEPER", MERGED_MAIN_COMMIT),
        ("ks-house/smart-gatekeeper", "f" * 40),
    ]
    runtime_identities.extend(
        ("ks-house/smart-gatekeeper", commit)
        for commit in RETIRED_SOURCE_COMMITS
    )
    for repository, ref in runtime_identities:
      with self.subTest(repository=repository, ref=ref):
        with self.assertRaisesRegex(
            trusted.PolicyError, "source repository/ref"
        ):
          self.verify_merged_main_digest_map(
              policy,
              MERGED_MAIN_DIGESTS,
              repository=repository,
              ref=ref,
              is_descendant=lambda _ancestor, _descendant: False,
          )

    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify_merged_main_digest_map(
          policy,
          MERGED_MAIN_DIGESTS,
          ref="a" * 40,
          is_descendant=lambda _ancestor, _descendant: False,
      )

  def test_merged_main_missing_partial_old_and_reordered_paths_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    deploy_path = policy["protected_paths"][0]

    missing_file = copy.deepcopy(policy)
    del missing_file["approved_bundles"][0]["files"][deploy_path]
    with self.assertRaisesRegex(trusted.PolicyError, "protected_paths exactly"):
      trusted.validate_policy(missing_file)

    partial = copy.deepcopy(policy)
    partial["protected_paths"] = OLD_FIVE_PATHS
    partial["protected_inventories"][".github/workflows/"] = sorted(
        path for path in OLD_FIVE_PATHS if path.startswith(".github/workflows/")
    )
    for bundle in partial["approved_bundles"]:
      bundle["files"] = {
          path: MERGED_MAIN_DIGESTS[path] for path in OLD_FIVE_PATHS
      }
    trusted.validate_policy(partial)
    with self.assertRaises(AssertionError):
      self.assert_current_main_baseline_is_exact(partial)

    reordered = copy.deepcopy(policy)
    reordered["protected_paths"][5], reordered["protected_paths"][6] = (
        reordered["protected_paths"][6],
        reordered["protected_paths"][5],
    )
    trusted.validate_policy(reordered)
    with self.assertRaises(AssertionError):
      self.assert_current_main_baseline_is_exact(reordered)

  def test_merged_main_swapped_mixed_partial_and_digest_mutations_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    deploy_path = ".github/workflows/deploy.yml"
    build_path = ".github/workflows/build_app.yml"

    swapped = dict(MERGED_MAIN_DIGESTS)
    swapped[deploy_path], swapped[build_path] = (
        swapped[build_path],
        swapped[deploy_path],
    )
    with self.assertRaises(trusted.PolicyError):
      self.verify_merged_main_digest_map(policy, swapped)

    mixed = dict(MERGED_MAIN_DIGESTS)
    mixed.update(RETIRED_MAIN_SAMPLE_DIGESTS)
    with self.assertRaises(trusted.PolicyError):
      self.verify_merged_main_digest_map(policy, mixed)

    partial = dict(MERGED_MAIN_DIGESTS)
    del partial["backend/app/main.py"]
    with self.assertRaises(KeyError):
      self.verify_merged_main_digest_map(policy, partial)

    for path in policy["protected_paths"]:
      with self.subTest(path=path):
        changed = dict(MERGED_MAIN_DIGESTS)
        changed[path] = "0" * 64
        with self.assertRaises(trusted.PolicyError):
          self.verify_merged_main_digest_map(policy, changed)

  def test_merged_main_policy_digest_or_extra_bundle_cannot_expand_authorization(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    mutated = copy.deepcopy(policy)
    mutated["approved_bundles"][0]["files"]["backend/app/main.py"] = "0" * 64
    trusted.validate_policy(mutated)
    with self.assertRaises(AssertionError):
      self.assert_current_main_baseline_is_exact(mutated)
    with self.assertRaises(trusted.PolicyError):
      self.verify_merged_main_digest_map(mutated, MERGED_MAIN_DIGESTS)

    extra = copy.deepcopy(policy)
    extra["approved_bundles"].append({
        "id": "unauthorized-second-bundle",
        "mode": "temporary-exact",
        "source": {
            "repository": "ks-house/smart-gatekeeper",
            "commit": "f" * 40,
        },
        "files": dict(MERGED_MAIN_DIGESTS),
    })
    trusted.validate_policy(extra)
    with self.assertRaises(AssertionError):
      self.assert_current_main_baseline_is_exact(extra)


class TrustedWorkflowStructureTest(unittest.TestCase):
  def setUp(self):
    self.workflow_path = ROOT / ".github/workflows/trusted_workflow_policy.yml"
    self.workflow_text = self.workflow_path.read_text(encoding="utf-8")
    self.workflow_data = yaml.safe_load(self.workflow_text)

  def test_current_workflow_matches_strict_policy(self):
    validate_trusted_workflow_structure(self.workflow_data, self.workflow_text)

  def test_no_paths_or_paths_ignore_suppression(self):
    on_block = self.workflow_data.get("on")
    self.assertIsNotNone(on_block, "Workflow must have an 'on' trigger block")
    pr_target = on_block.get("pull_request_target")
    self.assertIsNotNone(
        pr_target, "Workflow must trigger on pull_request_target"
    )
    self.assertNotIn(
        "paths", pr_target, "pull_request_target must not have a paths filter"
    )
    self.assertNotIn(
        "paths-ignore",
        pr_target,
        "pull_request_target must not have a paths-ignore filter",
    )

  def test_rejects_lf_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\n--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "LF newline"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_crlf_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\r\n--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "bare CR or CRLF"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_bare_cr_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\r--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "bare CR or CRLF"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_tab_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python\tscripts/verify_trusted_workflow_policy.py --policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "tab character"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_multiple_spaces_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python  scripts/verify_trusted_workflow_policy.py --policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "multiple consecutive spaces"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_sparse_checkout_mutation_dot(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][0]["with"]["sparse-checkout"] = "."
    with self.assertRaisesRegex(
        ValueError, "Step 1 sparse-checkout paths must be exactly"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_pr_title_execution(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "echo ${{ github.event.pull_request.title }}"
    )
    with self.assertRaisesRegex(
        ValueError, "unquoted expression or PR-title execution"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_extra_checkout_or_execution_steps(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"].append({
        "name": "Candidate execution step",
        "run": "python candidate.py",
    })
    with self.assertRaisesRegex(
        ValueError, "Job steps must be exactly 2 ordered steps"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_yaml_boolean_string_key_collision(self):
    mutated = {
        True: {
            "pull_request_target": {
                "branches": ["main"],
                "types": ["opened", "synchronize", "reopened"],
            }
        },
        "name": "Trusted Workflow Policy",
        "permissions": {"contents": "read"},
        "jobs": self.workflow_data["jobs"],
    }
    with self.assertRaisesRegex(
        ValueError, "YAML key collision / non-string key detected"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_unsafe_yaml_tags(self):
    unsafe_yaml = """
name: Trusted Workflow Policy
'on':
  pull_request_target:
    branches: [main]
    types: [opened, synchronize, reopened]
permissions:
  contents: read
jobs:
  verify: !!python/object/apply:os.system ["echo hack"]
"""
    with self.assertRaises((yaml.YAMLError, ValueError)):
      parsed = yaml.safe_load(unsafe_yaml)
      validate_trusted_workflow_structure(parsed, unsafe_yaml)

  def test_rejects_unexpected_jobs_steps_env_permissions(self):
    mutated1 = copy.deepcopy(self.workflow_data)
    mutated1["permissions"] = {"contents": "write"}
    with self.assertRaisesRegex(ValueError, "Permissions must be exactly"):
      validate_trusted_workflow_structure(mutated1)

    mutated2 = copy.deepcopy(self.workflow_data)
    mutated2["jobs"]["extra_job"] = {}
    with self.assertRaisesRegex(
        ValueError, "jobs block must contain exactly one job named 'verify'"
    ):
      validate_trusted_workflow_structure(mutated2)

    mutated3 = copy.deepcopy(self.workflow_data)
    mutated3["jobs"]["verify"]["steps"][1]["env"]["UNEXPECTED_ENV"] = "BAD"
    with self.assertRaisesRegex(ValueError, "Step 2 env keys must be exactly"):
      validate_trusted_workflow_structure(mutated3)

    mutated4 = copy.deepcopy(self.workflow_data)
    mutated4["jobs"]["verify"]["steps"][0]["extra_key"] = "bad"
    with self.assertRaisesRegex(ValueError, "Step 1 keys must be exactly"):
      validate_trusted_workflow_structure(mutated4)

  def test_c0_control_regression_wiki_log(self):
    log_path = ROOT / "wiki/log.md"
    log_bytes = log_path.read_bytes()

    try:
      log_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
      self.fail(f"wiki/log.md is not valid UTF-8: {err}")

    c0_bad = [
        (idx, byte)
        for idx, byte in enumerate(log_bytes)
        if (byte < 32 and byte not in (9, 10, 13)) or byte == 127
    ]
    self.assertEqual(
        c0_bad,
        [],
        f"wiki/log.md contains C0 control character regressions: {c0_bad}",
    )


if __name__ == "__main__":
  unittest.main()
