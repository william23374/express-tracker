# 华为云云商店「快递」API 接入完整向导（双商品）

> 本文档基于在 `express`(Express 快递追踪 CLI) 中**已真实跑通**的接入过程整理而成。
> 华为云云商店上有**多家**快递查询 API 商品，本项目目前对接了**两家**，它们都走**同一套华为云 APIG 签名**（`SDK-HMAC-SHA256`），但**网关域名、参数、返回格式、公司代码、手机号规则各不相同**，因此各自独立成一个 provider。

| 商品 | 服务商 | provider | 网关域名 |
|---|---|---|---|
| **快递查询【最新版】** | 聚美智数 / 杭州安那其科技 | `huawei_jm` | `expressqueryv2.apistore.huaweicloud.com` |
| **快递100实时查询** | 深圳前海百递网络（快递100/百递云） | `huawei_kd100` | `kdapi.apistore.huaweicloud.com` |

> ⚠️ **重点**：两家是**不同商品、不同 AppKey/AppSecret、不同接口**，不能混用凭据或参数。下面按「共同部分 → 各自部分」组织，避免混淆。

---

## 目录

1. [产品与购买（两家）](#1-产品与购买两家)
2. [认证方式（两家通用）](#2-认证方式两家通用)
3. [商品 A：快递查询【最新版】（聚美/安那其）](#3-商品-a快递查询最新版聚美安那其)
4. [商品 B：快递100实时查询（百递云）](#4-商品-b快递100实时查询百递云)
5. [签名算法详解（SDK-HMAC-SHA256）](#5-签名算法详解sdk-hmac-sha256)
6. [独立可运行 Python 示例](#6-独立可运行-python-示例)
7. [两家差异速览表](#7-两家差异速览表)
8. [快递公司代码与手机号要求](#8-快递公司代码与手机号要求)
9. [常见错误码与排查](#9-常见错误码与排查)
10. [官方链接与文档出处](#10-官方链接与文档出处)
11. [在 Express 项目中的接入与使用](#11-在-express-项目中的接入与使用)

---

## 1. 产品与购买（两家）

### 1.1 商品 A：快递查询【最新版】（聚美智数 / 杭州安那其科技有限公司）

- **产品名称**：快递查询【最新版】
- **商品类型**：云商店 API 商品，按调用次数计费（付费，每次调用扣点）
- **发布服务商**：聚美智数（杭州安那其科技有限公司）
- **商品链接**：
  <https://marketplace.huaweicloud.com/contents/52846e80-181e-4eb0-9fb2-ca3e8248b04c#productid=OFFI1109725229540491264>
- **Express provider**：`huawei_jm`

**购买流程**：登录华为云 → 打开商品链接 → 购买（选次套餐包）→「买家中心 → 我的云商店 → 已订购服务」→ 在订购详情里获取 **AppKey / AppSecret / AppCode**。

### 1.2 商品 B：快递100实时查询（深圳前海百递网络 / 快递100 / 百递云）

- **产品名称**：快递100实时查询接口
- **商品类型**：云商店 API 商品，按调用次数计费（付费）
- **发布服务商**：深圳前海百递网络有限公司（即快递100 / `kuaidi100.com` / 百递云）
- **商品链接**：
  <https://marketplace.huaweicloud.com/contents/af4f963a-0894-4aa3-860d-acab425267e7#productid=OFFI1000695969623982080>
- **Express provider**：`huawei_kd100`

**购买流程**：同上。**该商品的 AppKey/AppSecret 与商品 A 不同**，需在该商品的订购详情中单独获取。

### 1.3 需要准备的东西（每家各一套）

| 名称 | 用途 | 获取位置 |
|---|---|---|
| `AppKey` | APP 签名认证的 AK（`Access=` 值） | 对应商品的订购详情 |
| `AppSecret` | APP 签名认证的签名密钥（HMAC 密钥） | 对应商品的订购详情 |
| `AppCode` | 简易认证的 `X-Apig-AppCode` 头（可选） | 对应商品的订购详情 |

> ⚠️ **安全**：`AppSecret` 与 `AppCode` 属于密钥，**不要**明文写进代码或提交到仓库。建议通过环境变量或本地配置文件注入（见第 11 章）。

---

## 2. 认证方式（两家通用）

华为云 APIG（API 网关）对外提供两种 APP 认证方式，**二选一**。**两家商品共用这套机制**，只是各自的 AppKey/AppSecret 不同。

### 2.1 简易认证（Simple Auth）

- 在 HTTP 请求头加一个字段：

```
X-Apig-AppCode: <你的AppCode>
```

- **无需签名**，实现最简单，适合后端可信环境。

### 2.2 APP 签名认证（APP Signature，本次接入采用）

- 使用华为云 APIG SDK 的 **`SDK-HMAC-SHA256`** 签名算法。
- 需要在请求头填入：
  - `X-Sdk-Date`：当前 UTC 时间，格式 `%Y%m%dT%H%M%SZ`。
  - `Authorization`：`SDK-HMAC-SHA256 Access=<AppKey>, SignedHeaders=host;x-sdk-date, Signature=<签名>`。
- 网关会校验签名与 15 分钟有效期（时间偏差超过 ±15 分钟会拒绝）。
- 优点：不需要网关心跳、更安全、不暴露 AppCode。

> 本次在 `express` 中两家都选用 **APP 签名认证**（SDK 签名）。签名器 `HuaweiSigner` 复用同一个类，只通过构造时传入的 **host / path / params** 区分两家（见第 5、6 章）。

---

## 3. 商品 A：快递查询【最新版】（聚美/安那其）

> 对应代码：`src/express/providers/huawei_jm.py`，provider 名 `huawei_jm`。

### 3.1 请求信息

| 项 | 值 |
|---|---|
| Method | `POST` |
| URL | `https://expressqueryv2.apistore.huaweicloud.com/express/query-v2` |
| Host | `expressqueryv2.apistore.huaweicloud.com` |
| Path | `/express/query-v2` |
| Content-Type | `application/json` |

### 3.2 Query 参数（拼在 URL 上，参与签名）

| 参数 | 必填 | 说明 |
|---|---|---|
| `number` | 是 | 快递单号 |
| `expressCode` | 是 | 快递公司代码（**必须大写**，如 `SF/ZTO/YTO/YD/STO/JD/EMS/JT`） |
| `mobile` | 视快递 | 收件人**或寄件人**手机号，或**手机号后四位**；顺丰/跨越/中通**必填**且须与运单匹配 |
| `sort` | 否 | 排序，`1` 表示按时间升序（可选） |

### 3.3 响应示例

```json
{
  "code": 200,
  "msg": "success",
  "success": true,
  "taskNo": "xxx",
  "data": {
    "number": "JT4006791817090",
    "expressCode": "JT",
    "expressCompanyName": "极兔速递",
    "logisticsStatus": "TRANSPORT",
    "logisticsStatusDesc": "在途",
    "expWaybill": "...",
    "logisticsTraceDetails": [
      {
        "time": 1756451048000,
        "desc": "快件离开【上海浦西转运中心】已发往【深圳转运中心】",
        "areaName": "上海市",
        "logisticsStatus": "TRANSPORT"
      }
    ]
  }
}
```

**关键字段**

| 字段 | 说明 |
|---|---|
| `success` | 是否查询成功（业务层） |
| `code` | 业务状态码（`200` 成功；失败见第 9 章） |
| `msg` | 状态描述（失败时含排错信息） |
| `data.number` | 运单号（回显） |
| `data.expressCode` | 快递公司代码（大写） |
| `data.expressCompanyName` | 快递公司中文名 |
| `data.logisticsStatus` | 状态码（`ACCEPT/COLLECT/TRANSPORT/ON_THE_WAY/DELIVERING/SIGN/FAILED/RETURN`） |
| `data.logisticsStatusDesc` | 状态中文描述 |
| `data.logisticsTraceDetails[]` | 物流轨迹数组 |
| `data.logisticsTraceDetails[].time` | **毫秒时间戳** |
| `data.logisticsTraceDetails[].desc` | 轨迹描述 |
| `data.logisticsTraceDetails[].areaName` | 轨迹地点 |
| `data.logisticsTraceDetails[].logisticsStatus` | 单条轨迹状态码 |

> ⚠️ `time` 是 **毫秒** 时间戳（`int`, 13 位），转日期需 `/1000`。

---

## 4. 商品 B：快递100实时查询（百递云）

> 对应代码：`src/express/providers/huawei_kd100.py`，provider 名 `huawei_kd100`。

### 4.1 请求信息

| 项 | 值 |
|---|---|
| Method | `POST` |
| URL | `https://kdapi.apistore.huaweicloud.com/poll/channelquery.do?param=<json>` |
| Host | `kdapi.apistore.huaweicloud.com` |
| Path | `/poll/channelquery.do` |
| Content-Type | `application/x-www-form-urlencoded` |

> ⚠️ **与商品 A 的关键差别**：`param` 不是独立的 Query 参数，而是一个 **JSON 字符串**，通过 `param` 这一个 query 参数整体传入。且 `param` 的 JSON 字符串**参与签名**（作为 canonical query value 被 url-encode）。

### 4.2 `param` JSON 参数

`param` 是一个 JSON 字符串，例如：

```json
{
  "com": "auto",
  "num": "JT4006791817090",
  "phone": "13501297609",
  "resultv2": "1"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `com` | 是 | 快递公司**小写**代码（kuaidi100 风格，如 `shunfeng/zhongtong/yuantong/jtexpress`）或 `auto`（自动识别，推荐） |
| `num` | 是 | 快递单号 |
| `phone` | 视快递 | 收件人/寄件人手机号或后四位；**顺丰 `shunfeng`、丰网 `fengwang` 必填** |
| `resultv2` | 否 | `"1"` 表示开启 v2 增强返回（含 `areaName` 等） |

### 4.3 响应示例

```json
{
  "message": "ok",
  "nu": "JT4006791817090",
  "com": "jtexpress",
  "ischeck": "0",
  "state": "0",
  "status": "200",
  "condition": "00",
  "data": [
    {
      "time": "2026-08-31 08:57:26",
      "ftime": "2026-08-31 08:57:26",
      "context": "您的快件已抵达【深圳龙华区民乐网点】，正在积极为您安排派送。",
      "areaCode": "CN440309000000",
      "areaName": "广东,深圳市,龙华区",
      "status": "派件"
    }
  ]
}
```

**关键字段**

| 字段 | 说明 |
|---|---|
| `message` | `"ok"` 表示成功 |
| `status` | 接口状态（`"200"` 成功） |
| `nu` | 运单号 |
| `com` | 识别/回显的快递公司代码（小写 kuaidi100 风格） |
| `ischeck` | 是否已签收（`"1"` = 已签收） |
| `state` | 物流状态码（`0在途 1揽收 2疑难 3签收 4退签 5派件 8清关 14拒签`） |
| `data[]` | 物流轨迹数组 |
| `data[].time` / `data[].ftime` | 轨迹时间字符串 `YYYY-MM-DD HH:MM:SS`（**非毫秒**） |
| `data[].context` | 轨迹描述 |
| `data[].areaName` | 轨迹地点（省,市,区） |
| `data[].status` | 单条轨迹状态（中文如「在途」「派件」） |

> ⚠️ 与商品 A 的差别：**轨迹时间是字符串**（不是毫秒时间戳），`state` 用数字码（不是 `logisticsStatus` 英文码）。

---

## 5. 签名算法详解（SDK-HMAC-SHA256）

华为云 APIG SDK（`apig_sdk` / `huaweicloudsdkcore`）使用的签名流程与官方文档一致。**核心要点**（实测踩坑得出，两家通用）：

1. `Authorization` 使用 **`Access=`**（不是 `Credential=`）。用 `Credential=` 会报 `Authorization format is incorrect`。
2. `StringToSign` 里必须包含 **`x-sdk-date` 这一行**（`X_SDK_DATE`），否则报 `verify signature fail`。
3. `CanonicalURI` 末尾必须补 **`/`**（如商品 A `/express/query-v2/`、商品 B `/poll/channelquery.do/`），用 `quote(s, safe='~')` 编码。
4. **`CanonicalQueryString` 必须按 key 字母序排序后编码**。商品 A 的 `number/expressCode/mobile/sort` 需排序；商品 B 只有一个 `param` 键。**两者都必须与「实际发出的 URL」完全一致**，否则签名校验失败。**买家最容易踩的坑**：商品 B 的 `param` JSON 字符串作为 query 时，签名用的编码与 httpx 默认编码不完全等同，务必用同一套 `safe='~'` 编码（本项目用 `_url_encode` 统一处理）。
5. 空 body 的 SHA-256 哈希是固定常量（两家 body 都为空，因为参数都在 query）：
   ```
   e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
   ```

### 5.1 签名公式

```
CanonicalRequest =
    HTTPRequestMethod + '\n' +
    CanonicalURI + '\n' +
    CanonicalQueryString + '\n' +
    CanonicalHeaders + '\n' +
    SignedHeaders + '\n' +
    HexEncode(Hash(RequestPayload))

StringToSign =
    Algorithm + '\n' +
    X_SDK_DATE + '\n' +
    HexEncode(Hash(CanonicalRequest))

Signature = HexEncode(HMAC-SHA256(AppSecret, StringToSign))

Authorization =
    "SDK-HMAC-SHA256 Access=" + AppKey +
    ", SignedHeaders=" + SignedHeaders +
    ", Signature=" + Signature
```

### 5.2 各项说明

- **CanonicalURI**：补尾部 `/`，段各 `quote(..., safe='~')`。
- **CanonicalQueryString**：Query 参数按 **key 字母序**排序后 `key=value` 用 `&` 连接，值用 `quote(..., safe='~')`。
- **CanonicalHeaders**：`host:{Host}\nx-sdk-date:{X-Sdk-Date}\n`（注意都是小写、末尾 `\n`）。
- **SignedHeaders**：`host;x-sdk-date`（对应上面两个头）。
- **RequestPayload**：两个接口均为 query 传参、body 为空串，哈希即空串常量。

---

## 6. 独立可运行 Python 示例

### 6.1 方式 A：使用华为云官方 SDK（推荐）

```bash
pip install huaweicloudsdkcore
```

```python
import os
from apig_sdk import signer   # 官方离线 SDK：from apig_sdk import signer
import requests

APP_KEY = os.environ["HUAWEICLOUD_SDK_AK"]      # = 云商店 AppKey
APP_SECRET = os.environ["HUAWEICLOUD_SDK_SK"]   # = 云商店 AppSecret

sig = signer.Signer()
sig.Key = APP_KEY
sig.Secret = APP_SECRET

# —— 商品 A（聚美/安那其）——
url_a = (
    "https://expressqueryv2.apistore.huaweicloud.com/express/query-v2"
    "?number=JT4006791817090&expressCode=JT&sort=1"
)
r_a = signer.HttpRequest("POST", url_a)
sig.Sign(r_a)
resp_a = requests.post(r_a.url, headers=r_a.headers)
print("A status:", resp_a.status_code, resp_a.text[:300])

# —— 商品 B（快递100/百递云）——
import json, urllib.parse
param = json.dumps({"com": "auto", "num": "JDAP20550238955", "resultv2": "1"},
                   ensure_ascii=False, separators=(",", ":"))
url_b = "https://kdapi.apistore.huaweicloud.com/poll/channelquery.do?param=" + \
        urllib.parse.quote(param, safe="~")
r_b = signer.HttpRequest("POST", url_b)
sig.Sign(r_b)
resp_b = requests.post(r_b.url, headers=r_b.headers)
print("B status:", resp_b.status_code, resp_b.text[:300])
```

### 6.2 方式 B：纯标准库实现（无外部依赖）

签名核心函数（两家复用，只需换 `HOST/PATH/params`）：

```python
import datetime, hashlib, hmac, urllib.parse, json, requests

EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ALGO = "SDK-HMAC-SHA256"
DATE_FMT = "%Y%m%dT%H%M%SZ"

def enc(v):
    return urllib.parse.quote(str(v), safe="~")

def canonical_uri(path):
    uri = "/".join(enc(p) for p in urllib.parse.unquote(path).split("/"))
    return uri if uri.endswith("/") else uri + "/"

def canonical_query(params):
    return "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(params.items()))

def canonical_headers(host, x_date):
    return f"host:{host}\nx-sdk-date:{x_date}\n"

def sign(app_key, app_secret, method, host, path, params):
    x_date = datetime.datetime.now(datetime.timezone.utc).strftime(DATE_FMT)
    canonical = "\n".join([
        method.upper(),
        canonical_uri(path),
        canonical_query(params),
        canonical_headers(host, x_date),
        "host;x-sdk-date",
        EMPTY_HASH,                       # body 为空
    ])
    string_to_sign = "\n".join([
        ALGO, x_date, hashlib.sha256(canonical.encode()).hexdigest(),
    ])
    signature = hmac.new(app_secret.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"SDK-HMAC-SHA256 Access={app_key}, SignedHeaders=host;x-sdk-date, Signature={signature}"
    return x_date, auth

# —— 商品 A ——
def query_a(app_key, app_secret, number, express_code, mobile=""):
    host, path = "expressqueryv2.apistore.huaweicloud.com", "/express/query-v2"
    params = {"number": number, "expressCode": express_code, "mobile": mobile, "sort": "1"}
    x_date, auth = sign(app_key, app_secret, "POST", host, path, params)
    headers = {"Host": host, "X-Sdk-Date": x_date, "Authorization": auth,
               "Content-Type": "application/json"}
    return requests.post(f"https://{host}{path}", params=params, headers=headers, timeout=20).json()

# —— 商品 B ——
def query_b(app_key, app_secret, number, com="auto", phone=""):
    host, path = "kdapi.apistore.huaweicloud.com", "/poll/channelquery.do"
    p = {"com": com, "num": number, "resultv2": "1"}
    if phone:
        p["phone"] = phone
    # param 是 JSON 字符串，作为唯一 query 参数；编码必须与签名一致 (safe='~')
    param = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    params = {"param": param}
    x_date, auth = sign(app_key, app_secret, "POST", host, path, params)
    headers = {"Host": host, "X-Sdk-Date": x_date, "Authorization": auth,
               "Content-Type": "application/x-www-form-urlencoded"}
    url = f"https://{host}{path}?param={enc(param)}"
    return requests.post(url, headers=headers, timeout=20).json()

if __name__ == "__main__":
    ak, sk = os.environ["HW_APP_KEY"], os.environ["HW_APP_SECRET"]
    print(query_a(ak, sk, "JT4006791817090", "JT"))
    print(query_b(ak, sk, "JDAP20550238955", com="auto"))
```

> 注意：`query_a` 用 `requests.post(url, params=params)`，`query_b` 则**手动**把 `param` 编码后拼进 URL（因为 httpx/requests 对 JSON query 的编码可能和签名用的 `safe='~'` 不一致，手动统一才能保证签名匹配）。

---

## 7. 两家差异速览表

| 维度 | 商品 A（`huawei_jm`） | 商品 B（`huawei_kd100`） |
|---|---|---|
| 服务商 | 聚美智数 / 杭州安那其科技 | 深圳前海百递网络（快递100/百递云） |
| 网关域名 | `expressqueryv2.apistore.huaweicloud.com` | `kdapi.apistore.huaweicloud.com` |
| 路径 | `/express/query-v2` | `/poll/channelquery.do` |
| Content-Type | `application/json` | `application/x-www-form-urlencoded` |
| 传参方式 | 多个独立 query 参数 | 单个 `param` JSON 字符串作为 query 参数 |
| 公司代码 | **大写**（`SF/ZTO/YTO/YD/STO/JD/EMS/JT`） | **小写 kuaidi100**（`shunfeng/zhongtong/...`）+ `auto` 自动识别 |
| 快递范围 | 主流 8 家（非主流不支持，报 411） | 3000+ 家（支持自动识别） |
| 轨迹时间 | **毫秒时间戳** int | **字符串** `YYYY-MM-DD HH:MM:SS` |
| 状态字段 | `data.logisticsStatus`（英文码） | `state`（数字码）+ `ischeck` |
| 手机号规则 | ZTO/SF 需**完整号**，其余后四位 | 顺丰/丰网需**后四位**，其余可选 |
| 是否需解析公司名 | 有（`expressCompanyName`） | 无中文公司名（用 com 码） |

---

## 8. 快递公司代码与手机号要求

### 8.1 代码映射（内部小写 → 各家外部码）

**商品 A（`huawei_jm.py` `_TO_HW`，转为大写）**：

| 内部 code | 华为云 `expressCode` |
|---|---|
| `sf` / `shunfeng` | `SF` |
| `kd` / `kuayue` / `ky` | `KD` |
| `zto` / `zhongtong` | `ZTO` |
| `yto` / `yuantong` / `yt` | `YTO` |
| `yunda` / `yd` | `YD` |
| `sto` / `shentong` | `STO` |
| `jd` | `JD` |
| `ems` | `EMS` |
| `jt` / `jtexpress` / `jitu` | `JT` |

**商品 B（`huawei_kd100.py` `_TO_KD100`，转为 kuaidi100 小写）**：

| 内部 code | kuaidi100 `com` |
|---|---|
| `sf` / `shunfeng` | `shunfeng` |
| `zto` / `zhongtong` | `zhongtong` |
| `yto` / `yuantong` / `yt` | `yuantong` |
| `yunda` / `yd` | `yunda` |
| `sto` / `shentong` | `shentong` |
| `jd` | `jd` |
| `ems` | `ems` |
| `jt` / `jtexpress` / `jitu` | `jtexpress` |

> 商品 B 若未传 `com` 则用 `auto` 自动识别（覆盖 3000+ 家），识别结果从返回的 `com` 字段反向映射回内部码。

### 8.2 手机号要求（两家不同）

**商品 A（聚美/安那其）**：

- **顺丰 `SF`、跨越 `KD`、中通 `ZTO`**：**必填** `mobile`，取「收件人或寄件人手机号」或「手机号后四位」，且必须**与该运单匹配**。不匹配返回 `验证失败，请输入正确的手机号码`。
- **其它快递（极兔 `JT`、京东 `JD`、圆通 `YTO`、韵达 `YD`、申通 `STO`、EMS）**：**不需要**手机号（可传空）。
- **隐私虚拟件**：淘宝/拼多多/抖音单常绑定虚拟号（与订单绑定，非真实手机），需用**单上显示的虚拟号**而非真实裸号。
- 本项目通过 `_needs_full_phone()` 判断：`ZTO/SF/KD` 传**完整号**，其余传**后四位**。

**商品 B（快递100/百递云）**：

- **顺丰 `shunfeng`、丰网 `fengwang`**：**必填** `phone`，取收件人/寄件人手机号**后四位**即可。
- **其它快递**：`phone` **可不传**（或传后四位）。
- 本项目对 `shunfeng/fengwang` 自动补 `phone`（用 `normalize_phone_tail` 转后四位），其余若用户传了手机号也会带上。

---

## 9. 常见错误码与排查

### 9.1 商品 A（聚美/安那其）

| code | 含义 | 处理 |
|---|---|---|
| `411` | 不支持的快递公司代码 | 检查 `expressCode` 是否大写、是否映射到 `_TO_HW` |
| `412` | 运单号与快递公司不匹配 | 检查单号 / `C` 代码是否对应 |
| `400` + 「验证失败，请输入正确的手机号码」 | 手机号与运单不匹配 | 用收件人/寄件人真实手机（虚拟件用订单虚拟号） |
| `400` + 「顺丰/跨越/中通需传入收件人或寄件人手机号或后四位」 | 必填手机号未传 | 补 `mobile`（完整号或后四位） |
| `701` | 未查询到物流数据 | 单号可能未录入 / 已超期，可稍后重试 |

### 9.2 商品 B（快递100/百递云）

| 返回 | 含义 | 处理 |
|---|---|---|
| `status != "200"` | 接口层错误 | 查看 `message`，通常是单号/编码问题 |
| `result: false` + `returnCode: "500"` | 查询无结果 | 单号未录入 / 刚发货无轨迹，稍后重试 |
| `message` 含「无效」 | 参数错误 | 检查 `param` JSON 是否合法、`com` 是否支持 |
| HTTP `401` `verify signature fail` | 签名不匹配 | 确认 `param` JSON 编码与签名一致（`safe='~'`）、`CanonicalURI` 补 `/` |
| HTTP `400` `Invalid query parameter: ... required` | 参数传错位置 | 确认 `param` 放在 **query**（不是 body），且 JSON 是字符串 |

> 两家都有的通用 HTTP `401`：
> - `Authorization format incorrect` → 确认用 `Access=`，不是 `Credential=`。
> - `Signature expired` → 时间偏差超 15 分钟，校准系统时钟；`X-Sdk-Date` 用 UTC。

---

## 10. 官方链接与文档出处

### 10.1 商品 A（聚美/安那其）

- **云商店商品页**（快递查询【最新版】）：
  <https://marketplace.huaweicloud.com/contents/52846e80-181e-4eb0-9fb2-ca3e8248b04c#productid=OFFI1109725229540491264>

### 10.2 商品 B（快递100/百递云）

- **云商店商品页**（快递100实时查询接口）：
  <https://marketplace.huaweicloud.com/contents/af4f963a-0894-4aa3-860d-acab425267e7#productid=OFFI1000695969623982080>
- 配套使用指南为 PDF《快递100实时查询接口文档-华为云》，其中给出调用地址
  `http(s)://kdapi.apistore.huaweicloud.com/poll/channelquery.do`、`param` 参数及 `data[]` 返回字段定义。

### 10.3 签名与通用文档（两家共用）

- **华为云 Python 签名指导**（`apig_sdk` / `signer.Signer` 用法，`Authorization` 与 `X-Sdk-Date`）：
  <https://support.huaweicloud.com/devg-apisign/api-sign-sdk-python.html>
- **华为云 APIC Python SDK 使用说明**（后端签名校验、`Authorization` 格式 `Access=…, SignedHeaders=host;x-sdk-date, Signature=…`、`BasicDateFormat=%Y%m%dT%H%M%SZ`、15 分钟有效期）：
  <https://support.huaweicloud.com/devg-roma/apic-dev-190216022.html>
- **华为云 Stack Python SDK 使用说明**（同签名算法，双环境）：
  <https://doc.hcs.huawei.com/zh-cn/devg/roma/apic-dev-190216022.html>
- **`apig_sdk` 离线 SDK 目录结构**（`apig_sdk/__init__.py`、`apig_sdk/signer.py`，AK/SK 认证）：
  <https://doc.hcs.huawei.com/zh-cn/usermanual/modelarts/inference-modelarts-0024.html>
- **APIG 签名工具 / 多语言 SDK 下载入口**（请求签名流程）：
  <https://support.huaweicloud.com/topic/856579-5-Q>
- **空 body SHA-256 哈希常量出处**（body 签名主题）：
  <https://support.huaweicloud.com/topic/65281-5-B>
- **华为云 Python SDK 核心库**（PyPI，`huaweicloudsdkcore`，内含 `signer.py`）：
  <https://pypi.org/project/huaweicloudsdkcore/>

> 说明：以上官方页面均摘自华为云「帮助中心 / 开发者中心 / 云商店」。签名算法以 `huaweicloudsdkcore/signer/signer.py` 为基准，并在本项目中**对两家均实测通过真实查询**验证。

---

## 11. 在 Express 项目中的接入与使用

### 11.1 写凭据（两家各一段）

```
CONF:INIT
```

会在 `~/.express/config.toml` 生成模板，然后编辑（或用环境变量）：

```toml
# 商品 A：聚美/安那其
[huawei_jm]
app_key = "YOUR_APP_KEY"
app_secret = "YOUR_APP_SECRET"

# 商品 B：快递100/百递云
[huawei_kd100]
app_key = "YOUR_APP_KEY"
app_secret = "YOUR_APP_SECRET"
```

**两家凭据独立、不可混用**——商品 A 用 `[huawei_jm]`，商品 B 用 `[huawei_kd100]`。

环境变量（`load_config` 兼容）：  
- 商品 A（`huawei_jm`）：`EXPRESS_HUAWEI_JM_APPKEY` / `EL_HUAWEI_JM_APPKEY` / `EXPRESS_HUAWEI_JM_APPSECRET` / `EL_HUAWEI_JM_APPSECRET`。
- 商品 B：`EXPRESS_KD100_APPKEY` / `EL_KD100_APPKEY` / `EXPRESS_KD100_APPSECRET` / `EL_KD100_APPSECRET`。

### 11.2 启用并查询

```
PROV                    # 查看所有服务商（含两家华为云接口及其 configured 状态）
USE:huawei_jm          # 切到商品 A（聚美）
USE:huawei_kd100        # 切到商品 B（快递100/百递云）
SAVE:JT.../C:jt         # 保存（自动识别/手动指定）
TRACK:<单号>            # 查询（未保存单号会自动落库）
LIST / HIST:<单号>     # 查看已保存记录与完整时间线
```

### 11.3 配置/代码要点（新增商品 B 时）

- `src/express/config.py`：新增 `kd100_appkey` / `kd100_appsecret` 与 `has_kd100_credentials()`；两个配置段 `[huawei_jm]` / `[huawei_kd100]` 分别读取。
- `src/express/providers/huawei_jm.py`：`HuaweiSigner.sign()` 增加 `host` 参数（默认聚美域名，向后兼容），使签名器可复用给商品 B。
- `src/express/providers/huawei_kd100.py`：**新建**注册名 `huawei_kd100`，复用 `HuaweiSigner`，用 kdapi 的 `host/path/参数/返回` 做映射。
- `src/express/service.py`：`_chain_candidate` / `_build_single` / `switch_provider` 增加 `huawei_kd100` 分支。
- `src/express/providers/base.py`：`load_builtin_providers()` 导入 `huawei_kd100`。
- `src/express/commands.py`：`PROV`/`CONF` 显示两家凭据状态与描述。
- `macos/El.spec`：`hiddenimports` 加入 `express.providers.huawei_kd100`（打包桌面应用用）。
