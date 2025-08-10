# Excel → SQL Generator (Flask)

一个将 **Excel 表格** 批量转换为 **MySQL SQL 语句** 的轻量服务。支持生成 `UPDATE` / `INSERT` / `UPSERT`（`ON DUPLICATE KEY UPDATE`）三种语句；可灵活指定主键、更新列、是否跳过空值、列名别名映射等。

后端基于 **Flask** 开发，提供简单的网页（`/`）和两个接口：
- `POST /preview_columns`：预览 Excel 的工作表或列名
- `POST /generate`：生成 SQL 文件并返回下载

> 主要适用于把运营/财务/数据同学维护的 Excel 数据批量入库、修正或补数据等场景。

---

## 功能特性

- **三种语句类型**：`UPDATE` / `INSERT` / `UPSERT`
- **主键 + 可选更新列**：精确控制更新范围
- **空值策略**：可选择在 `SET` 中跳过空值
- **列名别名映射**（Excel 列 → 数据库列）：避免表结构与 Excel 字段不一致
- **类型安全序列化**：日期/时间、布尔、数值、字符串均做了安全处理与转义
- **MySQL 友好**：使用反引号包裹列名，`UPSERT` 采用 `ON DUPLICATE KEY UPDATE ... VALUES(col)` 写法

---

## 目录结构（建议）

```
your-project/
├─ app.py                  # 本服务（Flask）
├─ templates/
│   └─ index.html          # 可选：简单网页上传与生成
├─ static/                 # 可选：静态资源
└─ requirements.txt        # 依赖清单
```

> 本仓库的 `app.py` 默认使用 `templates/index.html` 作为首页。如不提供模板文件，仍可直接调用 API。

---

## 运行环境

- Python 3.9+（建议）
- 依赖组件：
  - Flask
  - pandas
  - openpyxl（pandas 读取 `.xlsx` 所需）

安装依赖：
```bash
pip install -r requirements.txt
```

或最小依赖安装：
```bash
pip install flask pandas openpyxl
```

---

## 启动服务

默认监听 `0.0.0.0:12080`：
```bash
python app.py
```

浏览器打开：
- 首页（可选页面）：`http://127.0.0.1:12080/`
- 接口说明见下文

> 代码中注释提示：浏览器的 6000 端口被部分浏览器视为不安全，已改为 `12080`。你也可以改为 `5000/8000/8080` 等常用端口。

---

## API 说明

### 1) 预览工作表 / 列名：`POST /preview_columns`

**用途**：在不清楚工作表名或列名时，先上传 Excel 快速查看。

- 当 **不传** `sheet_name`：返回工作表列表
- 当 **传入** `sheet_name`：返回该工作表的列名列表

请求（`multipart/form-data`）：
- `file`：Excel 文件（必填）
- `sheet_name`：可选，字符串或表索引（从 0 开始）

示例（返回工作表名）：
```bash
curl -X POST http://127.0.0.1:12080/preview_columns \
  -F "file=@./data.xlsx"
```

示例（返回列名）：
```bash
curl -X POST http://127.0.0.1:12080/preview_columns \
  -F "file=@./data.xlsx" \
  -F "sheet_name=Sheet1"
```

返回示例：
```json
{"sheets": ["Sheet1", "Sheet2"]}
```
或
```json
{"columns": ["id", "name", "amount", "updated_at"]}
```

---

### 2) 生成 SQL：`POST /generate`

根据参数生成 `UPDATE` / `INSERT` / `UPSERT` 的 `.sql` 文件，并作为附件返回。

请求（`multipart/form-data`）：

| 字段名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | Excel 文件（支持 `.xlsx` 等，取决于 pandas/openpyxl） |
| `table_name` | str | 是 | 目标表名 |
| `primary_keys` | str | 是 | 主键列，**逗号分隔**，如 `"id,tenant_id"` |
| `update_columns` | str | 否 | 勾选的列，**逗号分隔**；不传时根据语句类型有默认行为（见下） |
| `sheet_name` | str/int | 否 | 工作表名或索引，默认 `0` |
| `stmt` | str | 否 | 语句类型：`UPDATE`（默认）/ `INSERT` / `UPSERT` |
| `mysql_version` | str | 否 | `mysql57` / `mysql80`（当前仅保留参数位，行为一致） |
| `skip_nulls_in_set` | bool(str) | 否 | `true`/`false`（默认 `true`），为真时 `SET` 中跳过空值 |
| `column_alias_json` | JSON(str) | 否 | 列名映射 JSON：`{"Excel列":"数据库列", ...}` |

**语义说明**：
- `UPDATE`：
  - `SET` 列：默认使用 **除主键外的所有列**；若传了 `update_columns`，则只用传入列（仍会排除主键）。
- `INSERT`：
  - 插入列：默认 **所有列**；若传了 `update_columns`，则使用 **主键 ∪ update_columns** 的并集。
- `UPSERT`：
  - `INSERT` 部分与 `INSERT` 相同；
  - `UPDATE` 部分：默认使用 **除主键外的所有列**；若传了 `update_columns`，则只用传入列（排除主键）。
  - `UPDATE` 值采用 `VALUES(mapped_col)` 写法。

**列名别名映射**：
- 上传的 `column_alias_json` 会将 Excel 的列名映射为数据库目标列名，如：
  ```json
  {
    "用户ID": "user_id",
    "金额": "amount",
    "更新时间": "updated_at"
  }
  ```
- 若映射后出现**重复目标列名**，会报错提示。

**空值处理**：
- 当 `skip_nulls_in_set=true`（默认）时：生成 `UPDATE/UPSERT` 的 `SET` 子句时，**空值（NULL/NaN）对应的列会被跳过**；
- 当为 `false`：空值会按 `NULL` 写入 `SET`。

**序列化规则（简要）**：
- `datetime/date/pandas.Timestamp`：格式化为 `'YYYY-MM-DD HH:MM:SS'` 或 `'YYYY-MM-DD'`
- `bool`：`True -> 1`，`False -> 0`
- 数值：直接转字符串（`NaN` 视为空）
- 其他类型：作为字符串，且做了转义（反斜线、单引号）

示例（生成 `UPSERT` 并下载）：
```bash
curl -X POST http://127.0.0.1:12080/generate \
  -F "file=@./data.xlsx" \
  -F "table_name=orders" \
  -F "primary_keys=id,tenant_id" \
  -F "update_columns=amount,updated_at" \
  -F "sheet_name=Sheet1" \
  -F "stmt=UPSERT" \
  -F "mysql_version=mysql80" \
  -F "skip_nulls_in_set=true" \
  -F 'column_alias_json={"用户ID":"id","金额":"amount","更新时间":"updated_at","租户":"tenant_id"}' \
  -OJ
```

> `-OJ` 让 `curl` 按响应头里的文件名保存（形如 `upsert_orders.sql`）。

---

## 前端页面（可选）

如果提供了 `templates/index.html`，访问根路径 `/` 会渲染一个简洁的页面，支持：
- 上传 Excel、选择表、设置参数
- 提交后直接下载 SQL 文件

若不需要页面，可直接通过上述接口对接脚本或其他系统。

---

## 常见问题

1. **读取 `.xlsx` 报错**  
   安装/升级 `openpyxl`：  
   ```bash
   pip install -U openpyxl
   ```

2. **时区/时间格式**  
   服务按原始 Excel 时间值格式化为字符串，你可以在入库时指定时区或在 Excel 内先标准化。

3. **MySQL 版本**  
   目前 `mysql57/mysql80` 参数仅保留占位；`UPSERT` 使用 `ON DUPLICATE KEY UPDATE`，需确保表上存在唯一/主键约束。

4. **大文件/性能**  
   这是一个轻量工具型服务，若 Excel 非常大，建议分批或离线在本地脚本运行。

---

## 依赖（requirements.txt 示例）

```
flask
pandas
openpyxl
```

> 如果你要在生产环境用 WSGI 部署，还可以增加：`gunicorn`（Linux）或使用其它兼容服务器。

---

## 开发与调试

- 开启调试（默认 `debug=True`）：修改代码自动重载。
- 修改端口：编辑 `app.py` 末尾 `app.run(..., port=12080)`。

---

## License

MIT
