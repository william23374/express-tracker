# Express — interactive package tracking terminal

Prompt-first UX:

```text
$ express
express > LIST
express > SAVE:JT4006721151302
express > STAT:7
express > HIST:7
express > SO
```

## Layout (src layout)

```text
src/express/
  __main__.py      # entry: REPL or one-shot
  repl.py          # express > shell
  commands.py      # command dispatch
  display.py       # Rich output
  config.py        # ~/.express/
  models.py
  service.py
  storage.py
  validation.py
  status.py
  providers/       # auto/fallback | huawei_jm | huawei_kd100 | ali_kd100 | mock
```

## Install

```bash
bash scripts/install.sh
express                 # interactive shell
express LIST            # one-shot still works
```

Compatibility: `el` is an alias of `express`.

## Desktop package

```bash
bash macos/build_installer.sh
open dist/Express-Installer.dmg
```

> **Note — Gatekeeper**：本脚本打包默认是 **未公证 (ad-hoc)** 的。
> - 在本机 / 本机自用：直接打开即可。
> - 分发到**其它 Mac**：收件人需 **右键 → 打开**，或先执行
>   `xattr -d com.apple.quarantine <path-to-app>`，否则会提示“无法验证开发者”。
> - 若已配置 **Developer ID 证书 + 公证凭据**（见 `macos/build_installer.sh` 顶部注释），
>   脚本会自动审计并装订，产出可直接双击打开的已公证包，免去上述右键/xattr 操作。

## Config

`~/.express/config.toml` (auto-migrates from `~/.el` if present):

```toml
default_provider = "auto"
provider_chain = ["huawei_kd100", "ali_kd100", "huawei_jm"]

# Huawei Cloud marketplace 快递查询【最新版】 (聚美智数/杭州安那其) — AppKey/AppSecret
# (purchase at marketplace.huaweicloud.com, Resource Detail -> APIG gateway)
[huawei_jm]
app_key = "YOUR_APPKEY"
app_secret = "YOUR_APPSECRET"

# 快递100/百递云 via Huawei Cloud APIG (same APP signature, separate product)
# purchase at marketplace.huaweicloud.com/contents/af4f963a-0894-4aa3-860d-acab425267e7
[huawei_kd100]
app_key = "YOUR_APPKEY"
app_secret = "YOUR_APPSECRET"

# 快递100/百递云 via Aliyun Cloud Marketplace (AppCode simple auth)
# product: market.aliyun.com/detail/cmapi00053347 (快递物流轨迹查询单号识别时效预估服务)
[ali_kd100]
app_code = "YOUR_ALIYUN_APPCODE"
```

`auto` tries providers in `provider_chain` order and switches to the next
one when a provider fails (daily quota exhausted, network error, no data).
Providers without credentials are skipped automatically.

To switch the live provider (persists to config), use the shell:

```text
express > PROV                 # list all providers + configured status
express > USE:huawei_kd100      # switch to a specific provider
express > USE:auto             # back to auto-select (fallback chain)
```

Providers (all are cloud-marketplace APIs; each needs its own credential):
- `huawei_jm` — Huawei Cloud marketplace API 快递查询【最新版】(聚美/安那其; paid, per-call); needs AppKey+AppSecret.
  Courier codes are UPPERCASE (SF/ZTO/YTO/YD/STO/JD/EMS/JT); ZTO/SF want the FULL
  receiver phone (not just the last-4).
- `huawei_kd100` — 快递100/百递云 via Huawei Cloud APIG (paid, per-call); needs a
  separate AppKey+AppSecret (`[huawei_kd100]`). Uses kuaidi100 `com` codes
  (shunfeng/zhongtong/yuantong/jtexpress/...) and `com=auto` auto-detects; SF/丰网
  want the receiver-or-sender phone last-4.
- `ali_kd100` — 快递100/百递云 via Aliyun Cloud Marketplace (paid, per-call);
  needs an AppCode (`[ali_kd100] app_code`). Same kuaidi100 `com` codes and
  `com=auto`; SF/中通 want the receiver-or-sender phone last-4.

## Shell commands

| Command | Aliases |
|---------|---------|
| `LIST` | `li` `ls` |
| `SAVE:NUMBER[/C][/P][/N]` | |
| `TRACK:NUMBER[/C][/P]` | `tr` |
| `QUERY:NUMBER[/C][/P][/H]` | |
| `STAT:NUMBER[/C]` | `st` |
| `HIST:NUMBER[/C]` | `hist` |
| `MODIFY:NUMBER[/C][/P][/N][/T]` | `edit` `up` |
| `DEL:NUMBER[/C]` | `rm` |
| `CONF [/INIT]` | `cf` |
| `PROV` | `prov` |
| `USE:provider` | (`USE:auto` = auto-select) |
| `VER` | |
| `HELP [CMD]` | `?` |
| `SO` | `quit` |

`HIST:NUMBER` shows the accumulated track timeline. Events from each query are
deduped (by time + description) and stored locally per shipment, so the full history
keeps growing across queries and is no longer limited to what a single provider
response returns.
