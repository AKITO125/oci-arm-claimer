#!/usr/bin/env python3
"""
OCI Free Tier ARM Instance Auto-Claimer (Multi-Account)

複数の OCI アカウントで並行して Always Free ARM インスタンス
（VM.Standard.A1.Flex, 4 OCPU, 24 GB）を申請します。
取得成功したアカウントは申請を停止し、Discord に通知します。
全アカウントが成功または永続的に失敗した時点でプログラムが終了します。
"""

from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import tempfile

import aiohttp
import oci
import yaml
from dotenv import load_dotenv

load_dotenv()

# ── グローバル設定（.env から読み込み） ──────────────────────────────────────────
DISCORD_WEBHOOK_URL: str = os.environ.get("DISCORD_WEBHOOK_URL", "")
RETRY_INTERVAL: int = int(os.environ.get("RETRY_INTERVAL_SECONDS", "300"))
SSH_PUBLIC_KEY: str = os.environ.get("SSH_PUBLIC_KEY", "")
DEFAULT_INSTANCE_NAME: str = os.environ.get("INSTANCE_NAME", "arm-free-instance")

SHAPE = "VM.Standard.A1.Flex"
OCPUS = 4
MEMORY_GB = 24

_executor = ThreadPoolExecutor()
# ───────────────────────────────────────────────────────────────────────────────


@dataclass
class AccountConfig:
    profile: str
    name: str = ""
    compartment_id: str = ""
    subnet_id: str = ""
    image_id: str = ""
    instance_name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.profile
        if not self.instance_name:
            self.instance_name = DEFAULT_INSTANCE_NAME


def log(account_name: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{account_name}] {msg}", flush=True)


# ── accounts.yaml の読み込み ─────────────────────────────────────────────────────

def load_accounts(path: str = "accounts.yaml") -> list[AccountConfig]:
    if not os.path.exists(path):
        print(f"ERROR: {path} が見つかりません。accounts.yaml.example を参考に作成してください。")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    entries = data.get("accounts", [])
    if not entries:
        print("ERROR: accounts.yaml に accounts が定義されていません。")
        sys.exit(1)
    return [AccountConfig(**{k: v or "" for k, v in entry.items()}) for entry in entries]


# ── OCI 操作（同期）─ ThreadPoolExecutor で実行 ──────────────────────────────────

def _load_oci_config(profile: str) -> dict:
    # .env に OCI_USER_OCID 等が設定されていれば ~/.oci/config 不要
    user = os.environ.get("OCI_USER_OCID", "")
    fingerprint = os.environ.get("OCI_FINGERPRINT", "")
    tenancy = os.environ.get("OCI_TENANCY", "")
    region = os.environ.get("OCI_REGION", "")
    key_content = os.environ.get("OCI_KEY_CONTENT", "")
    key_file = os.environ.get("OCI_KEY_FILE", "")

    if user and fingerprint and tenancy and region and (key_content or key_file):
        if key_content and not key_file:
            # key_contentを一時ファイルに書き出してkey_fileとして渡す
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
            tmp.write(key_content.replace("\\n", "\n"))
            tmp.close()
            key_file = tmp.name
        config = {
            "user": user,
            "fingerprint": fingerprint,
            "tenancy": tenancy,
            "region": region,
            "key_file": key_file,
        }
    else:
        config = oci.config.from_file(profile_name=profile)

    passphrase = os.environ.get("OCI_KEY_PASSPHRASE", "")
    if passphrase:
        config["pass_phrase"] = passphrase

    oci.config.validate_config(config)
    return config


def _get_availability_domains(identity_client, compartment_id: str) -> list[str]:
    return [ad.name for ad in identity_client.list_availability_domains(compartment_id).data]


def _find_arm_image(compute_client, compartment_id: str) -> str | None:
    for os_name in ["Canonical Ubuntu", "Oracle Linux"]:
        try:
            images = compute_client.list_images(
                compartment_id=compartment_id,
                shape=SHAPE,
                operating_system=os_name,
                sort_by="TIMECREATED",
                sort_order="DESC",
                limit=1,
            )
            if images.data:
                return images.data[0].id
        except Exception:
            continue
    return None


def _find_subnet(vnet_client, compartment_id: str) -> str | None:
    try:
        for vcn in vnet_client.list_vcns(compartment_id=compartment_id, limit=10).data:
            subnets = vnet_client.list_subnets(
                compartment_id=compartment_id, vcn_id=vcn.id, limit=10
            ).data
            if subnets:
                return subnets[0].id
    except Exception:
        pass
    return None


def _try_create_instance(
    compute_client,
    compartment_id: str,
    availability_domain: str,
    subnet_id: str,
    image_id: str,
    instance_name: str,
    ssh_key: str,
) -> tuple[bool, str]:
    """
    インスタンス作成を試みる。
    戻り値: (成功フラグ, インスタンスID または エラーコード/メッセージ)
    エラーコード: "CAPACITY" | "RATE_LIMIT" | "LIMIT_EXCEEDED" | その他文字列
    """
    metadata = {"ssh_authorized_keys": ssh_key} if ssh_key else {}
    try:
        resp = compute_client.launch_instance(
            oci.core.models.LaunchInstanceDetails(
                compartment_id=compartment_id,
                availability_domain=availability_domain,
                display_name=instance_name,
                shape=SHAPE,
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=float(OCPUS),
                    memory_in_gbs=float(MEMORY_GB),
                ),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=image_id,
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=subnet_id,
                    assign_public_ip=True,
                ),
                metadata=metadata,
            )
        )
        return True, resp.data.id

    except oci.exceptions.ServiceError as e:
        msg: str = getattr(e, "message", str(e))
        if "Out of host capacity" in msg or e.status == 500:
            return False, "CAPACITY"
        if e.status == 429:
            return False, "RATE_LIMIT"
        if e.status == 400 and "LimitExceeded" in msg:
            return False, "LIMIT_EXCEEDED"
        return False, f"ServiceError {e.status}: {msg}"

    except Exception as e:
        return False, f"エラー: {e}"


# ── Discord 通知 ──────────────────────────────────────────────────────────────────

async def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {"content": message, "username": "OCI ARM Claimer"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                if resp.status == 204:
                    print("[Discord] 通知送信完了", flush=True)
                else:
                    print(f"[Discord] 通知失敗: HTTP {resp.status}", flush=True)
    except Exception as e:
        print(f"[Discord] 送信エラー: {e}", flush=True)


# ── アカウントごとの申請ループ ────────────────────────────────────────────────────

async def run_account(account: AccountConfig) -> str:
    """
    1アカウントの申請ループを実行する。
    戻り値: "success" | "limit_exceeded" | "setup_failed"
    """
    loop = asyncio.get_event_loop()
    name = account.name

    # OCI クライアント初期化
    try:
        config = await loop.run_in_executor(_executor, _load_oci_config, account.profile)
    except Exception as e:
        log(name, f"OCI設定エラー: {e} → スキップします")
        return "setup_failed"

    compute = oci.core.ComputeClient(config)
    identity = oci.identity.IdentityClient(config)
    vnet = oci.core.VirtualNetworkClient(config)

    compartment_id = account.compartment_id or config.get("tenancy", "")

    # 可用性ドメイン
    try:
        ads = await loop.run_in_executor(_executor, _get_availability_domains, identity, compartment_id)
    except Exception as e:
        log(name, f"可用性ドメイン取得失敗: {e} → スキップします")
        return "setup_failed"
    log(name, f"可用性ドメイン: {', '.join(ads)}")

    # イメージ
    image_id = account.image_id
    if not image_id:
        image_id = await loop.run_in_executor(_executor, _find_arm_image, compute, compartment_id)
        if not image_id:
            log(name, "ARM イメージが見つかりません → スキップします")
            return "setup_failed"
        log(name, "イメージ: 自動選択完了")

    # サブネット
    subnet_id = account.subnet_id
    if not subnet_id:
        subnet_id = await loop.run_in_executor(_executor, _find_subnet, vnet, compartment_id)
        if not subnet_id:
            log(name, "サブネットが見つかりません → スキップします")
            return "setup_failed"
        log(name, "サブネット: 自動選択完了")

    log(name, "申請ループ開始")
    attempt = 0

    while True:
        attempt += 1
        log(name, f"試行 #{attempt}")

        for ad in ads:
            success, result = await loop.run_in_executor(
                _executor,
                _try_create_instance,
                compute, compartment_id, ad, subnet_id, image_id,
                account.instance_name, SSH_PUBLIC_KEY,
            )

            if success:
                instance_id = result
                log(name, f"✅ 取得成功！ OCID: {instance_id}")
                await send_discord(
                    f"🎉 **OCI ARM インスタンス取得成功！**\n"
                    f"アカウント: **{name}** (プロファイル: `{account.profile}`)\n"
                    f"OCID: `{instance_id}`\n"
                    f"可用性ドメイン: `{ad}`\n"
                    f"スペック: {OCPUS} OCPU / {MEMORY_GB} GB RAM\n"
                    f"取得時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                return "success"

            if result == "LIMIT_EXCEEDED":
                log(name, "Always Free 上限に達しています → このアカウントの申請を停止します")
                await send_discord(
                    f"⚠️ **{name}** は既に Always Free 上限に達しています。申請を停止しました。"
                )
                return "limit_exceeded"

            if result == "RATE_LIMIT":
                log(name, "レート制限。60秒待機してから再試行...")
                await asyncio.sleep(60)
                continue

            log(name, f"  AD {ad}: {result}")

        log(name, f"全AD失敗。{RETRY_INTERVAL}秒後に再試行...")
        await asyncio.sleep(RETRY_INTERVAL)


# ── エントリポイント ──────────────────────────────────────────────────────────────

async def async_main() -> None:
    accounts = load_accounts()

    print()
    print("=" * 60)
    print("  OCI Free Tier ARM Instance Auto-Claimer (Multi-Account)")
    print("=" * 60)
    print(f"  対象アカウント数: {len(accounts)}")
    for a in accounts:
        print(f"    - {a.name} (プロファイル: {a.profile})")
    print(f"  シェイプ   : {SHAPE}")
    print(f"  スペック   : {OCPUS} OCPU / {MEMORY_GB} GB RAM")
    print(f"  再試行間隔 : {RETRY_INTERVAL} 秒")
    if not SSH_PUBLIC_KEY:
        print("  ⚠️  SSH_PUBLIC_KEY 未設定 (SSH接続できません)")
    print("=" * 60)
    print()

    results = await asyncio.gather(
        *[run_account(acc) for acc in accounts],
        return_exceptions=True,
    )

    print()
    print("=" * 60)
    print("  処理結果サマリー")
    print("=" * 60)
    for acc, res in zip(accounts, results):
        status = {
            "success": "✅ 取得成功",
            "limit_exceeded": "⚠️  上限超過（申請停止）",
            "setup_failed": "❌ 設定エラー（スキップ）",
        }.get(str(res), f"❌ 例外: {res}")
        print(f"  {acc.name}: {status}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n⛔ ユーザーが停止しました。")
        sys.exit(0)
