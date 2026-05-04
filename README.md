# qidian-dl

起点中文网书籍爬虫工具 — 通过浏览器自动化绕过腾讯 WAF 反爬机制，抓取书籍信息和全部章节内容。

## 功能

- **书籍信息抓取**：书名、作者、分类、字数、状态、简介、评分等
- **章节列表提取**：自动获取全书所有章节（含 VIP 章节）
- **章节正文下载**：逐章下载正文内容，存入 SQLite 数据库
- **WAF 绕过**：Playwright + stealth 脚本注入，伪装成正常浏览器
- **断点续爬**：已下载的章节会自动跳过，中断后重跑不会重复

## 环境要求

- Python 3.11+
- Google Chrome 浏览器（系统已安装即可，无需 Playwright 自带 Chromium）

## 安装

```bash
# 1. 克隆项目
git clone https://github.com/beishu721/-qidian-dl.git
cd -qidian-dl

# 2. 安装 Python 依赖
pip install -e .

# 3. Playwright 会自动使用系统的 Google Chrome（无需 playwright install）
```

## 使用方式

### 测试环境

正式爬取之前，先测试浏览器能否正常访问起点：

```bash
python -m qidian_spider test
```

如果输出类似 `成功! 页面标题: 小说,小说网,最新热门小说-起点中文网`，说明 WAF 绕过成功，可以开始爬取。

### 爬取单本书

```bash
python -m qidian_spider book <book_id>
```

示例：

```bash
python -m qidian_spider book 1010868264
```

`book_id` 的获取方式：打开起点书籍页面，地址栏中的数字即为 book_id。

```
https://book.qidian.com/info/1010868264/
                              ^^^^^^^^^^
                              这就是 book_id
```

### 有头模式（观察浏览器操作）

```bash
python -m qidian_spider book 1010868264 --no-headless
```

加上 `--no-headless` 后，你会看到一个真实的 Chrome 窗口弹出，可以亲眼看到自动翻页、提取内容的过程。适合首次使用或排查问题。

### 批量爬取

```bash
python -m qidian_spider batch 1010868264 1020599888 987654321
```

每本书之间默认间隔 30 秒，可以在代码中调整。

## 命令参考

| 命令 | 说明 |
|------|------|
| `test` | 测试浏览器 WAF 绕过，访问起点首页 |
| `book <id>` | 爬取单本书籍的全部信息+章节 |
| `batch <id1> <id2> ...` | 批量爬取多本书籍 |

| 选项 | 说明 |
|------|------|
| `--no-headless` | 关闭无头模式，显示浏览器窗口 |
| `--help` | 查看帮助 |

## 爬取流程

当你运行 `book` 命令后，工具会按以下步骤执行：

1. **启动浏览器** — 带 stealth 注入，伪装成真人用户
2. **访问书籍主页** — 提取书名、作者、简介、字数、状态等元信息
3. **打开目录页** — 列出所有章节（包括 VIP 章节），记入章节表
4. **逐章下载正文** — 每章间隔 3~8 秒随机延迟，模拟人类阅读
5. **每 10 章休息 10 秒** — 降低触发风控的概率
6. **存入数据库** — 每章下载完即时写入，中断不丢数据

## 数据存放

所有抓取的数据存储在：

```
data/db/qidian.db
```

这是一个 SQLite 数据库文件，包含两张主表：

### books 表

| 字段 | 说明 |
|------|------|
| `book_id` | 书籍 ID（主键） |
| `title` | 书名 |
| `author` | 作者 |
| `category` | 分类 |
| `status` | 状态（连载/完本） |
| `word_count` | 字数 |
| `description` | 简介 |
| `cover_url` | 封面图地址 |
| `rating_score` | 评分 |
| `total_recommend` | 推荐票 |
| `total_clicks` | 总点击 |
| `total_favorites` | 收藏数 |
| `monthly_ticket` | 月票 |

### chapters 表

| 字段 | 说明 |
|------|------|
| `chapter_id` | 章节 ID |
| `book_id` | 所属书籍 ID |
| `idx` | 章节序号 |
| `title` | 章节标题 |
| `is_vip` | 是否 VIP 章节 |
| `word_count` | 章节字数 |
| `content` | 正文内容 |
| `content_scraped` | 是否已爬取 |

### 查看数据

推荐用以下工具打开 `.db` 文件：
- [DB Browser for SQLite](https://sqlitebrowser.org/)（免费，图形界面）
- VS Code + SQLite Viewer 插件
- 命令行：`sqlite3 data/db/qidian.db`

查看某本书的完整内容：

```sql
-- 连接数据库
sqlite3 data/db/qidian.db

-- 查看所有书籍
SELECT * FROM books;

-- 查看某本书的所有章节（按序号排序）
SELECT idx, title, LENGTH(content) AS 字数
FROM chapters
WHERE book_id = 你的书ID
ORDER BY idx;
```

## 反爬策略说明

起点使用**腾讯 WAF**（Web Application Firewall）进行反爬保护，核心手段包括：

1. **JavaScript 指纹检测**（`probe.js`）— 检测 `navigator.webdriver`、插件列表、WebGL 指纹等
2. **行为分析** — 检测鼠标移动轨迹、滚动模式、点击间隔
3. **请求频率限制** — 高频访问触发 403 或验证码

本工具的应对方式：

- **8 项浏览器指纹伪装**：覆盖 `webdriver`、`plugins`、`chrome.runtime`、`WebGL` 等
- **随机延迟**：每次请求间隔 3~8 秒（可在 `config.py` 中调整 `min_delay_seconds` / `max_delay_seconds`）
- **模拟人类行为**：随机鼠标移动、随机滚动
- **Referer 头设置**：章节请求携带书籍页来源
- **低并发**：同时最多处理 2 个页面（`max_concurrent_pages`）

> 如果你需要更激进的速度，可以调小延迟参数，但会增加触发验证码的风险。

## 注意事项

1. **本工具仅供学习研究使用**，请勿用于商业用途或大规模数据采集
2. 爬取速度不要调得过快，建议保持默认的 3~8 秒间隔
3. VIP 章节需要你有对应书籍的订阅权限
4. 如果频繁触发验证码，建议隔一段时间再继续
5. 起点网站结构如果更新，章节选择器可能需要对应调整

## 项目结构

```
qidian-dl/
├── pyproject.toml                  # 项目配置与依赖
├── .gitignore
├── README.md
├── src/qidian_spider/
│   ├── __init__.py
│   ├── __main__.py                 # CLI 入口（book / batch / test）
│   ├── config.py                   # 配置管理（pydantic）
│   ├── models/
│   │   └── book.py                 # Book & Chapter 数据模型
│   ├── browser/
│   │   └── manager.py              # 浏览器管理 + WAF 绕过 + stealth 脚本
│   ├── spiders/
│   │   ├── base.py                 # 基础爬虫（随机延迟）
│   │   └── book_spider.py          # 书籍详情 + 章节内容爬取
│   ├── storage/
│   │   └── database.py             # SQLite 异步存储层
│   └── utils/
│       └── logger.py               # 日志配置
└── data/
    └── db/                         # SQLite 数据库存放目录（自动创建）
```

## License

MIT
